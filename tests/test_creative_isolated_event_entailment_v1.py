"""Offline protocol controls, never semantic adoption of an actual screenplay."""
from copy import deepcopy
import json
from pathlib import Path
import socket

import pytest

from scripts import creative_isolated_event_entailment_v1 as m
from scripts import creative_world_scene_replanned_workflow_v5 as wf
from tests.test_creative_full_review_protocol_v6 import case as full_case
from tests.test_creative_world_scene_derived_context_script_v1 import synthetic_native

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **k): raise AssertionError("no provider/network in isolated pure controls")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def synthetic_events(prepared, unknown=False):
    """Fresh mechanical fixture, not actual extraction or a content gold label."""
    payload = json.loads(prepared["request"]["messages"][1]["content"])
    schema = prepared["request"]["structured_schema"]
    native = {k: deepcopy(v["const"]) for k, v in schema["properties"].items() if "const" in v}
    native.update(steps={}, temporal_relations=[])
    for ref, step in payload["actual_steps"].items():
        speech = step["kind"] == "dialogue"
        native["steps"][ref] = {"disposition": "recorded", "reason": "OFFLINE synthetic extraction only",
            "events": [{"kind": "speech" if speech else "action", "actor_id": step["speaker"] if speech else None,
                "speech_force": "other" if speech else None, "proposition": "OFFLINE placeholder; semantic extraction not verified",
                "content_medium": None, "deadline": None, "occurrence": "occurred", "content_phase": "unspecified",
                "source_quote": step["text"][:200]}]}
    if unknown:
        first = next(iter(native["steps"].values()))
        first.update(disposition="unknown", events=[], reason="OFFLINE actual interpretation unresolved")
    return native


def synthetic_comparison(prepared, status="pass"):
    """Synthetic classification fixture; does not label actual field meanings."""
    assert status in ("pass", "fail", "unknown")
    schema = prepared["request"]["structured_schema"]
    native = {k: deepcopy(v["const"]) for k, v in schema["properties"].items() if "const" in v}
    native.update(fields={}, revision_target="none")
    for ref, row in prepared["views"]["source_fields"].items():
        native["fields"][ref] = {"source_segments": [{"source_text": row["text"], "role": "context", "expected": None,
            "event_refs": [], "verdict": "not_required", "temporal_requirement": "none", "prior_event_refs": [],
            "reason": "OFFLINE fixture only, not classification correctness"}]}
    first = next(iter(native["fields"].values()))["source_segments"][0]
    if status == "unknown": first.update(role="unknown", verdict="unknown")
    elif status == "fail":
        first.update(role="event_claim", expected={"kind": "speech", "actor_id": None, "speech_force": "promise",
            "proposition": "OFFLINE missing utterance control", "content_medium": None, "deadline": None,
            "occurrence": "occurred", "content_phase": "future"}, verdict="not_entailed")
        # A known speech actor is required; no claim is made about source meaning.
        first["expected"]["actor_id"] = json.loads(prepared["request"]["messages"][1]["content"])["actors"][0]["id"]
        native["revision_target"] = "script"
    return native


@pytest.fixture
def prepared():
    inputs, canonical, views, _ = full_case.__wrapped__()
    profile = json.loads((ROOT / "config/creative_fresh_source_session_profile_v2.json").read_text("utf-8-sig"))
    return m.prepare_events(inputs, profile, synthetic_native(canonical), views)


def compare_case(prepared, events=None):
    v = prepared["views"]
    events = synthetic_events(prepared) if events is None else events
    result = m.prepare_entailment(v["inputs"], v["profile"], v["native_script"], v["compiler_views"], events, prepared)
    return events, result, synthetic_comparison(result)


def event_atom(comparison, prepared, event_ref, **overrides):
    ledger = json.loads(prepared["request"]["messages"][1]["content"])["compiled_event_ledger"]
    event = ledger["events"][event_ref]
    first = next(iter(comparison["fields"].values()))["source_segments"][0]
    expected = {k: deepcopy(event[k]) for k in m._slots([])["properties"]}
    expected.update(overrides)
    first.update(role="event_claim", expected=expected, verdict="entailed", event_refs=[event_ref])
    return first


