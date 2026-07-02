# Atlas Protocol (ALP) — the Atlas SDK

**The open contract for autonomous-lab software.** `atlas_protocol` is the single
source of truth for how any capability — a tool, an oracle/model, a theorist, a
physical instrument, a grader, or a brain — registers with an Atlas kernel and
crosses the dispatch boundary. It is a small, dependency-light set of typed
[pydantic](https://docs.pydantic.dev/) models plus a schema-hashing/compat layer.

> This repository is the **open protocol layer**. The Atlas *engine* — the
> verification-firewall implementation, the per-lab compounding ledger, and the
> physical-instrument bridges — is a separate product and is **not** in this repo.
> The protocol is open so the contract is auditable and anyone can build to it;
> the engine is where the work happens.

Licensed under **Apache-2.0**.

---

## Why a protocol (and why open)

A discovery system is only trustworthy if the rules by which a result *counts*
are inspectable. ALP encodes those rules as types, not prose:

- **Capability kinds are a closed set.** The kernel routes on six `CapabilityKind`s —
  `tool`, `oracle`, `theorist`, `instrument`, `verifier`, `actuator`. Adding a
  science, an instrument, or a grader is always a **new plugin**, never an edit to
  a kernel file.
- **The actor firewall.** Every event is stamped with an `Actor`. The cognition
  brain (`Actor.ATLAS`) **never mints numbers and never actuates** — it phrases,
  it does not measure. Numbers acquire ledger authority *only* through the
  `Measurement` channel, authored by an `instrument`, a `researcher`, or a
  `software` worker.
- **Non-finite values can't enter the record.** `Measurement.value` rejects
  `NaN`/`Inf` at the boundary — a malformed reading can never poison the ledger.
- **Two channels, deliberately separated.** A `ToolResult` carries a `display`
  (projected + redacted, the only thing a brain may see) and a full `record`
  (ledger/UI only, never auto-fed back to a model). Sealed criterion targets stay
  out of every prompt.
- **Predicates travel with the capability.** Each `CapabilityDecl` carries `pre`
  and `post` conditions as [JSONLogic](https://jsonlogic.com/) over its
  input/output, enforced by the kernel — not buried in wrapper code.
- **Goals are graded predicates, not a single scalar.** A `Goal` is a set of
  `Criterion`s, each graded by a **named sealed verifier** returning a
  `GradeResult` (`passed`, a continuous `score`, `applicable`, `confidence`).
- **Transfer matches by meaning, not by spelling.** A `ProblemClass` carries
  unit-aware `Axis`es and an embedding, so `temp_C` and `temperature` can match
  for cross-campaign transfer. Nothing in the protocol reads a domain name.
- **The brain is a socket.** A `ModelDescriptor` selects a backend explicitly —
  Qwen today, your own local model tomorrow — the same seam. **The core never
  selects a cloud model; offline is a protocol-level guarantee.**
- **One source of truth for schemas.** `export_schemas()` emits Draft 2020-12 JSON
  Schemas for every public model; `schema_hash()` + `compat.py` gate
  backward-compatibility and stamp the exact contract a campaign ran against.

## Install

```bash
pip install atlas-protocol          # from PyPI (once published)
# or, from a checkout:
pip install -e .
```

Requires Python ≥ 3.10 and pydantic v2. The only runtime dependency is pydantic.

## Quickstart

```python
from atlas_protocol import (
    CapabilityManifest, CapabilityDecl, CapabilityKind,
    IoSchema, EffectDecl, Actor, Determinism,
    export_schemas, manifest_io_hashes,
)

manifest = CapabilityManifest(
    id="org.example.hplc_qc",
    version="0.1.0",
    description="HPLC purity readout",
    capabilities=[
        CapabilityDecl(
            name="measure_purity",
            kind=CapabilityKind.INSTRUMENT,      # actuates/measures
            actor=Actor.INSTRUMENT,              # authored by the device, not the brain
            determinism=Determinism.EFFECTFUL,   # touches the world; never cached
            io=IoSchema(
                input_schema={"type": "object", "properties": {"sample_id": {"type": "string"}}},
                output_schema={"type": "object", "properties": {"purity_pct": {"type": "number"}}},
            ),
            effects=EffectDecl(physical=True, reagent=True, irreversible=True),
            # post-condition enforced by the kernel: purity must be in [0, 100]
            post=[{"<=": [0, {"var": "purity_pct"}, 100]}],
        )
    ],
)

# The manifest validates on construction (extra fields forbidden, names linted).
print(manifest.capability("measure_purity").kind)        # CapabilityKind.INSTRUMENT
print(manifest_io_hashes(manifest))                       # per-capability io-schema hashes
schemas = export_schemas()                                # Draft 2020-12 JSON Schemas
```

## Versioning & negotiation

The protocol version (`PROTOCOL_VERSION`, currently `1.0`) is distinct from any
plugin's own `version`. A plugin declares the ALP it was authored against; the
kernel negotiates:

- different **major** → `refuse` (structural incompatibility),
- same major, **minor ≤ kernel** → `native`,
- same major, **minor > kernel** → `compat` (forward-compat; unknown additive
  fields preserved verbatim).

```python
from atlas_protocol import negotiate, ProtocolVersion
negotiate(ProtocolVersion(major=1, minor=2), ProtocolVersion(major=1, minor=0)).mode  # "compat"
```

## Conformance

The test suite is the executable conformance check:

```bash
pip install -e ".[dev]"
pytest -q
```

## Status

`v0.1.0`, protocol `1.0`. The protocol is published as a **draft standard**:
the shapes are stable and in production use, but minor fields may still be added
before a `1.0` distribution release. Adding an enum *value* or a model *field* is
a protocol change and is tracked in [`CHANGELOG.md`](CHANGELOG.md); adding a
*plugin* never is.

## Security

ALP is the contract for a system whose entire value rests on results being
trustworthy. If you find a way the typed boundary could be bypassed — a path that
lets the brain author a measurement, a non-finite value reaching the record, or a
schema-hash collision — please see [`SECURITY.md`](SECURITY.md).

## License

[Apache-2.0](LICENSE). © 2026 Contineon
