"""The wire envelope — every dispatch crosses two typed objects.

The old `dict-with-{valid,summary}` convention is gone. The kernel builds the
`ToolResult`; the wrapper returns its inner shape. Two channels separate what
the model may see (`display`, projected + redacted) from the full `record`
(ledger/UI only, never auto-fed to a brain), and numbers acquire ledger
authority only through `measurements`.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import Actor, Determinism, ErrCode
from .manifest import ProblemClassTag


class ResourceGrant(BaseModel):
    """A budget envelope passed into a dispatch (None = unbounded for that axis)."""

    model_config = ConfigDict(extra="forbid")

    wall_ms: Optional[int] = None
    tokens: Optional[int] = None
    max_actions: Optional[int] = None


class ApprovalGrant(BaseModel):
    """A researcher's authorization for a physical/irreversible capability.
    Issued only through an explicit API, never inferred from model prose."""

    model_config = ConfigDict(extra="forbid")

    approved_by: str
    scope: Literal["node", "session"]
    granted_at: str  # ISO-8601 (stamped by the caller; protocol is time-source-agnostic)
    max_actions: int = 1
    expires_at: Optional[str] = None
    args_hash: str = ""  # binds the grant to specific arguments


class ToolContext(BaseModel):
    """Ambient context for a dispatch."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    run_id: str = ""
    node_id: Optional[str] = None
    actor: Actor = Actor.SOFTWARE
    approvals: List[ApprovalGrant] = Field(default_factory=list)
    budget: Optional[ResourceGrant] = None
    problem_class: Optional[ProblemClassTag] = None
    event_cursor: int = 0


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    capability: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    context: ToolContext
    deadline_ms: Optional[int] = None


class Measurement(BaseModel):
    """The ONLY channel that grants a number ledger authority. NaN/Inf rejected
    at the boundary so a non-finite value can never enter the record."""

    model_config = ConfigDict(extra="forbid")

    key: str
    value: float
    unit: str = ""
    replicate: int = 0

    @field_validator("value")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("Measurement.value must be finite (NaN/Inf rejected)")
        return v


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrCode
    message: str = ""
    retriable: bool = False
    # For verifiers: False distinguishes "could not grade / misconfigured" from a
    # true negative (passed=False). Closes the swallow-everything observability gap.
    applicable: bool = True


class ToolDisplay(BaseModel):
    """Model-facing view: projection-shaped, redacted, sealed-stripped."""

    model_config = ConfigDict(extra="forbid")

    summary: str = ""
    salient: Dict[str, Any] = Field(default_factory=dict)


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: Actor
    capability_version: str = ""
    started_at: Optional[str] = None
    duration_ms: Optional[int] = None
    determinism: Determinism = Determinism.STOCHASTIC
    input_hash: str = ""
    cache: Literal["hit", "miss", "bypass"] = "miss"
    signed_by: str = ""


class ToolResult(BaseModel):
    """The typed dispatch envelope. The kernel constructs this around the
    wrapper's inner output."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    capability: str
    request_id: str = ""
    display: ToolDisplay = Field(default_factory=ToolDisplay)
    record: Dict[str, Any] = Field(default_factory=dict)  # FULL payload -> ledger/UI only
    measurements: Optional[List[Measurement]] = None
    error: Optional[ToolError] = None
    postcondition_violations: List[str] = Field(default_factory=list)
    provenance: Optional[Provenance] = None


class HandoffTicket(BaseModel):
    """Persisted when an actor cannot complete synchronously (instrument handoff,
    human approval, human input). One primitive serves all three."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: str
    node_id: str
    expected_actor: Actor
    resume_schema: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    expires_at: Optional[str] = None
