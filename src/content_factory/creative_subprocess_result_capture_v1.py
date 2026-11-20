"""Binary process capture and read-only durable result reconciliation.

Console text is diagnostic data, never a structured-result fallback. This
module has no model/browser client, retry loop, workflow resumer or state writer.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

CAPTURE_SCHEMA = "creative_subprocess_binary_capture/v1"
RECONCILIATION_SCHEMA = "creative_durable_process_reconciliation/v1"
TERMINAL_EXITS = {"completed": 0, "awaiting_media_analysis": 1, "blocked": 1, "failed": 1}


class ProcessResultError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _reject(code):
    raise ProcessResultError(code)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            _reject("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _strict_object(raw):
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs,
            parse_constant=lambda _: _reject("NONFINITE_JSON_VALUE"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _reject("DURABLE_JSON_INCOMPLETE_OR_INVALID")
    if not isinstance(value, dict):
        _reject("DURABLE_JSON_OBJECT_REQUIRED")
    def finite(item):
        if isinstance(item, float) and not math.isfinite(item):
            _reject("NONFINITE_JSON_VALUE")
        if isinstance(item, dict):
            for child in item.values(): finite(child)
        elif isinstance(item, list):
            for child in item: finite(child)
    finite(value)
    return value


def _load(path):
    try:
        raw = Path(path).read_bytes()
    except OSError:
        _reject("DURABLE_EVIDENCE_UNAVAILABLE")
    return _strict_object(raw), raw


def _save_json(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def decode_diagnostic_log(raw):
    """Display decoding records its evidence; its text has no acceptance role."""
    if not isinstance(raw, bytes):
        _reject("BINARY_LOG_BYTES_REQUIRED")
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return {"text": raw.decode(encoding), "encoding": encoding,
                "lossless_decode": True, "raw_sha256": _sha(raw), "structured_result_source": False}
        except UnicodeDecodeError:
            pass
    return {"text": raw.decode("utf-8", errors="replace"), "encoding": "utf-8-replacement",
        "lossless_decode": False, "raw_sha256": _sha(raw), "structured_result_source": False}


def run_binary_subprocess(command, *, cwd, artifact_root, dispatch_identity, timeout=None, runner=None):
    """One subprocess, bytes only, one capture claim before execution.

    ``dispatch_identity`` is caller-supplied non-secret binding metadata. The
    command itself is only hashed in artifacts. Timeout/error preserves any
    available raw partial bytes and rejects unknown completion; it never repeats.
    """
    if not isinstance(command, (list, tuple)) or not command or any(not isinstance(p, str) or not p for p in command):
        _reject("EXPLICIT_COMMAND_ARGUMENTS_REQUIRED")
    if not isinstance(dispatch_identity, dict) or not dispatch_identity:
        _reject("DISPATCH_IDENTITY_REQUIRED")
    root = Path(artifact_root).resolve()
    try:
        root.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        _reject("ORIGINAL_CAPTURE_EXISTS_NO_REDISPATCH")
    claim = {"schema": CAPTURE_SCHEMA, "at_utc": datetime.now(timezone.utc).isoformat(),
        "command_sha256": _sha(_canonical(list(command)).encode("utf-8")),
        "dispatch_identity_sha256": _sha(_canonical(dispatch_identity).encode("utf-8")),
        "cwd": str(Path(cwd).resolve()), "capture_mode": "bytes", "automatic_retry": False}
    _save_json(root / "PROCESS_CAPTURE_CLAIM.json", claim)
    try:
        result = (runner or subprocess.run)(list(command), cwd=cwd, capture_output=True,
            text=False, shell=False, check=False, timeout=timeout)
    except Exception as exc:
        streams = {}
        for label, raw in (("stdout", getattr(exc, "stdout", None)), ("stderr", getattr(exc, "stderr", None))):
            if isinstance(raw, bytes):
                with (root / ("PROCESS." + label + ".raw")).open("xb") as handle: handle.write(raw)
                streams[label] = {"available": True, "bytes": len(raw), "sha256": _sha(raw), "complete": False}
            else:
                streams[label] = {"available": False, "complete": False}
        _save_json(root / "PROCESS_CAPTURE_RESULT.json", {"schema": CAPTURE_SCHEMA,
            "process_completed": False, "observed_exit_code": None, "exception_type": type(exc).__name__,
            "streams": streams, "automatic_retry": False, "result_source": "unavailable"})
        _reject("PROCESS_COMPLETION_UNKNOWN")
    returncode, stdout, stderr = (getattr(result, key, None) for key in ("returncode", "stdout", "stderr"))
    if type(returncode) is not int or not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
        _save_json(root / "PROCESS_CAPTURE_RESULT.json", {"schema": CAPTURE_SCHEMA,
            "process_completed": False, "observed_exit_code": returncode if type(returncode) is int else None,
            "automatic_retry": False, "failure_code": "BINARY_PROCESS_RESULT_REQUIRED"})
        _reject("BINARY_PROCESS_RESULT_REQUIRED")
    streams = {}
    for label, raw in (("stdout", stdout), ("stderr", stderr)):
        path = root / ("PROCESS." + label + ".raw")
        with path.open("xb") as handle: handle.write(raw)
        decoded = decode_diagnostic_log(raw)
        with (root / ("PROCESS." + label + ".display.log")).open("x", encoding="utf-8") as handle:
            handle.write(decoded["text"])
        streams[label] = {"path": str(path), "bytes": len(raw), "sha256": _sha(raw), "complete": True,
            "display_encoding": decoded["encoding"], "lossless_decode": decoded["lossless_decode"]}
    manifest = {"schema": CAPTURE_SCHEMA, "process_completed": True, "observed_exit_code": returncode,
        "claim_sha256": _sha((root / "PROCESS_CAPTURE_CLAIM.json").read_bytes()), "streams": streams,
        "automatic_retry": False, "result_source": "durable_file_required"}
    _save_json(root / "PROCESS_CAPTURE_RESULT.json", manifest)
    return manifest


def _identity(actual, expected, code):
    if not isinstance(expected, dict) or not expected:
        _reject("EXPECTED_IDENTITY_REQUIRED")
    for key, value in expected.items():
        if key not in actual or _canonical(actual[key]) != _canonical(value):
            _reject(code)


def reconcile_durable_result(*, observed_exit_code, durable_result_path, authoritative_result_path,
                             expected_identity, identity_evidence_path=None, expected_evidence_identity=None):
    """Accept completion knowledge from exact durable evidence, never stdout.

    A known stop remains a stop. Even a completed envelope only permits further
    source validation; it does not grant creative approval or start any work.
    """
    if type(observed_exit_code) is not int:
        _reject("OBSERVED_EXIT_CODE_UNKNOWN_OR_INVALID")
    wrapper, wrapper_raw = _load(durable_result_path)
    payload = wrapper.get("result")
    if not isinstance(payload, dict):
        _reject("COMPLETE_DURABLE_RESULT_REQUIRED")
    status = wrapper.get("status")
    if status not in TERMINAL_EXITS or payload.get("status") != status:
        _reject("DURABLE_RESULT_UNKNOWN_OR_INCONSISTENT")
    if (type(wrapper.get("exit_code")) is not int or wrapper["exit_code"] != observed_exit_code
        or observed_exit_code != TERMINAL_EXITS[status]):
        _reject("PROCESS_DURABLE_EXIT_MISMATCH")
    if (wrapper.get("known_research_result") is not True or wrapper.get("authoritative_full_result_equal") is not True
        or wrapper.get("original_request_redispatched") is not False or wrapper.get("automatic_retry") is not False
        or any(type(wrapper.get(k)) is not int or wrapper[k] != 0 for k in ("new_model_calls", "new_media_calls"))):
        _reject("DURABLE_KNOWN_ZERO_MODEL_RESULT_REQUIRED")
    _identity(payload, expected_identity, "DURABLE_RESULT_IDENTITY_MISMATCH")
    authoritative, authoritative_raw = _load(authoritative_result_path)
    if (_canonical(authoritative) != _canonical(payload)
        or wrapper.get("authoritative_result_sha256") != _sha(authoritative_raw)):
        _reject("AUTHORITATIVE_COMPLETE_RESULT_MISMATCH")
    evidence_hashes = {str(Path(durable_result_path).resolve()): _sha(wrapper_raw),
        str(Path(authoritative_result_path).resolve()): _sha(authoritative_raw)}
    if identity_evidence_path is not None or expected_evidence_identity is not None:
        if identity_evidence_path is None or expected_evidence_identity is None:
            _reject("IDENTITY_EVIDENCE_PAIR_REQUIRED")
        identity, identity_raw = _load(identity_evidence_path)
        _identity(identity, expected_evidence_identity, "LIVE_IDENTITY_EVIDENCE_MISMATCH")
        evidence_hashes[str(Path(identity_evidence_path).resolve())] = _sha(identity_raw)
    stopped = status in {"blocked", "failed"}
    if stopped and (not isinstance(payload.get("stopped_reason"), str) or not payload["stopped_reason"].strip()
                    or wrapper.get("eligible_for_source_validation") is not False):
        _reject("KNOWN_STOP_REASON_OR_ELIGIBILITY_INVALID")
    # Check the actual file bytes again to reject an in-progress rewrite.
    for path, sha in evidence_hashes.items():
        if _sha(Path(path).read_bytes()) != sha:
            _reject("DURABLE_EVIDENCE_CHANGED_DURING_READ")
    return {"schema": RECONCILIATION_SCHEMA, "status": "known_collection_stop" if stopped else "durable_result_known",
        "observed_collection_status": status, "reason": payload.get("stopped_reason", ""),
        "observed_exit_code": observed_exit_code, "workflow_run_id": payload.get("workflow_run_id"),
        "known_complete_result": True, "creative_source_approved": False, "creative_quality_passed": False,
        "may_run_source_validation": not stopped, "automatic_redispatch": False,
        "evidence_sha256": evidence_hashes, "result": payload}


def reconcile_collection_durable_result(*, project_root, collection_root, observed_exit_code,
        expected_account_key, expected_account_uuid, expected_profile_version, expected_public_id,
        expected_workflow_run_id, expected_plan_path, expected_plan_sha256):
    """Collection adapter adds the established full native result/claim checks."""
    if (any(not isinstance(v, str) or not v for v in (expected_account_key, expected_account_uuid, expected_public_id))
        or type(expected_profile_version) is not int or expected_profile_version < 1
        or not isinstance(expected_workflow_run_id, str)
        or not re.fullmatch(r"research:[0-9a-f]{32}", expected_workflow_run_id)
        or not isinstance(expected_plan_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_plan_sha256)):
        _reject("EXPECTED_COLLECTION_BINDING_INVALID")
    project, root, plan_path = map(lambda p: Path(p).resolve(), (project_root, collection_root, expected_plan_path))
    if not root.is_relative_to(project) or not plan_path.is_relative_to(project):
        _reject("COLLECTION_EVIDENCE_OUTSIDE_PROJECT")
    wrapper, _ = _load(root / "COLLECTION_RESULT.json")
    authority = project / "data/trend_research_runs" / (expected_workflow_run_id.replace(":", "_") + ".json")
    result = reconcile_durable_result(observed_exit_code=observed_exit_code,
        durable_result_path=root / "COLLECTION_RESULT.json", authoritative_result_path=authority,
        expected_identity={"workflow_run_id": expected_workflow_run_id, "account_key": expected_account_key,
            "account_uuid": expected_account_uuid, "profile_version": expected_profile_version},
        identity_evidence_path=root / "LIVE_IDENTITY_CHECK.json", expected_evidence_identity={
            "healthy": True, "status": "active", "account_key": expected_account_key,
            "profile_version": expected_profile_version, "expected_public_id": expected_public_id,
            "actual_public_id": expected_public_id})
    claim, claim_raw = _load(root / "COLLECTION_CLAIM.json")
    plan, plan_raw = _load(plan_path)
    if _sha(plan_raw) != expected_plan_sha256 or wrapper.get("plan_sha256") != expected_plan_sha256:
        _reject("EXPECTED_PLAN_SHA_MISMATCH")
    identity, _ = _load(root / "LIVE_IDENTITY_CHECK.json")
    from scripts.run_fresh_legal_collection_local_recovery_v1 import validate_result
    native_validation = validate_result(stdout=(root / "COLLECTION.stdout.log").read_text(encoding="utf-8-sig"),
        native_result=wrapper["result"], claim=claim, identity=identity, plan_path=plan_path, plan=plan,
        plan_sha=expected_plan_sha256, expected_account_uuid=expected_account_uuid)
    result["full_native_collection_validation"] = native_validation
    result["evidence_sha256"].update({str(root / "COLLECTION_CLAIM.json"): _sha(claim_raw),
        str(plan_path): _sha(plan_raw), str(root / "COLLECTION.stdout.log"): _sha((root / "COLLECTION.stdout.log").read_bytes())})
    return result
