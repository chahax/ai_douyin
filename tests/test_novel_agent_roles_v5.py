"""Native-file, full-input and same-draft proofs for production review adapter."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.content_factory import novel_agent_roles_v5 as roles
from src.content_factory import novel_logic_contracts_v4 as contracts

ROOT = Path(__file__).resolve().parents[1]


def raw_bundle():
    cases = json.loads((ROOT / "tests/fixtures/novel_logic_v4/rule_corpus_v1.json").read_text(encoding="utf-8"))["cases"]
    ledger = deepcopy(cases[1]["scene_ledger"])
    del ledger["header"]
    return {"scene_ledger": ledger,
            "full_review": {"native_verdict": "pass", "whole_text_reviewed": True,
                            "source_complete": True, "draft_complete": True, "issues": [],
                            "checks": [{"dimension": item, "checked": True, "assessment": "本稿已核对。", "issue_ids": []}
                                       for item in contracts.REVIEW_DIMENSIONS]},
            "adjudication": {"new_issues": [], "dispositions": []}}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def native_case(tmp_path, *, mutate_payload=None, mutate_response=None):
    source = {"binding_id": "source-proof", "text": "完整的已取得小说正文。"}
    screenplay = "完整的MiniMax原生创作稿。"
    payload = roles.build_review_payload(source, screenplay)
    if mutate_payload: mutate_payload(payload)
    request = {"role": "director", "stage": "review_full", "messages": [
        {"role": "system", "content": roles.REVIEW_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]}
    request_binding = save(tmp_path / "request.json", request)
    text = json.dumps(raw_bundle(), ensure_ascii=False)
    usage = {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}
    response = {"role": "director", "stage": "review_full", "request_binding": request_binding,
                "response_text": text,
                "response_metadata": {"role": "director", "provider": "deepseek", "requested_model": "deepseek-flash",
                                      "response_model": "deepseek-flash", "response_id": "test-native-1",
                                      "finish_reason": "stop", **usage},
                "response_payload": {"id": "test-native-1", "model": "deepseek-flash", "usage": usage.copy(),
                                     "choices": [{"finish_reason": "stop", "message": {"content": text}}]}}
    if mutate_response: mutate_response(response)
    response_binding = save(tmp_path / "response.json", response)
    review = roles.parse_review_bundle(text, source_binding=source["binding_id"],
                                      draft_binding=hashlib.sha256(screenplay.encode()).hexdigest(),
                                      native_response_ref=response_binding["sha256"], artifact_prefix="review-002")["review"]
    return {"request": request, "response": response, "source": source, "screenplay": screenplay,
            "protocol": {"director": {"provider": "deepseek", "model": "deepseek-flash"}},
            "review": review, "request_binding": request_binding, "response_binding": response_binding}


def test_flags_only_created_after_actual_file_native_and_full_input_proofs(tmp_path):
    data = native_case(tmp_path)
    proof = roles.verify_review_evidence(**data)
    assert proof["files_verified"] is True
    assert proof["native_verdict"] == "pass"
    assert proof["native_response_ref"] == data["response_binding"]["sha256"]


def test_asserting_native_flags_without_bound_files_cannot_pass(tmp_path):
    data = native_case(tmp_path)
    del data["response_binding"]
    with pytest.raises(ValueError, match="file binding required"):
        roles.verify_review_evidence(**data)


def test_frozen_response_file_tamper_is_not_a_valid_review(tmp_path):
    data = native_case(tmp_path)
    Path(data["response_binding"]["path"]).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="file changed"):
        roles.verify_review_evidence(**data)


@pytest.mark.parametrize("field", ["source", "screenplay"])
def test_native_pass_for_different_or_partial_input_cannot_be_rebound(tmp_path, field):
    data = native_case(tmp_path, mutate_payload=lambda p: p.update({field: "truncated or different"}))
    with pytest.raises(ValueError, match="complete same source and draft"):
        roles.verify_review_evidence(**data)


def test_review_derived_verdict_cannot_be_changed_to_pass(tmp_path):
    data = native_case(tmp_path)
    data["review"]["native_verdict"] = "revise"
    with pytest.raises(ValueError, match="differs from native output"):
        roles.verify_review_evidence(**data)


@pytest.mark.parametrize("kind", ["unknown_usage", "truncated", "reasoning_only"])
def test_unknown_or_incomplete_native_response_never_creates_evidence_flags(tmp_path, kind):
    def mutate(r):
        if kind == "unknown_usage":
            del r["response_metadata"]["total_tokens"]
        elif kind == "truncated":
            r["response_metadata"]["finish_reason"] = "length"
            r["response_payload"]["choices"][0]["finish_reason"] = "length"
        else:
            r["response_payload"]["choices"][0]["message"] = {"content": None, "reasoning_content": "内部推理"}
            r["response_text"] = "内部推理"
    data = native_case(tmp_path, mutate_response=mutate)
    with pytest.raises(ValueError, match="Native review envelope not complete"):
        roles.verify_review_evidence(**data)


def required_issue():
    return {"issue_id": "old-candidate", "root_cause_id": "old-root", "dimensions": ["causality"],
            "event_ids": ["E1"], "evidence": ["旧稿该事件上下文"], "reasonable_explanations": [],
            "counterevidence": [], "impact": "需要核实影响", "severity": "major",
            "severity_certainty": "unknown", "finding_status": "unresolved", "blocking": False}


def test_carried_issue_is_program_bound_but_disposition_must_be_native():
    raw = raw_bundle()
    issue = required_issue()
    kwargs = {"source_binding": "s", "draft_binding": "d", "native_response_ref": "r",
              "artifact_prefix": "a", "required_issues": [issue]}
    with pytest.raises(ValueError, match="Auxiliary review contract invalid"):
        roles.parse_review_bundle(json.dumps(raw), **kwargs)
    raw["adjudication"]["dispositions"] = [{"issue_id": issue["issue_id"], "disposition": "rejected",
                                              "basis": ["核对完整上下文后该意见不成立。"], "new_issue_ids": [], "blocking": False}]
    result = roles.parse_review_bundle(json.dumps(raw), **kwargs)
    assert result["adjudication"]["new_issues"] == [issue]
    assert result["adjudication"]["dispositions"][0] == raw["adjudication"]["dispositions"][0]


def test_writer_and_review_payload_preserve_entire_input_without_cutting():
    source = {"binding_id": "s", "text": "正文\r\n" * 2000}
    draft = "原生完整稿\n" * 3000
    writer = roles.build_writer_payload(source, previous_draft=draft, feedback={"issue": "内容问题"})
    review = roles.build_review_payload(source, draft)
    assert writer["source"] == review["source"] == source
    assert writer["previous_draft"] == review["screenplay"] == draft
    assert not any(key in writer for key in ("tools", "tool_choice", "structured_schema"))


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', '[]', '', '推理后正文缺失'])
def test_native_parser_does_not_guess_or_repair_incomplete_objects(text):
    with pytest.raises(ValueError):
        roles.parse_json(text)
