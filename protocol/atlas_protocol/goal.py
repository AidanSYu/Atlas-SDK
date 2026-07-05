"""The Goal model — a set of graded predicates, not a single scalar.

This unifies the previously-incompatible goal shapes (a sealed scalar target, a
criteria list, a free-text definition-of-done) into one contract the loop, the
verifier, the narrator, and the ledger all share. Because a goal is a set of
criteria graded by named verifiers, a non-optimization goal does not force a
re-cut of `grade()` after the contract is locked.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .enums import Combinator
from .envelope import ToolError


class Criterion(BaseModel):
    """One gradeable success condition, graded by the named sealed verifier."""

    model_config = ConfigDict(extra="forbid")

    key: str
    plain: str  # plain-language statement of "done" for the researcher
    verifier: str  # name of the verifier capability that grades this
    criterion_schema_ref: str = ""  # schema the verifier expects for its criterion
    weight: float = 1.0  # used only when combinator == "weighted"


class Goal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str  # the human's broad ask, verbatim
    criteria: list[Criterion] = Field(min_length=1)
    combinator: Combinator = Combinator.ALL
    sealed: bool = False  # if true, criterion targets are kept out of every prompt


class GradeResult(BaseModel):
    """A verifier's verdict. `grade()` never raises; `applicable=False` +
    structured `error` distinguishes misconfiguration from a true negative."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    score: float = 0.0
    detail: str = ""
    applicable: bool = True
    confidence: float = 1.0
    error: Optional[ToolError] = None
