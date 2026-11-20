"""Only new v3 distinctions; native controls below are explicitly synthetic."""
from copy import deepcopy
import socket

import pytest
from jsonschema import Draft202012Validator

from scripts import creative_world_scene_source_state_audit_v3 as m
from test_creative_world_scene_source_state_audit_v2 import source_context
from test_creative_world_scene_source_state_audit_v2 import synthetic_report as previous_fixture


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **k): raise AssertionError("no actual provider authorized")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def synthetic_report(prepared, local_conflict=False):
    """OFFLINE report construction; not a conversion of any actual native audit."""
    native = previous_fixture(prepared, local_conflict=local_conflict)
    native["schema"] = m.VERSION
    for check in native["semantic_checks"].values(): check.pop("beat_ids")
    for family in ("quantity_chains", "custody_chains"):
        for chain in native[family]:
            for i, step in enumerate(chain["steps"]): step["event_id"] = f"OFFLINE_OBSERVATION_{i}"
    return native


def test_every_reading_has_wire_nonempty_id_and_invalid_contract_keeps_computed_conflict():
    p = m.prepare(*source_context()); native = synthetic_report(p, local_conflict=True)
    d = m.validate(native, p)
    assert d["valid"] and not d["accepted"] and d["computed_state_findings"]
    for reading in m.READINGS:
        changed = deepcopy(native); changed["quantity_chains"][0]["steps"][0].update(reading=reading, event_id="")
        assert list(Draft202012Validator(p["request"]["structured_schema"]).iter_errors(changed))
    native["quantity_chains"][0]["steps"][0]["event_id"] = ""
    before = deepcopy(native); d = m.validate(native, p)
    assert not d["valid"] and not d["accepted"] and d["contract_findings"]
    assert any(row["code"] == "QUANTITY_PRECONDITION_CONFLICT" for row in d["computed_state_findings"])
    assert native == before and not d["computed_state_analysis_incomplete"]


def test_semantic_scope_comes_only_from_exact_evidence_and_beats_stay_complete():
    p = m.prepare(*source_context()); native = synthetic_report(p)
    d = m.validate(native, p)
    assert d["accepted"]
    first = p["views"]["goal"]["whole_plan"]["beats"][0]["id"]
    assert all(scope == [first] for scope in d["semantic_scopes_from_evidence"].values())
    assert "beat_ids" not in p["request"]["structured_schema"]["properties"]["semantic_checks"]["properties"][m.CHECKS[0]]["properties"]
    changed = synthetic_report(p, local_conflict=True)
    changed["semantic_checks"][m.CHECKS[0]]["beat_ids"] = [first]
    checked = m.validate(changed, p)
    assert not checked["valid"] and checked["computed_state_findings"]
    native["beat_reviews"].pop(); assert not m.validate(native, p)["valid"]


def test_malformed_state_never_becomes_a_checked_native_and_unknown_still_stops():
    p = m.prepare(*source_context()); native = synthetic_report(p, local_conflict=True)
    native["quantity_chains"][0]["steps"] = {"item": native["quantity_chains"][0]["steps"]}
    d = m.validate(native, p)
    assert not d["valid"] and not d["accepted"] and d["computed_state_analysis_incomplete"]
    assert "computed_state_findings" in d
    native = synthetic_report(p); native["semantic_checks"][m.CHECKS[0]]["status"] = "unknown"
    d = m.validate(native, p); assert d["valid"] and not d["accepted"] and d["uncertainties"]
