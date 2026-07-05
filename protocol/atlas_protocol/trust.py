"""The local trust store — maps a signed package's public key to a TrustLevel.

A valid Ed25519 signature proves *tamper-evidence* (see :mod:`.signing`); the
trust store answers the separate question *"whose key is this, and are they
allowed to run in-proc?"*:

* ``FIRST_PARTY``    — key shipped with Atlas (``keys/first_party/*.pub``)
* ``TRUSTED_SIGNED`` — key a lab added to ``~/.atlas/trust/publishers/``
* ``UNKNOWN_SIGNED`` — a valid signature by a key nobody has trusted
* ``UNSIGNED``       — no signature, an invalid one, or a revoked key

The store is plain files so it works fully offline / air-gapped: a lab imports a
publisher's ``.pub`` once (out-of-band — USB, internal share) and thereafter that
publisher's packages are trusted with zero network. Revocation is a best-effort
local ``revoked.json``.

Layout::

    $ATLAS_TRUST_DIR (default ~/.atlas/trust)/
        publishers/<key_id>.pub     one hex public key per file
        revoked.json                {"key_ids": [...]}

    <bundled>/keys/first_party/*.pub   shipped with the distribution
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from .enums import TrustLevel
from . import signing

logger = logging.getLogger(__name__)

_BUNDLED_FIRST_PARTY = Path(__file__).resolve().parent / "keys" / "first_party"


def trust_dir() -> Path:
    """Root of the per-user trust store (``ATLAS_TRUST_DIR`` or ``~/.atlas/trust``)."""
    override = os.environ.get("ATLAS_TRUST_DIR")
    base = Path(override) if override else Path.home() / ".atlas" / "trust"
    return base


def _publishers_dir() -> Path:
    return trust_dir() / "publishers"


def _revoked_path() -> Path:
    return trust_dir() / "revoked.json"


def _load_pubkeys(directory: Path) -> Dict[str, str]:
    """Return ``{key_id: pubkey_hex}`` from every ``*.pub`` in a directory."""
    out: Dict[str, str] = {}
    if not directory.is_dir():
        return out
    for pub in sorted(directory.glob("*.pub")):
        try:
            hexval = pub.read_text(encoding="utf-8").strip()
            # tolerate a hex key, optionally as "<hex>  # comment"
            hexval = hexval.split()[0]
            bytes.fromhex(hexval)  # validate
            out[signing.key_id(hexval)] = hexval
        except Exception as exc:  # skip a malformed key file rather than fail closed on all
            logger.warning("ignoring malformed trust key %s: %s", pub, exc)
    return out


def first_party_keys() -> Dict[str, str]:
    return _load_pubkeys(_BUNDLED_FIRST_PARTY)


def trusted_publisher_keys() -> Dict[str, str]:
    return _load_pubkeys(_publishers_dir())


def revoked_key_ids() -> set[str]:
    path = _revoked_path()
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("key_ids", []))
    except Exception as exc:
        logger.warning("unreadable revocation list %s: %s", path, exc)
        return set()


# ---------------------------------------------------------------------------
# The load-bearing decision
# ---------------------------------------------------------------------------

def resolve_trust_level(sigblock: Optional[Dict], *, signature_verified: bool) -> TrustLevel:
    """Map a (cryptographically verified) sigblock to a TrustLevel.

    ``signature_verified`` MUST be the result of the crypto check — a sigblock
    whose signature did not verify is treated as UNSIGNED regardless of contents.
    """
    if not sigblock or not signature_verified:
        return TrustLevel.UNSIGNED

    pubkey_hex = sigblock.get("pubkey", "")
    if not pubkey_hex:
        return TrustLevel.UNSIGNED
    kid = sigblock.get("key_id") or signing.key_id(pubkey_hex)

    if kid in revoked_key_ids():
        logger.warning("package signed by REVOKED key %s — treating as unsigned", kid)
        return TrustLevel.UNSIGNED

    if pubkey_hex in first_party_keys().values():
        return TrustLevel.FIRST_PARTY
    if pubkey_hex in trusted_publisher_keys().values():
        return TrustLevel.TRUSTED_SIGNED
    return TrustLevel.UNKNOWN_SIGNED


def is_trusted(level: TrustLevel) -> bool:
    """Whether a package at this level may execute in-proc (the fast path)."""
    return level in (TrustLevel.FIRST_PARTY, TrustLevel.TRUSTED_SIGNED)


# ---------------------------------------------------------------------------
# Store management (used by `atlas trust ...`)
# ---------------------------------------------------------------------------

def add_trusted_publisher(pubkey_hex: str, *, label: str = "") -> str:
    """Trust a publisher's public key. Returns its key_id."""
    pubkey_hex = pubkey_hex.strip().split()[0]
    bytes.fromhex(pubkey_hex)  # validate
    kid = signing.key_id(pubkey_hex)
    pub_dir = _publishers_dir()
    pub_dir.mkdir(parents=True, exist_ok=True)
    content = pubkey_hex + (f"  # {label}" if label else "")
    (pub_dir / f"{kid}.pub").write_text(content, encoding="utf-8")
    logger.info("trusted publisher key %s%s", kid, f" ({label})" if label else "")
    return kid


def remove_trusted_publisher(key_id: str) -> bool:
    path = _publishers_dir() / f"{key_id}.pub"
    if path.exists():
        path.unlink()
        return True
    return False


def list_trusted() -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for kid, hexval in first_party_keys().items():
        out.append({"key_id": kid, "pubkey": hexval, "tier": "first_party"})
    for kid, hexval in trusted_publisher_keys().items():
        out.append({"key_id": kid, "pubkey": hexval, "tier": "trusted_signed"})
    return out


def revoke(key_id: str) -> None:
    path = _revoked_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = revoked_key_ids()
    ids.add(key_id)
    path.write_text(json.dumps({"key_ids": sorted(ids)}, indent=2), encoding="utf-8")
    logger.info("revoked key %s", key_id)