def test_actual_only_coverage_quotes_native_binding_unknown_and_no_summary(prepared):
    payload = json.loads(prepared["request"]["messages"][1]["content"])
    assert set(payload) == {"schema", "actors", "scene_locators", "actual_steps"}
    assert prepared["manifest"]["reference_occurrences"] == 0
    report = synthetic_events(prepared)
    result = m.validate_events(report, prepared)
    assert result["valid"] and result["ledger_usable"]
    assert result["status"] == "observable_ledger_usable_not_content_approval"
    bad = deepcopy(report); bad["steps"].pop(next(iter(bad["steps"])))
    assert not m.validate_events(bad, prepared)["valid"]
    bad = deepcopy(report); next(iter(bad["steps"].values()))["events"][0]["source_quote"] = "OFFLINE invented actual quote"
    assert not m.validate_events(bad, prepared)["valid"]
    unknown = m.validate_events(synthetic_events(prepared, unknown=True), prepared)
    assert unknown["valid"] and not unknown["ledger_usable"] and unknown["uncertainties"]
    unknown_dialogue = deepcopy(report)
    dialogue = next(ref for ref, step in prepared["views"]["actual_steps"].items() if step["kind"] == "dialogue")
    unknown_dialogue["steps"][dialogue].update(disposition="unknown", events=[])
    result = m.validate_events(unknown_dialogue, prepared)
    assert result["valid"] and not result["ledger_usable"] and result["uncertainties"]
    unknown_dialogue["steps"][dialogue]["disposition"] = "no_observable_event"
    assert not m.validate_events(unknown_dialogue, prepared)["valid"]
    v = prepared["views"]
    with pytest.raises(ValueError):
        m.prepare_entailment(v["inputs"], v["profile"], v["native_script"], v["compiler_views"], synthetic_events(prepared, True), prepared)


