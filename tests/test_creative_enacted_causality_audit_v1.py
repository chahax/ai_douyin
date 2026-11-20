"""Focused contract controls; synthetic findings are not calibration evidence."""
from copy import deepcopy
import json
from pathlib import Path
import socket

import pytest

from scripts import creative_enacted_causality_audit_v1 as m
from tests.test_creative_full_review_protocol_v6 import case as full_case
from tests.test_creative_world_scene_derived_context_script_v1 import synthetic_native

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **k): raise AssertionError("no model or network in pure focused controls")
    monkeypatch.setattr(socket.socket, "connect", deny); monkeypatch.setattr(socket, "create_connection", deny)


def synthetic_report(prepared, status="pass"):
    """Fresh fake tool object for SDK plumbing only; no actual draft adoption."""
    assert status in ("pass", "fail", "unknown")
    payload = json.loads(prepared["request"]["messages"][1]["content"])
    documents = {"goal": payload["native_goal_document"], "setup": payload["native_opening_setup_document"], "script": payload["native_script_document"]}
    directory = prepared["views"]["source_directory"]
    def proof(ref, group):
        row = directory[group][ref]
        return {"ref": ref, "quote": m._read(documents[row["source"]], row["path"])[:160]}
    first_a, first_e = next(iter(directory["assertions"])), next(iter(directory["actual_steps"]))
    def row(own, actual):
        return {"status": "pass", "reading": "enacted", "comparison": "OFFLINE synthetic comparison; not a semantic gold result",
            "assertion_evidence": [proof(own, "assertions")], "actual_evidence": [proof(actual, "actual_steps")],
            "searched_actual_scope": "all_current_steps", "required_revision": ""}
    schema = prepared["request"]["structured_schema"]
    native = {key: deepcopy(rule["const"]) for key, rule in schema["properties"].items() if "const" in rule}
    native.update(beat_reviews={}, checks={}, revision_target="none")
    for identifier, own in directory["target_assertion_refs"].items():
        actual = next((ref for ref, item in directory["actual_steps"].items() if item["beat_id"] == identifier), first_e)
        native["beat_reviews"][identifier] = row(own[0], actual)
    for key in m.CHECKS: native["checks"][key] = row(first_a, first_e)
    native["checks"]["world_and_story_time"].update(reading="background", actual_evidence=[])
    if status != "pass":
        item = next(iter(native["beat_reviews"].values()))
        item.update(status=status, reading="not_enacted" if status == "fail" else "unknown", actual_evidence=[],
            required_revision="OFFLINE complete-script revision control" if status == "fail" else "")
        native["revision_target"] = "script" if status == "fail" else "none"
    return native


@pytest.fixture
def prepared():
    inputs, canonical, views, _ = full_case.__wrapped__()
    profile = json.loads((ROOT / "config/creative_fresh_source_session_profile_v2.json").read_text("utf-8-sig"))
    return m.prepare(inputs, profile, synthetic_native(canonical), views)


def test_background_pass_fail_and_unknown_are_distinct_valid_semantic_results(prepared):
    for status in ("pass", "fail", "unknown"):
        result = m.validate(synthetic_report(prepared, status), prepared)
        assert result["valid"], result
        assert result["accepted"] is (status == "pass")
        assert bool(result["findings"]) is (status == "fail")
        assert bool(result["uncertainties"]) is (status == "unknown")
        assert not result["semantic_meaning_programmatically_verified"]


def test_summary_cannot_substitute_actual_step_and_missing_beat_or_fake_quote_reject(prepared):
    native = synthetic_report(prepared)
    first = next(iter(native["beat_reviews"]))
    bad = deepcopy(native); bad["beat_reviews"][first]["actual_evidence"] = bad["beat_reviews"][first]["assertion_evidence"]
    assert not m.validate(bad, prepared)["valid"]
    bad = deepcopy(native); bad["beat_reviews"][first]["actual_evidence"] = []
    assert not m.validate(bad, prepared)["valid"]
    bad = deepcopy(native); bad["beat_reviews"].pop(first)
    assert not m.validate(bad, prepared)["valid"]
    bad = deepcopy(native); bad["beat_reviews"][first]["actual_evidence"][0]["quote"] = "OFFLINE invented quote never in source"
    assert not m.validate(bad, prepared)["valid"]


def test_actual678_request_is_blind_full_source_once_and_old_story_not_reintroduced():
    read = lambda path: json.loads(path.read_text("utf-8-sig"))
    root = ROOT / "data/production_trials/world_scene_live_20261016"
    inputs = read(root / "round_03/INPUTS.json")
    receipt = read(root / "round_03/call_678_complete_script_14.json")
    authored = read(root / "round_03/call_intents/complete_script_14.json")["prepared"]
    config = read(root / "round_03/SESSION_CONFIG.json")
    prepared = m.prepare(inputs, read(Path(config["profile_path"])), receipt["output"], authored["views"])
    payload = json.loads(prepared["request"]["messages"][1]["content"])
    assert payload["native_script_document"] == m.source.compile_document(receipt["output"], authored["views"]["goal"], authored["views"]["brief"])["derived_script"]
    assert "expected_fail" not in json.dumps(payload) and "O01" not in json.dumps(payload)
    assert "source_packet" not in payload["authority_inputs"]
    assert "full_prior_script" not in payload["authority_inputs"]["production_preferences"]["prior_story_scope"]
    assert prepared["manifest"]["reference_occurrences"] == 1
    assert len(json.dumps(prepared["request"]["structured_schema"], ensure_ascii=False)) < 20000
    assert prepared["source_descriptor"]["native_script_sha256"] == m.digest(receipt["output"])
