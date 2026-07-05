"""Content-addressed resolution of large `.atlas` assets (fat ML models, native libs).

A `.atlas` container stays SMALL - it never embeds a multi-GB blob. Instead the
manifest declares each large asset by content hash + a list of sources::

    "assets": [
      {"name": "model.gguf",
       "sha256": "9f86d0...",
       "size": 4600000000,
       "sources": ["file://D:/atlas-mirror/model.gguf",
                   "hf://TheBloke/foo-GGUF/model.gguf",
                   "https://cdn.example.com/model.gguf"],
       "mode": "required"}
    ]

:func:`resolve_asset` returns a local path, fetching from the first reachable
source, **streaming to disk** (never the whole blob in RAM), and **verifying the
sha256 before use**. The digest is the security boundary: even an untrusted
mirror or a hostile CDN cannot substitute a different model - a hash mismatch is
rejected. Verified blobs live in a content-addressed cache keyed by hash, so a
weight shared by several plugins is stored once.

Offline / air-gapped: pre-seed the cache or point a ``file://`` source at a local
mirror and nothing touches the network. When an asset is missing AND every source
is unreachable, resolution raises with the exact manual fetch instructions
(mirroring the connectivity-aware ``plugin_installer`` pattern) rather than
hanging.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_CHUNK = 1024 * 1024  # 1 MiB streaming chunks
_CONNECT_TIMEOUT = 5


class AssetResolutionError(Exception):
    """A declared asset could not be resolved (missing + unreachable, or hash mismatch)."""


@dataclass(frozen=True)
class AssetRef:
    """A content-addressed reference to a large external asset."""

    name: str
    sha256: str
    size: int = 0
    sources: tuple = ()
    mode: str = "required"   # "required" | "optional"

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "AssetRef":
        if not isinstance(d, dict):
            raise AssetResolutionError(f"asset ref must be an object, got {type(d).__name__}")
        name = d.get("name")
        sha = (d.get("sha256") or "").lower()
        if not name or not sha:
            raise AssetResolutionError("asset ref requires 'name' and 'sha256'")
        try:
            bytes.fromhex(sha)
        except ValueError:
            raise AssetResolutionError(f"asset '{name}' has a non-hex sha256")
        if len(sha) != 64:
            raise AssetResolutionError(f"asset '{name}' sha256 must be 64 hex chars")
        return AssetRef(
            name=name, sha256=sha, size=int(d.get("size", 0) or 0),
            sources=tuple(d.get("sources", []) or []), mode=d.get("mode", "required"),
        )

    @property
    def required(self) -> bool:
        return self.mode != "optional"


def manifest_asset_refs(manifest: Dict[str, Any]) -> List[AssetRef]:
    """Parse the manifest's ``assets`` list into AssetRefs (empty when absent)."""
    return [AssetRef.from_dict(d) for d in (manifest.get("assets") or [])]


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def cache_dir() -> Path:
    """Content-addressed asset cache (``ATLAS_ASSET_CACHE`` or ``~/.atlas/cache``)."""
    override = os.environ.get("ATLAS_ASSET_CACHE")
    return Path(override) if override else Path.home() / ".atlas" / "cache"


def _cache_path(sha256: str) -> Path:
    return cache_dir() / sha256[:2] / sha256


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _network_allowed() -> bool:
    """Downloads over the network require an explicit opt-in (offline-first doctrine)."""
    return os.environ.get("ATLAS_ALLOW_ASSET_DOWNLOAD", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


# ---------------------------------------------------------------------------
# Source fetchers - stream to a temp file, caller verifies the hash
# ---------------------------------------------------------------------------

def _fetch_file(src: str, dest: Path) -> bool:
    """A ``file://`` or bare local-path source - copy from a local mirror."""
    parsed = urlparse(src)
    if parsed.scheme in ("file", ""):
        local = Path(parsed.path if parsed.scheme == "file" else src)
        # On Windows a file:// path can arrive as /D:/x - strip the leading slash.
        if os.name == "nt" and parsed.scheme == "file" and local.as_posix().startswith("/") \
                and len(local.as_posix()) > 2 and local.as_posix()[2] == ":":
            local = Path(local.as_posix()[1:])
        if local.is_file():
            shutil.copyfile(local, dest)
            return True
    return False


def _fetch_https(src: str, dest: Path) -> bool:
    if not _network_allowed():
        return False
    import urllib.request

    req = urllib.request.Request(src, headers={"User-Agent": "atlas-asset-resolver"})
    with urllib.request.urlopen(req, timeout=_CONNECT_TIMEOUT) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out, length=_CHUNK)
    return True


