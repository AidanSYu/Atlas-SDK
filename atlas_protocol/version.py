"""Atlas Protocol (ALP) versioning + negotiation.

The protocol version is distinct from any individual plugin's `version`. A
plugin declares the ALP it was authored against; the kernel advertises the
range it supports and negotiates: same-major + minor<=kernel loads native,
a higher minor loads in compat mode, a different major is refused.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class ProtocolVersion(BaseModel):
    """A two-part protocol version `{major, minor}` (patch is not contract-bearing).

    Frozen so the module-level `PROTOCOL_VERSION` constant cannot be mutated in
    place (which would silently shift every negotiation decision process-wide).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    major: int = 1
    minor: int = 0

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"{self.major}.{self.minor}"


# The version this build of the protocol implements.
PROTOCOL_VERSION = ProtocolVersion(major=1, minor=0)


class Negotiation(BaseModel):
    """Result of comparing a plugin's declared ALP against the kernel's."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["native", "compat", "refuse"]
    reason: str = ""


def negotiate(
    plugin: ProtocolVersion, kernel: Optional[ProtocolVersion] = None
) -> Negotiation:
    """Decide how (or whether) to load a plugin authored against `plugin`.

    - different major -> refuse (structural incompatibility)
    - same major, minor <= kernel.minor -> native
    - same major, minor  > kernel.minor -> compat (forward-compat, new-only
      features disabled; the kernel preserves unknown additive fields verbatim)

    `kernel` defaults to the current module-level `PROTOCOL_VERSION`, resolved at
    call time (not bound once at definition) so a kernel that re-advertises its
    version is honored.
    """
    if kernel is None:
        kernel = PROTOCOL_VERSION
    if plugin.major != kernel.major:
        return Negotiation(
            mode="refuse",
            reason=(
                f"protocol major {plugin.major} incompatible with kernel "
                f"major {kernel.major}"
            ),
        )
    if plugin.minor <= kernel.minor:
        return Negotiation(mode="native")
    return Negotiation(
        mode="compat",
        reason=(
            f"plugin minor {plugin.minor} newer than kernel {kernel.minor}; "
            "loading in forward-compat mode"
        ),
    )
