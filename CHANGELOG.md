# Changelog

All notable changes to the Atlas Protocol are recorded here. The protocol version
(`PROTOCOL_VERSION` in `atlas_protocol/version.py`) is bumped whenever an enum
value or model field is added/changed; the package version tracks releases.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

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
