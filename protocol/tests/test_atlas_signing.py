"""Ed25519 signing, the trust store, and TrustLevel-gated loading.

Proves the launch-blocker fix: a forged/HMAC-era package is rejected, a valid
signature verifies (tamper-evidence), the trust store maps keys to FIRST_PARTY /
TRUSTED_SIGNED / UNKNOWN_SIGNED / UNSIGNED, revocation demotes a key, and the
registry refuses to execute an untrusted .atlas unless ATLAS_ALLOW_UNTRUSTED.
"""
from __future__ import annotations

import pytest

from atlas_protocol import signing, trust
from atlas_protocol.enums import TrustLevel
from atlas_protocol.packaging import (
    AtlasFormatError,
    inspect_atlas,
    pack_atlas,
    read_atlas,
    write_atlas,
)

_MANIFEST = {"name": "signed_tool", "version": "0.1.0", "description": "d", "entry_point": "wrapper.py"}
# Module-level invoke() → the registry wraps it via _FunctionWrapper.
_SOURCE = "def invoke(arguments=None, context=None):\n    return {'ok': True}\n"


@pytest.fixture
def trust_home(tmp_path, monkeypatch):
    """Point the trust store at an isolated temp dir with NO first-party keys."""
    monkeypatch.setenv("ATLAS_TRUST_DIR", str(tmp_path / "trust"))
    # Neutralize any real bundled first-party keys so tests are deterministic.
    monkeypatch.setattr(trust, "_BUNDLED_FIRST_PARTY", tmp_path / "no_first_party")
    return tmp_path


def _sign(private_pem, passphrase=None):
    key = signing.load_private_key(private_pem, passphrase)
    return signing.make_signer(key)


# --------------------------------------------------------------------------- #
# Signature validity
# --------------------------------------------------------------------------- #

def test_valid_signature_verifies(tmp_path):
    priv, pub = signing.generate_keypair()
    data = pack_atlas(_MANIFEST, _SOURCE, sign=_sign(priv))
    path = tmp_path / "p.atlas"; path.write_bytes(data)
    pkg = read_atlas(path, verify_signature=True, manifest_only=True)
    assert pkg.is_signed and pkg.signature_verified
    assert pkg.sigblock["pubkey"] == pub


def test_tampered_signed_payload_is_rejected(tmp_path):
    priv, _ = signing.generate_keypair()
    data = bytearray(pack_atlas(_MANIFEST, _SOURCE, sign=_sign(priv)))
    # Flip a byte in the payload section (just after the 28-byte header + manifest).
    data[-1] ^= 0xFF  # corrupt the sigblock tail → sig no longer matches
    path = tmp_path / "p.atlas"; path.write_bytes(bytes(data))
    with pytest.raises(AtlasFormatError, match="signature|tamper|unreadable"):
        read_atlas(path, verify_signature=True, manifest_only=True)


def test_forged_hmac_era_bytes_are_not_valid_v2(tmp_path):
    # A v1-magic file (the old forgeable HMAC format) is refused outright.
    path = tmp_path / "old.atlas"
    path.write_bytes(b"ATLAS\x00\x01\x00" + b"\x00" * 60)
    with pytest.raises(AtlasFormatError, match="v1|rebuild"):
        read_atlas(path)


def test_atlas_sign_file_in_place(tmp_path):
    path = write_atlas(tmp_path / "u.atlas", _MANIFEST, _SOURCE)  # unsigned
    assert inspect_atlas(path)["signed"] is False
    priv, pub = signing.generate_keypair()
    signing.sign_file(path, priv)
    info = inspect_atlas(path)
    assert info["signed"] is True
    pkg = read_atlas(path, verify_signature=True, manifest_only=True)
    assert pkg.signature_verified and pkg.sigblock["pubkey"] == pub


# --------------------------------------------------------------------------- #
# Trust levels
# --------------------------------------------------------------------------- #

def test_unsigned_is_unsigned(trust_home):
    lvl = trust.resolve_trust_level({}, signature_verified=False)
    assert lvl == TrustLevel.UNSIGNED


