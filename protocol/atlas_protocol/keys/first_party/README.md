# First-party trust anchors

Every `*.pub` file in this directory is an Ed25519 **public** key whose signed
`.atlas` packages resolve to `TrustLevel.FIRST_PARTY` (in-proc fast path, no
prompt). One hex-encoded 32-byte public key per file; the filename is the
key id (`sha256(pubkey)[:16]`), e.g. `a1b2c3d4e5f60718.pub`.

**Never commit a private key.** Generate a keypair with `atlas keygen`, keep the
private half in the release owner's secret store (see the key-management runbook),
and drop only the `.pub` here for the release build.

This directory ships intentionally empty of production keys: the production
first-party public key is added at release time by the key custodian
(CORE_ARCHITECTURE Open Decision #7). Tests inject ephemeral keys via
`ATLAS_TRUST_DIR`, so an empty first-party anchor here is the correct default.
