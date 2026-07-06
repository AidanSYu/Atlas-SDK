"""CapabilityManifest — the single source of truth for plugin + core-tool metadata.

One `.atlas` package (or one core tool) ships one `CapabilityManifest` declaring
one or more capabilities. The runtime registry, the SDK, and the conformance
suite all import THESE classes — there is no second manifest definition.

Strictness policy (Postel): `extra="forbid"` at build time (typos and
domain-leak fields are rejected loudly and early). Forward-compat leniency at
load time (preserving unknown additive fields under a newer minor) is a kernel
concern handled during negotiation, not a relaxation of these models.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import (
    Actor,
    CapabilityKind,
    Determinism,
    FilesystemAccess,
    GpuAccess,
    RuntimeKind,
)
from .transfer import Axis
from .version import PROTOCOL_VERSION, ProtocolVersion

# Reverse-DNS package id, e.g. "org.atlas.proposer.botorch". Lowercase, dotted.
_ID_PATTERN = r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$"
# Tool-bus capability name, e.g. "propose_experiment". Lowercase snake; the
# regex structurally forbids domain-leak names like "SMILES" or "X50".
_NAME_PATTERN = r"^[a-z][a-z0-9_]{2,63}$"
# SemVer (major.minor.patch, no leading zeros, optional pre-release/build).
_SEMVER_PATTERN = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)([-+].+)?$"


class ResourceRequirements(BaseModel):
    """Hardware requirements. `exclusive_gpu` triggers the model-slot eviction
    handshake before dispatch (the correct single-GPU primitive)."""

    model_config = ConfigDict(extra="forbid")

    min_vram_mb: int = 0
    min_ram_mb: int = 0
    gpu_required: bool = False
    recommended_vram_mb: int = 0
    exclusive_gpu: bool = False


class EffectDecl(BaseModel):
    """Typed declaration of side effects — replaces the `'physical' in tags`
    string heuristic. The kernel reads these without executing the plugin."""

    model_config = ConfigDict(extra="forbid")

    physical: bool = False
    network: bool = False
    filesystem: FilesystemAccess = FilesystemAccess.NONE
    subprocess: bool = False
    gpu: GpuAccess = GpuAccess.NONE
    reagent: bool = False
    irreversible: bool = False


class PermissionSet(BaseModel):
    """Declared capabilities the runtime grants/enforces. Sandbox-enforced for
    non-python runtimes; static-lint-checked for python."""

    model_config = ConfigDict(extra="forbid")

    fs: List[str] = Field(default_factory=list)  # allowed path globs
    net: bool = False
    subprocess: bool = False
    gpu: GpuAccess = GpuAccess.NONE
    env: List[str] = Field(default_factory=list)  # allowed env var names


class IoSchema(BaseModel):
    """JSON Schema (Draft 2020-12) for a capability's input and output. Both are
    enforced: input pre-dispatch, output before it leaves the wrapper."""

    model_config = ConfigDict(extra="forbid")

    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)


class DurationHint(BaseModel):
    """Expected wall-clock; the kernel uses p95 as the per-step timeout."""

    model_config = ConfigDict(extra="forbid")

    p50: int = 0
    p95: int = 0


class ToModelProjection(BaseModel):
    """Shapes the model-facing view of a result (the kernel builds `display`
    from `record` using this). `redact` strips fields the brain must never see."""

    model_config = ConfigDict(extra="forbid")

    salient_fields: List[str] = Field(default_factory=list)
    max_chars: int = 400
    redact: List[str] = Field(default_factory=list)


class ProblemClassTag(BaseModel):
    """Declarative problem-class hint on a manifest.

    Uses the SAME `Axis` type as the runtime `ProblemClass` (transfer.py), which
    is derived from this tag (axes split by role + an embedding added) for
    cross-campaign transfer. One vocabulary — no manifest-to-runtime translation
    glue, no 'parameter' vs 'param' / 'direction' vs 'minimize' divergence."""

    model_config = ConfigDict(extra="forbid")

    axes: List[Axis] = Field(default_factory=list)
    domain_tags: List[str] = Field(default_factory=list)


class Author(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    email: str = ""
    key_id: str = ""  # ties the author to the signing key


class Conformance(BaseModel):
    """Self-certification stamp produced by `atlas test`."""

    model_config = ConfigDict(extra="forbid")

    suite_version: str
    report_sha256: str


class CapabilityDecl(BaseModel):
    """One exported capability. `kind` is the spine field driving kernel treatment."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=_NAME_PATTERN)
    kind: CapabilityKind
    io: IoSchema = Field(default_factory=IoSchema)
    actor: Actor = Actor.SOFTWARE
    # Default STOCHASTIC = never cached unless the author opts into pure/deterministic.
    # The safe direction: under-cache rather than silently serve a stale result.
    determinism: Determinism = Determinism.STOCHASTIC
    effects: EffectDecl = Field(default_factory=EffectDecl)
    permissions: PermissionSet = Field(default_factory=PermissionSet)
    pre: List[Dict[str, Any]] = Field(default_factory=list)   # JSONLogic over input
    post: List[Dict[str, Any]] = Field(default_factory=list)  # JSONLogic over output
    expected_duration_ms: Optional[DurationHint] = None
    resource_requirements: ResourceRequirements = Field(
        default_factory=ResourceRequirements
    )
    verifier_binding: Optional[str] = None  # name of the sealed verifier grading this
    to_model_projection: ToModelProjection = Field(default_factory=ToModelProjection)
    problem_class: Optional[ProblemClassTag] = None


class CapabilityManifest(BaseModel):
    """The whole-package manifest. Always cleartext in the `.atlas` container so
    the kernel can discover kind/effects/permissions without a decryption key."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    # PROTOCOL_VERSION is frozen, so sharing the one instance is safe (no copy needed).
    protocol: ProtocolVersion = Field(default_factory=lambda: PROTOCOL_VERSION)
    id: str = Field(pattern=_ID_PATTERN)  # reverse-DNS, globally unique
    version: str = Field(pattern=_SEMVER_PATTERN)
    description: str
    display_name: str = ""
    license: str = ""
    homepage: str = ""
    authors: List[Author] = Field(default_factory=list)
    capabilities: List[CapabilityDecl] = Field(min_length=1)
    runtime: RuntimeKind = RuntimeKind.PYTHON
    conformance: Optional[Conformance] = None
    signature_ref: Optional[int] = None  # index into the .atlas signature block

    @model_validator(mode="after")
    def _unique_capability_names(self) -> "CapabilityManifest":
        names = [c.name for c in self.capabilities]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"duplicate capability names in manifest: {dupes}")
        return self

    def capability(self, name: str) -> Optional[CapabilityDecl]:
        return next((c for c in self.capabilities if c.name == name), None)
