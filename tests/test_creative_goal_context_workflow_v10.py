"""Planning-stage responsibility wiring, native identity, and closed offline gates."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import ValidationError
import pytest

from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request, M31FlashRoleClients
from src.content_factory import creative_goal_context_workflow_v9 as frozen
from src.content_factory import creative_goal_context_workflow_v10 as workflow
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("v10 preparation tests cannot contact a provider or create a client")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


def payload(prepared):
    return json.loads(prepared["request"]["messages"][1]["content"])


def synthetic_bundle(inputs, profile, goal, module=workflow):
    source = module.prepare_goal_source_audit_request(inputs, profile, goal)
    drama = module.prepare_goal_drama_audit_request(inputs, profile, goal)
    judgement = {"status": "pass", "reason": "合成控制测试，不证明语义或审美", "required_revision": ""}
    ref = next(iter(module.citations.build_evidence_catalog(goal)))
    return module.build_goal_audit_bundle(
        {"schema": module.SOURCE_AUDIT_VERSION, "goal_sha256": module.digest(goal),
         "audit_context_sha256": module.digest(payload(source)),
         "claim_checks": {row["id"]: deepcopy(judgement) for row in goal["claims"]}},
        {"schema": module.DRAMA_AUDIT_VERSION, "goal_sha256": module.digest(goal),
         "audit_context_sha256": module.digest(payload(drama)),
         "goal_checks": {key: {**deepcopy(judgement), "evidence_refs": [ref],
             "counterexample_analysis": "合成观察仅验接线，不证明完整语义抽取", "counterevidence_refs": []}
             for key in module.GOAL_CHECKS},
         "scope_observations": {beat["id"]: {"audible_speakers": [], "operated_props": []}
             for beat in goal["whole_plan"]["beats"]}})


@pytest.mark.parametrize("stage", ["goal", "drama"])
def test_actual_payload_carries_finite_stage_responsibility_not_source_override(causal_scenario, stage):
    inputs, profile, goal, *_ = causal_scenario
    before = deepcopy((inputs, goal))
    request = (workflow.prepare_goal_request(inputs, profile) if stage == "goal" else
               workflow.prepare_goal_drama_audit_request(inputs, profile, goal))
    actual = payload(request)
    contract = actual["stage_responsibility_contract"]
    assert (inputs, goal) == before
    assert contract == workflow.STAGE_RESPONSIBILITY_CONTRACT
    assert set(contract["stage_owners"]) == {"whole_plan", "native_opening_setup",
        "complete_script_and_local_performance", "same_source_physical_review_and_compile"}
    policy = contract["planning_decision_policy"]
    assert "不能单独判规划fail或unknown" in policy["missing_later_owned_detail_only"]
    assert "fail" in policy["explicit_state_contradiction"]
    assert "fail" in policy["undeclared_actual_actor_voice_or_operated_prop"]
    assert "当前holder" in policy["owner_character_id"] and "观看者" in policy["owner_character_id"]
    assert "不等于实际操作" in policy["observation"]
    assert request["manifest"]["stage_responsibility_contract_sha256"] == workflow.digest(contract)
    assert request["manifest"]["payload_identity"] == workflow.contexts._measure(actual)
    assert workflow.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == 1
    assert actual["user_goal_contract"] == before[0]["user_goal_contract"]
    system = request["request"]["messages"][0]["content"]
    assert workflow.STAGE_RESPONSIBILITY_RULE in system
    if stage == "drama":
        assert actual["native_goal_document"] == goal
        assert actual["goal_check_criteria"] == workflow.GOAL_CHECK_CRITERIA
        for key in workflow.GOAL_CHECKS:
            if key != "closed_production_scope":
                assert actual["goal_check_criteria"][key] == frozen.GOAL_CHECK_CRITERIA[key]
        assert "由谁持有、操作前后是否仍能执行" not in actual["goal_check_criteria"]["closed_production_scope"]
        assert "逐拍追踪在场、离开与返回、材料来源与持物" not in system
        assert "仅提交Schema中的全部goal_checks，不提交claim_checks或额外检查" not in system
        schema = deepcopy(request["request"]["structured_schema"])
        for beat in schema["properties"]["scope_observations"]["properties"].values():
            assert "实际可辨人声" in beat["properties"]["audible_speakers"].pop("description")
            assert "仅提及、看见、注视" in beat["properties"]["operated_props"].pop("description")
        assert schema == frozen.build_goal_drama_audit_schema(goal, context_sha256=workflow.digest(actual))
    else:
        assert request["request"]["structured_schema"] == frozen.prepare_goal_request(inputs, profile)["request"]["structured_schema"]


def test_current_bundle_author_uses_v10_globals_and_rejects_pass_with_old_context(causal_scenario, monkeypatch):
    inputs, profile, goal, opening, _, ids, _ = causal_scenario
    old_bundle = synthetic_bundle(inputs, profile, goal, frozen)
    bundle = synthetic_bundle(inputs, profile, goal)
    assert bundle["native_source_audit"] == old_bundle["native_source_audit"]
    assert bundle["native_drama_audit"]["audit_context_sha256"] != old_bundle["native_drama_audit"]["audit_context_sha256"]
    def deny(*args, **kwargs):
        raise AssertionError("author cannot fall back to frozen v9 audit context")
    monkeypatch.setattr(frozen, "validate_goal_audit", deny)
    monkeypatch.setattr(frozen, "prepare_script_request", deny)
    request = workflow.prepare_script_request(inputs, profile, goal, bundle, opening_setup=opening, **ids)
    assert request["request"]["input_provenance"]["native_drama_audit_sha256"] == workflow.digest(bundle["native_drama_audit"])
    assert payload(request)["native_opening_setup_document"] == opening
    with pytest.raises(ValidationError):
        workflow.prepare_script_request(inputs, profile, goal, old_bundle, opening_setup=opening, **ids)


@pytest.mark.parametrize("field", ["verified_legal_context", "user_goal_contract", "reference_fulltext"])
def test_author_recomputes_unchanged_source_and_new_drama_authority(causal_scenario, field):
    inputs, profile, goal, opening, _, ids, _ = deepcopy(causal_scenario)
    bundle = synthetic_bundle(inputs, profile, goal)
    if field == "verified_legal_context":
        inputs[field]["scope"] += "合成来源变更"
    elif field == "user_goal_contract":
        inputs[field]["audience_goals"][0]["text"] += "合成目标变更"
    else:
        inputs[field] += "\n合成参考变更"
    with pytest.raises(ValidationError):
        workflow.prepare_script_request(inputs, profile, goal, bundle, opening_setup=opening, **ids)


@pytest.mark.parametrize("status", ["fail", "unknown"])
@pytest.mark.parametrize("kind", ["explicit_state_contradiction", "undeclared_operation"])
def test_native_failure_and_unknown_still_block_author(causal_scenario, status, kind):
    inputs, profile, goal, opening, _, ids, _ = causal_scenario
    bundle = synthetic_bundle(inputs, profile, goal)
    drama = bundle["native_drama_audit"]
    drama["goal_checks"]["closed_production_scope"].update(status=status,
        required_revision="完整原生新规划修复明示矛盾或未登记物件" if status == "fail" else "")
    if kind == "undeclared_operation":
        scope = workflow.drama_contract.build_production_scope_catalog(goal)
        beat_id = next(iter(scope["beat_scopes"]))
        ref = scope["beat_scopes"][beat_id]["evidence_refs"][0]
        drama["scope_observations"][beat_id]["operated_props"].append({"source_ref": ref,
            "quote": workflow.citations.build_evidence_catalog(goal)[ref]["quote"], "declared_prop_id": None})
    with pytest.raises(ValueError, match="must pass"):
        workflow.prepare_script_request(inputs, profile, goal, bundle, opening_setup=opening, **ids)


@pytest.mark.parametrize("table,field", [("operated_props", "declared_prop_id"),
                                        ("audible_speakers", "declared_character_id")])
def test_undeclared_observation_cannot_be_hidden_under_pass(causal_scenario, table, field):
    inputs, profile, goal, opening, _, ids, _ = causal_scenario
    bundle = synthetic_bundle(inputs, profile, goal)
    scope = workflow.drama_contract.build_production_scope_catalog(goal)
    beat_id = next(iter(scope["beat_scopes"]))
    ref = scope["beat_scopes"][beat_id]["evidence_refs"][0]
    bundle["native_drama_audit"]["scope_observations"][beat_id][table].append({"source_ref": ref,
        "quote": workflow.citations.build_evidence_catalog(goal)[ref]["quote"], field: None})
    with pytest.raises(ValueError, match="undeclared"):
        workflow.prepare_script_request(inputs, profile, goal, bundle, opening_setup=opening, **ids)


@pytest.mark.parametrize("defect", ["fail_no_revision", "pass_has_revision", "unresolved_counterevidence", "nonexistent_G"])
def test_frozen_drama_allof_and_finite_evidence_are_not_relaxed(causal_scenario, defect):
    inputs, profile, goal, *_ = causal_scenario
    bundle = synthetic_bundle(inputs, profile, goal)
    row = bundle["native_drama_audit"]["goal_checks"]["closed_production_scope"]
    if defect == "fail_no_revision":
        row["status"] = "fail"
    elif defect == "pass_has_revision":
        row["required_revision"] = "不能作为pass带出的返修"
    elif defect == "unresolved_counterevidence":
        row["counterevidence_refs"] = row["evidence_refs"][:]
    else:
        row["evidence_refs"] = ["G999999"]
    with pytest.raises(ValidationError):
        workflow.validate_goal_audit(bundle, goal, inputs=inputs)


@pytest.mark.parametrize("stage", ["goal", "source", "drama", "setup", "script", "semantic", "physical"])
def test_all_seven_requests_have_final_manifest_wire_sha_and_fixed_model_conditions(causal_scenario, stage):
    inputs, profile, goal, opening, _, ids, native = causal_scenario
    if stage == "goal":
        request = workflow.prepare_goal_request(inputs, profile)
    elif stage == "source":
        request = workflow.prepare_goal_source_audit_request(inputs, profile, goal)
    elif stage == "drama":
        request = workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    elif stage == "setup":
        request = workflow.prepare_opening_setup_request(inputs, profile, goal)
    elif stage == "script":
        bundle = synthetic_bundle(inputs, profile, goal)
        request = workflow.prepare_script_request(inputs, profile, goal, bundle, opening_setup=opening, **ids)
    else:
        views = workflow.compile_native_views(goal, opening, **ids)
        request = workflow.prepare_full_review_part_request(inputs, profile, native, views, stage)
        old = frozen.prepare_full_review_part_request(inputs, profile, native, views, stage)
        assert payload(request) == payload(old)
    assert request["manifest"]["workflow_version"] == "creative_goal_context_workflow/v10"
    assert request["request"]["input_provenance"]["workflow_version"] == workflow.VERSION
    assert request["request"]["input_provenance"]["context_manifest_sha256"] == workflow.digest(request["manifest"])
    assert request["request_sha256"] == workflow.digest(request["request"])
    assert request["wire"] == expected_wire_request(request["request"])
    assert request["sdk_max_retries"] == 0 and not request["dispatch_performed"]
    if stage in ("goal", "setup", "script"):
        assert request["wire"]["model"] == "MiniMax-M3.1-Flash-Preview"
        assert request["wire"]["reasoning_effort"] == "medium"
    else:
        assert request["wire"]["model"] == "deepseek-flash"
        assert request["wire"]["thinking"] == {"type": "disabled"}


@pytest.fixture
def actual_round09():
    root = Path(__file__).resolve().parents[1]
    source = root / "data/production_trials/goal_context_text_production_20261013/round_09"
    read = lambda name: json.loads((source / name).read_text(encoding="utf-8"))
    profile = json.loads((root / "config/creative_goal_context_model_profile_v2.json").read_text(encoding="utf-8"))
    return read("INPUTS.json"), profile, read("call_558_goal_plan_14.json"), read("call_560_goal_drama_audit_02.json")


def test_actual560_is_rejected_without_modification_and_owner_does_not_create_holder(actual_round09):
    inputs, profile, receipt, old_review = actual_round09
    goal = receipt["output"]
    before = deepcopy((receipt, old_review))
    prepared = workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    actual = payload(prepared)
    assert actual["native_goal_document"] == goal
    board = next(row for row in goal["whole_plan"]["props"] if row["id"] == "prop_attendance_board")
    assert board["owner_character_id"] == "macheng"
    assert set(board) == {"id", "description", "owner_character_id"}
    assert "观看者" in actual["stage_responsibility_contract"]["planning_decision_policy"]["owner_character_id"]
    assert actual["production_scope_catalog"] == workflow.drama_contract.build_production_scope_catalog(goal)
    assert set(actual["production_scope_catalog"]["beat_scopes"]) == {row["id"] for row in goal["whole_plan"]["beats"]}
    assert workflow.digest(actual) != old_review["output"]["audit_context_sha256"]
    with pytest.raises(ValidationError):
        workflow.validate_goal_drama_audit(old_review["output"], goal, context_sha256=workflow.digest(actual))
    assert (receipt, old_review) == before
    assert old_review["status"] == "contract_valid"
    assert not old_review["validation"]["accepted"]


def test_actual558_bounded_revision_keeps_entire_native_seed_and_exact_diagnostics(actual_round09):
    inputs, profile, receipt, old_review = actual_round09
    repaired_inputs = deepcopy(inputs)
    repaired_inputs.pop("fresh_reconception_context", None)
    goal = receipt["output"]
    repaired_inputs["previous_complete_document"] = deepcopy(goal)
    diagnostics = {"receipt_ordinal": 560,
        "true_defect": "文件夹未登记、明示纸张状态矛盾需要完整新规划",
        "reviewer_boundary": "考勤板owner与旁观者不同不构成矛盾，已登记道具起态和精确拍照朝向由后续补全"}
    repaired_inputs["revision_diagnostics"] = diagnostics
    before = deepcopy(repaired_inputs)
    request = workflow.prepare_goal_request(repaired_inputs, profile)
    actual = payload(request)
    assert repaired_inputs == before
    assert actual["previous_complete_document"] == goal and actual["revision_diagnostics"] == diagnostics
    assert request["manifest"]["generation_mode"] == "bounded_content_revision"
    assert actual["stage_responsibility_contract"] == workflow.STAGE_RESPONSIBILITY_CONTRACT
    assert request["wire"] == expected_wire_request(request["request"])
    assert old_review["status"] == "contract_valid"  # No old native response becomes a pass.


def test_private_validation_aliases_and_frozen_source_sha_are_preserved():
    assert workflow._validate_planning_input is frozen._validate_planning_input
    assert workflow._planning_authority_inputs is frozen._planning_authority_inputs
    assert workflow.DRAMA_AUDIT_VERSION == frozen.DRAMA_AUDIT_VERSION
    assert workflow.BUNDLE_VERSION == frozen.BUNDLE_VERSION
    assert hashlib.sha256(Path(frozen.__file__).read_bytes()).hexdigest() == "e2fa89460b4bd9b4e4674484bee72a5c4d6f1c8d1937cc546aa177b70b69d1e8"
