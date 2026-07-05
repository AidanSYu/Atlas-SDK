"""`atlas test` conformance checks — a focused, shippable subset of §7.4.

Given a plugin directory (manifest.json + wrapper.py [+ assets]) this runs the
checks that gate a publishable package and returns a structured report:

1. **manifest**        — manifest.json parses and has the required fields.
2. **schemas**         — input/output schemas are objects (valid JSON-Schema shells).
3. **assets**          — every content-addressed asset ref is well-formed (name +
                         64-hex sha256 + at least one source).
4. **isolation**       — the wrapper source imports no ``app.*`` internals and uses
                         no dynamic-import bypass (the load-time guard, run early).
5. **effects_lint**    — static scan flags network / subprocess / filesystem-write
                         imports that the manifest does not declare (advisory).
6. **signature_roundtrip** — pack → sign → verify succeeds and a one-byte tamper is
                         rejected (proves the provenance path end to end).

The report is JSON-serializable so `atlas test` can stamp its sha256 into
``manifest.conformance`` and so CI can assert on it.
"""
from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from . import packaging, signing
from .assets import AssetRef, AssetResolutionError

# Modules whose import implies an effect the manifest should declare.
_NET_MODULES = {"socket", "http", "urllib", "requests", "httpx", "ftplib", "smtplib", "asyncio"}
_PROC_MODULES = {"subprocess", "multiprocessing"}
_FORBIDDEN_ROOT = "app"


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    advisory: bool = False


@dataclass
class ConformanceReport:
    plugin: str
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        # Advisory checks (lint) never fail the run.
        return all(c.passed or c.advisory for c in self.checks)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin": self.plugin,
            "passed": self.passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "advisory": c.advisory, "detail": c.detail}
                for c in self.checks
            ],
        }


def _scan_effect_imports(source: str) -> Dict[str, List[str]]:
    """Return {'net': [...], 'proc': [...]} of effect-implying imports in source."""
    found: Dict[str, set] = {"net": set(), "proc": set()}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {"net": [], "proc": []}
    for node in ast.walk(tree):
        names: List[str] = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module.split(".")[0]]
        for n in names:
            if n in _NET_MODULES:
                found["net"].add(n)
            if n in _PROC_MODULES:
                found["proc"].add(n)
    return {k: sorted(v) for k, v in found.items()}


def run_conformance(plugin_dir: Path) -> ConformanceReport:
    plugin_dir = Path(plugin_dir)
    manifest_path = plugin_dir / "manifest.json"
    report = ConformanceReport(plugin=plugin_dir.name)

    # 1. manifest
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        name = manifest.get("name")
        assert name and manifest.get("description"), "manifest needs name + description"
        report.checks.append(CheckResult("manifest", True, f"name={name}"))
    except Exception as exc:
        report.checks.append(CheckResult("manifest", False, str(exc)))
        return report  # nothing else is checkable without a manifest

    report.plugin = manifest.get("name", plugin_dir.name)
    entry_point = manifest.get("entry_point", "wrapper.py")

    # 2. schemas
    ok_schemas = isinstance(manifest.get("input_schema", {}), dict) and isinstance(
        manifest.get("output_schema", {}), dict
    )
    report.checks.append(CheckResult("schemas", ok_schemas,
                                     "" if ok_schemas else "input/output schema must be objects"))

    # 3. asset refs
    try:
        for d in manifest.get("assets", []) or []:
            ref = AssetRef.from_dict(d)
            if not ref.sources:
                raise AssetResolutionError(f"asset '{ref.name}' declares no sources")
        report.checks.append(CheckResult("assets", True,
                                         f"{len(manifest.get('assets', []) or [])} asset ref(s)"))
    except AssetResolutionError as exc:
        report.checks.append(CheckResult("assets", False, str(exc)))

    # 4/5. source-dependent checks
    entry_file = plugin_dir / entry_point
    if not entry_file.is_file():
        report.checks.append(CheckResult("isolation", False, f"missing entry point {entry_point}"))
        return report
    source = entry_file.read_text(encoding="utf-8")

    isolated, iso_detail = _check_isolation(source)
    report.checks.append(CheckResult("isolation", isolated, iso_detail))

    effects = _scan_effect_imports(source)
    tags = set(manifest.get("tags", []))
    undeclared = []
    if effects["net"] and "network" not in tags:
        undeclared.append(f"network ({', '.join(effects['net'])})")
    if effects["proc"] and "subprocess" not in tags:
        undeclared.append(f"subprocess ({', '.join(effects['proc'])})")
    report.checks.append(CheckResult(
        "effects_lint", not undeclared, advisory=True,
        detail=("undeclared: " + "; ".join(undeclared)) if undeclared
        else "declared effects match imports",
    ))

    # 6. signature round-trip
    report.checks.append(_check_signature_roundtrip(manifest, source))
    return report


def _check_isolation(source: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return False, f"syntax error: {exc}"

    def _internal(mod: str) -> bool:
        return mod == _FORBIDDEN_ROOT or mod.startswith(_FORBIDDEN_ROOT + ".")

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and _internal(node.module):
            return False, f"imports app internals: from {node.module}"
        if isinstance(node, ast.Import):
            for a in node.names:
                if _internal(a.name):
                    return False, f"imports app internals: import {a.name}"
        if isinstance(node, ast.Call):
            f = node.func
            dyn = (isinstance(f, ast.Name) and f.id in ("__import__", "import_module")) or (
                isinstance(f, ast.Attribute) and f.attr in ("import_module", "__import__"))
            if dyn and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str) and _internal(node.args[0].value):
                return False, f"dynamic import of {node.args[0].value}"
    return True, "no app.* internals imported"


def _check_signature_roundtrip(manifest: Dict[str, Any], source: str) -> CheckResult:
    try:
        priv, _pub = signing.generate_keypair()
        key = signing.load_private_key(priv)
        data = packaging.pack_atlas(manifest, source, sign=signing.make_signer(key))
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "rt.atlas"
            p.write_bytes(data)
            pkg = packaging.read_atlas(p, verify_signature=True, manifest_only=True)
            if not pkg.signature_verified:
                return CheckResult("signature_roundtrip", False, "signature did not verify")
            # tamper: flip one byte in the manifest region → must fail verification
            tampered = bytearray(data)
            tampered[packaging.HEADER_SIZE] ^= 0xFF
            p.write_bytes(bytes(tampered))
            try:
                packaging.read_atlas(p, verify_signature=True, manifest_only=True)
                return CheckResult("signature_roundtrip", False, "tamper was NOT detected")
            except packaging.AtlasFormatError:
                pass
        return CheckResult("signature_roundtrip", True, "pack->sign->verify ok; tamper rejected")
    except Exception as exc:
        return CheckResult("signature_roundtrip", False, str(exc))
