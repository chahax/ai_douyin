"""Focused synthetic controls; no real narrative has been assessed here."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import pytest
from scripts import creative_isolated_source_claims_v1 as m
from tests.test_creative_full_review_protocol_v6 import case as full_case
from tests.test_creative_world_scene_derived_context_script_v1 import synthetic_native
from tests.test_creative_isolated_event_entailment_v3 import synthetic_events

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("no network/provider in source claims controls")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def synthetic_claims(prepared, unknown=False):
    """Fresh transport fixture, not a semantic interpretation of its prose."""
    units = prepared["views"]["source_units"]
    report = {"units": [{"parts": [{"tag": "context", "text": unit["text"], "mode": "background"}]} for unit in units.values()]}
    ref = next(iter(units))
    report["units"][0]["parts"] = [{"tag": "unknown", "text": units[ref]["text"], "reason": "OFFLINE unknown"} if unknown else
        {"tag": "action", "text": units[ref]["text"], "actor_ids": [], "occurrence": "occurred", "content_phase": "current", "temporal_requirement": "none"}]
    return report


def synthetic_comparison(prepared, status="pass"):
    payload = json.loads(prepared["request"]["messages"][1]["content"]); ledger = payload["actual_ledger"]; checks = []
    for cid, claim in payload["source_claims"]["claims"].items():
        def fits(e):
            if claim["tag"] == "speech": return e["kind"] == "speech" and e["actor_id"] == claim["actor_id"] and e["speech_force"] == claim["force"]
            return e["kind"] != "speech" and (not claim["actor_ids"] or e["actor_id"] in claim["actor_ids"])
        ref = next((r for r, e in ledger["events"].items() if fits(e)), next(iter(ledger["events"])))
        e = ledger["events"][ref]
        checks.append({"verdict": "unknown" if status == "unknown" else "supported", "support": [{"step_ref": e["step_ref"], "event_index": int(ref.rsplit("#", 1)[1])}],
            "counterevidence": [], "response_refs": [], "ordering": "not_required", "temporal_evidence": [], "facts": "clear", "reason": "OFFLINE fixture, not semantic proof"})
    if status == "fail": checks[0].update(verdict="missing", support=[], reason="OFFLINE definite missing event")
    return {"checks": checks, "revision_target": "script" if status == "fail" else "none"}


@pytest.fixture
def prepared():
    inputs, canonical, views, _ = full_case.__wrapped__()
    profile = json.loads((ROOT / "config/creative_fresh_source_session_profile_v2.json").read_text("utf-8-sig"))
    return m.prepare_claims(inputs, profile, synthetic_native(canonical), views)


def comparison(prepared, claims=None, events=None):
    v = prepared["views"]; ep = m.facts.prepare_events(v["inputs"], v["profile"], v["native_script"], v["compiler_views"])
    sn = claims if claims is not None else synthetic_claims(prepared); en = events if events is not None else synthetic_events(ep)
    cp = m.prepare_comparison(v["inputs"], v["profile"], v["native_script"], v["compiler_views"], sn, prepared, en, ep)
    return cp, ep, sn, en


def test_source_isolation_character_coverage_and_strict_shape(prepared):
    payload = json.loads(prepared["request"]["messages"][1]["content"])
    assert set(payload) == {"actors", "source_fields", "source_units", "source_unit_order"}
    assert prepared["request"]["parameters"]["max_completion_tokens"] == 16000
    from src.content_factory.creative_deepseek_strict_schema_v1 import compile_source_schema_with_manifest
    service, manifest = compile_source_schema_with_manifest(prepared["request"]["structured_schema"])
    assert service and not manifest["service_schema_is_weaker_than_local_contract"]
    native = synthetic_claims(prepared); original = deepcopy(native); decision = m.validate_claims(native, prepared)
    assert decision["valid"] and decision["claims_usable"] and native == original
    assert decision["native_report_sha256"] == m.digest(native)
    bad = deepcopy(native); bad["units"][0]["parts"][0]["text"] += "X"
    assert not m.validate_claims(bad, prepared)["valid"]
    changed = deepcopy(prepared); changed["request"]["messages"][1]["content"] += " "
    assert not m.validate_claims(native, changed)["valid"]


def test_distinct_assertions_cannot_drop_check_or_reclassify(prepared):
    sn = synthetic_claims(prepared); part = sn["units"][0]["parts"][0]; text = part["text"]; cut = max(1, len(text) // 2)
    sn["units"][0]["parts"] = [{**part, "text": text[:cut]}, {**part, "text": text[cut:]}]
    cp, _, _, _ = comparison(prepared, sn); native = synthetic_comparison(cp)
    assert len(native["checks"]) == 2 and m.validate_comparison(native, cp)["accepted"]
    bad = deepcopy(native); bad["checks"].pop()
    assert not m.validate_comparison(bad, cp)["valid"]
    bad = deepcopy(native); bad["checks"][0]["expected"] = {"tag": "context"}
    assert not m.validate_comparison(bad, cp)["valid"]
    fields = {"F": {"source": "script", "path": "/test", "role": "event", "beat_id": "B", "text": "扫码；已承诺明日交书面答复。"}}
    assert [u["text"] for u in m._units(fields).values()] == ["扫码；", "已承诺明日交书面答复。"]


def test_request_promise_and_future_fulfillment_axes(prepared):
    v = prepared["views"]; ep = m.facts.prepare_events(v["inputs"], v["profile"], v["native_script"], v["compiler_views"]); en = synthetic_events(ep)
    step_ref = next(ref for ref, row in en["steps"].items() if row["events"][0]["kind"] == "speech")
    event = en["steps"][step_ref]["events"][0]; event.update(speech_force="promise", required_content_form="written", content_phase="future", deadline="明天")
    sn = synthetic_claims(prepared); text = sn["units"][0]["parts"][0]["text"]
    sn["units"][0]["parts"] = [{"tag": "speech", "text": text, "actor_id": event["actor_id"], "force": "promise", "required_content_form": "written", "deadline": "明日",
        "occurrence": "occurred", "content_phase": "open", "temporal_requirement": "none"}]
    cp, _, _, _ = comparison(prepared, sn, en)
    assert m.validate_comparison(synthetic_comparison(cp), cp)["accepted"]
    sn["units"][0]["parts"][0]["force"] = "request"; cp, _, _, _ = comparison(prepared, sn, en)
    result = m.validate_comparison(synthetic_comparison(cp), cp)
    assert result["valid"] and not result["accepted"] and result["computed_slot_findings"]


def test_during_information_arrival_not_completed_before(prepared):
    sn = synthetic_claims(prepared); sn["units"][0]["parts"][0]["temporal_requirement"] = "available_before_response"
    cp, _, _, en = comparison(prepared, sn); native = synthetic_comparison(cp)
    ledger = json.loads(cp["request"]["messages"][1]["content"])["actual_ledger"]; row = native["checks"][0]; support = row["support"][0]
    event = ledger["events"][support["step_ref"] + "#0"]
    r = next(r for r, e in ledger["events"].items() if e["beat_id"] == event["beat_id"] and e["step_ref"] != support["step_ref"])
    response = ledger["events"][r]
    row.update(response_refs=[{"step_ref": response["step_ref"], "event_index": int(r.rsplit("#", 1)[1])}], ordering="during",
        temporal_evidence=[{"step_ref": e, "quote": ledger["source_steps"][e]["text"][:80]} for e in (support["step_ref"], response["step_ref"])])
    assert not en["temporal_relations"] and m.validate_comparison(native, cp)["accepted"]
    sn["units"][0]["parts"][0]["temporal_requirement"] = "completed_before_response"; cp, _, _, _ = comparison(prepared, sn, en)
    result = m.validate_comparison(native, cp)
    assert result["valid"] and not result["accepted"] and result["uncertainties"]
    row["ordering"] = "completed_before"
    assert m.validate_comparison(native, cp)["uncertainties"]


def test_unknown_all_context_and_native_failure_packet(prepared):
    unknown = m.validate_claims(synthetic_claims(prepared, True), prepared)
    assert unknown["valid"] and not unknown["claims_usable"] and unknown["uncertainties"]
    all_context = synthetic_claims(prepared)
    for row in all_context["units"]: row["parts"][0] = {"tag": "context", "text": row["parts"][0]["text"], "mode": "background"}
    assert not m.validate_claims(all_context, prepared)["claims_usable"]
    cp, ep, sn, en = comparison(prepared); cn = synthetic_comparison(cp, "fail"); failed = m.validate_comparison(cn, cp)
    assert failed["valid"] and not failed["accepted"] and not failed["uncertainties"]
    packet = m.build_repair_feedback(sn, prepared, en, ep, cn, cp)
    assert packet["native_source_claims_report"] == sn and packet["native_claim_comparison_report"] == cn
    assert packet["verified_compiled_event_ledger"]["native_events_sha256"] == m.digest(en)
    assert m.validate_comparison(synthetic_comparison(cp, "unknown"), cp)["uncertainties"]
    bad = deepcopy(cn); bad["checks"][0]["support"] = [{"step_ref": next(iter(en["steps"])), "event_index": True}]
    assert not m.validate_comparison(bad, cp)["valid"]
