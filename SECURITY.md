# Security Policy

Atlas Protocol is the contract for a system whose entire value rests on results
being trustworthy. The protocol's security properties are therefore part of its
correctness. We especially want to hear about any way to defeat one of these
invariants:

- **Actor firewall bypass** — a path that lets `Actor.ATLAS` (the cognition
  brain) author a `Measurement`, mint a number with ledger authority, or actuate.
- **Non-finite poisoning** — any way a `NaN`/`Inf` (or other non-finite value)
  reaches a `Measurement.value` or the canonical-JSON hashing layer.
- **Sealed-target leakage** — a `record`/`display` projection that lets a sealed
  criterion target reach a model-facing channel.
- **Schema-hash ambiguity** — two materially different schemas that
  `schema_hash()` treats as equal (a false-negative in the backward-compat gate),
  or a canonicalization that rejects a valid schema.

## Reporting

Please report suspected vulnerabilities privately via GitHub's **"Report a
vulnerability"** (Security → Advisories) on this repository, rather than opening a
public issue. Include a minimal reproduction. We aim to acknowledge within a few
business days.

This repository is the open protocol layer only; reports about the closed Atlas
engine should not be filed here.