def test_unknown_publisher_is_unknown_signed(trust_home):
    _, pub = signing.generate_keypair()
    sb = {"pubkey": pub, "key_id": signing.key_id(pub)}
    lvl = trust.resolve_trust_level(sb, signature_verified=True)
    assert lvl == TrustLevel.UNKNOWN_SIGNED


def test_added_publisher_is_trusted_signed(trust_home):
    _, pub = signing.generate_keypair()
    trust.add_trusted_publisher(pub, label="acme")
    sb = {"pubkey": pub, "key_id": signing.key_id(pub)}
    assert trust.resolve_trust_level(sb, signature_verified=True) == TrustLevel.TRUSTED_SIGNED
    assert any(e["tier"] == "trusted_signed" for e in trust.list_trusted())


def test_first_party_key_is_first_party(trust_home, tmp_path, monkeypatch):
    _, pub = signing.generate_keypair()
    fp = tmp_path / "fp"; fp.mkdir()
    (fp / f"{signing.key_id(pub)}.pub").write_text(pub, encoding="utf-8")
    monkeypatch.setattr(trust, "_BUNDLED_FIRST_PARTY", fp)
    sb = {"pubkey": pub, "key_id": signing.key_id(pub)}
    assert trust.resolve_trust_level(sb, signature_verified=True) == TrustLevel.FIRST_PARTY


def test_revocation_demotes_to_unsigned(trust_home):
    _, pub = signing.generate_keypair()
    trust.add_trusted_publisher(pub)
    kid = signing.key_id(pub)
    trust.revoke(kid)
    sb = {"pubkey": pub, "key_id": kid}
    assert trust.resolve_trust_level(sb, signature_verified=True) == TrustLevel.UNSIGNED


# --------------------------------------------------------------------------- #
# Registry gating
# --------------------------------------------------------------------------- #

def _install_registry(tmp_path):
    # The runtime registry ships only with the (closed) Atlas engine. In the
    # public Atlas-SDK checkout these integration tests skip; the pure
    # signing/trust tests above run everywhere.
    registry = pytest.importorskip("app.atlas_plugin_system.registry")
    plugdir = tmp_path / "plugins"; plugdir.mkdir()
    return registry.PluginRegistry(plugin_dir=plugdir), plugdir


def test_registry_refuses_unsigned_atlas(trust_home, tmp_path, monkeypatch):
    monkeypatch.delenv("ATLAS_ALLOW_UNTRUSTED", raising=False)
    reg, plugdir = _install_registry(tmp_path)
    write_atlas(plugdir / "signed_tool.atlas", _MANIFEST, _SOURCE)  # unsigned
    reg.refresh()
    rec = reg._plugins["signed_tool"]
    assert rec.trust_level == "unsigned"
    with pytest.raises(Exception) as ei:
        reg._load_wrapper(rec)
    assert "untrusted" in str(ei.value).lower()
    assert rec.load_error and "untrusted" in rec.load_error.lower()


def test_registry_loads_trusted_atlas(trust_home, tmp_path, monkeypatch):
    monkeypatch.delenv("ATLAS_ALLOW_UNTRUSTED", raising=False)
    priv, pub = signing.generate_keypair()
    trust.add_trusted_publisher(pub)
    reg, plugdir = _install_registry(tmp_path)
    write_atlas(plugdir / "signed_tool.atlas", _MANIFEST, _SOURCE, sign=_sign(priv))
    reg.refresh()
    rec = reg._plugins["signed_tool"]
    assert rec.trust_level == "trusted_signed"
    wrapper = reg._load_wrapper(rec)   # must not raise
    assert hasattr(wrapper, "invoke")


def test_allow_untrusted_env_permits_load(trust_home, tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_ALLOW_UNTRUSTED", "1")
    reg, plugdir = _install_registry(tmp_path)
    write_atlas(plugdir / "signed_tool.atlas", _MANIFEST, _SOURCE)  # unsigned
    reg.refresh()
    rec = reg._plugins["signed_tool"]
    wrapper = reg._load_wrapper(rec)   # allowed with the opt-in
    assert hasattr(wrapper, "invoke")
