"""Contract tests for the atlas_protocol package — the kernel's single source of truth."""
from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

import atlas_protocol as ap
from atlas_protocol import manifest as manifest_mod


def _valid_manifest_dict() -> dict:
    return {
        "id": "org.atlas.proposer.botorch",
        "version": "0.1.0",
        "description": "Multi-objective Bayesian optimization proposer.",
        "capabilities": [
            {
                "name": "propose_experiment",
                "kind": "oracle",
                "io": {
                    "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}}},
                    "output_schema": {"type": "object"},
                },
                "determinism": "stochastic",
            }
        ],
    }


# --- single source of truth ------------------------------------------------

def test_export_schemas_covers_public_models():
    schemas = ap.export_schemas()
    for name in ("CapabilityManifest", "ToolRequest", "ToolResult", "Goal", "ModelDescriptor"):
        assert name in schemas
        assert schemas[name].get("type") == "object"


def test_one_capability_manifest_class():
    # The package re-export and the module define the SAME class object — no fork.
    assert ap.CapabilityManifest is manifest_mod.CapabilityManifest


# --- manifest strictness + identifiers -------------------------------------

def test_manifest_builds_and_defaults():
    m = ap.CapabilityManifest(**_valid_manifest_dict())
    assert m.protocol.major == 1
    assert m.runtime == ap.RuntimeKind.PYTHON
    cap = m.capability("propose_experiment")
    assert cap is not None and cap.kind == ap.CapabilityKind.ORACLE


def test_extra_field_is_rejected_at_build():
    bad = _valid_manifest_dict()
    bad["sneaky_extra"] = True
    with pytest.raises(ValidationError):
        ap.CapabilityManifest(**bad)


def test_reverse_dns_id_regex():
    ap.CapabilityManifest(**_valid_manifest_dict())  # valid id passes
    bad = _valid_manifest_dict()
    bad["id"] = "Org.Atlas.BAD!"  # uppercase + illegal char
    with pytest.raises(ValidationError):
        ap.CapabilityManifest(**bad)


def test_capability_name_regex_forbids_domain_leak():
    bad = _valid_manifest_dict()
    bad["capabilities"][0]["name"] = "SMILES"  # uppercase domain-leak name
    with pytest.raises(ValidationError):
        ap.CapabilityManifest(**bad)


def test_semver_version_enforced():
    bad = _valid_manifest_dict()
    bad["version"] = "v1"  # not semver
    with pytest.raises(ValidationError):
        ap.CapabilityManifest(**bad)


def test_at_least_one_capability_required():
    bad = _valid_manifest_dict()
    bad["capabilities"] = []
    with pytest.raises(ValidationError):
        ap.CapabilityManifest(**bad)


def test_kind_enum_is_closed():
    bad = _valid_manifest_dict()
    bad["capabilities"][0]["kind"] = "wizard"  # not one of the five
    with pytest.raises(ValidationError):
        ap.CapabilityManifest(**bad)


# --- envelope: the NaN/Inf firewall ----------------------------------------

def test_measurement_rejects_non_finite():
    ap.Measurement(key="yield", value=0.91, unit="frac")  # finite ok
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            ap.Measurement(key="yield", value=bad)


def test_tool_result_minimal():
    r = ap.ToolResult(ok=True, capability="propose_experiment")
    assert r.measurements is None
    assert r.display.summary == ""


# --- goal ------------------------------------------------------------------

def test_goal_requires_a_criterion_and_defaults_to_all():
    g = ap.Goal(
        intent="maximize toughness",
        criteria=[ap.Criterion(key="opt", plain="hit target", verifier="optimization_target")],
    )
    assert g.combinator == ap.Combinator.ALL
    with pytest.raises(ValidationError):
        ap.Goal(intent="x", criteria=[])


# --- version negotiation ----------------------------------------------------

def test_negotiation_native_compat_refuse():
    k = ap.ProtocolVersion(major=1, minor=2)
    assert ap.negotiate(ap.ProtocolVersion(major=1, minor=2), k).mode == "native"
    assert ap.negotiate(ap.ProtocolVersion(major=1, minor=0), k).mode == "native"
    assert ap.negotiate(ap.ProtocolVersion(major=1, minor=5), k).mode == "compat"
    assert ap.negotiate(ap.ProtocolVersion(major=2, minor=0), k).mode == "refuse"


