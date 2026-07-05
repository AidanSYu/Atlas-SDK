"""Content-addressed resolution of large external `.atlas` assets.

Proves the fat-model story: the digest is the tamper boundary (a mirror can't
swap the file), a cache hit skips the fetch, a local mirror resolves fully
offline, sources fail over, a required-but-unreachable asset raises with manual
instructions, optional assets degrade to None, and the loader injects resolved
paths into the plugin namespace.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from atlas_protocol import assets
from atlas_protocol.assets import (
    AssetRef,
    AssetResolutionError,
    resolve_asset,
    resolve_manifest_assets,
)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_ASSET_CACHE", str(tmp_path / "cache"))
    monkeypatch.delenv("ATLAS_ALLOW_ASSET_DOWNLOAD", raising=False)
    return tmp_path


def _blob(tmp_path, name, content=b"weights-v1"):
    p = tmp_path / name
    p.write_bytes(content)
    return p, hashlib.sha256(content).hexdigest()


def _ref(name, sha, sources, mode="required", size=0):
    return AssetRef(name=name, sha256=sha, size=size, sources=tuple(sources), mode=mode)


def test_local_mirror_resolves_offline(cache, tmp_path):
    blob, sha = _blob(tmp_path, "model.bin")
    ref = _ref("model.bin", sha, [f"file://{blob.as_posix()}"])
    resolved = resolve_asset(ref)
    assert resolved.is_file()
    assert hashlib.sha256(resolved.read_bytes()).hexdigest() == sha


def test_rfc_file_uri_source_resolves(cache, tmp_path):
    # Path.as_uri() emits the RFC form (file:///C:/x on Windows, file:///home/x
    # elsewhere); the two-slash file://C:/x form is covered by the tests above.
    # Regression: the drive letter must survive urlparse on every platform even
    # when the current working drive differs (the CI-runner case).
    blob, sha = _blob(tmp_path, "model.bin")
    ref = _ref("model.bin", sha, [blob.as_uri()])
    resolved = resolve_asset(ref)
    assert resolved.is_file()
    assert hashlib.sha256(resolved.read_bytes()).hexdigest() == sha


def test_cache_hit_skips_fetch(cache, tmp_path):
    blob, sha = _blob(tmp_path, "model.bin")
    ref = _ref("model.bin", sha, [f"file://{blob.as_posix()}"])
    first = resolve_asset(ref)
    blob.unlink()                       # remove the only source
    second = resolve_asset(ref)         # must still resolve from cache
    assert second == first and second.is_file()


def test_digest_mismatch_is_rejected(cache, tmp_path):
    blob, _ = _blob(tmp_path, "model.bin", b"real-weights")
    wrong_sha = hashlib.sha256(b"different").hexdigest()
    ref = _ref("model.bin", wrong_sha, [f"file://{blob.as_posix()}"])
    with pytest.raises(AssetResolutionError, match="could not resolve"):
        resolve_asset(ref)
    # nothing poisoned the cache
    assert not (assets._cache_path(wrong_sha)).exists()


def test_source_failover(cache, tmp_path):
    blob, sha = _blob(tmp_path, "model.bin")
    ref = _ref("model.bin", sha, [
        "file://Z:/does/not/exist.bin",             # unreachable
        f"file://{blob.as_posix()}",                # good
    ])
    assert resolve_asset(ref).is_file()


def test_required_unreachable_raises_with_hint(cache):
    sha = hashlib.sha256(b"x").hexdigest()
    ref = _ref("model.bin", sha, ["file://Z:/nope.bin"])
    with pytest.raises(AssetResolutionError, match="mirror|ATLAS_ALLOW_ASSET_DOWNLOAD|place the file"):
        resolve_asset(ref)


def test_optional_unreachable_returns_none(cache):
    sha = hashlib.sha256(b"x").hexdigest()
    manifest = {"assets": [{"name": "opt.bin", "sha256": sha,
                            "sources": ["file://Z:/nope.bin"], "mode": "optional"}]}
    resolved = resolve_manifest_assets(manifest)
    assert resolved == {"opt.bin": None}


def test_https_source_needs_download_optin(cache):
    sha = hashlib.sha256(b"x").hexdigest()
    ref = _ref("model.bin", sha, ["https://example.invalid/model.bin"])
    # network disabled by default → the https source is skipped, resolution fails
    with pytest.raises(AssetResolutionError):
        resolve_asset(ref)


def test_asset_ref_validation():
    with pytest.raises(AssetResolutionError, match="name"):
        AssetRef.from_dict({"sha256": "a" * 64})
    with pytest.raises(AssetResolutionError, match="64 hex"):
        AssetRef.from_dict({"name": "m", "sha256": "abcd"})   # valid hex, wrong length
    with pytest.raises(AssetResolutionError, match="non-hex"):
        AssetRef.from_dict({"name": "m", "sha256": "z" * 64})  # right length, non-hex


def test_loader_injects_resolved_asset_paths(cache, tmp_path):
    from atlas_protocol.packaging import load_atlas_module, read_atlas, write_atlas

    blob, sha = _blob(tmp_path, "model.bin", b"model-bytes")
    manifest = {
        "name": "asset_plugin", "description": "x", "entry_point": "wrapper.py",
        "assets": [{"name": "model.bin", "sha256": sha, "sources": [f"file://{blob.as_posix()}"]}],
    }
    src = "def invoke(a, c=None):\n    return {'ok': True}\n"
    path = write_atlas(tmp_path / "a.atlas", manifest, src)
    pkg = read_atlas(path)
    module = load_atlas_module(pkg, cache_dir=tmp_path / "srccache")
    paths = module.__dict__["__atlas_asset_paths__"]
    assert "model.bin" in paths and Path(paths["model.bin"]).is_file()
