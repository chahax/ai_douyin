"""Native-response and full-review evidence without model/service dispatch."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.content_factory import novel_plaintext_contracts_v3 as contracts


def response(text="# 完整创作稿\n背景、角色、主线、规划、完整剧本。", role="writer"):
    provider, model = ("minimax", "MiniMax-M3") if role == "writer" else ("deepseek", "deepseek-flash")
    metadata = {
        "role": role, "provider": provider, "requested_model": model,
        "response_model": model, "response_id": "offline-response-1",
        "finish_reason": "stop", "output_mode": "content",
        "prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168,
    }
    native = {
        "id": metadata["response_id"], "model": model,
        "usage": {key: metadata[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")},
        "choices": [{"finish_reason": "stop", "message": {
            "content": text, "reasoning_content": None, "tool_calls": [],
        }}],
    }
    return ({"role": role, "response_metadata": metadata, "response_payload": native, "response_text": text},
            {"provider": provider, "model": model})


def review():
    return {"verdict": "pass", "whole_text_reviewed": True,
            "summary": "离线假审查，只验证审查覆盖合同，不证明创作质量。",
            "checks": [{"dimension": dimension, "checked": True,
                        "assessment": "已对照本稿完整相关场次检查；本例无阻断问题。", "issues": []}
                       for dimension in contracts.REVIEW_DIMENSIONS]}


def test_plaintext_without_tool_is_authoritative_and_unchanged():
    text = "原文引号可换成普通引号。\n\n剧本对白：不必逐字照搬。"
    record, protocol = response(text)
    assert contracts.response_evidence(record, protocol) == ([], 168, text)


@pytest.mark.parametrize("text", [
    "自己跟这群畜生之间，所有的恩怨情仇。\n\n一切，都要在今天做出个了断！",
    "自己跟这群畜生之间，所有的恩怨情仇。一切，都要在今天做出个了断！",
    '他说：“该走了。”', '他说："该走了。"',
])
def test_quote_layout_never_creates_a_writer_content_failure(text):
    record, protocol = response(text)
    assert contracts.response_evidence(record, protocol) == ([], 168, text)


def test_exact_saved_missing_tool_response_can_be_sent_to_review():
    path = Path(__file__).resolve().parents[1] / "data/novel_adaptation_production/20261017_acceptance_v1/run/RESPONSE_003.json"
    assert path.is_file(), "本次真实回放材料必须存在，不能用模拟响应冒充"
    record = json.loads(path.read_text(encoding="utf-8-sig"))
    before = path.read_bytes()
    errors, total, text = contracts.response_evidence(record, {"provider": "minimax", "model": "MiniMax-M3"})
    assert errors == []
    assert total == 15521 and len(text) == 7531
    assert text == record["response_payload"]["choices"][0]["message"]["content"]
    assert record["response_metadata"]["response_fault_code"] == "REQUIRED_TOOL_MISSING"
    assert path.read_bytes() == before
    # This is usable native text, never a claim that its analysis or story passes.
    assert '"world"' in text


def test_single_legacy_tool_body_is_preserved_without_parsing_or_projection():
    text = '{"screenplay_markdown":"旧原生稿"}'
    record, protocol = response(text)
    record["response_metadata"].update(finish_reason="tool_calls", output_mode="tool_call")
    choice = record["response_payload"]["choices"][0]
    choice["finish_reason"] = "tool_calls"
    choice["message"].update(content=None, tool_calls=[{
        "type": "function", "function": {"name": "submit_creative_json", "arguments": text},
    }])
    assert contracts.response_evidence(record, protocol) == ([], 168, text)


@pytest.mark.parametrize("field", ["prompt_tokens", "completion_tokens", "total_tokens"])
@pytest.mark.parametrize("bad", [None, -1, True, 168.0])
def test_missing_invalid_or_boolean_usage_is_unknown(field, bad):
    record, protocol = response()
    record["response_metadata"][field] = bad
    record["response_payload"]["usage"][field] = bad
    errors, total, _ = contracts.response_evidence(record, protocol)
    assert errors and total is None


def test_native_usage_mismatch_and_sum_mismatch_are_unknown():
    record, protocol = response()
    record["response_payload"]["usage"]["total_tokens"] += 1
    assert contracts.response_evidence(record, protocol)[1] is None
    record["response_metadata"]["total_tokens"] += 1
    errors, total, _ = contracts.response_evidence(record, protocol)
    assert "USAGE_SUM_MISMATCH" in errors and total is None


def test_truncation_keeps_known_bill_and_cannot_be_format_recovery():
    record, protocol = response("正文截断了")
    record["response_metadata"].update(finish_reason="length", response_fault_code="RESPONSE_TRUNCATED")
    record["response_payload"]["choices"][0]["finish_reason"] = "length"
    errors, total, text = contracts.response_evidence(record, protocol)
    assert "RESPONSE_TRUNCATED" in errors and total == 168 and text == "正文截断了"


@pytest.mark.parametrize("reason", [None, "", "content_filter", "cancelled"])
def test_unknown_or_incomplete_finish_stops(reason):
    record, protocol = response()
    record["response_metadata"]["finish_reason"] = reason
    record["response_payload"]["choices"][0]["finish_reason"] = reason
    assert contracts.response_evidence(record, protocol)[0]


def test_finish_mismatch_stops_even_if_metadata_says_complete():
    record, protocol = response()
    record["response_payload"]["choices"][0]["finish_reason"] = "length"
    assert "RESPONSE_TRUNCATED" in contracts.response_evidence(record, protocol)[0]


@pytest.mark.parametrize("key,value", [
    ("role", "director"), ("provider", "other"), ("requested_model", "other"),
    ("response_model", "other"), ("response_id", "different"),
])
def test_role_model_and_response_identity_mismatches_stop(key, value):
    record, protocol = response()
    record["response_metadata"][key] = value
    assert contracts.response_evidence(record, protocol)[0]


def test_deepseek_verified_native_alias_is_accepted():
    record, protocol = response("{}", "director")
    record["response_metadata"]["response_model"] = "DeepSeek-V4.1-Flash"
    record["response_payload"]["model"] = "DeepSeek-V4.1-Flash"
    assert contracts.response_evidence(record, protocol) == ([], 168, "{}")


@pytest.mark.parametrize("choices", [[], [{}, {}], None, [None]])
def test_nonunique_or_missing_native_choice_stops(choices):
    record, protocol = response()
    record["response_payload"]["choices"] = choices
    assert contracts.response_evidence(record, protocol)[0]


def test_reasoning_is_never_used_as_creative_body():
    record, protocol = response(None)
    record["response_payload"]["choices"][0]["message"]["reasoning_content"] = "不能把这段推理当成正文"
    errors, _, text = contracts.response_evidence(record, protocol)
    assert "NATIVE_BODY_MISSING" in errors and text is None


def test_response_text_must_match_native_body():
    record, protocol = response()
    record["response_text"] = "助手手工补写的稿"
    assert "NATIVE_BODY_WRAPPER_MISMATCH" in contracts.response_evidence(record, protocol)[0]


def test_unknown_error_is_not_ignored_when_native_looks_complete():
    record, protocol = response()
    record["error"] = "transport failure after unknown operation"
    assert "RECEIVED_ERROR" in contracts.response_evidence(record, protocol)[0]


@pytest.mark.parametrize("fault", ["EMPTY_RESPONSE", "MODEL_MISMATCH", "RESPONSE_NOT_COMPLETED", "UNEXPECTED_TOOL_CALL"])
def test_other_response_faults_stop(fault):
    record, protocol = response()
    record["response_metadata"]["response_fault_code"] = fault
    assert f"RESPONSE_FAULT:{fault}" in contracts.response_evidence(record, protocol)[0]


def test_nine_explicit_completed_review_checks_are_valid():
    assert contracts.validate_review(review()) == []


def test_revise_without_any_actionable_issue_is_invalid_review():
    value = review()
    value["verdict"] = "revise"
    assert any(item["code"] == "REVIEW_REVISION_WITHOUT_ISSUES" for item in contracts.validate_review(value))


@pytest.mark.parametrize("bad", [None, {}, [], "pass"])
def test_no_missing_review_can_be_assumed_pass(bad):
    assert contracts.validate_review(bad)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unchecked", "partial", "empty_assessment", "empty_summary"])
def test_review_coverage_and_actual_assessments_are_required(mutation):
    value = review()
    if mutation == "missing":
        value["checks"].pop()
    elif mutation == "duplicate":
        value["checks"][-1] = deepcopy(value["checks"][0])
    elif mutation == "unchecked":
        value["checks"][0]["checked"] = False
    elif mutation == "partial":
        value["whole_text_reviewed"] = False
    elif mutation == "empty_assessment":
        value["checks"][0]["assessment"] = "  "
    else:
        value["summary"] = "  "
    assert contracts.validate_review(value)


@pytest.mark.parametrize("severity", ["major", "blocking"])
def test_pass_with_substantive_issue_is_rejected(severity):
    value = review()
    value["checks"][0]["issues"] = [{"severity": severity, "location": "S1", "evidence": "稿中现有句子", "suggestion": "保留已证实动机"}]
    assert any(issue["code"] == "REVIEW_VERDICT_CONFLICT" for issue in contracts.validate_review(value))
    value["verdict"] = "revise"
    assert contracts.validate_review(value) == []


def test_semantic_review_can_reject_missing_end_or_invented_sequel():
    value = review()
    value["verdict"] = "revise"
    for dimension, location, evidence, suggestion in [
        ("completeness", "五、完整剧本末尾", "后续场景略", "实际写到本段结尾"),
        ("mainline_and_motivation", "S3", "三年后他继承集团", "只改编已取得章节，删除无源后续"),
    ]:
        check = next(item for item in value["checks"] if item["dimension"] == dimension)
        check["issues"] = [{"severity": "blocking", "location": location, "evidence": evidence, "suggestion": suggestion}]
    assert contracts.validate_review(value) == []
    assert value["verdict"] == "revise"


@pytest.mark.parametrize("field", ["location", "evidence", "suggestion"])
def test_review_issue_requires_specific_nonblank_fields(field):
    value = review()
    issue = {"severity": "minor", "location": "S1", "evidence": "句子", "suggestion": "具体建议"}
    issue[field] = "  "
    value["checks"][0]["issues"] = [issue]
    assert contracts.validate_review(value)


def test_pass_can_retain_minor_issues_without_human_approval():
    value = review()
    value["checks"][0]["issues"] = [{"severity": "minor", "location": "标题", "evidence": "场1", "suggestion": "可统一场次写法"}]
    assert contracts.validate_review(value) == []
    assert "human_approved" not in value
