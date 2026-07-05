"""The single canonical `.atlas` container format (v2).

This module is the ONE reader/writer for `.atlas` packages. The backend runtime
(`app.atlas_plugin_system.atlas_format`) and the SDK (`atlas_sdk.format`) both
re-export from here — there is no forked format module and no forked signature.

Container layout (v2)
---------------------
::

    MAGIC          8   b"ATLAS\\x00\\x02\\x00"
    FLAGS          4   uint32-LE  (bit0=encrypted, bit1=has_assets, bit2=signed)
    MANIFEST_SIZE  4   uint32-LE
    PAYLOAD_SIZE   4   uint32-LE
    ASSETS_SIZE    4   uint32-LE
    SIGBLOCK_SIZE  4   uint32-LE
    MANIFEST       var cleartext JSON  (invariant — discoverable without a key)
    PAYLOAD        var zipped .py SOURCE bundle; AES-256-GCM when encrypted
    ASSETS         var zip of SMALL embedded assets; AES-256-GCM when encrypted
    SIGBLOCK       var JSON {alg,pubkey,sig,key_id,created_at}  (empty when unsigned)

Design notes
------------
* **Source, not bytecode.** The payload is a zip of Python *source* files, not
  marshalled CPython bytecode. This is portable across interpreters, statically
  inspectable (the import-isolation guard can scan it), and removes the
  ``marshal.loads``-on-untrusted-input interpreter-crash surface.
* **Manifest is always cleartext** so the registry can discover kind / effects /
  permissions / asset refs without a decryption key.
* **Signature is asymmetric (Ed25519), carried in SIGBLOCK.** Signing is done by
  :mod:`atlas_protocol.signing` (Phase 2); this module only *carries* the
  sigblock and delegates verification to it via a lazy import, so the format
  layer stays free of a hard crypto-policy dependency.
* **Large binaries are NOT embedded.** Fat models / native libs are declared as
  content-addressed :class:`atlas_protocol.assets.AssetRef` entries in the
  manifest and resolved at load time. The container itself stays small, so a
  full ``read_bytes`` is safe and cheap.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ATLAS_MAGIC = b"ATLAS\x00\x02\x00"       # 8 bytes — v2
ATLAS_MAGIC_V1 = b"ATLAS\x00\x01\x00"    # legacy — rejected with a rebuild hint
HEADER_SIZE = len(ATLAS_MAGIC) + 4 + 4 + 4 + 4 + 4  # magic + flags + 4 sizes = 28

FLAG_ENCRYPTED = 1 << 0
FLAG_HAS_ASSETS = 1 << 1
FLAG_SIGNED = 1 << 2

PBKDF2_ITERATIONS = 600_000
SALT_SIZE = 16
NONCE_SIZE = 12
GCM_TAG_SIZE = 16

# A `.atlas` carries manifest + source + SMALL embedded assets only; fat blobs
# are external content-addressed refs. Cap the whole container so a hostile or
# corrupt file cannot force an unbounded read. The HTTP import route applies its
# own (configurable) cap on top of this.
MAX_CONTAINER_BYTES = 64 * 1024 * 1024   # 64 MiB
MAX_MANIFEST_BYTES = 4 * 1024 * 1024     # 4 MiB of cleartext JSON is already absurd

DEFAULT_ENTRY_POINT = "wrapper.py"

# A signature verifier is injected by atlas_protocol.signing at import time so
# this module never hard-depends on the crypto policy. Signature: (digest:bytes,
# sigblock:dict) -> bool. None => signature parsed but not cryptographically
# checked (Phase-1 / SDK-inspect contexts).
_SIGNATURE_VERIFIER: Optional[Callable[[bytes, Dict[str, Any]], bool]] = None


class AtlasFormatError(Exception):
    """A `.atlas` file is malformed, truncated, oversized, or wrong-version."""


def register_signature_verifier(fn: Callable[[bytes, Dict[str, Any]], bool]) -> None:
    """Install the crypto verifier used by :func:`read_atlas` for signed packages."""
    global _SIGNATURE_VERIFIER
    _SIGNATURE_VERIFIER = fn


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class AtlasPackage:
    """In-memory representation of a parsed `.atlas` file."""

    manifest: Dict[str, Any]
    payload_bytes: bytes                  # decrypted source-bundle zip
    assets_bytes: bytes = b""             # decrypted embedded-assets zip (may be empty)
    flags: int = 0
    sigblock: Dict[str, Any] = field(default_factory=dict)
    signature_verified: bool = False      # crypto sig checked against embedded pubkey
    source_path: Optional[Path] = None

    @property
    def is_encrypted(self) -> bool:
        return bool(self.flags & FLAG_ENCRYPTED)

    @property
    def has_assets(self) -> bool:
        return bool(self.flags & FLAG_HAS_ASSETS)

    @property
    def is_signed(self) -> bool:
        return bool(self.flags & FLAG_SIGNED)

    @property
    def code_bytes(self) -> bytes:
        """Back-compat alias — the payload is now a source bundle, not bytecode."""
        return self.payload_bytes


# ---------------------------------------------------------------------------
# Encryption helpers (AES-256-GCM via cryptography)
# ---------------------------------------------------------------------------

def _derive_key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, PBKDF2_ITERATIONS)


def _encrypt_section(plaintext: bytes, passphrase: str) -> bytes:
    """AES-256-GCM → SALT(16) | NONCE(12) | CIPHERTEXT+TAG."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt = os.urandom(SALT_SIZE)
    key = _derive_key(passphrase, salt)
    nonce = os.urandom(NONCE_SIZE)
    return salt + nonce + AESGCM(key).encrypt(nonce, plaintext, None)


