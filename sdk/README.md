# atlas-sdk

Developer toolkit for building **`.atlas`** plugin packages for the Atlas Framework.

A `.atlas` is a signed, tamper-evident container carrying a plugin's manifest
(always cleartext), a portable Python **source bundle**, small embedded assets,
and an **Ed25519 signature block**. Large binaries (fat ML models, native libs)
are *not* embedded — they are declared as **content-addressed** assets and fetched
+ hash-verified at load time, so the container stays small.

The one implementation of the format, signing, trust store, and asset resolver
lives in [`atlas-protocol`](https://github.com/AidanSYu/Atlas-SDK/tree/main/protocol);
this SDK is a thin front-end so a package you build and one the runtime loads
always agree.

## Install

```bash
pip install atlas-sdk        # pulls in atlas-protocol
```

## Quickstart

```bash
# 1. Scaffold (domain-neutral templates — pick a runtime)
atlas init my_tool --runtime python

# 2. Implement wrapper.py, then validate the manifest
atlas validate my_tool

# 3. Make a publisher keypair ONCE (keep the .key secret)
atlas keygen -o my_publisher

# 4. Build + sign
atlas build my_tool --sign my_publisher.key -o my_tool.atlas

# 5. Verify + inspect
atlas verify my_tool.atlas
atlas inspect my_tool.atlas

# 6. Run the conformance suite before publishing
atlas test my_tool
```

## Trust model

The runtime refuses to execute an **unsigned** or **unknown-publisher** `.atlas`
by default. To let a machine run your packages, trust your public key there once:

```bash
atlas trust add my_publisher.pub --label "My Lab"   # → trusted_signed
atlas trust list
atlas trust revoke <key_id>                          # best-effort revocation
```

Trust tiers: `first_party` (shipped with Atlas) and `trusted_signed` (in the
local trust store) run in-process; `unknown_signed` / `unsigned` are refused
unless `ATLAS_ALLOW_UNTRUSTED=1` (runs in-process with **no** OS isolation — a
named later hardening workstream, not a sandbox).

## Large models (content-addressed assets)

Declare big files in `manifest.json` instead of embedding them:

```json
"assets": [
  {"name": "model.gguf",
   "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
   "size": 4600000000,
   "sources": ["file:///mnt/models/model.gguf", "hf://ORG/REPO/model.gguf"],
   "mode": "required"}
]
```

At load the resolver checks a content-addressed cache, else fetches from the
first reachable source, **verifies the sha256** (a hostile mirror can't swap the
file), and caches it. Your wrapper reads the verified path from the injected
`__atlas_asset_paths__` map. Air-gapped? Pre-seed the cache or point a `file://`
source at a local mirror — nothing touches the network (network fetch also
requires `ATLAS_ALLOW_ASSET_DOWNLOAD=1`).

## CLI reference

| Command | Purpose |
|---|---|
| `atlas init <name> [--runtime ...]` | Scaffold a plugin (domain-neutral) |
| `atlas validate <dir>` | Validate manifest + schemas + asset refs |
| `atlas build [dir] [--encrypt] [--sign KEY]` | Build (+optionally encrypt/sign) a `.atlas` |
| `atlas keygen [-o name]` | Generate an Ed25519 publisher keypair |
| `atlas sign <file> --key KEY` | Sign a built `.atlas` in place |
| `atlas verify <file> [--pubkey HEX]` | Verify the signature + report trust level |
| `atlas trust add\|list\|remove\|revoke` | Manage the local trust store |
| `atlas inspect <file> [--json]` | Show manifest + metadata |
| `atlas test <dir> [--json]` | Run the conformance suite |
