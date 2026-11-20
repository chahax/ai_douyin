"""Source-bound payload controls; synthetic data is not a real-model result."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import pytest

from scripts import creative_isolated_event_entailment_v3 as m
from scripts import creative_world_scene_replanned_workflow_v7 as wf
from tests import test_creative_isolated_event_entailment_v2 as fixture2
from tests.test_creative_full_review_protocol_v6 import case as full_case
from tests.test_creative_world_scene_derived_context_script_v1 import synthetic_native

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **k): raise AssertionError("no network/provider in source-bound pure controls")
    monkeypatch.setattr(socket.socket, "connect", deny); monkeypatch.setattr(socket, "create_connection", deny)


def synthetic_events(prepared, unknown=False):
    return fixture2.synthetic_events(prepared, unknown=unknown)


def synthetic_comparison(prepared, status="pass"):
    return fixture2.synthetic_comparison(prepared, status=status)


@pytest.fixture
def prepared():
    inputs, canonical, views, _ = full_case.__wrapped__()
    profile = json.loads((ROOT/"config/creative_fresh_source_session_profile_v2.json").read_text("utf-8-sig"))
    return m.prepare_events(inputs, profile, synthetic_native(canonical), views)


def comparison_case(prepared, events):
    v = prepared["views"]
    result = m.prepare_entailment(v["inputs"], v["profile"], v["native_script"], v["compiler_views"], events, prepared)
    return result, synthetic_comparison(result)


def test_domain_exact_envelopes_restore_raw_sha_and_distinguish_checking_context(prepared):
    native = synthetic_events(prepared); original = deepcopy(native)
    assert set(native) == {"steps", "temporal_relations"}
    result = m.validate_events(native, prepared)
    assert result["valid"] and result["ledger_usable"] and native == original
    envelope = result["local_source_envelope"]
    canonical = {**envelope["canonical_checking_headers"], **native}
    assert {k: canonical[k] for k in native} == native
    assert result["native_report_sha256"] == result["compiled_ledger"]["native_events_sha256"] == m.digest(native)
    assert envelope["canonical_checking_report_sha256"] == m.digest(canonical) != m.digest(native)
    assert envelope["actual_context_sha256"] != envelope["canonical_checking_context_sha256"]
    checked = m.prior.validate_events(canonical, m._checking_events(prepared))
    for key in ("events", "source_steps", "temporal_relations", "step_coverage"):
        assert result["compiled_ledger"][key] == checked["compiled_ledger"][key]
    cp, comparison = comparison_case(prepared, native)
    assert set(comparison) == {"fields", "revision_target"}
    check = m.validate_entailment(comparison, cp)
    assert check["valid"] and check["accepted"] and check["native_report_sha256"] == m.digest(comparison)
    assert check["compiled_ledger_sha256"] == result["compiled_ledger_sha256"]
    assert check["local_source_envelope"]["actual_context_sha256"] != check["local_source_envelope"]["canonical_checking_context_sha256"]


def test_source_tamper_unknown_and_typed_bounds_still_block(prepared):
    report = synthetic_events(prepared)
    bad = deepcopy(prepared); bad["request"]["messages"][1]["content"] += " "
    assert not m.validate_events(report, bad)["valid"]
    refs = list(report["steps"])
    report["temporal_relations"] = [fixture2.relation(prepared, refs[0], refs[1])]
    report["temporal_relations"][0]["before_event"]["event_index"] = 8
    assert not m.validate_events(report, prepared)["valid"]
    unknown = m.validate_events(synthetic_events(prepared, True), prepared)
    assert unknown["valid"] and not unknown["ledger_usable"] and unknown["uncertainties"]


def test_fullfield_form_future_open_and_real_raw_packet(prepared):
    events = synthetic_events(prepared)
    ref = next(r for r, row in events["steps"].items() if row["events"][0]["kind"] == "speech")
    events["steps"][ref]["events"][0].update(speech_force="promise", content_phase="future")
    cp, native = comparison_case(prepared, events)
    event = events["steps"][ref]["events"][0]
    atom = next(iter(native["fields"].values()))["source_segments"][0]
    atom.update(role="event_claim", expected={k: deepcopy(v) for k, v in event.items() if k != "source_quote"}, verdict="entailed", event_refs=[ref+"#0"])
    atom["expected"]["content_phase"] = "open"
    assert m.validate_entailment(native, cp)["accepted"]
    atom["expected"][m.FORM] = "written"
    failed = m.validate_entailment(native, cp)
    assert failed["valid"] and not failed["accepted"] and failed["computed_slot_findings"]
    packet = m.build_repair_feedback(events, prepared, native, cp)
    assert packet["native_observable_events_report"] == events and packet["native_claim_comparison_report"] == native
    assert packet["local_source_envelopes"]["comparison"]["native_payload_sha256"] == m.digest(native)
    atom["source_text"] = atom["source_text"][:-1]
    assert not m.validate_entailment(native, cp)["valid"]
    assert wf.ReviewWorkflow.prepare_observable_events_request is m.prepare_events


def test_actual682_is_rejected_unchanged_not_stripped_or_repaired():
    r = ROOT/"data/production_trials/world_scene_live_20261016/round_06"
    read = lambda p: json.loads(p.read_text("utf-8-sig"))
    receipt = read(r/"call_682_observable_events_calibration_14.json")
    v = read(r/"call_intents/observable_events_calibration_14.json")["prepared"]["views"]
    prepared = m.prepare_events(v["inputs"], v["profile"], v["native_script"], v["compiler_views"])
    original = deepcopy(receipt["output"])
    assert not m.validate_events(receipt["output"], prepared)["valid"]
    assert receipt["output"] == original
    assert set(prepared["request"]["structured_schema"]["properties"]) == {"steps", "temporal_relations"}
