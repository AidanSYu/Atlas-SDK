"""The `atlas test` conformance subset."""
from __future__ import annotations

import json
from pathlib import Path

from atlas_protocol.conformance import run_conformance


def _plugin(tmp_path, manifest: dict, wrapper: str) -> Path:
    d = tmp_path / manifest["name"]
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (d / "wrapper.py").write_text(wrapper, encoding="utf-8")
    return d


_CLEAN = "def invoke(a, c=None):\n    return {'ok': True}\n"


def test_clean_plugin_passes(tmp_path):
    d = _plugin(tmp_path, {"name": "clean", "description": "x", "entry_point": "wrapper.py"}, _CLEAN)
    report = run_conformance(d)
    assert report.passed
    names = {c.name for c in report.checks}
    assert {"manifest", "schemas", "assets", "isolation", "effects_lint", "signature_roundtrip"} <= names


def test_app_import_fails_isolation(tmp_path):
    d = _plugin(tmp_path, {"name": "bad", "description": "x"},
                "import app.core.database\ndef invoke(a, c=None):\n    return {}\n")
    report = run_conformance(d)
    assert not report.passed
    iso = next(c for c in report.checks if c.name == "isolation")
    assert not iso.passed


def test_undeclared_network_is_advisory_warn(tmp_path):
    d = _plugin(tmp_path, {"name": "netty", "description": "x"},
                "import socket\ndef invoke(a, c=None):\n    return {}\n")
    report = run_conformance(d)
    lint = next(c for c in report.checks if c.name == "effects_lint")
    assert not lint.passed and lint.advisory
    assert report.passed  # advisory never fails the run


def test_declared_network_lint_clean(tmp_path):
    d = _plugin(tmp_path, {"name": "netok", "description": "x", "tags": ["network"]},
                "import socket\ndef invoke(a, c=None):\n    return {}\n")
    report = run_conformance(d)
    lint = next(c for c in report.checks if c.name == "effects_lint")
    assert lint.passed


def test_malformed_asset_ref_fails(tmp_path):
    d = _plugin(tmp_path, {"name": "am", "description": "x",
                           "assets": [{"name": "m", "sha256": "tooshort"}]}, _CLEAN)
    report = run_conformance(d)
    assert not report.passed
    a = next(c for c in report.checks if c.name == "assets")
    assert not a.passed
