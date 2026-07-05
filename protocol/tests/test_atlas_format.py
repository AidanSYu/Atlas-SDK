"""Round-trip + hardening tests for the canonical `.atlas` v2 container.

Covers pack/read fidelity (source-bundle payload, cleartext manifest, encrypted
sections, embedded assets), the loader, and — critically — that a malformed,
truncated, oversized, trailing-garbage, or legacy-v1 file is rejected with a
typed :class:`AtlasFormatError` rather than crashing or silently mis-parsing.
"""
from __future__ import annotations

import struct

import pytest

from atlas_protocol import packaging as pk
from atlas_protocol.packaging import (
    ATLAS_MAGIC,
    ATLAS_MAGIC_V1,
    HEADER_SIZE,
    AtlasFormatError,
    inspect_atlas,
    load_atlas_module,
    pack_atlas,
    pack_plugin_directory,
    read_atlas,
    write_atlas,
)

_MANIFEST = {"name": "demo_tool", "version": "0.1.0", "description": "d", "entry_point": "wrapper.py"}
_SOURCE = "def invoke(a, c=None):\n    return {'ok': True, 'echo': a}\nPLUGIN = invoke\n"


def _write(tmp_path, **kw):
    return write_atlas(tmp_path / "demo.atlas", _MANIFEST, _SOURCE, **kw)


# --------------------------------------------------------------------------- #
# Round-trip fidelity
# --------------------------------------------------------------------------- #

def test_pack_read_roundtrip_plaintext(tmp_path):
    path = _write(tmp_path)
    pkg = read_atlas(path)
    assert pkg.manifest == _MANIFEST
    assert not pkg.is_encrypted and not pkg.is_signed
    # payload is a zip SOURCE bundle, not marshalled bytecode
    assert pkg.payload_bytes[:2] == b"PK"


def test_manifest_is_cleartext_without_key(tmp_path):
    path = _write(tmp_path, passphrase="s3cret")
    # inspect never decrypts — manifest must still be readable
    info = inspect_atlas(path)
    assert info["manifest"]["name"] == "demo_tool"
    assert info["encrypted"] is True


def test_encrypted_roundtrip_requires_key(tmp_path):
    path = _write(tmp_path, passphrase="s3cret")
    with pytest.raises(AtlasFormatError, match="encrypted"):
        read_atlas(path)                       # no passphrase
    with pytest.raises(AtlasFormatError):
        read_atlas(path, passphrase="wrong")   # wrong key → GCM tag fails
    pkg = read_atlas(path, passphrase="s3cret")
    assert pkg.payload_bytes[:2] == b"PK"


def test_embedded_assets_roundtrip(tmp_path):
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data.txt", "hello")
    path = _write(tmp_path, assets_bytes=buf.getvalue())
    pkg = read_atlas(path)
    assert pkg.has_assets
    with zipfile.ZipFile(io.BytesIO(pkg.assets_bytes)) as zf:
        assert zf.read("data.txt") == b"hello"


def test_load_module_execs_entry_point(tmp_path):
    path = _write(tmp_path)
    pkg = read_atlas(path)
    module = load_atlas_module(pkg, cache_dir=tmp_path / "cache")
    assert "PLUGIN" in module.__dict__
    assert module.__dict__["__atlas_manifest__"]["name"] == "demo_tool"


def test_pack_plugin_directory_bundles_helpers(tmp_path):
    d = tmp_path / "plug"
    d.mkdir()
    (d / "manifest.json").write_text('{"name":"p","description":"x"}', encoding="utf-8")
    (d / "wrapper.py").write_text("from helper import v\nPLUGIN=lambda a,c=None:{'v':v}\n", encoding="utf-8")
    (d / "helper.py").write_text("v = 42\n", encoding="utf-8")
    data = pack_plugin_directory(d, {"name": "p", "description": "x", "entry_point": "wrapper.py"})
    (tmp_path / "p.atlas").write_bytes(data)
    pkg = read_atlas(tmp_path / "p.atlas")
    module = load_atlas_module(pkg, cache_dir=tmp_path / "c")
    assert module.__dict__["PLUGIN"](None) == {"v": 42}


# --------------------------------------------------------------------------- #
# Reader hardening — every malformed input raises a typed error, never crashes
# --------------------------------------------------------------------------- #

def test_rejects_too_small(tmp_path):
    p = tmp_path / "x.atlas"
    p.write_bytes(b"tiny")
    with pytest.raises(AtlasFormatError, match="too small"):
        read_atlas(p)


def test_rejects_bad_magic(tmp_path):
    p = tmp_path / "x.atlas"
    p.write_bytes(b"NOTATLAS" + b"\x00" * 40)
    with pytest.raises(AtlasFormatError, match="magic"):
        read_atlas(p)


def test_rejects_legacy_v1_with_rebuild_hint(tmp_path):
    p = tmp_path / "x.atlas"
    p.write_bytes(ATLAS_MAGIC_V1 + b"\x00" * 40)
    with pytest.raises(AtlasFormatError, match="v1|rebuild"):
        read_atlas(p)


def test_rejects_truncated_sections(tmp_path):
    path = _write(tmp_path)
    raw = path.read_bytes()
    path.write_bytes(raw[:-5])           # chop the tail
    with pytest.raises(AtlasFormatError, match="size|truncat"):
        read_atlas(path)


def test_rejects_trailing_garbage(tmp_path):
    path = _write(tmp_path)
    raw = path.read_bytes()
    path.write_bytes(raw + b"EXTRA-HIDDEN-DATA")
    with pytest.raises(AtlasFormatError, match="size|trailing"):
        read_atlas(path)


def test_rejects_size_field_overflow(tmp_path):
    # A manifest_size that claims more than the file holds must be rejected by the
    # exact-sum check, not silently produce a short slice.
    path = _write(tmp_path)
    raw = bytearray(path.read_bytes())
    struct.pack_into("<I", raw, len(ATLAS_MAGIC) + 4, 0xFFFFFF)  # manifest_size huge
    path.write_bytes(bytes(raw))
    with pytest.raises(AtlasFormatError):
        read_atlas(path)


def test_rejects_malformed_manifest_json(tmp_path):
    # Hand-build a container whose manifest bytes are not valid JSON.
    bad = b"{not json"
    payload = b"PK\x00\x00"
    header = (ATLAS_MAGIC + struct.pack("<I", 0)
              + struct.pack("<I", len(bad)) + struct.pack("<I", len(payload))
              + struct.pack("<I", 0) + struct.pack("<I", 0))
    p = tmp_path / "x.atlas"
    p.write_bytes(header + bad + payload)
    with pytest.raises(AtlasFormatError, match="manifest"):
        read_atlas(p)


def test_rejects_oversized_container(tmp_path, monkeypatch):
    path = _write(tmp_path)
    monkeypatch.setattr(pk, "MAX_CONTAINER_BYTES", 8)
    with pytest.raises(AtlasFormatError, match="bytes"):
        read_atlas(path)


def test_header_size_constant():
    assert HEADER_SIZE == len(ATLAS_MAGIC) + 20
