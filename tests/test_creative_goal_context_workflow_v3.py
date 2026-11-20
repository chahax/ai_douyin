"""Offline integration only; synthetic judgements are never production reviews."""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator, ValidationError
import pytest

from scripts import preview_goal_context_workflow_v2 as preview
from src.content_factory import creative_goal_context_workflow_v3 as workflow
from src.content_factory import creative_full_review_contract_v3 as reviews
from src.content_factory import creative_fresh_legal_text_pipeline_v1 as legacy
from tests.test_creative_goal_source_contract_v2 import native_goal
from tests.test_creative_fresh_legal_text_pipeline_v1 import review_for


@pytest.fixture
def scenario():
    inputs, _, _, _, _ = preview.production_inputs()
    inputs["user_goal_contract"] = {"constraints": [{"id": "UC1", "text": "合成：完整稿"}],
        "audience_goals": [{"id": "UG1", "text": "合成：可见局部结果"}],
        "limitations": ["合成合同测试，不是用户改变目标或新故事采用"]}
    document = native_goal()
    document["contract_version"] = "creative_goal_source_v3"
    for prop in document["whole_plan"]["props"]:
        prop["presence_at_start"] = "present"
    ids = workflow.origin_ids(inputs)
    document["claims"][2]["origin_ids"] = [ids["source_ids"][0]]
    document["claims"][3]["origin_ids"] = [ids["legal_ids"][0]]
    profile = preview.read(preview.PROJECT / "config/creative_goal_context_model_profile_v2.json")
    request = workflow.prepare_goal_audit_request(inputs, profile, document)
    audit = {"goal_sha256": workflow.digest(document), "audit_context_sha256": request["request"]["structured_schema"]["properties"]["audit_context_sha256"]["const"],
        "claim_checks": {}, "goal_checks": {}}
    for i, row in enumerate(document["claims"]):
        audit["claim_checks"][row["id"]] = {"status": "pass", "reason": "合成判断，仅测试验收与状态分支",
            "document_path": f"claims.{i}.text", "quote": row["text"], "required_revision": ""}
    for key in workflow.GOAL_CHECKS:
        audit["goal_checks"][key] = {"status": "pass", "reason": "合成判断，仅合同测试，非审美金标",
            "document_path": "whole_plan.ending.visible_consequence", "quote": document["whole_plan"]["ending"]["visible_consequence"], "required_revision": ""}
    native = {"title": "合成接线样例", "premise": "这不是本轮生成或采用的剧本", "beats": [
        {"id": "B1", "event": "询问", "trigger": "听见推迟", "steps": [
            {"kind": "dialogue", "speaker": "worker", "text": "请给我一个明确答复。"}]},
        {"id": "B2", "event": "拒收", "trigger": "要求明确答复", "steps": [
            {"kind": "dialogue", "speaker": "hr", "text": "这份申请我今天不收。"},
            {"kind": "action", "speaker": "", "text": "员工保持坐姿，手里的记录本仍然合拢。"}]}]}
    return inputs, profile, document, audit, ids, native


def author(scenario):
    inputs, profile, document, audit, ids, _ = scenario
    return workflow.prepare_script_request(inputs, profile, document, audit, **ids)


