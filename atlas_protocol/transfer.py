"""ProblemClass — the runtime fingerprint that makes cross-campaign transfer fire.

The previous transfer keyed on an exact (sorted param names, sorted objective
names) signature, so `temp_C` and `temperature` shared nothing and the
self-improvement moat silently never triggered across labs that name axes
differently. A ProblemClass carries an embedding (from name+unit+description+
domain) and unit-aware axes so matching is by meaning + unit, never by literal
name. Nothing here reads a domain name.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class Axis(BaseModel):
    """One parameter or objective axis, unit-aware for normalization."""

    model_config = ConfigDict(extra="forbid")

    name: str
    unit: str = ""
    kind: Literal["continuous", "ordinal", "categorical"] = "continuous"
    role: Literal["param", "objective"] = "param"
    minimize: Optional[bool] = None  # objectives only


class ProblemClass(BaseModel):
    """A campaign's problem fingerprint, used to retrieve transferable priors."""

    model_config = ConfigDict(extra="forbid")

    param_axes: List[Axis] = Field(default_factory=list)
    objective_axes: List[Axis] = Field(default_factory=list)
    domain_tags: List[str] = Field(default_factory=list)
    embedding: Optional[List[float]] = None  # computed from name+unit+desc+tags
