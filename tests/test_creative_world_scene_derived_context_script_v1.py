"""Fresh synthetic representation controls; no actual bad draft is adopted."""
from copy import deepcopy
import json
from pathlib import Path
import socket

import pytest
from jsonschema import Draft202012Validator

from scripts import creative_world_scene_derived_context_script_v1 as c
from scripts import creative_world_scene_replanned_workflow_v3 as w
from src.content_factory import creative_full_review_protocol_v6 as full
from tests.test_creative_full_review_protocol_v6 import case as full_case, synthetic_full_reports
from tests.test_creative_world_scene_source_state_audit_v4 import synthetic_report
from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **k): raise AssertionError("pure representation controls cannot use the network")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def synthetic_native(canonical_fixture):
    """Only for clearly synthetic fixtures, never an actual native migration."""
    result = deepcopy(canonical_fixture)
    result["contract_version"] = c.NATIVE_VERSION
    for context in result["scene_contexts"]: context.pop("previous_context_id")
    return result


@pytest.fixture
def case():
    inputs, canonical, views, legal = full_case.__wrapped__()
    return inputs, synthetic_native(canonical), views, legal


def test_deterministic_links_exact_roundtrip_and_three_source_identities(case):
    inputs, raw, views, _ = case; original = deepcopy(raw)
    result = c.compile_document(raw, views["goal"], views["brief"])
    assert raw == original and result["provider_native"] == original
    assert result["derived_script"]["scene_contexts"][0]["previous_context_id"] is None
    for index, context in enumerate(result["derived_script"]["scene_contexts"][1:], 1):
        assert context["previous_context_id"] == result["derived_script"]["scene_contexts"][index-1]["id"]
    recovered = c.recover_compiled(result["script"], views["goal"], views["brief"])
    assert recovered == result
    descriptor = result["source_descriptor"]
    assert descriptor["native_script_sha256"] == c.digest(raw)
    assert descriptor["derived_script_sha256"] == c.digest(result["derived_script"])
    assert descriptor["compiled_script_sha256"] == c.digest(result["script"])
    assert len(set(descriptor[key] for key in ("native_script_sha256", "derived_script_sha256", "compiled_script_sha256"))) == 3
    changed = deepcopy(result["script"]); changed["scene_contexts"][0]["previous_context_id"] = "wrong"
    with pytest.raises(ValueError): c.recover_compiled(changed, views["goal"], views["brief"])
    text = c.render_script(raw, views["goal"])
    assert "场次前置链接由确定性编译派生" in text


def test_old_native_extra_field_wrong_goal_and_large_array_remain_rejected(case):
    _, raw, views, _ = case
    old = c.derive(raw, views["goal"])
    assert not c.diagnose(old, views["goal"])["valid"]
    extra = deepcopy(raw); extra["scene_contexts"][0]["previous_context_id"] = None
    assert not c.diagnose(extra, views["goal"])["valid"]
    wrong = deepcopy(raw); wrong["native_goal_sha256"] = "f" * 64
    assert not c.diagnose(wrong, views["goal"])["valid"]
    bad = deepcopy(raw); bad["beats"] *= 20
    measured = json.dumps(c.diagnose(bad, views["goal"]), ensure_ascii=False)
    assert raw["beats"][0]["steps"][0]["text"] not in measured
    assert len(measured) < len(json.dumps(bad, ensure_ascii=False)) / 2


def test_actual675_is_not_rewritten_or_accepted_by_new_contract():
    folder = ROOT / "data/production_trials/world_scene_live_20261016"
    native = json.loads((folder / "round_02/call_675_complete_script_11.json").read_text("utf-8-sig"))["output"]
    goal = json.loads((folder / "round_01/call_665_whole_plan_01.json").read_text("utf-8-sig"))["output"]
    before = deepcopy(native)
    decision = c.diagnose(native, goal)
    assert not decision["valid"] and native == before
    assert native["scene_contexts"][0]["previous_context_id"] == ""