def _fetch_hf(src: str, dest: Path) -> bool:
    """An ``hf://repo/path`` source - resolved only if huggingface_hub is present."""
    if not _network_allowed():
        return False
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        logger.info("hf:// source skipped (huggingface_hub not installed): %s", src)
        return False
    rest = src[len("hf://"):]
    parts = rest.split("/")
    if len(parts) < 3:
        return False
    repo_id = "/".join(parts[:2])
    filename = "/".join(parts[2:])
    downloaded = hf_hub_download(repo_id=repo_id, filename=filename)
    shutil.copyfile(downloaded, dest)
    return True


def _fetch(src: str, dest: Path) -> bool:
    scheme = urlparse(src).scheme
    if scheme in ("file", ""):
        return _fetch_file(src, dest)
    if scheme in ("http", "https"):
        return _fetch_https(src, dest)
    if scheme == "hf":
        return _fetch_hf(src, dest)
    logger.warning("unknown asset source scheme: %s", src)
    return False


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------

def resolve_asset(ref: AssetRef, *, extra_sources: Optional[List[str]] = None) -> Path:
    """Return a verified local path for ``ref``, fetching + caching as needed.

    Order: (1) cache hit -> return; (2) each declared source, then ``extra_sources``
    (a lab-wide mirror), streamed to a temp file and sha256-verified; the first
    that matches is atomically promoted into the cache. A downloaded blob whose
    hash does not match is discarded (never cached, never used).
    """
    target = _cache_path(ref.sha256)
    if target.is_file():
        return target  # content-addressed: presence at this path == verified

    target.parent.mkdir(parents=True, exist_ok=True)
    sources = list(ref.sources) + list(extra_sources or [])
    tried: List[str] = []
    for src in sources:
        tried.append(src)
        fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), suffix=".part")
        tmp = Path(tmp_name)
        os.close(fd)
        try:
            if not _fetch(src, tmp):
                continue
            actual = _sha256_file(tmp)
            if actual != ref.sha256:
                logger.warning(
                    "asset '%s' from %s has sha256 %s (expected %s) - rejected",
                    ref.name, src, actual, ref.sha256,
                )
                continue
            os.replace(tmp, target)  # atomic promote
            logger.info("resolved asset '%s' (%s) from %s", ref.name, ref.sha256[:12], src)
            return target
        except Exception as exc:
            logger.warning("asset '%s' source %s failed: %s", ref.name, src, exc)
        finally:
            tmp.unlink(missing_ok=True)

    hint = _manual_hint(ref)
    raise AssetResolutionError(
        f"could not resolve asset '{ref.name}' (sha256 {ref.sha256[:12]}...). "
        f"Tried {len(tried)} source(s). {hint}"
    )


def _manual_hint(ref: AssetRef) -> str:
    dest = _cache_path(ref.sha256)
    net = "" if _network_allowed() else (
        "Network fetch is disabled - set ATLAS_ALLOW_ASSET_DOWNLOAD=1 to enable, or "
    )
    return (
        f"{net}place the file at '{dest}' (a local mirror), or point a source at it "
        f"via a file:// URL. Verify it hashes to {ref.sha256}."
    )


def resolve_manifest_assets(
    manifest: Dict[str, Any],
    *,
    extra_sources: Optional[List[str]] = None,
) -> Dict[str, Optional[Path]]:
    """Resolve every declared asset -> ``{name: path}``.

    A ``required`` asset that cannot be resolved raises; an ``optional`` one that
    is unreachable maps to ``None`` so the plugin can degrade gracefully.
    """
    out: Dict[str, Optional[Path]] = {}
    for ref in manifest_asset_refs(manifest):
        try:
            out[ref.name] = resolve_asset(ref, extra_sources=extra_sources)
        except AssetResolutionError:
            if ref.required:
                raise
            logger.info("optional asset '%s' unresolved - continuing", ref.name)
            out[ref.name] = None
    return out