def test_exact_source_segments_no_true_subclause_mask_and_all_fields(prepared):
    _, comparison_prepared, native = compare_case(prepared)
    assert m.validate_entailment(native, comparison_prepared)["accepted"]  # only a fixture, not source semantics
    first = next(iter(native["fields"].values()))["source_segments"]
    text = first[0]["source_text"]; split = max(1, len(text)//2)
    a = deepcopy(first[0]); b = deepcopy(first[0])
    a["source_text"], b["source_text"] = text[:split], text[split:]
    if not b["source_text"]: pytest.skip("synthetic source field too short for split control")
    first[:] = [a, b]
    assert m.validate_entailment(native, comparison_prepared)["valid"]
    first.pop()
    assert not m.validate_entailment(native, comparison_prepared)["valid"]
    native = synthetic_comparison(comparison_prepared)
    native["fields"].pop(next(iter(native["fields"])))
    assert not m.validate_entailment(native, comparison_prepared)["valid"]


def test_coherent_actor_force_required_slots_and_promise_future_axes(prepared):
    events = synthetic_events(prepared)
    speech_ref = next(ref for ref, row in events["steps"].items() if row["events"][0]["kind"] == "speech")
    actual = events["steps"][speech_ref]["events"][0]
    actual.update(speech_force="promise", content_medium="written", deadline="OFFLINE future deadline", content_phase="future")
    _, cp, native = compare_case(prepared, events)
    atom = event_atom(native, cp, speech_ref + "#0")
    assert m.validate_entailment(native, cp)["accepted"]  # promise uttered now, delivery remains future
    atom["expected"]["speech_force"] = "request"
    failed = m.validate_entailment(native, cp)
    assert failed["valid"] and not failed["accepted"] and failed["computed_slot_findings"]
    assert native["revision_target"] == "none" and failed["native_revision_target"] == "none" and failed["revision_target"] == "script"
    atom["expected"]["speech_force"] = "promise"
    atom["expected"]["actor_id"] = next(a["id"] for a in json.loads(cp["request"]["messages"][1]["content"])["actors"] if a["id"] != actual["actor_id"])
    assert m.validate_entailment(native, cp)["computed_slot_findings"]
    atom["expected"]["actor_id"] = actual["actor_id"]; atom["expected"]["deadline"] = "OFFLINE differently phrased deadline"
    assert m.validate_entailment(native, cp)["accepted"]  # free-text equality is not entailment
    # Force classification is semantic, so a grammatical question may be an indirect request.
    actual["speech_force"] = "request"
    _, cp, native = compare_case(prepared, events)
    event_atom(native, cp, speech_ref + "#0")
    assert m.validate_entailment(native, cp)["accepted"]


def test_before_relation_requires_evidence_not_e_index_and_cycle_reject(prepared):
    events, cp, native = compare_case(prepared)
    refs = list(json.loads(cp["request"]["messages"][1]["content"])["compiled_event_ledger"]["events"])
    atom = event_atom(native, cp, refs[1]); atom.update(temporal_requirement="before", prior_event_refs=[refs[0]])
    missing = m.validate_entailment(native, cp)
    assert missing["valid"] and not missing["accepted"] and missing["uncertainties"]
    first_step = refs[0].split("#")[0]
    proof = {"step_ref": first_step, "quote": prepared["views"]["actual_steps"][first_step]["text"][:60]}
    events["temporal_relations"] = [{"before_event": refs[0], "after_event": refs[1], "reason": "OFFLINE stipulated chronological control", "evidence": [proof]}]
    _, cp, native = compare_case(prepared, events)
    atom = event_atom(native, cp, refs[1]); atom.update(temporal_requirement="before", prior_event_refs=[refs[0]])
    assert m.validate_entailment(native, cp)["accepted"]
    events["temporal_relations"].append({**deepcopy(events["temporal_relations"][0]), "before_event": refs[1], "after_event": refs[0]})
    assert not m.validate_events(events, prepared)["valid"]


def test_future_fulfilment_can_remain_open_without_mechanical_slot_failure(prepared):
    events = synthetic_events(prepared)
    ref = next(ref for ref, row in events["steps"].items() if row["events"][0]["kind"] == "speech")
    events["steps"][ref]["events"][0].update(speech_force="promise", occurrence="occurred", content_phase="future")
    _, cp, native = compare_case(prepared, events)
    atom = event_atom(native, cp, ref + "#0", content_phase="open")
    result = m.validate_entailment(native, cp)
    assert result["valid"] and result["accepted"] and not result["computed_slot_findings"]
    assert atom["expected"]["occurrence"] == "occurred"  # utterance and fulfilment remain separate axes
    atom["expected"]["content_phase"] = "unknown"
    result = m.validate_entailment(native, cp)
    assert result["valid"] and not result["accepted"] and result["uncertainties"]


def test_native_fail_unknown_and_feedback_packet_are_separate(prepared):
    events, cp, _ = compare_case(prepared)
    for status in ("pass", "fail", "unknown"):
        native = synthetic_comparison(cp, status)
        decision = m.validate_entailment(native, cp)
        assert decision["valid"], decision
        assert decision["accepted"] is (status == "pass")
        packet = m.build_review_packet(events, prepared, native, cp)
        assert packet["native_observable_events_report"] == events
        assert packet["native_claim_comparison_report"] == native
        assert all("text" not in row for row in packet["used_source_fields"].values())
        if status == "fail": assert m.build_repair_feedback(events, prepared, native, cp)["schema"].endswith("/repair_feedback")
        else:
            with pytest.raises(ValueError): m.build_repair_feedback(events, prepared, native, cp)
    assert wf.ReviewWorkflow.prepare_observable_events_request is m.prepare_events


def test_actual678_blind_projection_68_fields_profile_and_old_story_absence():
    read = lambda p: json.loads(p.read_text("utf-8-sig"))
    root = ROOT / "data/production_trials/world_scene_live_20261016"
    inputs = read(root / "round_03/INPUTS.json")
    raw = read(root / "round_03/call_678_complete_script_14.json")["output"]
    views = read(root / "round_03/call_intents/complete_script_14.json")["prepared"]["views"]
    profile = read(Path(read(root / "round_03/SESSION_CONFIG.json")["profile_path"]))
    ep = m.prepare_events(inputs, profile, raw, views)
    payload = json.loads(ep["request"]["messages"][1]["content"])
    assert len(payload["actual_steps"]) == 42
    actual_texts = [s["text"] for s in payload["actual_steps"].values()]
    assert actual_texts == [s["text"] for b in raw["beats"] for s in b["steps"]]
    assert "native_goal_document" not in payload and "premise" not in payload and "authority_inputs" not in payload
    assert inputs["reference_fulltext"] not in ep["request"]["messages"][1]["content"]
    assert ep["request"]["parameters"] == {**profile["director"]["parameters"], **profile["stage_parameters"]["full_review"]}
    # Only a no-dispatch format/size preview. No synthetic ledger is an actual extraction result.
    events = synthetic_events(ep)
    cp = m.prepare_entailment(inputs, profile, raw, views, events, ep)
    assert len(cp["views"]["source_fields"]) == 68
    assert all(row["text"] for row in cp["views"]["source_fields"].values())
    assert "full_prior_script" not in ep["request"]["messages"][1]["content"]
    assert "expected_fail" not in cp["request"]["messages"][1]["content"]
    assert len(json.dumps(cp["request"]["structured_schema"], ensure_ascii=False)) < 30000
