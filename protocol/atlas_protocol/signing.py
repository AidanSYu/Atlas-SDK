"""Ed25519 provenance for `.atlas` packages.

Replaces the forgeable v1 HMAC (a hardcoded, public key that authenticated
nothing) with real asymmetric signatures:

* the publisher signs the package digest (``sha256(manifest ‖ payload ‖ assets)``)
  with their Ed25519 **private** key;
* the container carries a sigblock with the publisher's **public** key + the
  signature — anyone can verify tamper-evidence, nobody can forge it;
* :mod:`atlas_protocol.trust` maps the public key to a *trust level* against the
  local trust store (who is allowed to run in-proc).

This module registers its verifier with :mod:`atlas_protocol.packaging` on
import, so ``read_atlas(..., verify_signature=True)`` cryptographically checks a
signed package's tamper-evidence.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Callable, Dict, Optional, Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature

from . import packaging

logger = logging.getLogger(__name__)

SIG_ALG = "ed25519"


# ---------------------------------------------------------------------------
# Key material
# ---------------------------------------------------------------------------

def key_id(pubkey_hex: str) -> str:
    """Short stable id for a public key — ``sha256(pubkey)[:16]`` in hex."""
    return hashlib.sha256(bytes.fromhex(pubkey_hex)).hexdigest()[:16]


def generate_keypair(passphrase: Optional[str] = None) -> Tuple[bytes, str]:
    """Return ``(private_pem, public_hex)`` for a fresh Ed25519 keypair.

    ``private_pem`` is PKCS8 PEM, encrypted with ``passphrase`` when supplied.
    ``public_hex`` is the 32-byte raw public key, hex-encoded — the form stored
    in the trust store and embedded in the sigblock.
    """
    priv = Ed25519PrivateKey.generate()
    enc = (
        serialization.BestAvailableEncryption(passphrase.encode("utf-8"))
        if passphrase else serialization.NoEncryption()
    )
    private_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=enc,
    )
    public_hex = public_hex_of(priv.public_key())
    return private_pem, public_hex


def public_hex_of(pub: Ed25519PublicKey) -> str:
    raw = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return raw.hex()


def load_private_key(private_pem: bytes, passphrase: Optional[str] = None) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(
        private_pem, password=passphrase.encode("utf-8") if passphrase else None
    )
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("not an Ed25519 private key")
    return key


def load_public_key(pubkey_hex: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(pubkey_hex))


# ---------------------------------------------------------------------------
# Sign
# ---------------------------------------------------------------------------

def make_signer(
    private_key: Ed25519PrivateKey,
    *,
    created_at: str = "",
) -> Callable[[bytes], Dict[str, Any]]:
    """Return the ``sign(digest) -> sigblock`` callable that :func:`pack_atlas` wants."""
    public_hex = public_hex_of(private_key.public_key())
    kid = key_id(public_hex)

    def _sign(digest: bytes) -> Dict[str, Any]:
        return {
            "alg": SIG_ALG,
            "pubkey": public_hex,
            "sig": private_key.sign(digest).hex(),
            "key_id": kid,
            "created_at": created_at,
        }

    return _sign


def sign_file(
    path,
    private_pem: bytes,
    *,
    passphrase: Optional[str] = None,
    created_at: str = "",
) -> None:
    """Re-sign an existing (unsigned or re-signed) `.atlas` file in place.

    Reads the package structurally, recomputes the digest over its exact
    manifest/payload/assets sections, and rewrites the container with a fresh
    sigblock. This lets ``atlas sign`` operate on a built artifact.
    """
    from pathlib import Path
    import struct

    path = Path(path)
    raw = path.read_bytes()
    flags, m, p, a, _s = packaging._read_header(raw, path)  # validates structure
    off = packaging.HEADER_SIZE
    manifest_bytes = raw[off : off + m]; off += m
    payload_section = raw[off : off + p]; off += p
    assets_section = raw[off : off + a]

    key = load_private_key(private_pem, passphrase)
    digest = packaging.package_digest(manifest_bytes, payload_section, assets_section)
    sigblock = make_signer(key, created_at=created_at)(digest)

    import json
    sigblock_bytes = json.dumps(sigblock, ensure_ascii=True, sort_keys=True).encode("utf-8")
    flags |= packaging.FLAG_SIGNED
    header = (
        packaging.ATLAS_MAGIC
        + struct.pack("<I", flags)
        + struct.pack("<I", len(manifest_bytes))
        + struct.pack("<I", len(payload_section))
        + struct.pack("<I", len(assets_section))
        + struct.pack("<I", len(sigblock_bytes))
    )
    path.write_bytes(header + manifest_bytes + payload_section + assets_section + sigblock_bytes)


# ---------------------------------------------------------------------------
# Verify — registered into the packaging reader
# ---------------------------------------------------------------------------

def verify_sigblock(digest: bytes, sigblock: Dict[str, Any]) -> bool:
    """True iff ``sigblock`` is a valid Ed25519 signature of ``digest``.

    This proves tamper-evidence (the bytes are exactly what the holder of the
    embedded public key signed). It does NOT establish trust — that is
    :func:`atlas_protocol.trust.resolve_trust_level`.
    """
    if not isinstance(sigblock, dict) or sigblock.get("alg") != SIG_ALG:
        return False
    pubkey_hex = sigblock.get("pubkey", "")
    sig_hex = sigblock.get("sig", "")
    if not pubkey_hex or not sig_hex:
        return False
    try:
        pub = load_public_key(pubkey_hex)
        pub.verify(bytes.fromhex(sig_hex), digest)
        return True
    except (InvalidSignature, ValueError):
        return False
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("signature verification error: %s", exc)
        return False


# Register with the format reader so read_atlas can verify signed packages.
packaging.register_signature_verifier(verify_sigblock)
