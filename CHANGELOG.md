# Changelog

All notable changes to the Atlas SDK are recorded here — for both packages,
`atlas-protocol` and `atlas-sdk`. The protocol version (`PROTOCOL_VERSION` in
`atlas_protocol/version.py`) is bumped whenever an enum value or model field is
added/changed; package versions track releases.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [1.0.1] — 2026-07-06

### Fixed
- **atlas-protocol**: Windows `file://` asset sources with the drive letter in
  the URL authority (`file://C:/mirror/model.bin` — the form the module docs
  advertise) lost the drive during parsing and resolved against the current
  working drive. `_fetch_file` now rejoins authority + path and treats a
  `localhost` authority as empty (RFC 8089). Caught by the CI Windows runners,
  whose workspace lives on `D:`; regression test added for the RFC
  `file:///C:/...` form too.
- Packages bumped in lockstep to 1.0.1; `atlas-sdk` now requires
  `atlas-protocol>=1.0.1`.

## [1.0.0] — 2026-07-06

The repo is now the **Atlas SDK monorepo**: `protocol/` ships `atlas-protocol`
(Atlas Protocol / ALP) and `sdk/` ships `atlas-sdk` (the `atlas` CLI). Protocol
version stays **1.0** — everything added below landed inside the announced
0.1.0 draft window, which this release closes.

### atlas-protocol 1.0.0

#### Added
- **The `.atlas` container format v2** (`packaging.py`): signed, tamper-evident
  plugin packages carrying a cleartext manifest, a portable Python **source
  bundle** (no marshalled bytecode), small embedded artifacts, and optional
  AES-256-GCM payload encryption.
- **Ed25519 signing** (`signing.py`): keypair generation, detached signature
  blocks over the full payload, file signing, and verification. One flipped
  byte fails verification.
- **The local trust store** (`trust.py`): publisher keys resolve to
  `TrustLevel.FIRST_PARTY` / `TRUSTED_SIGNED` / `UNKNOWN_SIGNED` / `UNSIGNED`;
  add/list/remove plus best-effort revocation; `ATLAS_TRUST_DIR` override;
  bundled first-party anchors under `atlas_protocol/keys/first_party/`
  (public keys only).
- **Content-addressed external assets** (`assets.py`): fat models/native libs
  declared by `sha256` + size + sources (`file://` | `hf://` | `https://`),
  hash-verified on fetch, cached, air-gap friendly (network fetch is opt-in via
  `ATLAS_ALLOW_ASSET_DOWNLOAD=1`).
- **Executable conformance suite** (`conformance.py`): validates a plugin
  directory the way a runtime would (manifest strictness, schema sanity, import
  isolation); surfaced as `atlas test`.
- `TrustLevel` enum; `py.typed` marker (PEP 561).

#### Changed
- Runtime dependencies are now **pydantic + cryptography** (was pydantic only)
  to carry the signing layer.
- Package version aligned to the finalized contract: `1.0.0` implements
  protocol `1.0` and container format `v2`.

### atlas-sdk 1.0.0 (new package)

- The **`atlas` CLI** (also installed as `atlas-sdk`): `init` (scaffold from
  domain-neutral templates for `python`/`gguf`/`onnx`/`native`/`generic`
  runtimes), `validate`, `build` (+`--sign`/`--encrypt`), `keygen`, `sign`,
  `verify`, `trust add|list|remove|revoke`, `inspect`, `test`.
- `PluginManifest` validation mirroring runtime strictness, so build == load.
- End-to-end CLI test suite (`sdk/tests/test_cli_e2e.py`) — the README
  quickstart, executed: scaffold → validate → keygen → build+sign → verify →
  trust → inspect → conformance, plus unsigned/tampered/wrong-key refusal paths.

### Repository

- Restructured into the two-package monorepo layout (`protocol/` + `sdk/`) with
  an umbrella README fixing the SDK-vs-protocol naming scheme.
- CI: test matrix (Ubuntu/Windows × Python 3.10/3.13), wheel builds with
  `twine check`, and a CLI smoke test against `examples/hello_sensor/`.
- Release workflow: pushing a `v*` tag builds both packages and attaches the
  artifacts to the GitHub Release.
- `examples/hello_sensor/` — a runnable example plugin, exercised by CI.

## [0.1.0] — 2026-07-01

First public release of the open protocol layer. Protocol version **1.0**.

### Added
- `CapabilityManifest` / `CapabilityDecl` — the single source of truth for plugin
  and core-tool metadata, with `extra="forbid"` strictness and name linting.
- The six `CapabilityKind`s (`tool`, `oracle`, `theorist`, `instrument`,
  `verifier`, `actuator`) and the `Actor` firewall vocabulary.
- The wire envelope: `ToolRequest`/`ToolResult`, `Measurement` (the sole
  ledger-authority channel, NaN/Inf rejected), the `display`/`record` split,
  `ApprovalGrant`, `HandoffTicket`, `Provenance`.
- `Goal`/`Criterion`/`GradeResult` — graded predicates over named sealed verifiers.
- `ProblemClass`/`Axis` — unit-aware, embedding-backed cross-campaign transfer.
- `ModelDescriptor` — the model-agnostic, offline-by-contract brain socket.
- `export_schemas()`, `schema_hash()`, and the `compat.py` backward-compatibility
  gate (`diff_io_schemas`, `is_backward_compatible`).
- Protocol version negotiation (`negotiate`, `ProtocolVersion`).
