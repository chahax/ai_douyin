"""Fresh synthetic v2 controls; original 681 is only a rejected v1 negative."""
from copy import deepcopy
import json
from pathlib import Path
import socket

import pytest
from jsonschema import Draft202012Validator
from scripts import creative_isolated_event_entailment_v2 as m
from scripts import creative_world_scene_replanned_workflow_v6 as wf
from tests import test_creative_isolated_event_entailment_v1 as prior_tests
from tests.test_creative_full_review_protocol_v6 import case as full_case
from tests.test_creative_world_scene_derived_context_script_v1 import synthetic_native

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **k): raise AssertionError("no real provider in v2 pure controls")
    monkeypatch.setattr(socket.socket, "connect", deny); monkeypatch.setattr(socket, "create_connection", deny)


def synthetic_events(prepared, unknown=False):
    """Generate fresh synthetic tool data, not a conversion of service 681."""
    result = prior_tests.synthetic_events(prepared, unknown=unknown)
    for row in result["steps"].values():
        for event in row["events"]:
            event.pop("content_medium")
            event[m.FORM] = "unspecified" if event["kind"] == "speech" else None
    return result


def synthetic_comparison(prepared, status="pass"):
    result = m._rename_schema(prior_tests.synthetic_comparison(prepared, status))
    for row in result["fields"].values():
        for segment in row["source_segments"]:
            if segment["expected"] is not None and segment["expected"]["kind"] == "speech": segment["expected"][m.FORM] = "unspecified"
    return result


@pytest.fixture
def prepared():
    inputs, canonical, views, _ = full_case.__wrapped__()
    profile = json.loads((ROOT/"config/creative_fresh_source_session_profile_v2.json").read_text("utf-8-sig"))
    return m.prepare_events(inputs, profile, synthetic_native(canonical), views)


def relation(prepared, before, after):
    return {"before_event": {"step_ref": before, "event_index": 0}, "after_event": {"step_ref": after, "event_index": 0},
        "reason": "OFFLINE stipulated chronological relation, not language proof",
        "evidence": [{"step_ref": before, "quote": prepared["views"]["actual_steps"][before]["text"][:100]}]}


def comparison_case(prepared, native):
    v = prepared["views"]
    cp = m.prepare_entailment(v["inputs"], v["profile"], v["native_script"], v["compiler_views"], native, prepared)
    return cp, synthetic_comparison(cp)


def test_typed_native_endpoints_compile_with_real_v2_hash_and_no_native_mutation(prepared):
    report = synthetic_events(prepared); refs = list(report["steps"])
    report["temporal_relations"] = [relation(prepared, refs[0], refs[1])]
    before = deepcopy(report); result = m.validate_events(report, prepared)
    assert result["valid"] and result["ledger_usable"], result
    assert result["compiled_ledger"]["native_events_sha256"] == m.digest(report)
    compiled = result["compiled_ledger"]["temporal_relations"][0]
    assert compiled["before_event"] == refs[0]+"#0" and compiled["after_event"] == refs[1]+"#0"
    assert report == before and isinstance(report["temporal_relations"][0]["before_event"], dict)


def test_endpoint_bounds_integer_missing_and_cycle_have_no_default_zero(prepared):
    report = synthetic_events(prepared); refs = list(report["steps"])
    report["temporal_relations"] = [relation(prepared, refs[0], refs[1])]
    variants = []
    for index in (True, 0.0, 7, -1):
        bad = deepcopy(report); bad["temporal_relations"][0]["before_event"]["event_index"] = index; variants.append(bad)
    bad = deepcopy(report); bad["temporal_relations"][0]["before_event"].pop("event_index"); variants.append(bad)
    bad = deepcopy(report); bad["temporal_relations"][0]["before_event"] = refs[0]; variants.append(bad)
    bad = deepcopy(report); bad["temporal_relations"].append(relation(prepared, refs[1], refs[0])); variants.append(bad)
    for bad in variants: assert not m.validate_events(bad, prepared)["valid"]


def test_quotes_coverage_speaker_and_unknown_still_block(prepared):
    report = synthetic_events(prepared)
    bad = deepcopy(report); bad["steps"].pop(next(iter(bad["steps"])))
    assert not m.validate_events(bad, prepared)["valid"]
    bad = deepcopy(report); next(iter(bad["steps"].values()))["events"][0]["source_quote"] = "OFFLINE nonexistent quote"
    assert not m.validate_events(bad, prepared)["valid"]
    unknown = m.validate_events(synthetic_events(prepared, True), prepared)
    assert unknown["valid"] and not unknown["ledger_usable"] and unknown["uncertainties"]


def test_content_form_is_not_speech_channel_and_future_open_not_conflict(prepared):
    report = synthetic_events(prepared)
    ref = next(ref for ref, row in report["steps"].items() if row["events"][0]["kind"] == "speech")
    report["steps"][ref]["events"][0].update(speech_force="promise", content_phase="future")
    cp, native = comparison_case(prepared, report)
    event = report["steps"][ref]["events"][0]
    atom = next(iter(native["fields"].values()))["source_segments"][0]
    expected = {key: deepcopy(value) for key, value in event.items() if key != "source_quote"}
    expected["content_phase"] = "open"
    atom.update(role="event_claim", expected=expected, event_refs=[ref+"#0"], verdict="entailed")
    assert m.validate_entailment(native, cp)["accepted"]
    expected[m.FORM] = "written"
    decision = m.validate_entailment(native, cp)
    assert decision["valid"] and not decision["accepted"] and decision["computed_slot_findings"]
    expected[m.FORM] = "unknown"
    assert m.validate_entailment(native, cp)["uncertainties"]


def test_segments_and_native_packet_preserve_exact_sources(prepared):
    events = synthetic_events(prepared); cp, _ = comparison_case(prepared, events)
    native = synthetic_comparison(cp, "fail")
    packet = m.build_repair_feedback(events, prepared, native, cp)
    assert packet["native_observable_events_report"] == events and packet["native_claim_comparison_report"] == native
    assert packet["verified_compiled_event_ledger"]["native_events_sha256"] == m.digest(events)
    first = next(iter(native["fields"].values()))["source_segments"][0]
    first["source_text"] = first["source_text"][:-1]
    assert not m.validate_entailment(native, cp)["valid"]
    assert wf.ReviewWorkflow.prepare_observable_events_request is m.prepare_events


def test_actual681_has_all_48_wire_errors_and_cannot_be_adopted_as_v2():
    r = ROOT/"data/production_trials/world_scene_live_20261016/round_05"
    read = lambda p: json.loads(p.read_text("utf-8-sig"))
    receipt = read(r/"call_681_observable_events_calibration_14.json")
    errors = list(Draft202012Validator(receipt["request"]["structured_schema"]).iter_errors(receipt["output"]))
    assert len(errors) == 48 and all(e.validator == "pattern" for e in errors)
    original = read(r/"call_intents/observable_events_calibration_14.json")["prepared"]["views"]
    prepared = m.prepare_events(original["inputs"], original["profile"], original["native_script"], original["compiler_views"])
    assert not m.validate_events(receipt["output"], prepared)["valid"]
    assert "before_event/after_event使用上述派生ID" not in prepared["request"]["messages"][0]["content"]
    assert "不合成#ID" in prepared["request"]["messages"][0]["content"]
    assert len(prepared["views"]["actual_steps"]) == 42
    assert "content_medium" not in json.dumps(prepared["request"]["structured_schema"])
