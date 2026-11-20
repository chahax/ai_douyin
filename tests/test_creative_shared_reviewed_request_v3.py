"""Full immutable request review bindings; offline originals are synthetic."""
from copy import deepcopy
import json
import socket

import pytest

from scripts import run_creative_shared_full_production_v1 as original
from src.content_factory import creative_complete_production_pipeline_v3 as pipeline
from src.content_factory import creative_shared_media_contract_v3 as media
from src.content_factory import creative_shared_production_contract_v1 as shared
from tests.test_creative_complete_production_coordinator_v3 import receipt
from tests.test_creative_shared_media_contract_v3 import bootstrap_fixture


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("reviewed media request tests are offline")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def fixture(tmp_path):
    script, manifest, _, context = bootstrap_fixture(tmp_path)
    preview = media.compile_request_preview(context, context["prompt_fragment"], 4)
    inputs = {"brief": {"note": "离线夹具"}, "full_current_script": script,
        "source_catalog": original.source.catalog(script), "shared_manifest": manifest,
        "whole_direction": {"schema": "offline-direction"},
        "complete_compilation": {"schema": "offline-complete-production"},
        "all_local_performances": [{"schema": "offline-local"}],
        "all_planned_video_prompts": [context["prompt_fragment"]],
        "opening_actual_video_prompt": context["prompt_fragment"], "opening_shared_projection": context,
        "opening_actual_provider_request": preview["request"], "opening_actual_request_proof": preview["proof"],
        "reference_fulltext": "离线完整参考分析夹具，不是生产内容。",
        "source_full_review_binding": {"note": "离线已知同源记录夹具"}, "scope": {"offline_only": True}}
    schema = original.review_schema(original.PRODUCTION_CHECKS, list(original.source.catalog(script)))
    request = pipeline.build_request("whole_production_review", inputs, schema, "deepseek-flash")
    native = {"checks": [{"check": name, "status": "pass", "source_refs": ["B1.S01"],
        "reason": "离线模拟全文复审，不是创作质量证据"} for name in original.PRODUCTION_CHECKS],
        "revision_requirements": [], "review_limitations": ["未观看媒体。"]}
    review_receipt = receipt("whole_production_review_v3_d1", request, native, 518)
    options = {"expected_reviewed_request_sha256": shared.digest(preview["request"]),
        "expected_review_receipt_sha256": shared.digest(review_receipt), "expected_review_input": deepcopy(inputs),
        "expected_checks": original.PRODUCTION_CHECKS}
    return preview, review_receipt, options


def test_original_full_review_binds_every_parameter_and_does_not_authorize_dispatch(tmp_path):
    preview, review_receipt, options = fixture(tmp_path)
    proof = media.verify_reviewed_request(preview["request"], preview, review_receipt, **options)
    assert proof["all_provider_parameters_equal_to_reviewed"] is True
    assert proof["original_full_review_tool_verified"] is True
    assert proof["calls_authorized"] is False and proof["new_paid_calls"] == 0
    assert proof["actual_media_quality_passed"] is False
    assert proof["same_account_live_credentials_verified"] is False


@pytest.mark.parametrize("field,value", [("duration", 8), ("ratio", "16:9"), ("resolution", "720p"),
    ("generate_audio", False), ("watermark", True), ("return_last_frame", False), ("seed", 3)])
def test_actual_request_parameter_change_after_review_is_blocked(tmp_path, field, value):
    preview, review_receipt, options = fixture(tmp_path)
    changed = deepcopy(preview["request"]); changed[field] = value
    with pytest.raises(ValueError, match="immutable full-reviewed request"):
        media.verify_reviewed_request(changed, preview, review_receipt, **options)


@pytest.mark.parametrize("failure", ["unknown_usage", "missing_tool", "truncated", "unknown_check", "failed_check", "missing_input", "changed_actual_input", "changed_receipt", "duplicate_checks"])
def test_unknown_incomplete_failed_or_wrong_original_full_review_blocks(tmp_path, failure):
    preview, r, options = fixture(tmp_path)
    if failure == "unknown_usage": r["response_metadata"]["total_tokens"] = None
    elif failure == "missing_tool": r["response_payload"]["choices"][0]["message"]["tool_calls"] = []
    elif failure == "truncated": r["response_metadata"]["finish_reason"] = "length"
    elif failure in ("unknown_check", "failed_check", "duplicate_checks"):
        value = deepcopy(r["output"])
        if failure == "duplicate_checks": value["checks"][1]["check"] = value["checks"][0]["check"]
        else:
            value["checks"][0]["status"] = "unknown" if failure == "unknown_check" else "fail"
            value["revision_requirements"] = ["离线整改"]
        r["output"] = value
        r["response_payload"]["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = json.dumps(value)
    elif failure in ("missing_input", "changed_actual_input"):
        inputs = json.loads(r["request"]["messages"][1]["content"])
        if failure == "missing_input": inputs.pop("complete_compilation")
        else: inputs["opening_actual_provider_request"]["duration"] = 9
        r["request"]["messages"][1]["content"] = json.dumps(inputs)
        r["request_sha256"] = shared.digest(r["request"])
    elif failure == "changed_receipt": r["ordinal"] = 999
    if failure != "changed_receipt": options["expected_review_receipt_sha256"] = shared.digest(r)
    with pytest.raises(ValueError):
        media.verify_reviewed_request(preview["request"], preview, r, **options)


def test_recomputed_replacement_preview_cannot_change_frozen_reviewed_request_digest(tmp_path):
    preview, review_receipt, options = fixture(tmp_path)
    changed = deepcopy(preview)
    changed["request"]["generate_audio"] = False
    changed["proof"]["actual_request_sha256"] = shared.digest(changed["request"])
    with pytest.raises(ValueError, match="immutable full-reviewed request"):
        media.verify_reviewed_request(changed["request"], changed, review_receipt, **options)
