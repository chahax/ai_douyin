"""New native report controls; never upgrades any historical response."""
from copy import deepcopy
import json
from pathlib import Path
import socket

import pytest

from src.content_factory import creative_full_review_protocol_v7 as p
from scripts import creative_world_scene_replanned_workflow_v4 as w
from tests.test_creative_full_review_protocol_v6 import case as full_case, synthetic_full_reports
from tests.test_creative_world_scene_derived_context_script_v1 import synthetic_native

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **k): raise AssertionError("no live reviewer in pure v7 controls")
    monkeypatch.setattr(socket.socket, "connect", deny); monkeypatch.setattr(socket, "create_connection", deny)


def synthetic_v7_reports(views, legal, contexts, *, prior_story_scope=None):
    """Fresh synthetic v6 factory output only, not a historical response edit."""
    reports = synthetic_full_reports(views, legal, contexts, prior_story_scope=prior_story_scope)
    for part, native in reports.items():
        native["schema"] = p.VERSION
        if part == "semantic":
            for row in native["world_scene_checks"].values(): row["counterevidence"] = []
    return reports


@pytest.fixture
def case():
    inputs, canonical, views, _ = full_case.__wrapped__()
    raw = synthetic_native(canonical)
    wf = w.ReviewWorkflow(w.prior.base.workflow, p.prior)
    compiled = wf.validate_script_document(raw, views, inputs["production_preferences"])
    profile = json.loads((ROOT / "config/creative_fresh_source_session_profile_v2.json").read_text("utf-8-sig"))
    prepared = {part: wf.prepare_full_review_part_request(inputs, profile, raw, views, part) for part in p.PART_TABLES}
    contexts = {part: value["part_context_sha256"] for part, value in prepared.items()}
    legal = prepared["semantic"]["review_legal_context"]
    reports = synthetic_v7_reports({**deepcopy(views), "compiled_script": compiled["script"]}, legal, contexts,
        prior_story_scope=inputs["production_preferences"].get("prior_story_scope"))
    return inputs, wf, compiled, views, prepared, contexts, legal, reports


def checked(case, native, part="semantic"):
    inputs, wf, compiled, views, prepared, contexts, legal, _ = case
    return wf.full_reviews().validate_part(native, part, compiled["script"], views["brief"], views["plan"], legal,
        context_sha256=contexts[part], goal_contract=views["goal"], opening_setup=views["opening_setup"],
        prior_story_scope=inputs["production_preferences"].get("prior_story_scope"))


def test_new_native_full_parts_bundle_keep_true_sha_and_system_wire_agree(case):
    inputs, wf, compiled, views, prepared, contexts, legal, reports = case
    original = deepcopy(reports)
    for part in p.PART_TABLES:
        result = checked(case, reports[part], part)
        assert result["valid"] and result["accepted"], result
        assert result["native_part_sha256"] == p.digest(reports[part])
        assert result["native_version"] == p.VERSION
        request = prepared[part]["request"]
        assert "v6响应" not in request["messages"][0]["content"]
        assert "v7响应" in request["messages"][0]["content"] and p.WORLD_RULE in request["messages"][0]["content"]
        assert request["structured_schema"]["properties"]["schema"] == {"const": p.VERSION}
        assert prepared[part]["context_sha256"] == p.digest(json.loads(request["messages"][1]["content"]))
    bundle = wf.full_reviews().build_review_bundle(reports["semantic"], reports["physical"])
    result = wf.full_reviews().validate_bundle(bundle, compiled["script"], views["brief"], views["plan"], legal,
        semantic_context_sha256=contexts["semantic"], physical_context_sha256=contexts["physical"],
        goal_contract=views["goal"], opening_setup=views["opening_setup"], prior_story_scope=inputs["production_preferences"].get("prior_story_scope"))
    assert result["valid"] and result["accepted"], result
    assert result["native_bundle_sha256"] == p.digest(bundle)
    assert result["part_results"]["semantic"]["native_part_sha256"] == p.digest(reports["semantic"])
    assert reports == original


def test_world_counterproof_cannot_pass_or_disappear_from_valid_failure_and_unknown(case):
    report = deepcopy(case[-1]["semantic"]); key = next(iter(report["world_scene_checks"]))
    row = report["world_scene_checks"][key]
    row["counterevidence"] = [row["evidence"][0]]
    assert not checked(case, report)["valid"]
    row.update(status="fail", required_revision="OFFLINE explicit full revision control")
    report["revision_target"] = "script"
    result = checked(case, report)
    assert result["valid"] and not result["accepted"], result
    own = next(item for item in result["findings"] if item["table"] == "world_scene_checks" and item["item_id"] == key)
    assert own["finding"]["counterevidence"] == row["counterevidence"]
    row.update(status="unknown", required_revision=""); report["revision_target"] = "none"
    result = checked(case, report)
    assert result["valid"] and not result["accepted"] and result["uncertainties"], result
    row["counterevidence"] = ["invented-not-a-source-ref"]
    assert not checked(case, report)["valid"]


def test_original679_is_not_converted_or_accepted(case):
    path = ROOT / "data/production_trials/world_scene_live_20261016/round_03/call_679_full_review_semantic_14.json"
    original = json.loads(path.read_text("utf-8-sig"))["output"]; before = deepcopy(original)
    assert original["schema"] == p.prior.VERSION
    assert not checked(case, original)["valid"]
    assert original == before
