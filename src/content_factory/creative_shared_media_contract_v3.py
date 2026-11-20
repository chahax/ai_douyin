"""Offline media gates layered over the immutable shared-production v1 contract.

No network, media inspection, approval writing or ledger mutation occurs here.
Provider/source metadata and original bytes are checked; pixel identity and
provider input acceptance still require their respective human/service checks.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import base64
import hashlib
import json
import re

from jsonschema import Draft202012Validator, ValidationError

from . import creative_shared_production_contract_v1 as shared
from .seedance_client import ARK_BASE_URL, SeedanceClient, SeedanceConfig, SeedanceReference
from .seedance_models import ark_model
from . import creative_production_revision_loop_v3 as production_loop

VERSION = "creative_shared_media_contract/v3"


def _sha_file(path):
    if not isinstance(path, (str, Path)):
        raise ValueError("bound original artifact path missing")
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("bound original artifact missing or empty")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checked_json(path, sha256):
    if _sha_file(path) != sha256:
        raise ValueError("bound evidence file SHA changed")
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("bound evidence must be a JSON object")
    return value


def fixed_identity_projection(compiled):
    """Compare immutable casting/wardrobe/scene, excluding new asset approvals."""
    projection = compiled["projection"]
    # Compare values, not provenance additions made when the user maps subjects.
    def value(fact):
        return {"status": fact["status"], "value": deepcopy(fact["value"])}
    return {
        "actors": [{"id": a["id"], "name": a["name"],
            "profile": {key: value(a["profile"][key]) for key in shared.PROFILE_FIELDS}}
            for a in projection["actors"]],
        "scene": {"id": projection["scene"]["id"],
            **{key: value(projection["scene"][key]) for key in ("setting", "appearance")}},
        "props": [{"id": p["id"], **{key: value(p[key]) for key in ("appearance", "owner")}}
            for p in projection["props"]],
    }


def _actor_mapping(compiled):
    return [{"actor_id": actor["id"], **deepcopy(actor["asset_binding"]["value"])}
        for actor in compiled["projection"]["actors"]]


def verify_original_tail_evidence(compiled, original_tail_source):
    """Verify a real saved original tail and explicit mapped-role user approval.

    original_tail_source contains generation_receipt_path,
    generation_receipt_sha256 and human_review_path. Approval is supplied by the
    caller from trusted user evidence; this function never creates it.
    """
    media = compiled["media_binding"]
    if media["role"] != "first_frame" or compiled["casting_bootstrap"]:
        raise ValueError("original-tail verification only applies to formal first_frame continuation")
    if not isinstance(original_tail_source, dict):
        raise ValueError("original saved receipt and explicit human tail approval required")
    tail = media.get("tail_evidence")
    if tail is None:
        raise ValueError("original tail binding missing")
    review_path = original_tail_source.get("human_review_path")
    if review_path != tail["human_review_path"]:
        raise ValueError("human review path differs from the actual tail binding")
    receipt_path = original_tail_source.get("generation_receipt_path")
    receipt_sha = original_tail_source.get("generation_receipt_sha256")
    receipt = _checked_json(receipt_path, receipt_sha)
    review = _checked_json(review_path, tail["human_review_sha256"])
    if (receipt.get("technical_status") != "succeeded"
        or receipt.get("provider_task_status", receipt.get("status")) != "succeeded"
        or receipt.get("task_id") != tail["source_task_id"]
        or receipt.get("segment_id") != tail["source_segment_id"]
        or receipt.get("last_frame_source") != "generation_service_original"
        or receipt.get("last_frame") != tail["path"]
        or receipt.get("last_frame_sha256") != tail["sha256"]
        or receipt.get("video_sha256") != tail["source_video_sha256"]):
        raise ValueError("original service receipt is unknown, failed or belongs to another tail")
    final = receipt.get("final", {})
    if final.get("id") != receipt["task_id"] or final.get("status") != "succeeded" or not final.get("content", {}).get("last_frame_url"):
        raise ValueError("original terminal service response must return this tail")
    if (_sha_file(tail["path"]) != tail["sha256"]
        or _sha_file(receipt["video_path"]) != tail["source_video_sha256"]):
        raise ValueError("original video or tail bytes changed")
    plan = receipt.get("plan_snapshot", {})
    previous = plan.get("shared_context")
    if (not isinstance(previous, dict)
        or previous.get("script_sha256") != compiled["script_sha256"]
        or fixed_identity_projection(previous) != fixed_identity_projection(compiled)
        or plan.get("completed_source_refs", []) + plan.get("source_refs", [])
            != compiled["projection"]["dynamic_state"]["completed_source_refs"]):
        raise ValueError("original media does not bind the same fixed identities and immediate source prefix")
    if (receipt.get("request_sha256") != shared.digest(receipt.get("request"))
        or receipt.get("provider") != compiled["projection"]["provider_policy"]["provider_id"]
        or receipt.get("model") != compiled["projection"]["provider_policy"]["model"]):
        raise ValueError("original media provider/model/request binding changed")
    previous_request = receipt["request"]
    previous_texts = [row for row in previous_request.get("content", []) if row.get("type") == "text"]
    if len(previous_texts) != 1 or previous_texts[0].get("text", "").count(previous["prompt_fragment"]) != 1:
        raise ValueError("original request did not contain its complete fixed identity projection")
    if (review.get("decision") != "approved"
        or review.get("decision_source") != "explicit_user_statement"
        or not str(review.get("user_statement", "")).strip()
        or review.get("source_receipt") != receipt_path
        or review.get("source_receipt_sha256") != receipt_sha
        or review.get("original_video") != receipt["video_path"]
        or review.get("original_video_sha256") != receipt["video_sha256"]
        or review.get("raw_tail") != tail["path"]
        or review.get("raw_tail_sha256") != tail["sha256"]):
        raise ValueError("explicit user approval is missing or belongs to another original video/tail")
    mapping = review.get("actor_subject_mapping")
    if (review.get("global_manifest_sha256") != compiled["global_manifest_sha256"]
        or not isinstance(mapping, list)
        or [{key: row.get(key) for key in ("actor_id", "asset_id", "subject_key")} for row in mapping]
            != _actor_mapping(compiled)
        or any(not isinstance(row.get("subject_description"), str)
            or not row["subject_description"].strip() for row in mapping)):
        raise ValueError("human-approved actor subject mapping missing or changed")
    return {"schema": VERSION + "/original_tail_proof",
        "generation_receipt_path": receipt_path, "generation_receipt_sha256": receipt_sha,
        "human_review_path": review_path, "human_review_sha256": tail["human_review_sha256"],
        "original_video_sha256": receipt["video_sha256"], "original_tail_sha256": tail["sha256"],
        "global_manifest_sha256": compiled["global_manifest_sha256"],
        "fixed_identity_sha256": shared.digest(fixed_identity_projection(compiled)),
        "explicit_user_tail_approval_verified": True, "actor_subject_mapping_declared_by_user": True,
        "assistant_pixel_identity_verified": False, "calls_authorized": False}


def _aware(value):
    if not isinstance(value, str):
        raise ValueError("trusted video timestamp missing")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("trusted video timestamps need timezone")
    return result.astimezone(timezone.utc)


def _trusted_video_assets(compiled, sources, authorization, now):
    if (not isinstance(authorization, dict) or authorization.get("mode") != "reference_video"
        or authorization.get("decision_source") != "explicit_user_statement"
        or not str(authorization.get("user_statement", "")).strip()
        or authorization.get("global_manifest_sha256") != compiled["global_manifest_sha256"]):
        raise ValueError("reference_video needs a separate explicit mode authorization; preview cannot grant it")
    assets = compiled["media_binding"]["assets"]
    if not isinstance(sources, list) or len(sources) != len(assets) or not 1 <= len(assets) <= 3:
        raise ValueError("trusted video originals and receipt bindings missing")
    results, total_duration = [], 0
    for asset, evidence in zip(assets, sources):
        if not isinstance(evidence, dict) or not all(key in evidence for key in (
                "generation_receipt_path", "generation_receipt_sha256", "input_url_expires_at")):
            raise ValueError("trusted video original receipt/time binding incomplete")
        receipt = _checked_json(evidence["generation_receipt_path"], evidence["generation_receipt_sha256"])
        policy = compiled["projection"]["provider_policy"]
        if (asset["kind"] != "video" or evidence.get("asset_id") != asset["asset_id"]
            or evidence.get("input_account_binding_sha256") != receipt.get("provider_account_binding_sha256")
            or not receipt.get("provider_account_binding_sha256")
            or not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("provider_account_binding_sha256", "")))
            or receipt.get("provider") != policy["provider_id"]
            or receipt.get("technical_status") != "succeeded"
            or receipt.get("video_sha256") != asset["sha256"]
            or _sha_file(receipt["video_path"]) != asset["sha256"]
            or receipt.get("final", {}).get("id") != receipt.get("task_id")
            or receipt.get("final", {}).get("status") != "succeeded"
            or receipt.get("final", {}).get("content", {}).get("video_url") != asset["path"]):
            raise ValueError("trusted video original/account/URL binding unknown or changed")
        if ark_model(receipt.get("model"))["family"] not in ("2.0", "2.5"):
            raise ValueError("original reference model has no documented trusted portrait route")
        created = _aware(receipt["completed_at"])
        if not 0 <= (now - created).total_seconds() <= 30 * 86400:
            raise ValueError("trusted original video outside same-account 30-day window")
        if _aware(evidence["input_url_expires_at"]) <= now:
            raise ValueError("original video URL expired; do not substitute edited media")
        duration = receipt.get("technical_metadata", {}).get("duration_seconds")
        if type(duration) not in (int, float) or not 2 <= duration <= 15:
            raise ValueError("trusted reference duration unknown or unsupported")
        total_duration += duration
        results.append({"asset_id": asset["asset_id"], "sha256": asset["sha256"],
            "reference_mode": compiled["media_binding"]["role"],
            "original_receipt_sha256": evidence["generation_receipt_sha256"]})
    if total_duration > 15:
        raise ValueError("trusted reference videos exceed 15-second total")
    return results


def validate_actual_request(compiled, payload, provider_id, *, original_tail_source=None,
        reference_mode_authorization=None, trusted_video_sources=None, now=None):
    """Derive coverage from actual content bytes/URLs, never supplied attachments."""
    if not isinstance(payload, dict):
        raise ValueError("actual provider payload must be an object")
    content = payload.get("content")
    if not isinstance(content, list) or any(not isinstance(row, dict) for row in content):
        raise ValueError("actual provider content must be a list")
    texts = [row for row in content if row.get("type") == "text"]
    refs = [row for row in content if row.get("type") != "text"]
    if len(texts) != 1 or not isinstance(texts[0].get("text"), str):
        raise ValueError("actual provider needs exactly one bound text input")
    roles = [row.get("role") for row in refs]
    if "first_frame" in roles and any(role != "first_frame" for role in roles):
        raise ValueError("first_frame and reference_video/multimodal references are mutually exclusive")
    mode = compiled["media_binding"]["role"]
    assets = compiled["media_binding"]["assets"]
    if len(refs) != len(assets):
        raise ValueError("actual reference count differs from bound originals")
    tail_proof = None
    if mode == "text_to_video_bootstrap":
        if not compiled["casting_bootstrap"] or refs or compiled["projection"]["dynamic_state"]["completed_source_refs"]:
            raise ValueError("bootstrap is only the new initial segment without references")
        attached = []
    elif mode == "first_frame":
        tail_proof = verify_original_tail_evidence(compiled, original_tail_source)
        attached = []
        for row, asset in zip(refs, assets):
            url = row.get("image_url", {}).get("url", "")
            if row.get("type") != "image_url" or row.get("role") != "first_frame" or not url.startswith("data:image/") or ";base64," not in url:
                raise ValueError("actual first_frame must contain the saved original image bytes")
            try:
                actual_sha = hashlib.sha256(base64.b64decode(url.split(",", 1)[1], validate=True)).hexdigest()
            except Exception as exc:
                raise ValueError("actual first_frame base64 malformed") from exc
            attached.append({"asset_id": asset["asset_id"], "sha256": actual_sha, "reference_mode": mode})
    elif mode == "trusted_generated_reference":
        if now is not None and (not isinstance(now, datetime) or now.tzinfo is None):
            raise ValueError("trusted video verification time must be timezone-aware")
        attached = _trusted_video_assets(compiled, trusted_video_sources, reference_mode_authorization,
            now or datetime.now(timezone.utc))
        for row, asset in zip(refs, assets):
            if row.get("type") != "video_url" or row.get("role") != "reference_video" or row.get("video_url", {}).get("url") != asset["path"]:
                raise ValueError("actual reference_video input differs from trusted original URL")
    else:
        raise ValueError("this v3 media route only supports bootstrap, approved tail or authorized original video")
    coverage = shared.validate_provider_request_coverage(compiled, texts[0]["text"], attached,
        provider_id, payload.get("model"))
    return {"schema": VERSION + "/actual_request_proof", **coverage,
        "actual_request_sha256": shared.digest(payload), "input_mode": mode,
        "original_tail_proof": tail_proof, "reference_video_mode_authorized": mode == "trusted_generated_reference",
        "bootstrap_visual_cast_approved": False if compiled["casting_bootstrap"] else None,
        "wire_content_verified": True, "media_status": "awaiting_human_review",
        "same_account_original_metadata_checked": mode == "trusted_generated_reference",
        "same_account_live_credentials_verified": False, "provider_trust_acceptance_verified": False,
        "new_paid_calls": 0, "calls_authorized": False, "budget_reset": False}


def compile_request_preview(compiled, prompt, duration, *, provider_id="ark_api", ratio="9:16",
        resolution="480p", seed=None, original_tail_source=None,
        reference_mode_authorization=None, trusted_video_sources=None, now=None):
    """Build through the real pure Seedance payload builder, then verify it."""
    policy = compiled["projection"]["provider_policy"]
    mode = compiled["media_binding"]["role"]
    refs = []
    for asset in compiled["media_binding"]["assets"]:
        if mode == "first_frame":
            encoded = base64.b64encode(Path(asset["path"]).read_bytes()).decode("ascii")
            refs.append(SeedanceReference("image", "data:image/png;base64," + encoded, "first_frame"))
        elif mode == "trusted_generated_reference":
            refs.append(SeedanceReference("video", asset["path"], "reference_video"))
        else:
            raise ValueError("unsupported bound media input mode")
    client = object.__new__(SeedanceClient)
    client.config = SeedanceConfig(api_key="offline-not-a-credential", base_url=ARK_BASE_URL,
        model=policy["model"], provider=provider_id)
    request = client.build_task_payload(prompt, duration=duration, ratio=ratio, resolution=resolution,
        generate_audio=True, return_last_frame=True, watermark=False, seed=seed, references=refs,
        task_type="text" if mode == "text_to_video_bootstrap" else "auto")
    proof = validate_actual_request(compiled, request, provider_id, original_tail_source=original_tail_source,
        reference_mode_authorization=reference_mode_authorization, trusted_video_sources=trusted_video_sources, now=now)
    return {"schema": VERSION + "/request_preview", "request": request, "proof": proof,
        "dispatched": False, "new_paid_calls": 0, "human_approved": False}


def verify_reviewed_request(actual_payload, reviewed_payload_or_preview, review_receipt, *,
        expected_reviewed_request_sha256, expected_review_receipt_sha256,
        expected_review_input, expected_checks):
    """Bind every actual wire parameter to the immutable full-review candidate.

    Expected digests/input/checks come from the calling runner's frozen binding,
    not from model suggestions or recomputed untrusted replacements. This gate
    proves request identity after a complete original tool review. It does not
    grant submission permission, inspect media or consume a new candidate.
    """
    if (not isinstance(reviewed_payload_or_preview, dict)
        or not isinstance(actual_payload, dict) or not isinstance(review_receipt, dict)
        or not isinstance(expected_review_input, dict)):
        raise ValueError("original reviewed request, receipt and full input bindings required")
    reviewed = reviewed_payload_or_preview.get("request", reviewed_payload_or_preview)
    if (not isinstance(reviewed, dict)
        or shared.digest(reviewed) != expected_reviewed_request_sha256
        or shared.digest(actual_payload) != expected_reviewed_request_sha256
        or actual_payload != reviewed):
        raise ValueError("actual provider request differs from the immutable full-reviewed request")
    if ("proof" in reviewed_payload_or_preview
        and (not isinstance(reviewed_payload_or_preview["proof"], dict)
            or reviewed_payload_or_preview["proof"].get("actual_request_sha256") != expected_reviewed_request_sha256)):
        raise ValueError("reviewed request preview proof changed")
    if shared.digest(review_receipt) != expected_review_receipt_sha256:
        raise ValueError("immutable original full-review receipt changed")
    evidence = production_loop.normalize_receipt(review_receipt)
    if not evidence["known_complete"] or evidence["status"] != "contract_valid":
        raise ValueError("original full review must be complete, have known usage and submit the required tool: "
            + ",".join(evidence["errors"]))
    request = evidence["request"]
    users = [row for row in request["messages"] if row.get("role") == "user"]
    if request.get("stage") != "whole_production_review" or request.get("role") != "director" or len(users) != 1:
        raise ValueError("original review is not the whole-production review stage")
    actual_input = evidence["actual_input"]
    required = {"full_current_script", "source_catalog", "shared_manifest", "whole_direction", "complete_compilation",
        "all_local_performances", "all_planned_video_prompts", "opening_actual_video_prompt", "opening_shared_projection",
        "opening_actual_provider_request", "reference_fulltext", "source_full_review_binding", "scope"}
    if (not required.issubset(actual_input)
        or actual_input != expected_review_input
        or actual_input["opening_actual_provider_request"] != reviewed
        or shared.digest(actual_input["opening_actual_provider_request"]) != expected_reviewed_request_sha256
        or not actual_input["full_current_script"] or not actual_input["complete_compilation"]
        or not actual_input["all_local_performances"]
        or not isinstance(actual_input["reference_fulltext"], str) or not actual_input["reference_fulltext"].strip()):
        raise ValueError("original full review did not receive the exact complete production and provider request")
    native = evidence["native_document"]
    schema = request.get("structured_schema")
    if not isinstance(schema, dict):
        raise ValueError("original full-review schema binding missing")
    try:
        Draft202012Validator(schema).validate(native)
    except ValidationError as exc:
        raise ValueError("original full-review document violates its schema") from exc
    checks = native.get("checks")
    expected_checks = list(expected_checks)
    if (not expected_checks or len(set(expected_checks)) != len(expected_checks)
        or not isinstance(checks, list)
        or [row.get("check") for row in checks] != expected_checks
        or any(row.get("status") != "pass" for row in checks)
        or native.get("revision_requirements") != []):
        raise ValueError("all original full-production checks must pass without unknown or revision")
    return {"schema": VERSION + "/reviewed_request_proof", "status": "reviewed_actual_request_binding_valid",
        "actual_request_sha256": expected_reviewed_request_sha256,
        "reviewed_request_sha256": expected_reviewed_request_sha256,
        "original_review_receipt_sha256": expected_review_receipt_sha256,
        "original_review_request_sha256": evidence["request_sha256"],
        "original_review_input_sha256": evidence["actual_input_sha256"],
        "original_review_ordinal": review_receipt.get("ordinal"),
        "original_full_review_tool_verified": True, "all_provider_parameters_equal_to_reviewed": True,
        "media_status_after_save": "awaiting_human_review", "actual_media_quality_passed": False,
        "same_account_live_credentials_verified": False, "calls_authorized": False,
        "new_paid_calls": 0, "budget_reset": False, "automatic_retry": False}
