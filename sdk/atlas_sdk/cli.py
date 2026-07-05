#!/usr/bin/env python3
"""atlas - developer CLI for building, signing, and verifying .atlas plugins.

Commands
--------
    atlas init <name> [--runtime python|gguf|onnx|native|generic]
    atlas validate <dir>
    atlas build [dir] [-o out.atlas] [--encrypt] [--key KEY] [--sign KEYFILE] [--key-pass P]
    atlas keygen [-o name] [--pass P]
    atlas sign <file.atlas> --key KEYFILE [--key-pass P]
    atlas verify <file.atlas> [--pubkey HEX]
    atlas trust add <pubkey-or-file> [--label L] | list | remove <key_id> | revoke <key_id>
    atlas inspect <file.atlas> [--json]
    atlas test <dir> [--json]

The one `.atlas` implementation lives in ``atlas_protocol`` - this CLI is a thin
front-end over it, so a package it builds and one the runtime loads always agree.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from atlas_protocol import assets, conformance, packaging, signing, trust
from atlas_sdk.manifest import PluginManifest
from atlas_sdk.templates import SUPPORTED_RUNTIMES, get_manifest, get_wrapper


def _die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def _load_manifest(plugin_dir: Path) -> dict:
    mp = plugin_dir / "manifest.json"
    if not mp.exists():
        _die(f"no manifest.json in {plugin_dir}")
    try:
        data = json.loads(mp.read_text(encoding="utf-8"))
        PluginManifest.model_validate(data)
    except Exception as exc:
        _die(f"invalid manifest.json: {exc}")
    return data


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #

def cmd_init(args: argparse.Namespace) -> None:
    runtime = args.runtime or "python"
    if runtime not in SUPPORTED_RUNTIMES:
        _die(f"unknown runtime '{runtime}'. Choose from: {', '.join(SUPPORTED_RUNTIMES)}")
    out_dir = Path(args.output or ".") / args.name
    if out_dir.exists():
        _die(f"directory already exists: {out_dir}")
    out_dir.mkdir(parents=True)
    (out_dir / "manifest.json").write_text(get_manifest(args.name, runtime), encoding="utf-8")
    (out_dir / "wrapper.py").write_text(get_wrapper(args.name, runtime), encoding="utf-8")
    print(f"Scaffolded {out_dir}/  (runtime: {runtime})")
    print("  Edit manifest.json (description, schemas) and wrapper.py, then: atlas build")


# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #

def cmd_validate(args: argparse.Namespace) -> None:
    plugin_dir = Path(args.directory)
    manifest = _load_manifest(plugin_dir)
    entry = manifest.get("entry_point", "wrapper.py")
    if not (plugin_dir / entry).exists():
        _die(f"entry point not found: {plugin_dir / entry}")
    # Asset refs must be well-formed.
    for d in manifest.get("assets", []) or []:
        try:
            ref = assets.AssetRef.from_dict(d)
            if "TODO" in ref.sha256:
                _die(f"asset '{ref.name}' still has a TODO sha256 - run atlas build to fill it in")
        except assets.AssetResolutionError as exc:
            _die(str(exc))
    print(f"OK: {manifest['name']} v{manifest.get('version', '?')} - manifest and schemas valid")


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #

def cmd_build(args: argparse.Namespace) -> None:
    plugin_dir = Path(args.directory or ".")
    manifest = _load_manifest(plugin_dir)

    passphrase = None
    if args.encrypt:
        import os
        passphrase = args.key or os.environ.get("ATLAS_PLUGIN_KEY")
        if not passphrase:
            _die("--encrypt requires --key or ATLAS_PLUGIN_KEY")

    sign = None
    if args.sign:
        pem = Path(args.sign).read_bytes()
        key = signing.load_private_key(pem, args.key_pass)
        sign = signing.make_signer(key)

    try:
        data = packaging.pack_plugin_directory(plugin_dir, manifest, passphrase=passphrase, sign=sign)
    except packaging.AtlasFormatError as exc:
        _die(str(exc))

    out = Path(args.output or f"{manifest['name']}.atlas")
    out.write_bytes(data)
    flags = []
    if passphrase:
        flags.append("encrypted")
    if sign:
        flags.append("signed")
    print(f"Built {out} ({out.stat().st_size:,} bytes){' [' + ', '.join(flags) + ']' if flags else ''}")
    if not sign:
        print("  note: unsigned - the runtime refuses unsigned .atlas unless ATLAS_ALLOW_UNTRUSTED=1.")
        print("  Sign it: atlas keygen && atlas sign " + out.name + " --key <name>.key")


# --------------------------------------------------------------------------- #
# keygen / sign / verify
# --------------------------------------------------------------------------- #

def cmd_keygen(args: argparse.Namespace) -> None:
    name = args.output or "atlas_publisher"
    priv, pub = signing.generate_keypair(passphrase=args.key_pass)
    key_path = Path(f"{name}.key")
    pub_path = Path(f"{name}.pub")
    if key_path.exists() or pub_path.exists():
        _die(f"{key_path} or {pub_path} already exists - choose another -o name")
    key_path.write_bytes(priv)
    pub_path.write_text(pub, encoding="utf-8")
    print(f"Wrote {key_path} (PRIVATE - keep secret) and {pub_path} (public)")
    print(f"  key_id: {signing.key_id(pub)}")
    print(f"  Trust this publisher on a machine with: atlas trust add {pub_path}")


def cmd_sign(args: argparse.Namespace) -> None:
    path = Path(args.file)
    if not path.exists():
        _die(f"file not found: {path}")
    pem = Path(args.key).read_bytes()
    signing.sign_file(path, pem, passphrase=args.key_pass)
    info = packaging.inspect_atlas(path)
    print(f"Signed {path}  (key_id {info['publisher_key_id']})")


def cmd_verify(args: argparse.Namespace) -> None:
    path = Path(args.file)
    if not path.exists():
        _die(f"file not found: {path}")
    try:
        pkg = packaging.read_atlas(path, verify_signature=True, manifest_only=True)
    except packaging.AtlasFormatError as exc:
        print(f"FAIL: {path} - {exc}", file=sys.stderr)
        sys.exit(1)
    if not pkg.is_signed:
        print(f"UNSIGNED: {path} - no signature (the runtime refuses this by default)")
        sys.exit(1)
    if args.pubkey and pkg.sigblock.get("pubkey") != args.pubkey:
        print(f"FAIL: {path} - signed by a different key than --pubkey", file=sys.stderr)
        sys.exit(1)
    level = trust.resolve_trust_level(pkg.sigblock, signature_verified=pkg.signature_verified)
    print(f"OK: {path} - signature valid")
    print(f"  key_id:      {pkg.sigblock.get('key_id')}")
    print(f"  trust_level: {level.value}")


# --------------------------------------------------------------------------- #
# trust
# --------------------------------------------------------------------------- #

def cmd_trust(args: argparse.Namespace) -> None:
    if args.action == "list":
        entries = trust.list_trusted()
        if not entries:
            print("(no trusted keys)")
        for e in entries:
            print(f"  {e['tier']:14} {e['key_id']}  {e['pubkey'][:16]}...")
        print(f"trust store: {trust.trust_dir()}")
        return
    if args.action == "add":
        val = args.value
        p = Path(val)
        pubhex = p.read_text(encoding="utf-8").strip() if p.exists() else val
        kid = trust.add_trusted_publisher(pubhex, label=args.label or "")
        print(f"Trusted publisher {kid}")
        return
    if args.action == "remove":
        print("removed" if trust.remove_trusted_publisher(args.value) else "not found")
        return
    if args.action == "revoke":
        trust.revoke(args.value)
        print(f"revoked {args.value}")
        return
    _die(f"unknown trust action: {args.action}")


# --------------------------------------------------------------------------- #
# inspect / test
# --------------------------------------------------------------------------- #

def cmd_inspect(args: argparse.Namespace) -> None:
    path = Path(args.file)
    if not path.exists():
        _die(f"file not found: {path}")
    info = packaging.inspect_atlas(path)
    if args.json:
        print(json.dumps(info, indent=2))
        return
    m = info["manifest"]
    print(f"Atlas package: {path}  ({info['file_size']:,} bytes)")
    print(f"  name:        {m.get('name')}  v{m.get('version', '?')}")
    print(f"  description: {m.get('description', '')}")
    print(f"  encrypted:   {info['encrypted']}    signed: {info['signed']}"
          + (f"  (key_id {info['publisher_key_id']})" if info['signed'] else ""))
    print(f"  assets:      {len(m.get('assets', []) or [])} content-addressed ref(s)")


def cmd_test(args: argparse.Namespace) -> None:
    report = conformance.run_conformance(Path(args.directory))
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"Conformance: {report.plugin}")
        for c in report.checks:
            mark = "PASS" if c.passed else ("WARN" if c.advisory else "FAIL")
            print(f"  [{mark}] {c.name}: {c.detail}")
        print("RESULT:", "PASS" if report.passed else "FAIL")
    sys.exit(0 if report.passed else 1)


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="atlas", description="Build, sign, and verify .atlas plugins.")
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("init", help="scaffold a new plugin")
    pi.add_argument("name")
    pi.add_argument("--runtime", help=f"one of: {', '.join(SUPPORTED_RUNTIMES)}")
    pi.add_argument("-o", "--output", help="parent directory")
    pi.set_defaults(func=cmd_init)

    pv = sub.add_parser("validate", help="validate a plugin directory")
    pv.add_argument("directory")
    pv.set_defaults(func=cmd_validate)

    pb = sub.add_parser("build", help="compile a plugin directory to .atlas")
    pb.add_argument("directory", nargs="?", default=".")
    pb.add_argument("-o", "--output")
    pb.add_argument("--encrypt", action="store_true", help="AES-256-GCM encrypt the payload")
    pb.add_argument("--key", help="encryption passphrase (or ATLAS_PLUGIN_KEY)")
    pb.add_argument("--sign", help="Ed25519 private key file to sign with")
    pb.add_argument("--key-pass", help="passphrase for the signing key")
    pb.set_defaults(func=cmd_build)

    pk = sub.add_parser("keygen", help="generate an Ed25519 signing keypair")
    pk.add_argument("-o", "--output", help="basename (writes <name>.key and <name>.pub)")
    pk.add_argument("--key-pass", help="encrypt the private key with this passphrase")
    pk.set_defaults(func=cmd_keygen)

    ps = sub.add_parser("sign", help="sign a .atlas in place")
    ps.add_argument("file")
    ps.add_argument("--key", required=True, help="Ed25519 private key file")
    ps.add_argument("--key-pass")
    ps.set_defaults(func=cmd_sign)

    pver = sub.add_parser("verify", help="verify a .atlas signature + report trust")
    pver.add_argument("file")
    pver.add_argument("--pubkey", help="assert the package was signed by this hex public key")
    pver.set_defaults(func=cmd_verify)

    pt = sub.add_parser("trust", help="manage the local trust store")
    pt.add_argument("action", choices=["add", "list", "remove", "revoke"])
    pt.add_argument("value", nargs="?", help="pubkey/file (add) or key_id (remove/revoke)")
    pt.add_argument("--label", help="label for an added publisher")
    pt.set_defaults(func=cmd_trust)

    pins = sub.add_parser("inspect", help="show manifest + metadata")
    pins.add_argument("file")
    pins.add_argument("--json", action="store_true")
    pins.set_defaults(func=cmd_inspect)

    ptest = sub.add_parser("test", help="run the conformance suite")
    ptest.add_argument("directory")
    ptest.add_argument("--json", action="store_true")
    ptest.set_defaults(func=cmd_test)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
