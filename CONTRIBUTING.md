# Contributing to Atlas Protocol

Thanks for your interest. This package is the **contract surface** for Atlas, so
changes are held to a high bar: a change here ripples to every plugin, kernel,
and conformance suite that imports it.

## Ground rules

- **Adding an enum value or a model field is a protocol change.** It must bump the
  protocol minor (`atlas_protocol/version.py`) and be recorded in `CHANGELOG.md`.
  Adding a *plugin* is never a protocol change and does not belong here.
- **Keep it dependency-light.** The runtime dependency set is `pydantic` only.
  Please do not add others.
- **No domain leakage.** The protocol must not read or encode any specific science
  (no `SMILES`, `IC50`, etc.). Capability/field names are linted against this.
- **Everything is typed and `extra="forbid"`.** New models follow the same
  strictness; typos and stray fields should fail loudly at build time.
- **Backward compatibility is mechanical.** `schemas.py` + `compat.py` decide
  whether a change is breaking. Run the suite and the compat gate before opening a
  PR.

## Developer setup

```bash
pip install -e ".[dev]"
pytest -q
```

## DCO / CLA

By contributing you agree your contribution is licensed under Apache-2.0. A CLA
may be requested for substantial contributions so the project retains licensing
flexibility for the broader Atlas framework.
