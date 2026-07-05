# Atlas SDK

[![CI](https://github.com/AidanSYu/Atlas-SDK/actions/workflows/ci.yml/badge.svg)](https://github.com/AidanSYu/Atlas-SDK/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**Everything you need to build for [Atlas](https://github.com/AidanSYu) — the
autonomous-lab framework — in one repo.** The Atlas SDK is two small Python
packages with one job each:

| Package | Import | You want to… | Docs |
|---|---|---|---|
| **`atlas-protocol`** — Atlas Protocol (ALP) | `atlas_protocol` | Depend on the open *contract*: typed capability manifests, the actor-firewall envelope, goals, transfer, and the signed `.atlas` container format | [`protocol/`](protocol/README.md) |
| **`atlas-sdk`** — the developer toolkit | `atlas_sdk` | *Build and ship* a plugin: the `atlas` CLI scaffolds, validates, builds, signs, verifies, and conformance-tests `.atlas` packages | [`sdk/`](sdk/README.md) |

```bash
pip install atlas-sdk        # the toolkit; pulls in atlas-protocol
pip install atlas-protocol   # just the contract library (pydantic + cryptography)
```

> The Atlas **engine** — the verification-firewall implementation, the per-lab
> compounding ledger, and the physical-instrument bridges — is a separate,
> closed product and is **not** in this repo. The protocol is open so the
> contract is auditable and anyone can build to it.

## The names, once and for all

- **Atlas SDK** — this repository: the umbrella developer kit.
- **Atlas Protocol (ALP)** — the open contract, shipped as the `atlas-protocol`
  package. If a thing defines *what counts* (types, schemas, signatures, trust
  levels), it lives here.
- **`atlas-sdk`** — the toolkit package that ships the **`atlas`** CLI. If a
  thing helps a *developer do* something (scaffold, build, sign, inspect), it
  lives here. The CLI is a thin front-end: the one implementation of the format,
  signing, trust store, and asset resolver lives in `atlas-protocol`, so a
  package you build and one the runtime loads always agree.
- **`.atlas`** — the signed, tamper-evident plugin container format defined by
  the protocol (container format **v2**).

Three version axes, deliberately distinct:

1. **Protocol version** (`PROTOCOL_VERSION`, currently **1.0**) — the wire/type
   contract. Plugins declare the ALP they were authored against; kernels
   negotiate `native` / `compat` / `refuse`.
2. **Container format version** (currently **v2**) — the `.atlas` binary layout
   (source bundle, Ed25519 signature block, content-addressed assets).
3. **Package versions** (semver) — releases of the two distributions above.

## Quickstart — ship a signed plugin in five commands

```bash
pip install atlas-sdk

atlas init my_tool --runtime python     # scaffold manifest.json + wrapper.py
atlas keygen -o my_publisher            # Ed25519 keypair (keep the .key secret)
atlas build my_tool --sign my_publisher.key -o my_tool.atlas
atlas verify my_tool.atlas              # signature + trust level
atlas test my_tool                      # conformance suite
```

A runnable example lives in [`examples/hello_sensor/`](examples/hello_sensor) —
CI builds, signs, verifies, and conformance-tests it on every push.

## Repository layout

```
protocol/          the atlas-protocol package (Atlas Protocol / ALP)
  atlas_protocol/    typed models + .atlas packaging, signing, trust, assets, conformance
  tests/             executable conformance suite for the contract
sdk/               the atlas-sdk package (developer toolkit)
  atlas_sdk/         the `atlas` CLI, manifest validation, scaffolding templates
  tests/             end-to-end CLI tests (the README quickstart, executed)
examples/          runnable example plugins
```

Develop from a checkout:

```bash
pip install -e "./protocol[dev]" -e ./sdk
pytest protocol/tests sdk/tests
```

## Security

The protocol is the contract for a system whose entire value rests on results
being trustworthy: the actor firewall, non-finite rejection, sealed-target
separation, Ed25519 signing, and the trust store are security surfaces. See
[`SECURITY.md`](SECURITY.md) for the invariants we most want adversarial eyes
on, and how to report privately.

## License

[Apache-2.0](LICENSE). © 2026 Contineon.