def _decrypt_section(blob: bytes, passphrase: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if len(blob) < SALT_SIZE + NONCE_SIZE + GCM_TAG_SIZE:
        raise AtlasFormatError("encrypted section too short to contain salt+nonce+tag")
    salt = blob[:SALT_SIZE]
    nonce = blob[SALT_SIZE : SALT_SIZE + NONCE_SIZE]
    ct = blob[SALT_SIZE + NONCE_SIZE :]
    try:
        return AESGCM(_derive_key(passphrase, salt)).decrypt(nonce, ct, None)
    except Exception as exc:  # InvalidTag etc. — wrong key or tampered ciphertext
        raise AtlasFormatError(f"decryption failed (wrong key or tampered payload): {exc}") from exc


# ---------------------------------------------------------------------------
# Digest — the bytes a signature covers
# ---------------------------------------------------------------------------

def package_digest(manifest_bytes: bytes, payload_section: bytes, assets_section: bytes) -> bytes:
    """sha256 over the exact on-disk (post-encryption) manifest+payload+assets."""
    h = hashlib.sha256()
    h.update(manifest_bytes)
    h.update(payload_section)
    h.update(assets_section)
    return h.digest()


# ---------------------------------------------------------------------------
# Source-bundle + asset collection (the ONE collect_assets — collapses the
# three divergent bundlers: sdk._collect_assets, compile_all_plugins,
# compile_plugins).
# ---------------------------------------------------------------------------

_SOURCE_SUFFIXES = {".py"}
_SKIP_SUFFIXES = {".pyc", ".pyo", ".atlas"}
# Files above this size must be declared as content-addressed asset refs, not
# embedded — a multi-GB blob has no business inside the signed container.
MAX_EMBEDDED_ASSET_BYTES = 10 * 1024 * 1024   # 10 MiB


def build_source_bundle(entry_point: str, source_code: str,
                        additional_sources: Optional[Dict[str, str]] = None) -> bytes:
    """Zip the entry point + optional helper modules into the payload bundle."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(entry_point, source_code)
        for name, src in (additional_sources or {}).items():
            if name == entry_point:
                continue
            zf.writestr(name, src)
    return buf.getvalue()


def gather_sources(plugin_dir: Path, manifest: Dict[str, Any]) -> tuple[str, Dict[str, str]]:
    """Return ``(entry_source, {helper_name: source})`` for all `.py` in a dir."""
    plugin_dir = Path(plugin_dir)
    entry_point = manifest.get("entry_point", DEFAULT_ENTRY_POINT)
    entry_path = plugin_dir / entry_point
    if not entry_path.is_file():
        raise AtlasFormatError(f"entry point not found: {entry_path}")

    sources: Dict[str, str] = {}
    for py in sorted(plugin_dir.rglob("*.py")):
        if not py.is_file() or py.name.startswith("."):
            continue
        rel = py.relative_to(plugin_dir).as_posix()
        sources[rel] = py.read_text(encoding="utf-8")
    entry_src = sources.pop(entry_point, entry_path.read_text(encoding="utf-8"))
    return entry_src, sources


def collect_assets(plugin_dir: Path, manifest: Dict[str, Any], *,
                   max_embedded_bytes: int = MAX_EMBEDDED_ASSET_BYTES) -> bytes:
    """Zip SMALL non-`.py` asset files into the embedded-assets section.

    Honors ``manifest['artifacts']`` (explicit files/dirs) and an ``assets/``
    convention folder. Files larger than ``max_embedded_bytes`` are refused with
    a pointer to content-addressed asset refs — the container must stay small.
    """
    plugin_dir = Path(plugin_dir)
    entry_point = manifest.get("entry_point", DEFAULT_ENTRY_POINT)
    entries: List[tuple[Path, str]] = []
    seen: set[str] = set()

    def _add(path: Path, arc: str) -> None:
        if not path.is_file():
            return
        arc = arc.replace("\\", "/")
        if arc in seen or path.name == entry_point or path.suffix in _SOURCE_SUFFIXES:
            return
        if path.name.startswith(".") or path.suffix in _SKIP_SUFFIXES:
            return
        size = path.stat().st_size
        if size > max_embedded_bytes:
            raise AtlasFormatError(
                f"asset '{arc}' is {size:,} bytes (> {max_embedded_bytes:,}). "
                "Large binaries must be declared as content-addressed asset refs "
                "in the manifest (assets: [{name, sha256, size, sources}]), not embedded."
            )
        seen.add(arc)
        entries.append((path, arc))

    for relative in manifest.get("artifacts", []) or []:
        ap = (plugin_dir / relative).resolve()
        if ap.is_file():
            _add(ap, str(Path(relative).as_posix()))
        elif ap.is_dir():
            for nested in sorted(ap.rglob("*")):
                if nested.is_file():
                    _add(nested, (Path(relative) / nested.relative_to(ap)).as_posix())

    assets_dir = plugin_dir / "assets"
    if assets_dir.is_dir():
        for nested in sorted(assets_dir.rglob("*")):
            if nested.is_file():
                _add(nested, "assets/" + nested.relative_to(assets_dir).as_posix())

    if not entries:
        return b""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, arc in entries:
            zf.write(path, arc)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def pack_atlas(
    manifest: Dict[str, Any],
    source_code: str,
    *,
    additional_sources: Optional[Dict[str, str]] = None,
    assets_bytes: bytes = b"",
    passphrase: Optional[str] = None,
    sign: Optional[Callable[[bytes], Dict[str, Any]]] = None,
) -> bytes:
    """Pack a manifest + source into the `.atlas` v2 container.

    Parameters
    ----------
    manifest : dict
        Plugin manifest (cleartext). Must include at least ``name``.
    source_code : str
        Source of the entry-point module (default ``wrapper.py``).
    additional_sources : dict, optional
        ``{filename: source}`` helper modules bundled alongside the entry point.
    assets_bytes : bytes
        Optional zip of SMALL embedded assets (see :func:`collect_assets`).
    passphrase : str, optional
        If set, encrypts the payload (and assets) with AES-256-GCM.
    sign : callable, optional
        ``(digest: bytes) -> sigblock: dict`` producing the Ed25519 signature
        block (supplied by :mod:`atlas_protocol.signing`). ``None`` → unsigned.
    """
    entry_point = manifest.get("entry_point", DEFAULT_ENTRY_POINT)
    payload = build_source_bundle(entry_point, source_code, additional_sources)

    flags = 0
    if passphrase:
        flags |= FLAG_ENCRYPTED
    if assets_bytes:
        flags |= FLAG_HAS_ASSETS

    if passphrase:
        payload_section = _encrypt_section(payload, passphrase)
        assets_section = _encrypt_section(assets_bytes, passphrase) if assets_bytes else b""
    else:
        payload_section = payload
        assets_section = assets_bytes

    manifest_bytes = json.dumps(manifest, ensure_ascii=True, indent=2).encode("utf-8")

    sigblock_bytes = b""
    if sign is not None:
        digest = package_digest(manifest_bytes, payload_section, assets_section)
        sigblock = sign(digest)
        sigblock_bytes = json.dumps(sigblock, ensure_ascii=True, sort_keys=True).encode("utf-8")
        flags |= FLAG_SIGNED

    header = (
        ATLAS_MAGIC
        + struct.pack("<I", flags)
        + struct.pack("<I", len(manifest_bytes))
        + struct.pack("<I", len(payload_section))
        + struct.pack("<I", len(assets_section))
        + struct.pack("<I", len(sigblock_bytes))
    )
    return header + manifest_bytes + payload_section + assets_section + sigblock_bytes


def write_atlas(
    output_path: Path,
    manifest: Dict[str, Any],
    source_code: str,
    *,
    additional_sources: Optional[Dict[str, str]] = None,
    assets_bytes: bytes = b"",
    passphrase: Optional[str] = None,
    sign: Optional[Callable[[bytes], Dict[str, Any]]] = None,
) -> Path:
    """Pack and write a `.atlas` file to disk."""
    data = pack_atlas(
        manifest, source_code, additional_sources=additional_sources,
        assets_bytes=assets_bytes, passphrase=passphrase, sign=sign,
    )
    output_path = Path(output_path)
    output_path.write_bytes(data)
    logger.info("Wrote .atlas package: %s (%d bytes)", output_path, len(data))
    return output_path


def pack_plugin_directory(
    plugin_dir: Path,
    manifest: Dict[str, Any],
    *,
    passphrase: Optional[str] = None,
    sign: Optional[Callable[[bytes], Dict[str, Any]]] = None,
) -> bytes:
    """Build a `.atlas` from a plugin directory — the ONE directory bundler.

    Collapses the three historically divergent bundlers (SDK ``_collect_assets``,
    ``compile_all_plugins``, ``compile_plugins``): gathers every `.py` as the
    source bundle and every small non-`.py` asset as the embedded section.
    """
    plugin_dir = Path(plugin_dir)
    entry_src, additional = gather_sources(plugin_dir, manifest)
    assets_bytes = collect_assets(plugin_dir, manifest)
    return pack_atlas(
        manifest, entry_src, additional_sources=additional,
        assets_bytes=assets_bytes, passphrase=passphrase, sign=sign,
    )


# ---------------------------------------------------------------------------
# Reader (hardened)
# ---------------------------------------------------------------------------

def _read_header(raw: bytes, file_path: Path) -> tuple[int, int, int, int, int]:
    """Parse + fully validate the header. Returns (flags, m, p, a, s) sizes."""
    if len(raw) < HEADER_SIZE:
        raise AtlasFormatError(f"file too small to be a valid .atlas package: {file_path}")

    magic = raw[: len(ATLAS_MAGIC)]
    if magic != ATLAS_MAGIC:
        if magic == ATLAS_MAGIC_V1:
            raise AtlasFormatError(
                f"{file_path} is a legacy v1 .atlas (HMAC/bytecode) and is no longer "
                "supported. Rebuild it with `atlas build`."
            )
        raise AtlasFormatError(f"invalid .atlas magic bytes in {file_path}")

    off = len(ATLAS_MAGIC)
    flags = struct.unpack_from("<I", raw, off)[0]; off += 4
    manifest_size = struct.unpack_from("<I", raw, off)[0]; off += 4
    payload_size = struct.unpack_from("<I", raw, off)[0]; off += 4
    assets_size = struct.unpack_from("<I", raw, off)[0]; off += 4
    sigblock_size = struct.unpack_from("<I", raw, off)[0]; off += 4

    if manifest_size > MAX_MANIFEST_BYTES:
        raise AtlasFormatError(f"manifest section implausibly large ({manifest_size:,} bytes)")

    # The four sections must account for EVERY byte after the header — no
    # truncation, no trailing/hidden data smuggled past the declared sizes.
    expected = HEADER_SIZE + manifest_size + payload_size + assets_size + sigblock_size
    if expected != len(raw):
        raise AtlasFormatError(
            f"{file_path} section sizes ({manifest_size}+{payload_size}+{assets_size}+"
            f"{sigblock_size}) + header {HEADER_SIZE} = {expected} != file size {len(raw)} "
            "(truncated, corrupt, or trailing data)."
        )
    return flags, manifest_size, payload_size, assets_size, sigblock_size


def read_atlas(
    file_path: Path,
    *,
    passphrase: Optional[str] = None,
    verify_signature: bool = True,
    manifest_only: bool = False,
) -> AtlasPackage:
    """Read + parse a `.atlas` v2 file, validating structure before trusting it.

    ``verify_signature`` cryptographically checks the Ed25519 signature against
    the pubkey embedded in the sigblock (tamper-evidence). It does NOT decide
    *trust level* — that is :func:`atlas_protocol.trust.resolve_trust_level`,
    which maps the pubkey to the local trust store.
    """
    file_path = Path(file_path)
    try:
        size = file_path.stat().st_size
    except OSError as exc:
        raise AtlasFormatError(f"cannot stat {file_path}: {exc}") from exc
    if size > MAX_CONTAINER_BYTES:
        raise AtlasFormatError(
            f"{file_path} is {size:,} bytes (> {MAX_CONTAINER_BYTES:,}). A .atlas "
            "carries code + small assets only; large binaries belong in external "
            "content-addressed asset refs."
        )

    raw = file_path.read_bytes()
    flags, m_size, p_size, a_size, s_size = _read_header(raw, file_path)

    off = HEADER_SIZE
    manifest_bytes = raw[off : off + m_size]; off += m_size
    payload_section = raw[off : off + p_size]; off += p_size
    assets_section = raw[off : off + a_size]; off += a_size
    sigblock_bytes = raw[off : off + s_size]

    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AtlasFormatError(f"{file_path} has an unreadable manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise AtlasFormatError(f"{file_path} manifest is not a JSON object")

    sigblock: Dict[str, Any] = {}
    if sigblock_bytes:
        try:
            sigblock = json.loads(sigblock_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AtlasFormatError(f"{file_path} has an unreadable signature block: {exc}") from exc
        if not isinstance(sigblock, dict):
            raise AtlasFormatError(f"{file_path} signature block is not a JSON object")

    signature_verified = False
    if (flags & FLAG_SIGNED) and verify_signature:
        verifier = _SIGNATURE_VERIFIER
        if verifier is None:
            # Importing signing registers the verifier as a side effect.
            try:
                import atlas_protocol.signing  # noqa: F401
                verifier = _SIGNATURE_VERIFIER
            except Exception:  # pragma: no cover - crypto import should not fail
                verifier = None
        if verifier is None:
            raise AtlasFormatError(
                f"{file_path} is signed but no signature verifier is available "
                "(atlas_protocol.signing could not be imported)."
            )
        digest = package_digest(manifest_bytes, payload_section, assets_section)
        if not verifier(digest, sigblock):
            raise AtlasFormatError(
                f"{file_path} signature is invalid — the file has been tampered with "
                "or was signed by a mismatched key."
            )
        signature_verified = True

    if manifest_only:
        return AtlasPackage(
            manifest=manifest, payload_bytes=b"", assets_bytes=b"", flags=flags,
            sigblock=sigblock, signature_verified=signature_verified, source_path=file_path,
        )

    if flags & FLAG_ENCRYPTED:
        if not passphrase:
            raise AtlasFormatError(
                f"{file_path} is encrypted but no passphrase was provided "
                "(set ATLAS_PLUGIN_KEY or pass --key)."
            )
        payload_bytes = _decrypt_section(payload_section, passphrase)
        assets_bytes = _decrypt_section(assets_section, passphrase) if assets_section else b""
    else:
        payload_bytes = payload_section
        assets_bytes = assets_section

    return AtlasPackage(
        manifest=manifest, payload_bytes=payload_bytes, assets_bytes=assets_bytes,
        flags=flags, sigblock=sigblock, signature_verified=signature_verified,
        source_path=file_path,
    )


def inspect_atlas(file_path: Path) -> Dict[str, Any]:
    """Read only the manifest + metadata (no decryption, no crypto verify)."""
    pkg = read_atlas(file_path, verify_signature=False, manifest_only=True)
    return {
        "manifest": pkg.manifest,
        "encrypted": pkg.is_encrypted,
        "has_assets": pkg.has_assets,
        "signed": pkg.is_signed,
        "publisher_key_id": pkg.sigblock.get("key_id", "") if pkg.sigblock else "",
        "file_size": Path(file_path).stat().st_size,
    }


# ---------------------------------------------------------------------------
# Loader — extract the source bundle and exec the entry point
# ---------------------------------------------------------------------------

def _safe_extract_zip(zip_bytes: bytes, dest: Path) -> None:
    """Extract a zip, refusing any member that escapes ``dest`` (zip-slip)."""
    dest_resolved = dest.resolve()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for member in zf.infolist():
            target = (dest / member.filename).resolve()
            if dest_resolved != target and dest_resolved not in target.parents:
                raise AtlasFormatError(f"refusing to extract '{member.filename}': escapes {dest}")
        zf.extractall(dest)


def load_atlas_module(
    package: AtlasPackage,
    *,
    source_guard: Optional[Callable[[str, str], None]] = None,
    resolve_assets: Optional[Callable[[Dict[str, Any]], Any]] = None,
    cache_dir: Optional[Path] = None,
):
    """Extract the source bundle and exec the entry point into a fresh module.

    Parameters
    ----------
    source_guard : callable, optional
        ``(source, origin) -> None`` run on EVERY `.py` in the bundle before any
        code executes. The backend passes its import-isolation guard here; the
        format layer stays free of app-specific policy.
    resolve_assets : callable, optional
        ``(manifest) -> {name: path}`` returning resolved content-addressed
        external assets. When not provided, the manifest's ``assets`` list is
        resolved via :func:`atlas_protocol.assets.resolve_manifest_assets`.
        Small embedded assets are always extracted to a directory exposed as
        ``__atlas_assets__``; resolved external assets are exposed as
        ``__atlas_asset_paths__`` (a ``{name: Path}`` map).
    cache_dir : Path, optional
        Where to extract the source bundle + embedded assets (default: system temp).
    """
    import sys
    import tempfile
    import types

    name = package.manifest.get("name", "unknown")
    entry_point = package.manifest.get("entry_point", DEFAULT_ENTRY_POINT)

    base = Path(cache_dir or tempfile.gettempdir()) / "atlas_src_cache"
    digest = hashlib.sha256(package.payload_bytes).hexdigest()[:16]
    src_dir = base / f"{name}-{digest}"
    if not (src_dir / ".atlas_extracted").exists():
        src_dir.mkdir(parents=True, exist_ok=True)
        _safe_extract_zip(package.payload_bytes, src_dir)
        (src_dir / ".atlas_extracted").write_text("ok", encoding="utf-8")

    # Static isolation guard on every source module before anything executes.
    if source_guard is not None:
        for py in sorted(src_dir.rglob("*.py")):
            source_guard(py.read_text(encoding="utf-8"), f"<atlas:{name}>!{py.name}")

    entry_file = src_dir / entry_point
    if not entry_file.is_file():
        raise AtlasFormatError(f".atlas package '{name}' is missing its entry point {entry_point}")

    # Embedded (small) assets → a directory injected as __atlas_assets__.
    assets_value: Any = None
    if package.has_assets and package.assets_bytes:
        assets_dir = base / f"{name}-{digest}-assets"
        if not (assets_dir / ".atlas_extracted").exists():
            assets_dir.mkdir(parents=True, exist_ok=True)
            _safe_extract_zip(package.assets_bytes, assets_dir)
            (assets_dir / ".atlas_extracted").write_text("ok", encoding="utf-8")
        assets_value = assets_dir

    # External content-addressed (large) assets → a {name: path} map, resolved
    # and hash-verified on demand (fat models never live inside the container).
    external_assets: Dict[str, Any] = {}
    if resolve_assets is not None:
        external_assets = resolve_assets(package.manifest) or {}
    elif package.manifest.get("assets"):
        from atlas_protocol import assets as _assets
        external_assets = _assets.resolve_manifest_assets(package.manifest)

    module = types.ModuleType(f"atlas_plugin_{name}")
    module.__file__ = str(entry_file)
    module.__loader__ = None
    module.__dict__["__atlas_assets__"] = assets_value
    module.__dict__["__atlas_asset_paths__"] = external_assets
    module.__dict__["__atlas_manifest__"] = package.manifest

    # Put the bundle dir on sys.path so sibling helper modules import, then exec
    # the entry point. Guarded so the path entry is always removed.
    sys.path.insert(0, str(src_dir))
    try:
        code = compile(entry_file.read_text(encoding="utf-8"), module.__file__, "exec")
        exec(code, module.__dict__)  # noqa: S102 — trust-gated + isolation-guarded upstream
    finally:
        try:
            sys.path.remove(str(src_dir))
        except ValueError:
            pass
    return module