# --- backward-compat gate ---------------------------------------------------

def test_backward_compat_gate_flags_schema_change():
    m = ap.CapabilityManifest(**_valid_manifest_dict())
    baseline = ap.manifest_io_hashes(m)
    assert ap.is_backward_compatible(baseline, m)  # unchanged -> compatible

    changed = copy.deepcopy(_valid_manifest_dict())
    changed["capabilities"][0]["io"]["input_schema"]["properties"]["n"]["type"] = "string"
    m2 = ap.CapabilityManifest(**changed)
    breaks = ap.diff_io_schemas(baseline, m2)
    assert len(breaks) >= 1
    assert breaks[0].channel == "input"


def test_backward_compat_gate_flags_removed_capability():
    m = ap.CapabilityManifest(**_valid_manifest_dict())
    baseline = ap.manifest_io_hashes(m)
    dropped = copy.deepcopy(_valid_manifest_dict())
    dropped["capabilities"][0]["name"] = "propose_batch"  # original name gone
    m2 = ap.CapabilityManifest(**dropped)
    breaks = ap.diff_io_schemas(baseline, m2)
    assert any(b.channel == "capability" for b in breaks)


# --- cognition socket -------------------------------------------------------

def test_model_descriptor_no_filename_heuristic():
    d = ap.ModelDescriptor(
        backend="llamacpp", model_id="qwen3-4b-instruct", context_length=40960,
        dialect="qwen_chatml", role_default="reason",
    )
    assert d.backend == ap.Backend.LLAMACPP


# --- review-finding regressions --------------------------------------------

def test_duplicate_capability_names_rejected():
    bad = _valid_manifest_dict()
    bad["capabilities"].append(copy.deepcopy(bad["capabilities"][0]))  # same name twice
    with pytest.raises(ValidationError):
        ap.CapabilityManifest(**bad)


def test_protocol_version_is_frozen():
    with pytest.raises(ValidationError):
        ap.PROTOCOL_VERSION.minor = 99  # frozen -> cannot mutate the shared constant


def test_negotiate_resolves_kernel_at_call_time(monkeypatch):
    import atlas_protocol.version as vmod
    monkeypatch.setattr(vmod, "PROTOCOL_VERSION", ap.ProtocolVersion(major=1, minor=5))
    # plugin minor 4 vs the *rebound* kernel minor 5 -> native (proves no def-time binding)
    assert vmod.negotiate(ap.ProtocolVersion(major=1, minor=4)).mode == "native"


def test_canonical_json_rejects_non_finite():
    import math
    with pytest.raises(ValueError):
        ap.canonical_json({"maximum": math.inf})
    with pytest.raises(ValueError):
        ap.schema_hash({"x": float("nan")})


def test_schema_hash_collapses_integral_floats():
    assert ap.schema_hash({"minimum": 1}) == ap.schema_hash({"minimum": 1.0})
    assert ap.schema_hash({"a": [1, 2]}) == ap.schema_hash({"a": [1.0, 2.0]})
    assert ap.schema_hash({"x": True}) != ap.schema_hash({"x": 1})  # bool stays bool


def test_compat_partial_baseline_flags_missing_channel():
    m = ap.CapabilityManifest(**_valid_manifest_dict())
    full = ap.manifest_io_hashes(m)
    partial = {"propose_experiment": {"input": full["propose_experiment"]["input"]}}  # lost 'output'
    breaks = ap.diff_io_schemas(partial, m)
    assert any(b.channel == "output" for b in breaks)


def test_semver_leading_zeros_rejected():
    bad = _valid_manifest_dict()
    bad["version"] = "01.0.0"
    with pytest.raises(ValidationError):
        ap.CapabilityManifest(**bad)


def test_problem_class_tag_uses_shared_axis_vocabulary():
    md = _valid_manifest_dict()
    md["capabilities"][0]["problem_class"] = {
        "axes": [
            {"name": "temp", "unit": "C", "role": "param"},
            {"name": "toughness", "role": "objective", "minimize": False},
        ],
        "domain_tags": ["materials"],
    }
    m = ap.CapabilityManifest(**md)
    ax = m.capability("propose_experiment").problem_class.axes[0]
    assert isinstance(ax, ap.Axis) and ax.role == "param"
