"""JSON Schema export + content hashing.

`export_schemas()` emits the Draft 2020-12 JSON Schemas for every public model.
The SDK and CI validate against the *emitted* schemas, never a hand-fork — this
is what guarantees one source of truth. Per-capability io-schema hashes feed the
backward-compatibility gate (see compat.py) and are stamped into the ledger so a
campaign is reproducible against the exact contract it ran on.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, Tuple

from .cognition import ModelDescriptor
from .envelope import (
    ApprovalGrant,
    HandoffTicket,
    Measurement,
    ToolRequest,
    ToolResult,
)
from .goal import Goal, GradeResult
from .manifest import CapabilityDecl, CapabilityManifest
from .transfer import ProblemClass

# The public models whose schemas are the contract surface.
_PUBLIC_MODELS = {
    "CapabilityManifest": CapabilityManifest,
    "CapabilityDecl": CapabilityDecl,
    "ToolRequest": ToolRequest,
    "ToolResult": ToolResult,
    "Measurement": Measurement,
    "ApprovalGrant": ApprovalGrant,
    "HandoffTicket": HandoffTicket,
    "Goal": Goal,
    "GradeResult": GradeResult,
    "ModelDescriptor": ModelDescriptor,
    "ProblemClass": ProblemClass,
}


def export_schemas() -> Dict[str, Dict[str, Any]]:
    """Return `{model_name: json_schema}` for every public protocol model."""
    return {name: model.model_json_schema() for name, model in _PUBLIC_MODELS.items()}


def _canonicalize(obj: Any) -> Any:
    """Normalize a JSON-Schema value so semantically-equal schemas hash equal.

    - integral floats collapse to int (`1.0` and `1` are equal in JSON Schema),
      killing a common false-positive in the backward-compat gate;
    - non-finite numbers (NaN/Inf) are rejected, since they have no valid JSON
      representation and would hash to non-portable tokens.
    """
    if isinstance(obj, bool):  # bool is a subclass of int — keep it a bool
        return obj
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise ValueError("non-finite number (NaN/Inf) is not a valid JSON-Schema value")
        return int(obj) if obj.is_integer() else obj
    if isinstance(obj, dict):
        return {k: _canonicalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_canonicalize(v) for v in obj]
    return obj


def canonical_json(obj: Any) -> str:
    """Stable JSON for hashing: canonicalized values, sorted keys, no whitespace."""
    return json.dumps(
        _canonicalize(obj), sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def schema_hash(schema: Dict[str, Any]) -> str:
    """sha256 over a canonicalized JSON Schema."""
    return hashlib.sha256(canonical_json(schema).encode("utf-8")).hexdigest()


def io_schema_hashes(decl: CapabilityDecl) -> Tuple[str, str]:
    """`(input_hash, output_hash)` for one capability — the unit of compat tracking."""
    return (
        schema_hash(decl.io.input_schema),
        schema_hash(decl.io.output_schema),
    )


def manifest_io_hashes(manifest: CapabilityManifest) -> Dict[str, Dict[str, str]]:
    """`{capability_name: {input, output}}` io-schema hashes for a whole manifest."""
    out: Dict[str, Dict[str, str]] = {}
    for decl in manifest.capabilities:
        in_hash, out_hash = io_schema_hashes(decl)
        out[decl.name] = {"input": in_hash, "output": out_hash}
    return out
