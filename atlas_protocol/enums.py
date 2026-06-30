"""Controlled vocabularies for the Atlas Protocol.

These are the closed sets the kernel routes on. They are string enums so they
serialize cleanly to JSON Schema (as `enum`) and read naturally in manifests.
Adding a *value* here is a protocol change; adding a *plugin* never is.
"""
from __future__ import annotations

from enum import Enum


class CapabilityKind(str, Enum):
    """The six kinds the kernel dispatches on. This is the spine field."""

    TOOL = "tool"            # generic validated invoke
    ORACLE = "oracle"        # pure/deterministic/stochastic predictor (the FM socket)
    THEORIST = "theorist"    # proposes a candidate THEORY from principles (the Einstein socket)
    INSTRUMENT = "instrument"  # actuates/measures; may hand off to a human/robot
    VERIFIER = "verifier"    # sealed grader; never on the model-facing bus
    ACTUATOR = "actuator"    # physical/irreversible; deny-by-default


class Actor(str, Enum):
    """Who executes a capability. Stamped on every event; drives the firewall."""

    ATLAS = "atlas"          # the cognition brain — never mints numbers, never actuates
    RESEARCHER = "researcher"  # a human at the bench / keyboard
    INSTRUMENT = "instrument"  # a measuring/robotic device
    SOFTWARE = "software"    # an in-process CPU/GPU worker


class Determinism(str, Enum):
    """Caching/replay contract for a capability's outputs."""

    PURE = "pure"                  # same input -> byte-identical output, no state
    DETERMINISTIC = "deterministic"  # reproducible given declared inputs (+seed)
    STOCHASTIC = "stochastic"      # varies run to run (declare a seed input to pin)
    EFFECTFUL = "effectful"        # touches the world; never cached


class FilesystemAccess(str, Enum):
    NONE = "none"
    READ = "read"
    WRITE = "write"


class GpuAccess(str, Enum):
    NONE = "none"
    SHARED = "shared"
    EXCLUSIVE = "exclusive"  # triggers the model-slot eviction handshake


class RuntimeKind(str, Enum):
    """How the wrapper code is executed — ties to TrustLevel at load."""

    PYTHON = "python"          # in-process (trusted publishers only)
    SUBPROCESS = "subprocess"  # OS-isolated (untrusted publishers)
    WASM = "wasm"              # sandboxed (untrusted, as it matures)


class Combinator(str, Enum):
    """How a Goal's criteria compose into a pass/fail."""

    ALL = "all"
    ANY = "any"
    WEIGHTED = "weighted"


class MatchTier(str, Enum):
    """Provenance of a cross-campaign transfer match (most to least exact)."""

    EXACT = "exact"
    TAG = "tag"
    UNIT = "unit"
    SEMANTIC = "semantic"


class TrustLevel(str, Enum):
    """Resolved at load from the signature; gates which runtime executes code."""

    FIRST_PARTY = "first_party"
    TRUSTED_SIGNED = "trusted_signed"
    UNKNOWN_SIGNED = "unknown_signed"
    UNSIGNED = "unsigned"


class ErrCode(str, Enum):
    """Typed dispatch errors. `applicable=False` on a verifier means misconfigured,
    distinct from a real negative result."""

    VALIDATION_ERROR = "validation_error"        # input/output schema violation
    CONTRACT_VIOLATION = "contract_violation"    # a pre/postcondition failed
    APPROVAL_REQUIRED = "approval_required"      # actuator hit the deny-by-default gate
    ALP_MAJOR_MISMATCH = "alp_major_mismatch"    # protocol major incompatible
    ORACLE_NETWORK_FORBIDDEN = "oracle_network_forbidden"  # oracle declared network
    NOT_APPLICABLE = "not_applicable"            # verifier could not grade this evidence
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"                  # capability not loaded / failed to load
    INTERNAL_ERROR = "internal_error"


class Backend(str, Enum):
    """Cognition backends. The interface is the seam; offline-local only in core."""

    LLAMACPP = "llamacpp"
    VLLM = "vllm"
    OPENAI_COMPAT = "openai_compat"  # a LOCAL OpenAI-compatible server, never cloud
    MLX = "mlx"
    ATLAS_FM = "atlas_fm"            # Atlas's own future foundation models
    MOCK = "mock"                   # deterministic offline brain for tests/dev