def test_actual_writer_schema_rules_source4_gate_and_request_identity():
    scenario = json.loads((ROOT / "data/qa/creative_world_scene_workflow28_20261015/SCENARIO_HAPPY_v1.json").read_text("utf-8-sig"))
    inputs, profile, docs = scenario["inputs"], scenario["profile"], scenario["documents"]
    goal, setup = docs["whole_plan_01"]["output"], docs["opening_setup_01"]["output"]
    wf = w.ReviewWorkflow(w.base.workflow, full)
    bundle = wf.build_goal_audit_bundle(*(docs[k + "_audit_01"]["output"] for k in wf.AUDITS))
    source_prepared = wf.prepare_source_state_audit_request(inputs, profile, goal, setup)
    prepared = wf.prepare_script_request(inputs, profile, goal, bundle, opening_setup=setup,
        source_state_audit=synthetic_report(source_prepared), source_state_prepared=source_prepared, **wf.origin_ids(inputs))
    rule = prepared["request"]["messages"][0]["content"]
    assert w._OLD_WORLD_LINK_RULE not in rule and w.prior.prior.contract.RELATION_RULE not in rule
    assert w._NEW_WORLD_LINK_RULE in rule and c.RELATION_RULE in rule
    assert prepared["request"]["structured_schema"] == c.prepare_schema(goal)["schema"]
    assert "previous_context_id" not in prepared["request"]["structured_schema"]["properties"]["scene_contexts"]["items"]["properties"]
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["request_sha256"] == c.digest(prepared["request"])
    assert prepared["manifest"]["reference_occurrences"] == 1


def test_same_native_reviews_canonical_once_and_preserve_all_report_sha(case):
    inputs, raw, views, _ = case
    wf = w.ReviewWorkflow(w.base.workflow, full)
    result = wf.validate_script_document(raw, views, inputs["production_preferences"])
    parts = {part: wf.prepare_full_review_part_request(inputs,
        json.loads((ROOT / "config/creative_fresh_source_session_profile_v2.json").read_text("utf-8-sig")), raw, views, part)
        for part in ("semantic", "physical")}
    contexts = {part: prepared["part_context_sha256"] for part, prepared in parts.items()}
    compiled_views = {**deepcopy(views), "compiled_script": result["script"]}
    legal = parts["semantic"]["review_legal_context"]
    reports = synthetic_full_reports(compiled_views, legal, contexts, prior_story_scope=inputs["production_preferences"].get("prior_story_scope"))
    originals = deepcopy(reports); reviews = wf.full_reviews()
    for part, prepared in parts.items():
        payload = json.loads(prepared["request"]["messages"][1]["content"])
        assert payload["native_script_document"] == result["derived_script"]
        assert payload["review_source_derivation"] == result["source_descriptor"]
        assert payload["native_script_sha256"] == c.digest(result["derived_script"]) != c.digest(raw)
        assert prepared["part_context_sha256"] == c.digest(payload)
        assert prepared["wire"] == expected_wire_request(prepared["request"])
        Draft202012Validator(prepared["request"]["structured_schema"]).validate(reports[part])
        checked = reviews.validate_part(reports[part], part, result["script"], views["brief"], views["plan"], legal,
            context_sha256=contexts[part], goal_contract=views["goal"], opening_setup=views["opening_setup"],
            prior_story_scope=inputs["production_preferences"].get("prior_story_scope"))
        assert checked["valid"] and checked["accepted"], checked
        assert checked["origin_native_script_sha256"] == c.digest(raw)
        assert checked["native_script_sha256"] == c.digest(result["derived_script"])
        assert checked["native_part_sha256"] == c.digest(originals[part])
    bundle = reviews.build_review_bundle(reports["semantic"], reports["physical"])
    checked = reviews.validate_bundle(bundle, result["script"], views["brief"], views["plan"], legal,
        semantic_context_sha256=contexts["semantic"], physical_context_sha256=contexts["physical"],
        goal_contract=views["goal"], opening_setup=views["opening_setup"],
        prior_story_scope=inputs["production_preferences"].get("prior_story_scope"))
    assert checked["valid"] and checked["accepted"], checked
    assert checked["source_descriptor"] == result["source_descriptor"] and reports == originals
    changed = deepcopy(reports["physical"]); changed["native_script_sha256"] = c.digest(raw)
    assert not reviews.validate_part(changed, "physical", result["script"], views["brief"], views["plan"], legal,
        context_sha256=contexts["physical"], goal_contract=views["goal"], opening_setup=views["opening_setup"])["valid"]
