"""Backward-compatibility gate for capability io-schemas.

`atlas build` records a per-capability baseline of io-schema hashes. A
minor/patch version bump that changes a previously-published input or output
schema is a breaking change and must fail the build; only a major bump may break
the contract. This is what stops a plugin from silently shifting the shape a
running campaign was validated against.
"""
from __future__ import annotations

from typing import Dict, List, Literal

from pydantic import BaseModel, ConfigDict

from .manifest import CapabilityManifest
from .schemas import manifest_io_hashes

# A baseline is the previously-published {capability_name: {input, output}} hashes.
Baseline = Dict[str, Dict[str, str]]


class CompatBreak(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: str
    channel: Literal["input", "output", "capability"]
    detail: str


def diff_io_schemas(baseline: Baseline, manifest: CapabilityManifest) -> List[CompatBreak]:
    """Return the breaking changes between a published baseline and a manifest.

    A removed capability or a changed input/output schema is breaking. Added
    capabilities are additive (not breaking). The caller decides severity by
    version bump: any break on a non-major bump fails the build.
    """
    breaks: List[CompatBreak] = []
    current = manifest_io_hashes(manifest)

    for cap_name, channels in baseline.items():
        if cap_name not in current:
            breaks.append(
                CompatBreak(
                    capability=cap_name,
                    channel="capability",
                    detail="capability was removed",
                )
            )
            continue
        for channel in ("input", "output"):
            old = channels.get(channel)
            new = current[cap_name].get(channel)
            # Conservative: a missing baseline channel (old is None) vs a present
            # current hash counts as a change, so a malformed/partial baseline can
            # never silently hide a breaking schema change.
            if old != new:
                old_s = "<absent>" if old is None else f"{old[:12]}…"
                new_s = "<absent>" if new is None else f"{new[:12]}…"
                breaks.append(
                    CompatBreak(
                        capability=cap_name,
                        channel=channel,
                        detail=f"{channel}_schema changed ({old_s} -> {new_s})",
                    )
                )
    return breaks


def is_backward_compatible(baseline: Baseline, manifest: CapabilityManifest) -> bool:
    """True iff no breaking io-schema change exists vs the baseline."""
    return len(diff_io_schemas(baseline, manifest)) == 0
