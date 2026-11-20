"""Evidence-only tests, using immutable501 and simulated provider receipts."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.content_factory import creative_format_recovery_contract_v1 as contract

ROOT = Path(__file__).resolve().parents[1] / "data/production_revisions/selected_script_video_trial_20261011/script487_continuation_v2"
SOURCE_SHA = "cbb125ea23dbefca1c314d53bc26ce7c231d1b3ab39b256b1b20d8dcde520d0d"


def original():
    receipt_bytes = (ROOT / "call_501_continuation_performance.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    ledger = json.loads((ROOT / "CALL_LEDGER.json").read_text(encoding="utf-8"))
    rows = [row for row in ledger["calls"] if row["ordinal"] == 501]
    assert len(rows) == 1
    expected = {key: receipt[key] for key in ["ordinal", "label", "request_sha256", "source_binding_sha256"]}
    expected.update(role=receipt["request"]["role"], model=receipt["request"]["model"], receipt_sha256=rows[0]["receipt_sha256"])
    evidence = ROOT / "call_evidence/call_501"
    return {"receipt": receipt, "expected_identity": expected, "receipt_bytes": receipt_bytes,
        "response_body": (evidence / "response_body.raw").read_bytes(),
        "response_manifest": json.loads((evidence / "RESPONSE_BODY_MANIFEST.json").read_text(encoding="utf-8")),
        "evidence_identity": json.loads((evidence / "IDENTITY.json").read_text(encoding="utf-8"))}


def validate(bundle, **kwargs):
    return contract.validate_format_recovery_seed(expected_source_sha=SOURCE_SHA, **bundle, **kwargs)


def reseal(bundle):
    """Simulation only: immutable production files are never written."""
    body = bundle["receipt"]["response_payload"]
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    body_sha = hashlib.sha256(raw).hexdigest()
    bundle["response_body"] = raw
    bundle["response_manifest"].update(stored_sha256=body_sha, original_sha256=body_sha, bytes=len(raw))
    bundle["receipt"]["response_metadata"]["raw_body_sha256"] = body_sha
    receipt_bytes = json.dumps(bundle["receipt"], ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    bundle["receipt_bytes"] = receipt_bytes
    bundle["expected_identity"]["receipt_sha256"] = hashlib.sha256(receipt_bytes).hexdigest()
    return bundle


def test_actual501_known_full_missing_tool_only_returns_evidence_without_adopting_content():
    bundle = original(); before = deepcopy(bundle)
    decision = validate(bundle)
    assert decision["original_reported_total_tokens"] == 6240
    assert decision["original_receipt_sha256"] == "a80f95290e4bda201dafb5cf105f286fff5ad58429201b80662f7029f516fffe"
    assert decision["original_status_retained"] == "interface_rejected"
    assert decision["max_new_format_requests"] == decision["next_recovery_count"] == 1
    assert decision["requires_new_request_identity"] and decision["source_binding_must_remain_unchanged"]
    assert not decision["old_message_content_adopted"] and not decision["automatic_retry"] and not decision["budget_reset"]
    assert not decision["semantic_approval"] and not decision["media_submission_authorized_by_this_contract"]
    assert "output" not in decision and "document_output" not in decision and "response_body" not in decision
    assert bundle == before


def test_unknown_or_truncated_results_cannot_be_revised():
    for defect in ["unknown_outcome", "unknown_status", "length", "unknown_finish", "incomplete_metadata", "incomplete_manifest"]:
        bundle = original(); receipt = bundle["receipt"]
        if defect == "unknown_outcome": receipt["failure"]["provider_outcome_known"] = False
        elif defect == "unknown_status": receipt["status"] = "outcome_unknown"
        elif defect == "length":
            receipt["response_metadata"]["finish_reason"] = receipt["response_payload"]["choices"][0]["finish_reason"] = "length"
        elif defect == "unknown_finish": receipt["response_metadata"]["finish_reason"] = None
        elif defect == "incomplete_metadata": receipt["response_metadata"]["response_body_complete"] = False
        else: bundle["response_manifest"]["body_complete"] = False
        with pytest.raises(ValueError): validate(reseal(bundle))


def test_unknown_negative_or_noninteger_usage_cannot_be_revised():
    for value in [None, -1, True, "6240", 6240.5]:
        bundle = original()
        bundle["receipt"]["response_metadata"]["total_tokens"] = value
        bundle["receipt"]["response_payload"]["usage"]["total_tokens"] = value
        with pytest.raises(ValueError, match="usage"): validate(reseal(bundle))
    bundle = original(); bundle["receipt"]["response_payload"]["usage"]["total_tokens"] += 1
    with pytest.raises(ValueError, match="usage"): validate(reseal(bundle))


def test_http_and_provider_success_must_be_known_in_all_original_evidence():
    for defect in ["http", "failure_http", "manifest_http", "provider_metadata", "provider_body", "unknown_provider"]:
        bundle = original(); receipt = bundle["receipt"]
        if defect == "http": receipt["response_metadata"]["http_status_code"] = 500
        elif defect == "failure_http": receipt["failure"]["http_status_code"] = None
        elif defect == "manifest_http": bundle["response_manifest"]["http_metadata"]["http_status_code"] = 429
        elif defect == "provider_metadata": receipt["response_metadata"]["provider_status_code"] = 1001
        elif defect == "provider_body": receipt["response_payload"]["base_resp"]["status_code"] = 1001
        else: receipt["response_payload"]["base_resp"] = None
        with pytest.raises(ValueError): validate(reseal(bundle))


def test_other_fault_or_actual_tool_output_or_prior_adoption_is_not_missing_tool_recovery():
    for defect in ["other_fault", "other_category", "actual_tool", "legacy_tool", "malformed_tool", "adopted_content"]:
        bundle = original(); receipt = bundle["receipt"]
        if defect == "other_fault": receipt["failure"]["code"] = "RESPONSE_TRUNCATED"
        elif defect == "other_category": receipt["failure"]["category"] = "state_contract"
        elif defect == "actual_tool": receipt["response_payload"]["choices"][0]["message"]["tool_calls"] = [{"id": "t1"}]
        elif defect == "legacy_tool": receipt["response_payload"]["choices"][0]["message"]["function_call"] = {"name": "submit_creative_json"}
        elif defect == "malformed_tool": receipt["response_payload"]["choices"][0]["message"]["tool_calls"] = ""
        else: receipt["document_output"] = {"manual_conversion": True}
        with pytest.raises(ValueError): validate(reseal(bundle))


def test_second_recovery_and_any_existing_or_unknown_media_submission_are_blocked():
    for count in [1, 2, -1, True, None, 0.0]:
        with pytest.raises(ValueError, match="one format revision"): validate(original(), prior_recovery_count=count)
    for exists in [True, None, 0]:
        with pytest.raises(ValueError, match="prior media submission"): validate(original(), media_submission_exists=exists)


def test_receipt_bytes_request_sha_and_independent_identity_cannot_be_changed():
    for defect in ["dict", "receipt_bytes", "request", "ordinal", "label", "binding", "model"]:
        bundle = original()
        if defect == "dict": bundle["receipt"]["error"] = "changed"
        elif defect == "receipt_bytes": bundle["receipt_bytes"] += b" "
        elif defect == "request":
            bundle["receipt"]["request"]["parameters"]["temperature"] = 0.8
            reseal(bundle)
        else:
            key = "source_binding_sha256" if defect == "binding" else defect
            bundle["expected_identity"][key] = 502 if key == "ordinal" else "x" * 64 if key.endswith("sha256") else "changed"
        with pytest.raises(ValueError): validate(bundle)


def test_selected_source_binding_cannot_be_changed_despite_complete_known_response():
    bundle = original()
    with pytest.raises(ValueError, match="source binding"):
        contract.validate_format_recovery_seed(expected_source_sha="0" * 64, **bundle)
    bundle = original(); bundle["receipt"]["request"]["inner_document_schema"]["properties"]["script_sha256"]["const"] = "0" * 64
    request_sha = contract._digest(bundle["receipt"]["request"])
    bundle["receipt"]["request_sha256"] = bundle["expected_identity"]["request_sha256"] = request_sha
    bundle["evidence_identity"]["identity"]["request_sha256"] = request_sha
    identity_sha = contract._digest(bundle["evidence_identity"]["identity"])
    bundle["evidence_identity"]["identity_sha256"] = bundle["receipt"]["call_evidence"]["identity_sha256"] = identity_sha
    bundle["response_manifest"]["identity_sha256"] = identity_sha
    with pytest.raises(ValueError, match="source binding"): validate(reseal(bundle))


def test_body_bytes_manifest_and_call_evidence_identity_are_cross_bound():
    for defect in ["body_bytes", "manifest_hash", "manifest_identity", "identity", "redacted", "length"]:
        bundle = original()
        if defect == "body_bytes": bundle["response_body"] += b" "
        elif defect == "manifest_hash": bundle["response_manifest"]["original_sha256"] = "0" * 64
        elif defect == "manifest_identity": bundle["response_manifest"]["identity_sha256"] = "0" * 64
        elif defect == "identity": bundle["evidence_identity"]["identity"]["ordinal"] += 1
        elif defect == "redacted": bundle["response_manifest"]["credential_redacted"] = True
        else: bundle["response_manifest"]["bytes"] -= 1
        with pytest.raises(ValueError): validate(bundle)


def test_message_content_is_opaque_even_when_it_is_malformed_inner_json():
    for content in ['{"apparently_valid":true}', '{not complete inner JSON', "not JSON at all"]:
        bundle = original(); bundle["receipt"]["response_payload"]["choices"][0]["message"]["content"] = content
        decision = validate(reseal(bundle))
        assert decision["status"] == "format_recovery_seed_valid" and not decision["old_message_content_adopted"]
        assert content not in json.dumps(decision, ensure_ascii=False)


def test_original_bytes_must_be_complete_unique_finite_json_objects():
    for raw in [b'{"choices":', b'{"x":1,"x":2}', b'{"x":NaN}', b'[]']:
        bundle = original(); bundle["response_body"] = raw
        with pytest.raises(ValueError): validate(bundle)
    bundle = original(); bundle["expected_identity"].pop("receipt_sha256")
    with pytest.raises(ValueError, match="identity fields"): validate(bundle)


def test_known_tool_calls_finish_without_actual_tool_can_still_get_one_new_identity():
    bundle = original()
    bundle["receipt"]["response_metadata"]["finish_reason"] = "tool_calls"
    bundle["receipt"]["response_payload"]["choices"][0]["finish_reason"] = "tool_calls"
    bundle["receipt"]["response_payload"]["choices"][0]["message"]["tool_calls"] = []
    assert validate(reseal(bundle))["requires_new_request_identity"]
