"""Atlas Protocol (ALP) — the single source of truth for the kernel contract.

Everything that registers with the Atlas kernel — core tools, `.atlas` plugins,
the SDK builder, the conformance suite — imports these models. There is no
second manifest, envelope, or goal definition anywhere in the codebase.

The protocol routes the kernel on a closed set of capability *kinds*; adding a
science, instrument, grader, or brain is always a new plugin, never an edit to a
kernel file.
"""
from __future__ import annotations

from .cognition import ModelDescriptor
from .compat import (
    Baseline,
    CompatBreak,
    diff_io_schemas,
    is_backward_compatible,
)
from .enums import (
    Actor,
    Backend,
    CapabilityKind,
    Combinator,
    Determinism,
    ErrCode,
    FilesystemAccess,
    GpuAccess,
    MatchTier,
    RuntimeKind,
    TrustLevel,
)
from .envelope import (
    ApprovalGrant,
    HandoffTicket,
    Measurement,
    Provenance,
    ResourceGrant,
    ToolContext,
    ToolDisplay,
    ToolError,
    ToolRequest,
    ToolResult,
)
from .goal import Criterion, Goal, GradeResult
from .manifest import (
    Author,
    CapabilityDecl,
    CapabilityManifest,
    Conformance,
    DurationHint,
    EffectDecl,
    IoSchema,
    PermissionSet,
    ProblemClassTag,
    ResourceRequirements,
    ToModelProjection,
)
from .schemas import (
    canonical_json,
    export_schemas,
    io_schema_hashes,
    manifest_io_hashes,
    schema_hash,
)
from .transfer import Axis, ProblemClass
from .version import PROTOCOL_VERSION, Negotiation, ProtocolVersion, negotiate

# .atlas container format + provenance (single source of truth for runtime + SDK).
from .packaging import (
    AtlasFormatError,
    AtlasPackage,
    collect_assets,
    inspect_atlas,
    load_atlas_module,
    pack_atlas,
    pack_plugin_directory,
    read_atlas,
    write_atlas,
)
from .signing import (
    generate_keypair,
    key_id,
    load_private_key,
    load_public_key,
    make_signer,
    sign_file,
    verify_sigblock,
)
from .trust import (
    add_trusted_publisher,
    list_trusted,
    resolve_trust_level,
    revoke,
    trust_dir,
)
from .assets import (
    AssetRef,
    AssetResolutionError,
    manifest_asset_refs,
    resolve_asset,
    resolve_manifest_assets,
)

__all__ = [
    # version + negotiation
    "PROTOCOL_VERSION",
    "ProtocolVersion",
    "Negotiation",
    "negotiate",
    # enums
    "CapabilityKind",
    "Actor",
    "Determinism",
    "FilesystemAccess",
    "GpuAccess",
    "RuntimeKind",
    "Combinator",
    "MatchTier",
    "TrustLevel",
    "ErrCode",
    "Backend",
    # manifest
    "CapabilityManifest",
    "CapabilityDecl",
    "IoSchema",
    "EffectDecl",
    "PermissionSet",
    "ResourceRequirements",
    "DurationHint",
    "ToModelProjection",
    "ProblemClassTag",
    "Author",
    "Conformance",
    # envelope
    "ToolRequest",
    "ToolContext",
    "ToolResult",
    "ToolDisplay",
    "ToolError",
    "Measurement",
    "Provenance",
    "ApprovalGrant",
    "ResourceGrant",
    "HandoffTicket",
    # goal
    "Goal",
    "Criterion",
    "GradeResult",
    # cognition
    "ModelDescriptor",
    # transfer
    "ProblemClass",
    "Axis",
    # schemas + compat
    "export_schemas",
    "schema_hash",
    "canonical_json",
    "io_schema_hashes",
    "manifest_io_hashes",
    "diff_io_schemas",
    "is_backward_compatible",
    "Baseline",
    "CompatBreak",
    # .atlas container format
    "AtlasPackage",
    "AtlasFormatError",
    "pack_atlas",
    "write_atlas",
    "read_atlas",
    "inspect_atlas",
    "load_atlas_module",
    "pack_plugin_directory",
    "collect_assets",
    # signing + trust
    "generate_keypair",
    "key_id",
    "make_signer",
    "sign_file",
    "verify_sigblock",
    "load_private_key",
    "load_public_key",
    "resolve_trust_level",
    "add_trusted_publisher",
    "list_trusted",
    "revoke",
    "trust_dir",
    # content-addressed assets
    "AssetRef",
    "AssetResolutionError",
    "resolve_asset",
    "resolve_manifest_assets",
    "manifest_asset_refs",
]