def test_native_goal_audit_author_full_review_use_actual_origin_mapping_and_verified_wire(scenario, monkeypatch):
    from scripts.creative_m31_flash_role_clients_v1 import M31FlashRoleClients
    monkeypatch.setattr(M31FlashRoleClients, "__init__", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client construction")))
    inputs, profile, document, audit, ids, native = scenario
    prepared = author(scenario)
    assert prepared["wire"]["model"] == "MiniMax-M3.1-Flash-Preview"
    assert prepared["wire"]["reasoning_effort"] == "medium"
    assert "thinking" not in prepared["wire"] and "tool_choice" not in prepared["wire"]
    assert prepared["request"]["input_provenance"]["goal_audit_sha256"] == workflow.digest(audit)
    assert prepared["production_dispatch_eligible"] is False
    review = workflow.prepare_full_review_request(inputs, profile, native, prepared["views"])
    actual = json.loads(review["wire"]["messages"][1]["content"])
    assert actual["full_current_script"] == legacy.contract.compile_script(native, prepared["views"]["brief"])
    assert actual["origin_catalog"]["verified_legal"]["L001"]["path"] == "verified_legal_context.facts.0"
    assert review["wire"]["model"] == "deepseek-flash"
    assert review["wire"]["max_tokens"] == 24000
    assert review["wire"]["thinking"] == {"type": "disabled"}
    assert review["manifest"]["reference_proof"]["payload_occurrences"] == 1
    assert review["dispatch_performed"] is False
    actual_law = actual["verified_legal_context"]
    assert review["request"]["structured_schema"]["properties"]["legal_context_sha256"]["const"] == workflow.digest(actual_law)
    assert review["review_legal_context"] == actual_law
    for key, value in inputs["verified_legal_context"].items():
        if key != "creative_boundaries":
            assert actual_law[key] == value


def test_same_source_mock_complete_review_roundtrip_is_only_a_machine_verdict(scenario):
    inputs, _, document, _, _, native = scenario
    views = author(scenario)["views"]
    script = legacy.contract.compile_script(native, views["brief"])
    old = review_for(script, views["brief"], views["plan"], inputs["verified_legal_context"])
    synthetic = deepcopy(old)
    for table, key in reviews._COVERAGE_KEYS.items():
        synthetic[table] = {row[key]: {k: v for k, v in row.items() if k != key} for row in old[table]}
    for ref, row in synthetic["dialogue_checks"].items():
        row.update(source_refs=[ref], turn_function="request", purpose="合成检查话轮", stimulus_ref=None, reaction_refs=[], emotional_change=None)
    synthetic["action_checks"] = {"E0003": {"status": "pass", "source_refs": ["E0003"], "reason": "合成状态判断",
        "required_revision": "", "subjects": ["worker", "book"], "preconditions": [], "state_changes": []}}
    for table in ("initial_checks", "observed_prop_initial"):
        for key, row in synthetic[table].items():
            if key in ("character:worker", "prop:book", "book"):
                row["source_refs"] = ["E0003"]
    synthetic["goal_checks"] = {key: {"status": "pass", "source_refs": ["E0002"], "reason": "合成局部结果判断",
        "required_revision": "", "evidence": [{"source_ref": "E0002", "quote": "这份申请我今天不收。"}]} for key in reviews.GOAL_FIELDS}
    synthetic.update(schema=reviews.VERSION, goal_contract_sha256=legacy.digest(document))
    result = reviews.validate_full_review(synthetic, script, views["brief"], views["plan"], inputs["verified_legal_context"], goal_contract=document)
    assert result["valid"] and result["accepted"], result
    assert result["human_quality_approved"] is False and result["creative_quality_passed"] is False


def test_complete_script_revision_does_not_invalidate_unchanged_goal_authority(scenario):
    inputs, profile, document, audit, ids, native = scenario
    original = workflow.prepare_script_request(inputs, profile, document, audit, **ids)
    repair_inputs = {**deepcopy(inputs), "previous_complete_document": native,
        "revision_diagnostics": {"finding": "synthetic complete native content repair"}}
    repaired = workflow.prepare_script_request(repair_inputs, profile, document, audit, **ids)
    assert repaired["goal_audit_sha256"] == original["goal_audit_sha256"]
    assert repaired["manifest"]["generation_mode"] == "bounded_content_revision"
    actual = json.loads(repaired["request"]["messages"][1]["content"])
    assert actual["previous_complete_document"] == native
    assert repaired["request_sha256"] != original["request_sha256"]


@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_goal_semantic_rejection_or_uncertainty_blocks_author_without_mutating_native(scenario, status):
    _, _, document, audit, _, _ = scenario
    old = deepcopy(document)
    audit["goal_checks"]["user_goal_priority"].update(status=status, required_revision="整份新规划重新表达目标" if status == "fail" else "")
    with pytest.raises(ValueError, match="not accepted"):
        author(scenario)
    assert document == old


@pytest.mark.parametrize("field", ["verified_legal_context", "user_goal_contract", "source_packet"])
def test_old_goal_audit_cannot_approve_changed_source_context(scenario, field):
    inputs, *_ = scenario
    if field == "source_packet":
        inputs[field]["candidate"]["title"] += "改变"
    elif field == "user_goal_contract":
        inputs[field]["audience_goals"][0]["text"] += "改变"
    else:
        inputs[field]["scope"] += "改变"
    with pytest.raises(ValidationError):
        author(scenario)


def test_unknown_external_catalog_cannot_replace_actual_request_catalog(scenario):
    inputs, profile, document, audit, ids, _ = scenario
    ids["legal_ids"] = ["FALSE_CATALOG"]
    with pytest.raises(ValueError, match="actual supplied"):
        workflow.prepare_script_request(inputs, profile, document, audit, **ids)


@pytest.mark.parametrize("alter", ["incomplete", "too_many_actors", "reference_duplicate", "context_overflow"])
def test_goal_audit_preflight_rejects_bad_native_before_review_cost(scenario, alter):
    inputs, profile, document, *_ = scenario
    if alter == "incomplete":
        del document["whole_plan"]
    elif alter == "too_many_actors":
        document["whole_plan"]["characters"].append({**deepcopy(document["whole_plan"]["characters"][0]), "id": "third"})
    elif alter == "reference_duplicate":
        document["whole_plan"]["premise"] += inputs["reference_fulltext"]
    else:
        inputs["context_policy"] = {"max_payload_characters": 50_000, "max_payload_utf8_bytes": 150_000}
        document["whole_plan"]["premise"] += "测" * 60_000
    with pytest.raises(ValueError):
        workflow.prepare_goal_audit_request(inputs, profile, document)


def test_blank_audit_reason_and_current_quote_do_not_count_as_review(scenario):
    *_, audit, ids, native = scenario
    audit["claim_checks"]["U1"]["reason"] = " "
    with pytest.raises(ValueError, match="nonblank"):
        author(scenario)


def test_copy_only_views_preserve_choice_authority_and_unknown_state(scenario):
    inputs, profile, document, audit, ids, _ = scenario
    views = author(scenario)["views"]
    assert views["brief"]["facts"][0]["kind"] == "creative_choice"
    assert "not_user_law_or_metadata" in views["brief"]["facts"][0]["authority"]
    assert views["plan"]["source_order"] == views["plan"]["source_obligations"] == []
    assert views["brief"]["initial_state"]["prop_states"][0]["orientation"] is None
    assert views["brief"]["typed_claim_registry"] == document["claims"]


def test_fullscript_wrong_order_and_missing_cast_are_not_ready_for_review(scenario):
    inputs, _, _, _, _, native = scenario
    views = author(scenario)["views"]
    native["beats"].reverse()
    with pytest.raises(ValueError, match="ordered whole-plan"):
        workflow.validate_script_document(native, views, inputs["production_preferences"])
    native["beats"].reverse()
    native["beats"][1]["steps"][0]["speaker"] = "worker"
    with pytest.raises(ValueError, match="exact declared"):
        workflow.validate_script_document(native, views, inputs["production_preferences"])


def receipt():
    request = {"model": "MiniMax-M3.1-Flash-Preview", "stage": "complete_script"}
    record = {"ordinal": 999, "request_sha256": workflow.digest(request), "status": "contract_rejected", "output": {"native": "完整合成对象"},
        "response_metadata": {"http_status_code": 200, "response_body_complete": True, "finish_reason": "tool_calls", "total_tokens": 10,
            "output_mode": "tool_call", "requested_model": request["model"], "response_model": request["model"]}}
    return record, request


@pytest.mark.parametrize("alter,action", [
    (lambda r: r["response_metadata"].update(finish_reason="length"), "stop_truncated"),
    (lambda r: r["response_metadata"].update(response_body_complete=False), "reconcile_original_request_only"),
    (lambda r: r["response_metadata"].update(total_tokens=None), "stop_usage_unknown"),
    (lambda r: r["response_metadata"].update(output_mode="content"), "stop_missing_tool_separate_format_scope_required"),
    (lambda r: r.update(output=None), "stop_incomplete_native_document"),
    (lambda r: r["response_metadata"].update(response_model="other"), "stop_exact_model_identity_mismatch"),
    (lambda r: r.update(request_sha256="changed"), "stop_source_identity_mismatch"),
])
def test_known_failure_isolated_from_unknown_and_no_automatic_dispatch(alter, action):
    record, request = receipt()
    alter(record)
    decision = workflow.revision_route(record, request, used=1, limit=3, scope_verified=True)
    assert decision["action"] == action
    assert decision["used"] == 1 and decision["automatic_dispatch"] is False and decision["budget_reset"] is False


def test_known_complete_type_failure_only_prepares_new_native_version_with_inherited_count():
    record, request = receipt()
    old = deepcopy(record)
    for _ in range(2):
        decision = workflow.revision_route(record, request, used=2, limit=3, scope_verified=True)
        assert decision["action"] == "prepare_new_complete_native_revision_then_full_review"
        assert decision["next_used"] == 3 and decision["original_ordinal"] == 999
    assert record == old
    assert workflow.revision_route(record, request, used=3, limit=3, scope_verified=True)["action"].startswith("stop_revision_scope")
    assert workflow.revision_route(record, request, used=0, limit=3)["action"].startswith("stop_revision_scope")


def test_semantic_unknown_cannot_be_reinterpreted_as_a_content_failure():
    record, request = receipt()
    result = workflow.revision_route(record, request, used=1, limit=3, scope_verified=True,
        semantic_result={"valid": True, "findings": [{"known_fail": True}], "uncertainties": ["unknown"]})
    assert result["action"] == "stop_review_unknown_or_incomplete"


def test_accepted_text_does_not_create_human_or_video_approval():
    record, request = receipt()
    record["status"] = "contract_valid"
    result = workflow.revision_route(record, request, used=1, limit=3)
    assert result["action"] == "advance_text_stage_only"
    assert result["human_approval_created"] is False


def test_actual_530_is_rejected_at_coverage_and_original_production_is_unchanged():
    result = preview.build_preview()
    summary = result["summary"]
    assert summary["previous_530_replay"]["findings"][0]["code"] == "DIALOGUE_COVERAGE_EMPTY"
    assert summary["paid_claims"] == 0 and summary["existing_call_ordinals"] == [529, 530]
    assert summary["source_check"]["source_packet_sha256"] == workflow.digest(preview.read(preview.SOURCE_ROOT / "source/SOURCE_PACKET.json"))
    assert len(summary["original_frozen_files_unchanged"]) == 1151
    assert summary["measurement"]["new_review_schema_characters"] < 25_000


def test_valid_complete_source_cannot_be_mixed_with_an_old_compact_request(monkeypatch):
    original_read = preview.read
    def different(path):
        value = original_read(path)
        if str(path).endswith("source\\SOURCE_PACKET.json") or str(path).endswith("source/SOURCE_PACKET.json"):
            value["prepared_at"] = "changed synthetic source identity"
        return value
    monkeypatch.setattr(preview, "read", different)
    monkeypatch.setattr(legacy.graph_bridge, "validate_packet", lambda value, **kw: value)
    with pytest.raises(ValueError, match="compact request identity"):
        preview.production_inputs()
