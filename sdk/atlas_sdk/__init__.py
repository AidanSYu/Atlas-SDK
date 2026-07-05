"""atlas_sdk — developer toolkit for building .atlas plugins.

The `.atlas` container, signing, trust, and asset resolution all come from the
one source of truth, ``atlas_protocol`` (re-exported via ``atlas_sdk.format``).
This package adds the CLI, manifest validation, and scaffolding templates.
"""
from __future__ import annotations

__version__ = "1.0.1"

from atlas_sdk.format import (  # noqa: F401
    AtlasFormatError,
    AtlasPackage,
    inspect_atlas,
    pack_atlas,
    pack_plugin_directory,
    read_atlas,
    write_atlas,
)
from atlas_sdk.manifest import PluginManifest  # noqa: F401

__all__ = [
    "__version__",
    "PluginManifest",
    "AtlasPackage",
    "AtlasFormatError",
    "pack_atlas",
    "pack_plugin_directory",
    "write_atlas",
    "read_atlas",
    "inspect_atlas",
]
