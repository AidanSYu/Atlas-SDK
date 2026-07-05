# Contributing to the Atlas SDK

Thanks for your interest. This repo is the **open developer surface** of Atlas:
`protocol/` ships the contract (`atlas-protocol`) and `sdk/` ships the `atlas`
CLI (`atlas-sdk`). Changes to the protocol are held to a high bar: a change
there ripples to every plugin, kernel, and conformance suite that imports it.

## Which package does my change belong in?

- Defines *what counts* — a type, schema, wire shape, signature/trust rule, or
  the `.atlas` format itself → `protocol/atlas_protocol/`.
- Helps a *developer do* something — CLI behavior, scaffolding templates,
  validation UX → `sdk/atlas_sdk/`. The SDK must stay a thin front-end: format,
  signing, trust, and asset logic live in the protocol package only, so a
  package you build and one a runtime loads always agree.

## Ground rules

- **Adding an enum value or a model field is a protocol change.** It must bump the
  protocol minor (`protocol/atlas_protocol/version.py`) and be recorded in
  `CHANGELOG.md`. Adding a *plugin* is never a protocol change and does not
  belong here.
- **Keep it dependency-light.** Runtime deps for `atlas-protocol` are
  `pydantic` + `cryptography` only; `atlas-sdk` adds nothing beyond those.
  Please do not add others.
- **No domain leakage.** The protocol must not read or encode any specific science
  (no `SMILES`, `IC50`, etc.). Capability/field names are linted against this.
- **Everything is typed and `extra="forbid"`.** New models follow the same
  strictness; typos and stray fields should fail loudly at build time.
- **Backward compatibility is mechanical.** `schemas.py` + `compat.py` decide
  whether a change is breaking. Run the suite and the compat gate before opening a
  PR.
- **Never commit a private key.** Only `*.pub` trust anchors may live in
  `protocol/atlas_protocol/keys/first_party/`; `.gitignore` blocks `*.key`.

## Developer setup

```bash
pip install -e "./protocol[dev]" -e ./sdk
pytest protocol/tests sdk/tests -q
```

The CLI end-to-end suite (`sdk/tests/test_cli_e2e.py`) is the executable
version of the README quickstart — if you change CLI behavior, change it too.

## Releases

Versions live in `protocol/pyproject.toml` and `sdk/pyproject.toml` (kept in
lockstep with `atlas_sdk.__version__`). Tag `vX.Y.Z` on `main`; the release
workflow builds both packages, runs `twine check`, and attaches the artifacts
to the GitHub Release for that tag.

## DCO / CLA

By contributing you agree your contribution is licensed under Apache-2.0. A CLA
may be requested for substantial contributions so the project retains licensing
flexibility for the broader Atlas framework.
