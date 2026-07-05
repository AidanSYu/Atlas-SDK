"""End-to-end tests for the `atlas` CLI — the full publisher flow.

Drives the real CLI entry point (no mocks) through scaffold -> validate ->
keygen -> build+sign -> verify -> trust -> inspect -> conformance, plus the
refusal paths (unsigned, tampered). These are the executable version of the
README quickstart, so if the docs drift from the CLI this suite fails.
"""
from __future__ import annotations

import json
import sys

import pytest

from atlas_sdk import cli


def _run(capsys, *args: str) -> tuple[int, str]:
    """Invoke the CLI exactly as the console script does; return (exit_code, output)."""
    old_argv = sys.argv
    sys.argv = ["atlas", *args]
    code = 0
    try:
        cli.main()
    except SystemExit as exc:  # argparse errors and _die() land here
        code = int(exc.code or 0)
    finally:
        sys.argv = old_argv
    captured = capsys.readouterr()
    return code, captured.out + captured.err


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """Isolated cwd + trust store so keygen/trust never touch the real machine."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ATLAS_TRUST_DIR", str(tmp_path / "trust"))
    monkeypatch.delenv("ATLAS_ALLOW_UNTRUSTED", raising=False)
    return tmp_path


def _scaffold(capsys, workdir, name: str = "hello_sensor"):
    code, out = _run(capsys, "init", name, "--runtime", "python")
    assert code == 0, out
    plugin = workdir / name
    manifest_path = plugin / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # A publishable plugin has a real description; the scaffold ships a TODO.
    manifest["description"] = "Echoes its input back (end-to-end test plugin)."
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return plugin


def test_full_publish_flow(capsys, workdir):
    plugin = _scaffold(capsys, workdir)

    code, out = _run(capsys, "validate", str(plugin))
    assert code == 0 and "OK" in out

    code, out = _run(capsys, "keygen", "-o", "publisher")
    assert code == 0
    assert (workdir / "publisher.key").exists() and (workdir / "publisher.pub").exists()

    out_atlas = workdir / "hello_sensor.atlas"
    code, out = _run(capsys, "build", str(plugin), "--sign", "publisher.key", "-o", str(out_atlas))
    assert code == 0 and out_atlas.exists(), out
    assert "signed" in out

    # Signed by a key the machine has never seen -> valid sig, unknown publisher.
    code, out = _run(capsys, "verify", str(out_atlas))
    assert code == 0 and "signature valid" in out
    assert "unknown_signed" in out

    code, out = _run(capsys, "trust", "add", "publisher.pub", "--label", "e2e")
    assert code == 0 and "Trusted publisher" in out

    code, out = _run(capsys, "verify", str(out_atlas))
    assert code == 0 and "trusted_signed" in out

    code, out = _run(capsys, "trust", "list")
    assert code == 0 and "trusted_signed" in out

    code, out = _run(capsys, "inspect", str(out_atlas), "--json")
    assert code == 0
    info = json.loads(out)
    assert info["signed"] is True and info["manifest"]["name"] == "hello_sensor"

    code, out = _run(capsys, "test", str(plugin))
    assert code == 0, f"conformance failed:\n{out}"
    assert "RESULT: PASS" in out


def test_unsigned_build_is_flagged_and_refused(capsys, workdir):
    plugin = _scaffold(capsys, workdir, "bare_tool")
    out_atlas = workdir / "bare_tool.atlas"
    code, out = _run(capsys, "build", str(plugin), "-o", str(out_atlas))
    assert code == 0 and "unsigned" in out

    code, out = _run(capsys, "verify", str(out_atlas))
    assert code == 1 and "UNSIGNED" in out


def test_tampered_package_fails_verify(capsys, workdir):
    plugin = _scaffold(capsys, workdir)
    _run(capsys, "keygen", "-o", "publisher")
    out_atlas = workdir / "hello_sensor.atlas"
    code, _ = _run(capsys, "build", str(plugin), "--sign", "publisher.key", "-o", str(out_atlas))
    assert code == 0

    blob = bytearray(out_atlas.read_bytes())
    blob[len(blob) // 2] ^= 0xFF
    out_atlas.write_bytes(bytes(blob))

    code, out = _run(capsys, "verify", str(out_atlas))
    assert code == 1, "a tampered .atlas must never verify"


def test_verify_rejects_wrong_pubkey(capsys, workdir):
    plugin = _scaffold(capsys, workdir)
    _run(capsys, "keygen", "-o", "publisher")
    _run(capsys, "keygen", "-o", "other")
    out_atlas = workdir / "hello_sensor.atlas"
    _run(capsys, "build", str(plugin), "--sign", "publisher.key", "-o", str(out_atlas))

    other_pub = (workdir / "other.pub").read_text(encoding="utf-8").strip()
    code, out = _run(capsys, "verify", str(out_atlas), "--pubkey", other_pub)
    assert code == 1 and "different key" in out


def test_validate_missing_manifest_dies(capsys, workdir):
    empty = workdir / "empty"
    empty.mkdir()
    code, out = _run(capsys, "validate", str(empty))
    assert code == 1 and "no manifest.json" in out


def test_init_refuses_existing_directory(capsys, workdir):
    _scaffold(capsys, workdir, "dupe")
    code, out = _run(capsys, "init", "dupe", "--runtime", "python")
    assert code == 1 and "already exists" in out
