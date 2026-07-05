"""SDK re-export of the canonical `.atlas` container format.

The one implementation lives in :mod:`atlas_protocol.packaging`; the SDK imports
it rather than forking it, so a package built by the SDK and a package read by
the runtime always agree on format, signature scheme, and asset bundling
(spec invariant #3/#4). The old duplicated HMAC writer/reader is gone.
"""
from __future__ import annotations

try:
    from atlas_protocol.packaging import (  # noqa: F401
        ATLAS_MAGIC,
        FLAG_ENCRYPTED,
        FLAG_HAS_ASSETS,
        FLAG_SIGNED,
        AtlasFormatError,
        AtlasPackage,
        collect_assets,
        inspect_atlas,
        pack_atlas,
        pack_plugin_directory,
        read_atlas,
        write_atlas,
    )
except ImportError as exc:  # pragma: no cover - install guidance
    raise ImportError(
        "atlas_sdk requires the 'atlas-protocol' package (the single source of "
        "truth for the .atlas format). Install it with `pip install atlas-protocol`."
    ) from exc

__all__ = [
    "ATLAS_MAGIC",
    "FLAG_ENCRYPTED",
    "FLAG_HAS_ASSETS",
    "FLAG_SIGNED",
    "AtlasFormatError",
    "AtlasPackage",
    "collect_assets",
    "inspect_atlas",
    "pack_atlas",
    "pack_plugin_directory",
    "read_atlas",
    "write_atlas",
]
