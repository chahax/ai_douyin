"""Lossless fixed-column review transport tests; no service transport."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import creative_compact_review_transport_v8 as compact
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_creative_script_review_sources_v7 import two_script_beats, previous_ref


def valid_review(*, failed=False):
    context, review = two_script_beats()
    check = review["coverage"][1]["checks"]["continuity"]
    check["evidence_refs"].append(previous_ref(context))
    review["suggestions"] = [{"location": "B02", "proposal": "可选表演留白", "reason": "仅审美建议"}]
    review["calibration_focus"] = ["后续由用户审核实际视频"]
    if failed:
        check.update(status="fail", issue_ids=["I01"])
        review["story_preserved"] = False
        review["issues"] = [{"id": "I01", "owner": "writer", "location": "B02", "severity": "major",
            "rule": "离线测试原始必修", "evidence": context["script"]["beats"][1]["before"],
            "contradiction": "保留原失败结论", "impact": "连续性测试", "proposal": "完整新稿修复",
            "evidence_refs": deepcopy(check["evidence_refs"])}]
    return context, review


def serialized(raw):
    return json.dumps(raw, ensure_ascii=False, separators=(",", ":"))


@pytest.mark.parametrize("failed", [False, True])
def test_exact_roundtrip_preserves_every_reason_reference_issue_and_original_failure(failed):
    context, review = valid_review(failed=failed)
    before = deepcopy((context, review))
    raw = compact.encode_review(review, context)
    raw_before = deepcopy(raw)
    effective = compact.expand_review(raw, context)
    assert effective == review
    assert compact.accept_response(serialized(raw), context, finish_reason="stop") == review
    assert raw == raw_before and (context, review) == before
    assert raw["context_sha256"] == compact.context_digest(context)
    assert len(raw["coverage"][0]) == 7
    assert all(len(cell) == 4 for cell in raw["coverage"][0][1:])
    assert effective["story_preserved"] is (not failed)


@pytest.mark.parametrize("defect", ["missing_row", "duplicate_row", "old_row", "row_object", "missing_column", "check_object", "missing_cell", "unknown_status", "bool_status", "numeric_reason", "refs_object", "ref_object", "ref_long", "ids_object", "numeric_id", "bool_story", "extra_top", "old_version"])
def test_malformed_dimensions_types_and_enums_never_receive_defaults(defect):
    context, review = valid_review()
    raw = compact.encode_review(review, context)
    if defect == "missing_row": raw["coverage"].pop()
    elif defect == "duplicate_row": raw["coverage"][1] = deepcopy(raw["coverage"][0])
    elif defect == "old_row": raw["coverage"][1][0] = "OLD_BEAT"
    elif defect == "row_object": raw["coverage"][0] = {"item": raw["coverage"][0]}
    elif defect == "missing_column": raw["coverage"][0].pop()
    elif defect == "check_object": raw["coverage"][0][1] = {"item": raw["coverage"][0][1]}
    elif defect == "missing_cell": raw["coverage"][0][1].pop()
    elif defect == "unknown_status": raw["coverage"][0][1][0] = "approved"
    elif defect == "bool_status": raw["coverage"][0][1][0] = True
    elif defect == "numeric_reason": raw["coverage"][0][1][1] = 42
    elif defect == "refs_object": raw["coverage"][0][1][2] = {"item": []}
    elif defect == "ref_object": raw["coverage"][0][1][2][0] = {"path": "script.beats.0.before", "quote": "许宁"}
    elif defect == "ref_long": raw["coverage"][0][1][2][0].append("extra")
    elif defect == "ids_object": raw["coverage"][0][1][3] = {"item": []}
    elif defect == "numeric_id": raw["coverage"][0][1][3] = [42]
    elif defect == "bool_story": raw["story_preserved"] = 1
    elif defect == "extra_top": raw["approved"] = True
    else: raw["schema"] = "old_transport"
    before = deepcopy(raw)
    with pytest.raises(CreativeContractError):
        compact.expand_review(raw, context)
    assert raw == before


def test_full_context_sha_binds_reference_changes_not_only_script():
    context, review = valid_review()
    context["reference_pack"] = [{"id": "R01", "text": "完整参考原文"}]
    raw = compact.encode_review(review, context)
    context["reference_pack"][0]["text"] += "变化"
    with pytest.raises(compact.CompactReviewTransportError, match="COMPACT_CONTEXT_STALE"):
        compact.expand_review(raw, context)


def test_previous_source_is_enforced_after_decoding_without_automatic_insertion():
    context, review = valid_review()
    raw = compact.encode_review(review, context)
    raw["coverage"][1][3][2] = [pair for pair in raw["coverage"][1][3][2] if not pair[0].startswith("script.beats.0.")]
    before = deepcopy(raw)
    with pytest.raises(CreativeContractError, match="v7"):
        compact.expand_review(raw, context)
    assert raw == before


@pytest.mark.parametrize("defect", ["array_target", "unknown_path", "bad_quote"])
def test_original_scalar_leaf_and_verbatim_gate_stays_authoritative(defect):
    context, review = valid_review()
    context["script"]["beats"][0]["dialogue"] = []
    raw = compact.encode_review(review, context)
    pair = {"array_target": ["script.beats.0.dialogue", "[]"],
            "unknown_path": ["script.beats.99.before", "不存在"],
            "bad_quote": ["script.beats.0.before", "未发生的动作"]}[defect]
    raw["coverage"][1][3][2].append(pair)
    with pytest.raises(CreativeContractError, match="引用路径或逐字证据无效"):
        compact.expand_review(raw, context)


@pytest.mark.parametrize("defect", ["length_even_valid_json", "truncated_stop", "duplicate_field", "unknown_finish", "nonfinite"])
def test_incomplete_or_ambiguous_response_cannot_adopt_partial_true(defect):
    context, review = valid_review()
    text = serialized(compact.encode_review(review, context))
    reason = "stop"
    if defect == "length_even_valid_json": reason = "length"
    elif defect == "truncated_stop": text = text[:-1]
    elif defect == "duplicate_field": text = text[:-1] + ',"story_preserved":false}'
    elif defect == "unknown_finish": reason = None
    else: text = text.replace('"story_preserved":true', '"story_preserved":NaN')
    with pytest.raises(CreativeContractError):
        compact.accept_response(text, context, finish_reason=reason)


def test_legacy_47_replay_is_exact_but_cannot_bypass_real_candidate_v7():
    path = Path(__file__).resolve().parents[1] / "data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/call_047_linear_script_review_v4.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    context = json.loads(receipt["request"]["messages"][1]["content"])
    before = deepcopy(receipt["output"])
    replay = compact.replay_legacy_v6(before, context)
    assert replay["effective_review"] == before
    assert replay["exact_roundtrip"] is True
    assert replay["candidate_v7_validation"]["result"] == "rejected"
    assert replay["automatic_approval"] is False and replay["real_model_test"] is False
    assert [row["id"] for row in replay["effective_review"]["issues"]] == ["I01", "I02", "I03", "I04"]
    assert replay["effective_review"]["story_preserved"] is False
    with pytest.raises(CreativeContractError, match="v7"):
        compact.expand_review(replay["raw_transport"], context)


def test_wire_keeps_whole_context_parameters_and_reports_insufficient_original_budget():
    context, _ = valid_review()
    context["reference_pack"] = [{"id": "R01", "text": "完整参考全文"}]
    context["creative_brief"] = {"theme": "观众感受原文"}
    context["static_visual_manifest"] = {"characters": [{"name": "许宁"}]}
    before = deepcopy(context)
    parameters = {"max_completion_tokens": 11000, "temperature": 0.4, "thinking": "disabled"}
    wire = compact.build_wire_preview(context, model="deepseek-flash", parameters=parameters)
    assert json.loads(wire["messages"][1]["content"]) == context == before
    assert wire["parameters"] == parameters
    assert wire["structured_schema"] is None
    assert "[path,quote]" in wire["messages"][0]["content"]
    assert "context_sha256逐字填写" in wire["messages"][0]["content"]
    budget = compact.budget_preview(wire, reported_tokens=490913)
    assert budget["remaining_reported_tokens"] == 9087
    assert budget["fits_original_budget"] is False
    assert budget["max_output_tokens"] == 11000
    assert budget["network_calls"] == 0 and budget["dispatched"] is False
    assert budget["provider_output_token_savings"] is None



def test_joint_encoding_keeps_v7_contract_but_script_prompt_refuses_joint_scope():
    from tests.test_creative_script_review_sources_v7 import prepared
    context, review = prepared()
    before = deepcopy((context, review))
    raw = compact.encode_review(review, context)
    assert compact.expand_review(raw, context) == review
    with pytest.raises(compact.CompactReviewTransportError, match="COMPACT_SCOPE_UNSUPPORTED"):
        compact.build_review_messages(context)
    assert (context, review) == before


@pytest.mark.parametrize("context", [{"script": {"beats": []}}, {"shots": {"shots": []}}])
def test_empty_body_cannot_claim_complete_review(context):
    review = {"story_preserved": True, "issues": [], "suggestions": [], "calibration_focus": [], "coverage": []}
    raw = {"schema": compact.VERSION, "context_sha256": compact.context_digest(context), **review}
    with pytest.raises(CreativeContractError, match="COMPACT_CONTEXT_INVALID"):
        compact.expand_review(raw, context)
    with pytest.raises(CreativeContractError):
        compact.build_review_messages(context)


@pytest.mark.parametrize("cap", [True, 0, 11000.0])
def test_direct_budget_preview_rejects_nonpositive_or_noninteger_output_cap(cap):
    with pytest.raises(compact.CompactReviewTransportError, match="COMPACT_PARAMETERS_INVALID"):
        compact.budget_preview({"parameters": {"max_completion_tokens": cap}}, reported_tokens=490913)



def test_request_protocol_changes_keep_all_frozen_semantic_instructions():
    from scripts.review_linear_script_probe_v6 import PROMPT
    context, _ = valid_review()
    prompt = compact.build_review_messages(context)[0]["content"]
    protocol_prefixes = ("仅返回JSON", "coverage逐一覆盖", "evidence_refs每项")
    for line in PROMPT.splitlines():
        if not line.startswith(protocol_prefixes):
            assert line in prompt
    assert "requirements,timing,continuity,dialogue_timing,first_frame,assets" in prompt
    assert "有前拍的连续性同时引用前拍真实正文" in prompt



def test_actual_48_preview_preserves_all_steps_and_bound_references_exactly():
    from scripts.creative_linear_script_v2 import accept_linear_script
    base = Path(__file__).resolve().parents[1] / "data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1"
    draft = json.loads((base / "call_048_linear_draft_v5.json").read_text(encoding="utf-8"))
    rejected_review = json.loads((base / "call_049_linear_script_review_v6.json").read_text(encoding="utf-8"))
    context = json.loads(rejected_review["request"]["messages"][1]["content"])
    writer = json.loads(draft["request"]["messages"][1]["content"])
    names = sorted({step["speaker"] for beat in draft["output"]["beats"] for step in beat["steps"] if step["kind"] == "dialogue"})
    derived = accept_linear_script(writer["previous_script"], draft["output"], character_names=names)
    derived.pop("screenplay_markdown")
    assert derived == context["script"]
    before = deepcopy(context)
    wire = compact.build_wire_preview(context, model=rejected_review["request"]["model"], parameters=rejected_review["request"]["parameters"])
    restored = json.loads(wire["messages"][1]["content"])
    assert restored == context == before
    assert set(restored) == set(context)
    for key in ("creative_brief", "static_visual_manifest", "material_ref", "reference_pack", "reference_expression_rule", "script_revision_source"):
        assert restored[key] == context[key]
    assert len(restored["script"]["beats"]) == 14
    assert restored["script"]["duration_seconds"] == 135
    for raw_beat, derived_beat in zip(draft["output"]["beats"], restored["script"]["beats"]):
        assert derived_beat["event"] == raw_beat["event"] and derived_beat["trigger"] == raw_beat["trigger"]
        for step in raw_beat["steps"]:
            if step["kind"] == "dialogue":
                assert {"speaker": step["speaker"], "text": step["text"]} in derived_beat["dialogue"]
            else:
                assert any(step["text"] in derived_beat[field] for field in ("before", "during", "after"))
