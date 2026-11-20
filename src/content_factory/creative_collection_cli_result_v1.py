"""Read-only reconciliation of one metadata collector's saved failed result.

This does not resume a collection, promote observations or modify any evidence.
The complete CLI result must match its authoritative saved research log. Callers
provide the expected identity and workflow; the pre-call collection claim does
not itself contain the workflow id assigned later by the research process.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

VERSION = "creative_collection_cli_reconciliation/v1"


class CollectionResultReconcileError(ValueError):
    """A stable code without exposing logs, private URLs or credentials."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _reject(code):
    raise CollectionResultReconcileError(code)


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            _reject("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _constant(_):
    _reject("NONFINITE_JSON_VALUE")


def _decoder():
    return json.JSONDecoder(object_pairs_hook=_pairs, parse_constant=_constant)


def _json(raw):
    try:
        text = raw.decode("utf-8-sig")
        value, end = _decoder().raw_decode(text.lstrip())
        if text.lstrip()[end:].strip():
            _reject("TRAILING_JSON_CONTENT")
    except (UnicodeDecodeError, json.JSONDecodeError):
        _reject("INCOMPLETE_OR_INVALID_JSON")
    if not isinstance(value, dict):
        _reject("JSON_OBJECT_REQUIRED")
    return value


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def extract_terminal_research_json(stdout):
    """Allow plain log lines before exactly one complete terminal JSON object.

    Standalone structured log output, half JSON and non-whitespace suffixes are
    ambiguous and rejected. Nested objects inside the one result are not counted
    as extra documents. Inline structural braces in a log prefix are rejected
    conservatively rather than silently treating a second JSON as harmless log.
    """
    if not isinstance(stdout, str):
        _reject("STDOUT_TEXT_REQUIRED")
    text = stdout.lstrip("\ufeff")
    candidates = []
    end_of_previous = 0
    for match in re.finditer(r"(?m)^[ \t]*(?=[{\[])", text):
        start = match.end()
        if start < end_of_previous:
            continue
        try:
            value, end = _decoder().raw_decode(text, start)
        except json.JSONDecodeError:
            _reject("INCOMPLETE_OR_AMBIGUOUS_STDOUT_JSON")
        candidates.append((value, start, end))
        end_of_previous = end
    if not candidates:
        _reject("TERMINAL_RESEARCH_JSON_MISSING")
    if len(candidates) != 1:
        _reject("MULTIPLE_STDOUT_JSON_DOCUMENTS")
    value, start, end = candidates[0]
    if not isinstance(value, dict):
        _reject("RESEARCH_JSON_OBJECT_REQUIRED")
    if text[end:].strip():
        _reject("RESEARCH_JSON_NOT_TERMINAL")
    prefix = text[:start]
    if any(char in prefix for char in "{}[]"):
        _reject("AMBIGUOUS_STRUCTURED_LOG_PREFIX")
    for line in prefix.splitlines():
        if not line.strip():
            continue
        try:
            _, line_end = _decoder().raw_decode(line.lstrip())
        except json.JSONDecodeError:
            continue
        if not line.lstrip()[line_end:].strip():
            _reject("MULTIPLE_STDOUT_JSON_DOCUMENTS")
    return value


def _instant(value):
    if not isinstance(value, str) or not value.strip():
        _reject("INVALID_BOUND_TIMESTAMP")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _reject("INVALID_BOUND_TIMESTAMP")
    if result.tzinfo is None or result.utcoffset() is None:
        _reject("NAIVE_BOUND_TIMESTAMP")
    return result.astimezone(timezone.utc)


def _inside(path, project):
    result = Path(path)
    if not result.is_absolute():
        result = project / result
    result = result.resolve()
    if not result.is_relative_to(project):
        _reject("EVIDENCE_PATH_OUTSIDE_PROJECT")
    return result


def reconcile_collection_cli_result(*, project_root, collection_root,
                                    expected_account_key,
                                    expected_account_uuid,
                                    expected_profile_version,
                                    expected_public_id,
                                    expected_workflow_run_id,
                                    expected_claim_sha256=None,
                                    now=None, max_elapsed_seconds=3600):
    """Reconcile only a known failed/human-required result without side effects.

    Expected values come from trusted account/call evidence, never this stdout.
    ``expected_claim_sha256`` optionally pins a caller's previously recorded
    claim hash. Returned hashes bind the full files read; none are overwritten.
    Unknown, successful, truncated, multiple or contradictory results raise a
    ``CollectionResultReconcileError`` and cannot become accepted source data.
    """
    project = Path(project_root).resolve()
    root = _inside(collection_root, project)
    if type(expected_profile_version) is not int or expected_profile_version < 1:
        _reject("EXPECTED_PROFILE_VERSION_REQUIRED")
    if not all(isinstance(value, str) and value.strip() for value in (
            expected_account_key, expected_account_uuid, expected_public_id,
            expected_workflow_run_id)):
        _reject("EXPECTED_IDENTITY_REQUIRED")
    if not re.fullmatch(r"research:[0-9a-f]{32}", expected_workflow_run_id):
        _reject("EXPECTED_WORKFLOW_ID_INVALID")
    if type(max_elapsed_seconds) is not int or max_elapsed_seconds <= 0:
        _reject("BOUNDED_ATTEMPT_WINDOW_REQUIRED")

    files = {}

    def read(path):
        path = _inside(path, project)
        try:
            raw = path.read_bytes()
        except OSError:
            _reject("REQUIRED_EVIDENCE_UNAVAILABLE")
        files[path] = raw
        return raw

    claim_path = root / "COLLECTION_CLAIM.json"
    claim_raw = read(claim_path)
    claim_sha = hashlib.sha256(claim_raw).hexdigest()
    if expected_claim_sha256 is not None and claim_sha != expected_claim_sha256:
        _reject("COLLECTION_CLAIM_HASH_CHANGED")
    claim = _json(claim_raw)
    identity = _json(read(root / "LIVE_IDENTITY_CHECK.json"))
    try:
        stdout = read(root / "COLLECTION.stdout.log").decode("utf-8-sig")
    except UnicodeDecodeError:
        _reject("STDOUT_ENCODING_INVALID")
    result = extract_terminal_research_json(stdout)
    if (claim.get("account_key") != expected_account_key
            or any(claim.get(key) is not True for key in
                   ("metadata_only", "no_model_calls", "no_media_calls"))
            or claim.get("automatic_retry") is not False):
        _reject("COLLECTION_CLAIM_SCOPE_MISMATCH")
    if (identity.get("healthy") is not True or identity.get("status") != "active"
            or identity.get("account_key") != expected_account_key
            or type(identity.get("profile_version")) is not int
            or identity["profile_version"] != expected_profile_version
            or identity.get("expected_public_id") != expected_public_id
            or identity.get("actual_public_id") != expected_public_id):
        _reject("LIVE_ACCOUNT_IDENTITY_MISMATCH")
    if (result.get("workflow_run_id") != expected_workflow_run_id
            or result.get("account_uuid") != expected_account_uuid
            or result.get("account_key") != expected_account_key
            or type(result.get("profile_version")) is not int
            or result["profile_version"] != expected_profile_version):
        _reject("RESEARCH_WORKFLOW_IDENTITY_MISMATCH")

    log_path = result.get("log_path")
    if not isinstance(log_path, str) or not log_path:
        _reject("AUTHORITATIVE_LOG_PATH_REQUIRED")
    log = _inside(log_path, project)
    expected_log = (project / "data/trend_research_runs" /
                    (expected_workflow_run_id.replace(":", "_") + ".json")).resolve()
    if log != expected_log:
        _reject("AUTHORITATIVE_LOG_WORKFLOW_PATH_MISMATCH")
    authoritative = _json(read(log))
    if _canonical(authoritative) != _canonical(result):
        _reject("CLI_AUTHORITATIVE_RESULT_DIFFERENT")

    plan_path = claim.get("plan_path")
    if not isinstance(plan_path, str) or not plan_path:
        _reject("CLAIM_PLAN_PATH_REQUIRED")
    plan_path = _inside(plan_path, project)
    plan_raw = read(plan_path)
    plan_sha = hashlib.sha256(plan_raw).hexdigest()
    if plan_sha != claim.get("plan_sha256"):
        _reject("COLLECTION_PLAN_HASH_CHANGED")
    plan = _json(plan_raw)
    if (plan.get("schema") != "legal_core_topic_plan/v1"
            or plan.get("account_uuid") != expected_account_uuid
            or plan.get("account_key") != expected_account_key
            or type(plan.get("profile_version")) is not int
            or plan["profile_version"] != expected_profile_version):
        _reject("COLLECTION_PLAN_IDENTITY_MISMATCH")
    cli_plan = result.get("legal_core_plan")
    if not isinstance(cli_plan, dict):
        _reject("CLI_PLAN_BINDING_REQUIRED")
    expected_plan = {
        "path": str(plan_path), "file_sha256": plan_sha,
        "plan_id": plan.get("plan_id"), "core_tag": plan.get("core_tag"),
        "related_tags": plan.get("related_tags"),
        "estimated_pages": plan.get("estimated_pages"),
        "metadata_only": True, "script_generation_submitted": False,
    }
    if _canonical(cli_plan) != _canonical(expected_plan):
        _reject("CLI_PLAN_BINDING_DIFFERENT")
    if (not isinstance(plan.get("plan_id"), str) or not plan["plan_id"].strip()
            or not isinstance(plan.get("core_tag"), str) or not plan["core_tag"].strip()
            or not isinstance(plan.get("related_tags"), list)
            or not all(isinstance(tag, str) and tag.strip() for tag in plan["related_tags"])
            or type(plan.get("estimated_pages")) is not int or plan["estimated_pages"] < 1):
        _reject("COLLECTION_PLAN_FIELDS_INVALID")

    claimed = _instant(claim.get("at_utc"))
    identified = _instant(identity.get("at_utc"))
    started = _instant(result.get("started_at"))
    finished = _instant(result.get("finished_at"))
    observed = _instant(now) if isinstance(now, str) else now or datetime.now(timezone.utc)
    if not isinstance(observed, datetime) or observed.tzinfo is None:
        _reject("INVALID_RECONCILIATION_TIME")
    observed = observed.astimezone(timezone.utc)
    if not (claimed <= identified <= started <= finished <= observed):
        _reject("RESEARCH_ATTEMPT_TIME_MISMATCH")
    if (finished - claimed).total_seconds() > max_elapsed_seconds:
        _reject("RESEARCH_OUTSIDE_BOUND_ATTEMPT_WINDOW")

    if result.get("status") != "failed":
        _reject("ONLY_KNOWN_FAILED_RESULT_RECONCILABLE")
    reason = result.get("stopped_reason")
    if not isinstance(reason, str) or not reason.strip():
        _reject("KNOWN_FAILED_STOP_REASON_REQUIRED")
    counters = ("collected_observations", "unique_videos", "tag_relations",
                "tag_traffic_snapshots", "clusters", "briefs",
                "content_analyses", "opportunities")
    if any(type(result.get(key)) is not int or result[key] < 0 for key in counters):
        _reject("RESULT_COUNTS_INVALID")
    if not isinstance(result.get("video_records"), list):
        _reject("RESULT_VIDEO_RECORDS_REQUIRED")
    if (result.get("collection_run_id") == ""
            and (any(result[key] != 0 for key in counters) or result["video_records"])):
        _reject("EMPTY_COLLECTION_CONTRADICTS_DATA")
    if not isinstance(result.get("collection_run_id"), str):
        _reject("RESULT_COLLECTION_ID_REQUIRED")
    if reason == "human_required":
        stages = result.get("stages")
        if not isinstance(stages, list) or not any(
                isinstance(stage, dict) and stage.get("stage") == "trend_collection"
                and stage.get("status") == "failed"
                and stage.get("message") == "human_required" for stage in stages):
            _reject("HUMAN_REQUIRED_STAGE_NOT_CONFIRMED")

    # A concurrent writer cannot silently replace any input during reconciliation.
    try:
        if any(path.read_bytes() != raw for path, raw in files.items()):
            _reject("EVIDENCE_CHANGED_DURING_READ")
    except OSError:
        _reject("EVIDENCE_UNAVAILABLE_DURING_READ")
    return {
        "schema": VERSION,
        "status": "human_required" if reason == "human_required" else "failed",
        "observed_research_status": "failed", "reason": reason,
        "workflow_run_id": expected_workflow_run_id,
        "account_key": expected_account_key, "account_uuid": expected_account_uuid,
        "profile_version": expected_profile_version,
        "collection_run_id": result["collection_run_id"],
        "result": result, "authoritative_full_result_equal": True,
        "claim_sha256": claim_sha, "plan_sha256": plan_sha,
        "evidence_sha256": {str(path): hashlib.sha256(raw).hexdigest()
                            for path, raw in files.items()},
        "original_request_redispatched": False, "automatic_retry": False,
        "new_model_calls": 0, "new_media_calls": 0,
        "original_frozen_or_result_modified": False,
        "eligible_for_creative_source": False,
    }
