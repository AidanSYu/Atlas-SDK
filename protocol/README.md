# Atlas Protocol (ALP)

**The open contract for autonomous-lab software.** `atlas_protocol` is the single
source of truth for how any capability — a tool, an oracle/model, a theorist, a
physical instrument, a grader, or a brain — registers with an Atlas kernel and
crosses the dispatch boundary, and for the signed **`.atlas`** container that
carries a capability from a publisher to a lab. It is a small set of typed
[pydantic](https://docs.pydantic.dev/) models plus a schema-hashing/compat layer
and one implementation of the container format (packaging, Ed25519 signing, the
local trust store, content-addressed assets, conformance).

> This package is the **protocol half of the [Atlas SDK](../README.md)**; the
> `atlas` CLI that builds and signs packages lives in the sibling
> [`atlas-sdk`](../sdk/README.md) package. The Atlas *engine* — the
> verification-firewall implementation, the per-lab compounding ledger, and the
> physical-instrument bridges — is a separate product and is **not** in this
> repo. The protocol is open so the contract is auditable and anyone can build
> to it; the engine is where the work happens.

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

## The `.atlas` container (format v2)

Since 1.0.0 the protocol also owns the distribution story — the same invariants,
extended to the artifact a lab actually loads:

- **Signed, tamper-evident packages.** A `.atlas` carries a cleartext manifest,
  a portable Python **source bundle** (no marshalled bytecode), small embedded
  artifacts, and an **Ed25519 signature block** (`packaging.py`, `signing.py`).
  One flipped byte anywhere under the signature fails verification.
- **A local trust store with tiers.** `trust.py` resolves a package's publisher
  to `first_party` / `trusted_signed` / `unknown_signed` / `unsigned`
  (`TrustLevel`); runtimes refuse untrusted packages by default, and revocation
  demotes a key. First-party trust anchors ship under
  [`atlas_protocol/keys/first_party/`](atlas_protocol/keys/first_party/README.md)
  — public keys only, never private.
- **Content-addressed external assets.** Fat models and native libs are *not*
  embedded: `assets.py` declares them by `sha256` + size + sources
  (`file://` | `hf://` | `https://`), fetches from the first reachable source,
  **verifies the hash** (a hostile mirror can't swap the file), and caches —
  air-gap friendly by construction.
- **An executable conformance suite.** `conformance.py` checks a plugin
  directory the way a runtime would (manifest strictness, schema sanity, import
  isolation) — `atlas test` in the CLI is a thin wrapper over it.

## Install

```bash
pip install atlas-protocol            # from PyPI (once published)
# or, from a checkout of the Atlas-SDK repo:
pip install -e ./protocol
```

Requires Python ≥ 3.10. Runtime dependencies: pydantic v2 and cryptography
(for Ed25519 signing/verification).

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

To *build* a `.atlas` from a plugin directory, use the
[`atlas` CLI](../sdk/README.md) — it calls straight into this package, so a
package you build and one the runtime loads always agree.

## Versioning & negotiation

The protocol version (`PROTOCOL_VERSION`, currently `1.0`) is distinct from any
plugin's own `version` and from this package's release version (see the
[three version axes](../README.md#the-names-once-and-for-all)). A plugin
declares the ALP it was authored against; the kernel negotiates:

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
pip install -e "./protocol[dev]"
pytest protocol/tests -q
```

## Status

Package `1.0.0`, protocol `1.0`, container format `v2`. The draft window is
closed: the 0.1.0 release published the shapes as a draft standard, and 1.0.0
finalizes protocol 1.0 with the container format, signing, trust, and asset
layers included. Adding an enum *value* or a model *field* is a protocol change
and is tracked in [`CHANGELOG.md`](../CHANGELOG.md); adding a *plugin* never is.

## Security

ALP is the contract for a system whose entire value rests on results being
trustworthy. If you find a way the typed boundary could be bypassed — a path that
lets the brain author a measurement, a forged signature that verifies, a trust
tier that resolves too high, an asset that loads without matching its hash, or a
schema-hash collision — please see [`SECURITY.md`](../SECURITY.md).

## License

[Apache-2.0](LICENSE). © 2026 Contineon.
