"""Compile explicit original-asset bindings into actual reference payloads.

This is a pure local gate: it performs no network request, media inspection,
approval recording or generation.  File hashes and supplied original service /
read-only GET records establish metadata correspondence, never visual identity
or provider input acceptance.  ``verified=True`` is not evidence.

The outer binding contract extends (and does not mutate) the frozen v1 manifest.
Each asset has original receipt + approval file bindings and declared subjects.
Roles and content ordering are explicit; the compiler never changes input mode.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

VERSION = "creative_reference_compiler/v4"
BINDING_SCHEMA = "creative_reference_binding/v4"
_KINDS = {"image": "image_url", "video": "video_url", "audio": "audio_url"}
_ROLES = {"image": {"first_frame", "last_frame", "reference_image"},
          "video": {"reference_video"}, "audio": {"reference_audio"}}
_SHA = re.compile(r"[0-9a-f]{64}")


class ReferenceCompilerError(ValueError):
    """A deterministic local binding error, not an unknown service result."""

    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def _fail(code: str, detail: str):
    raise ReferenceCompilerError(code, detail)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _time(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            _fail("EVIDENCE_TIME_INVALID", label)
    else:
        _fail("EVIDENCE_TIME_INVALID", label)
    if result.tzinfo is None:
        _fail("EVIDENCE_TIME_INVALID", label + " requires timezone")
    return result.astimezone(timezone.utc)


def _file(path: Any, expected_sha: Any, label: str) -> bytes:
    if not isinstance(path, str) or not isinstance(expected_sha, str) or not _SHA.fullmatch(expected_sha):
        _fail("ORIGINAL_EVIDENCE_MISSING", label)
    try:
        data = Path(path).read_bytes()
    except (OSError, ValueError):
        _fail("ORIGINAL_EVIDENCE_MISSING", label)
    if not data or hashlib.sha256(data).hexdigest() != expected_sha:
        _fail("ORIGINAL_BYTES_CHANGED", label)
    return data


def _json_file(binding: Any, label: str) -> dict:
    if not isinstance(binding, dict):
        _fail("ORIGINAL_EVIDENCE_MISSING", label)
    try:
        result = json.loads(_file(binding.get("path"), binding.get("sha256"), label))
    except (UnicodeError, json.JSONDecodeError):
        _fail("ORIGINAL_EVIDENCE_INVALID", label)
    if not isinstance(result, dict):
        _fail("ORIGINAL_EVIDENCE_INVALID", label)
    return result


def _unique(rows: Any, key: str, label: str) -> dict:
    if not isinstance(rows, list) or any(not isinstance(row, dict)
            or not isinstance(row.get(key), str) or not row[key] for row in rows):
        _fail("BINDING_CONTRACT_INVALID", label)
    found = {row[key]: row for row in rows}
    if len(found) != len(rows):
        _fail("BINDING_CONTRACT_INVALID", label + " contains duplicates")
    return found


def _subjects(asset: dict) -> dict:
    found = _unique(asset.get("subjects"), "subject_key", "asset subjects")
    if not found:
        _fail("SUBJECT_MAPPING_INVALID", "selected original needs at least one explicit subject")
    for row in found.values():
        if (row.get("entity_type") not in {"actor", "scene", "voice"}
            or not isinstance(row.get("entity_id"), str) or not row["entity_id"]
            or not isinstance(row.get("description"), str) or not row["description"].strip()):
            _fail("SUBJECT_MAPPING_INVALID", asset["asset_id"])
        if row["entity_type"] in {"actor", "scene"} and asset.get("kind") not in {"image", "video"}:
            _fail("VISUAL_SUBJECT_INPUT_INVALID", "actor/scene need image/video subjects")
        if row["entity_type"] == "voice" and asset.get("kind") != "audio":
            _fail("VOICE_INPUT_UNBOUND", "a named voice subject needs independent audio input")
    return found


def _mime(asset: dict, data: bytes) -> str:
    mime = asset.get("mime_type")
    if asset["kind"] == "image":
        signatures = {"image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/jpeg": data.startswith(b"\xff\xd8\xff"),
            "image/webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP"}
        if mime not in signatures or not signatures[mime]:
            _fail("IMAGE_BYTES_INVALID", asset["asset_id"])
    elif not isinstance(mime, str) or not mime.startswith(asset["kind"] + "/"):
        _fail("ASSET_MIME_INVALID", asset["asset_id"])
    return mime


def _native_get(asset: dict, receipt: dict, contract: dict, now: datetime,
                expected_account: str | None, get_evidence: dict | None) -> dict:
    """Check supplied original GET records without pretending to contact Ark."""
    if not isinstance(expected_account, str) or not _SHA.fullmatch(expected_account):
        _fail("NATIVE_ACCOUNT_UNKNOWN", asset["asset_id"])
    if (contract.get("input_account_binding_sha256") != expected_account
        or receipt.get("provider_account_binding_sha256") != expected_account
        or receipt.get("provider_id") != contract["provider_id"]):
        _fail("NATIVE_ACCOUNT_MISMATCH", asset["asset_id"])
    if not isinstance(get_evidence, dict) or asset["asset_id"] not in get_evidence:
        _fail("NATIVE_GET_EVIDENCE_MISSING", asset["asset_id"])
    evidence = get_evidence[asset["asset_id"]]
    if (not isinstance(evidence, dict) or evidence.get("method") != "GET"
        or evidence.get("http_status") != 200
        or evidence.get("requested_task_id") != receipt["task_id"]
        or evidence.get("provider_id") != contract["provider_id"]
        or evidence.get("account_binding_sha256") != expected_account):
        _fail("NATIVE_GET_EVIDENCE_INVALID", asset["asset_id"])
    received = _time(evidence.get("received_at"), "original GET time")
    if not 0 <= (now - received).total_seconds() <= 86400:
        _fail("NATIVE_GET_EVIDENCE_STALE", asset["asset_id"])
    body = _json_file(evidence.get("response_body"), "original GET raw body")
    if body.get("id") != receipt["task_id"] or body.get("status") != "succeeded":
        _fail("NATIVE_GET_TASK_MISMATCH", asset["asset_id"])
    if body.get("model", receipt.get("model")) != receipt.get("model"):
        _fail("NATIVE_GET_TASK_MISMATCH", asset["asset_id"])
    created = body.get("created_at")
    if (type(created) not in {int, float} or not math.isfinite(created) or created < 0
        or receipt.get("service_result", {}).get("created_at") != created):
        _fail("NATIVE_ORIGIN_TIME_UNKNOWN", "original service / GET creation timestamp required")
    try:
        created_at = datetime.fromtimestamp(created, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        _fail("NATIVE_ORIGIN_TIME_UNKNOWN", asset["asset_id"])
    # Task creation is a conservative origin-window boundary. Local completed_at
    # cannot renew the original output's 30-day qualification.
    if not 0 <= (now - created_at).total_seconds() <= 30 * 86400:
        _fail("NATIVE_WINDOW_EXPIRED", asset["asset_id"])
    return {"body": body, "raw_body_sha256": evidence["response_body"]["sha256"],
        "account_binding_sha256": expected_account,
        "original_service_created_at": created_at.isoformat(),
        "metadata_qualification": "locally_bound_original_get",
        "provider_input_acceptance": "unknown"}


def _original(asset: dict, contract: dict, now: datetime, expected_account=None,
              get_evidence=None, expected_continuation=None) -> dict:
    kind = asset.get("kind")
    if kind not in _KINDS or asset.get("role") not in _ROLES[kind]:
        _fail("ASSET_ROLE_INVALID", str(asset.get("asset_id")))
    data = _file(asset.get("local_path"), asset.get("sha256"), "original asset")
    mime = _mime(asset, data)
    origin = asset.get("original")
    receipt = _json_file(origin, "original generation receipt")
    task_id = origin.get("task_id")
    artifact_key = origin.get("artifact_key")
    artifact = receipt.get("artifacts", {}).get(artifact_key, {})
    original_result = receipt.get("service_result", {})
    if (not task_id or receipt.get("task_id") != task_id
        or not isinstance(origin.get("provider_id"), str) or not origin["provider_id"]
        or receipt.get("provider_id") != origin["provider_id"]
        or receipt.get("status") != "succeeded"
        or receipt.get("source") != "generation_service_original"
        or original_result.get("id") != task_id or original_result.get("status") != "succeeded"
        or artifact.get("path") != asset["local_path"] or artifact.get("sha256") != asset["sha256"]
        or artifact.get("kind") != kind or artifact.get("mime_type") != mime):
        _fail("ORIGINAL_TASK_BINDING_INVALID", asset["asset_id"])
    content_key = artifact.get("service_content_key")
    original_url = original_result.get("content", {}).get(content_key)
    if not isinstance(original_url, str) or not original_url:
        _fail("ORIGINAL_SERVICE_RESULT_MISSING", asset["asset_id"])
    if asset["role"] == "first_frame" and (artifact_key != "last_frame"
        or content_key != "last_frame_url"):
        _fail("FIRST_FRAME_NOT_ORIGINAL_TAIL", asset["asset_id"])
    continuation = contract.get("continuation")
    if asset["role"] == "first_frame":
        # Current source / identity / source prefix comes from the caller's
        # independently frozen current program state, not from old evidence.
        if not isinstance(expected_continuation, dict):
            _fail("CURRENT_CONTINUATION_BINDING_UNKNOWN", "independent current source/state binding required")
        if continuation != expected_continuation:
            _fail("CURRENT_CONTINUATION_BINDING_MISMATCH", "old original cannot substitute for current source/state")
        if (not isinstance(continuation, dict) or continuation.get("previous_task_id") != task_id
            or not _SHA.fullmatch(str(continuation.get("script_sha256", "")))
            or not _SHA.fullmatch(str(continuation.get("fixed_identity_sha256", "")))
            or not isinstance(continuation.get("completed_source_refs"), list)
            or not continuation["completed_source_refs"]
            or receipt.get("continuation_binding") != continuation):
            _fail("CONTINUATION_SOURCE_BINDING_INVALID", asset["asset_id"])
    subjects = _subjects(asset)
    approval = _json_file(asset.get("approval"), "explicit user approval")
    mapped = approval.get("subject_mappings")
    expected_mapped = [{key: row[key] for key in ("subject_key", "entity_type", "entity_id", "description")}
        for row in asset["subjects"]]
    if (approval.get("decision") != "approved"
        or approval.get("decision_source") != "explicit_user_statement"
        or not isinstance(approval.get("user_statement"), str) or not approval["user_statement"].strip()
        or approval.get("asset_id") != asset["asset_id"]
        or approval.get("asset_sha256") != asset["sha256"]
        or approval.get("original_task_id") != task_id
        or approval.get("original_receipt_sha256") != origin["sha256"]
        or (asset["role"] == "first_frame" and approval.get("continuation_binding") != continuation)
        or mapped != expected_mapped):
        _fail("EXPLICIT_APPROVAL_INVALID", asset["asset_id"])
    eligibility = asset.get("eligibility")
    if not isinstance(eligibility, dict) or eligibility.get("route") not in {"non_portrait", "native_generated_portrait"}:
        _fail("ASSET_ELIGIBILITY_UNKNOWN", asset["asset_id"])
    native = None
    if eligibility["route"] == "non_portrait" and any(row["entity_type"] == "actor" for row in subjects.values()):
        _fail("PORTRAIT_ELIGIBILITY_UNKNOWN", asset["asset_id"])
    if eligibility["route"] == "native_generated_portrait":
        # Only exact already-registered Seedance originals are wired here.
        # Documented Seedream origins need a separate exact-model registry /
        # receipt adapter; a name-prefix guess cannot establish their trust.
        from .seedance_models import ark_model
        try:
            allowed = ark_model(receipt.get("model"))["family"] in {"2.0", "2.5"} \
                and (kind != "image" or artifact_key == "last_frame")
        except ValueError:
            allowed = False
        if not allowed:
            _fail("NATIVE_MODEL_UNSUPPORTED", asset["asset_id"])
        native = _native_get(asset, receipt, contract, now, expected_account, get_evidence)
    input_url = asset.get("input_url")
    if kind in {"video", "audio"}:
        if not isinstance(input_url, str) or not input_url.startswith(("https://", "asset://")):
            _fail("INPUT_URL_INVALID", asset["asset_id"])
        # A URL may be renewed by an original task GET, never by a filename guess.
        resolved_url = native["body"].get("content", {}).get(content_key) if native else original_url
        if input_url != resolved_url:
            _fail("INPUT_URL_TASK_MISMATCH", asset["asset_id"])
        if input_url.startswith("https://") and _time(eligibility.get("input_url_expires_at"),
                "reference URL expiry") <= now:
            _fail("INPUT_URL_EXPIRED", asset["asset_id"])
    duration = artifact.get("duration_seconds")
    if kind in {"video", "audio"} and (type(duration) not in (int, float)
        or not math.isfinite(duration) or duration <= 0):
        _fail("REFERENCE_DURATION_UNKNOWN", asset["asset_id"])
    return {"data": data, "mime_type": mime, "receipt_sha256": origin["sha256"],
        "approval_sha256": asset["approval"]["sha256"], "original_task_id": task_id,
        "subjects": subjects, "duration_seconds": duration, "native": native}


def _contract(binding: dict) -> dict:
    if (not isinstance(binding, dict) or binding.get("schema") != BINDING_SCHEMA
        or binding.get("mode") not in {"first_frame", "multimodal_reference"}
        or not isinstance(binding.get("provider_id"), str) or not binding["provider_id"]
        or not isinstance(binding.get("model"), str) or not binding["model"]):
        _fail("BINDING_CONTRACT_INVALID", "schema/provider/model/mode")
    assets = _unique(binding.get("assets"), "asset_id", "reference assets")
    if not assets:
        _fail("BINDING_CONTRACT_INVALID", "explicit reference mode needs assets")
    roles = [asset.get("role") for asset in assets.values()]
    if binding["mode"] == "first_frame":
        if len(roles) != 1 or roles != ["first_frame"]:
            _fail("FRAME_REFERENCE_MODE_MIXED", "formal continuation requires exactly one original first frame")
    elif any(role in {"first_frame", "last_frame"} for role in roles):
        _fail("FRAME_REFERENCE_MODE_MIXED", "multimodal references cannot become formal frame inputs")
    _unique(binding.get("entity_bindings"), "binding_id", "entity bindings")
    _required_entities(binding.get("required_entities"))
    return assets


def _required_entities(rows: Any) -> set:
    if not isinstance(rows, list) or not rows:
        _fail("REQUIRED_ENTITIES_MISSING", "this selection needs explicit required actor/scene/voice ids")
    values = set()
    for row in rows:
        if (not isinstance(row, dict) or row.get("entity_type") not in {"actor", "scene", "voice"}
            or not isinstance(row.get("entity_id"), str) or not row["entity_id"]):
            _fail("REQUIRED_ENTITIES_MISSING", "invalid required entity")
        value = (row["entity_type"], row["entity_id"])
        if value in values:
            _fail("REQUIRED_ENTITIES_MISSING", "duplicate required entity")
        values.add(value)
    return values


def _entity_map(binding: dict, assets: dict, originals: dict, numbered: dict) -> tuple[list, list]:
    mapped, used, entity_keys = [], set(), set()
    for row in binding["entity_bindings"]:
        kind, eid = row.get("entity_type"), row.get("entity_id")
        aid, skey = row.get("asset_id"), row.get("subject_key")
        if aid not in assets or skey not in originals[aid]["subjects"]:
            _fail("SUBJECT_MAPPING_INVALID", str(row.get("binding_id")))
        subject = originals[aid]["subjects"][skey]
        if subject["entity_type"] != kind or subject["entity_id"] != eid:
            _fail("SUBJECT_MAPPING_INVALID", str(row.get("binding_id")))
        key = (kind, eid, aid, skey)
        if key in used:
            _fail("SUBJECT_MAPPING_DUPLICATE", str(key))
        used.add(key)
        entity_keys.add((kind, eid))
        if kind == "voice" and assets[aid]["kind"] != "audio":
            _fail("VOICE_INPUT_UNBOUND", "voice needs an actual independent reference_audio")
        if kind in {"actor", "scene"} and assets[aid]["kind"] not in {"image", "video"}:
            _fail("VISUAL_SUBJECT_INPUT_INVALID", "actor/scene need actual image or video reference inputs")
        mapped.append({"binding_id": row["binding_id"], "entity_type": kind, "entity_id": eid,
            "asset_id": aid, "subject_key": skey, "subject_description": subject["description"],
            **numbered[aid]})
    # Bound voices must refer to an actual attached audio subject, never a name / claim.
    voices = binding.get("voices", [])
    if not isinstance(voices, list):
        _fail("VOICE_INPUT_UNBOUND", "voice statuses must be a list")
    statuses = []
    seen = set()
    for voice in voices:
        if not isinstance(voice, dict) or not voice.get("actor_id") or voice["actor_id"] in seen:
            _fail("VOICE_INPUT_UNBOUND", "voice actor missing or duplicated")
        seen.add(voice["actor_id"])
        status = voice.get("status")
        matches = [row for row in mapped if row["entity_type"] == "voice"
            and row["entity_id"] == voice["actor_id"]]
        if status == "bound":
            if len(matches) != 1 or voice.get("binding_id") != matches[0]["binding_id"]:
                _fail("VOICE_INPUT_UNBOUND", voice["actor_id"])
        elif status in {"unbound", "unknown"}:
            if matches or voice.get("binding_id") is not None or not str(voice.get("reason", "")).strip():
                _fail("VOICE_INPUT_UNBOUND", voice["actor_id"])
        else:
            _fail("VOICE_INPUT_UNBOUND", voice["actor_id"])
        statuses.append(deepcopy(voice))
    voice_entities = {row["entity_id"] for row in mapped if row["entity_type"] == "voice"}
    if not voice_entities <= seen:
        _fail("VOICE_INPUT_UNBOUND", "attached voice mappings need explicit status")
    for actor in {eid for kind, eid in entity_keys if kind == "actor"} - seen:
        statuses.append({"actor_id": actor, "status": "unbound", "binding_id": None,
            "reason": "No actual reference_audio is attached; cross-segment voice identity is unbound."})
    if {row["asset_id"] for row in mapped} != set(assets):
        _fail("UNMAPPED_REFERENCE_ASSET", "each selected asset needs an explicit subject purpose")
    missing = _required_entities(binding.get("required_entities")) - entity_keys
    if missing:
        _fail("REQUIRED_ENTITY_BINDING_MISSING", str(sorted(missing)))
    return mapped, sorted(statuses, key=lambda row: row["actor_id"])


def _asset_content(asset: dict, original: dict) -> dict:
    kind = asset["kind"]
    url = ("data:" + original["mime_type"] + ";base64," + base64.b64encode(original["data"]).decode("ascii")) \
        if kind == "image" else asset["input_url"]
    return {"type": _KINDS[kind], _KINDS[kind]: {"url": url}, "role": asset["role"]}


def render_reference_mapping(mapped: list, voices: list) -> str:
    """The exact deterministic identity/material suffix sent with the action."""
    return "\n素材与主体绑定（编号由实际输入顺序生成）：\n" + json.dumps(
        {"entity_asset_mapping": mapped, "voice_bindings": voices}, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"))


def _coverage(payload: dict, binding: dict, *, now, expected_account_binding_sha256=None,
              provider_get_evidence=None, expected_continuation=None) -> dict:
    assets = _contract(binding)
    now = _time(now, "verification time")
    if not isinstance(payload, dict) or payload.get("model") != binding["model"]:
        _fail("ACTUAL_MODEL_MISMATCH", "actual payload model differs")
    content = payload.get("content")
    if not isinstance(content, list) or any(not isinstance(row, dict) for row in content):
        _fail("ACTUAL_CONTENT_INVALID", "content list")
    texts = [row for row in content if row.get("type") == "text"]
    if len(texts) != 1 or not isinstance(texts[0].get("text"), str) or not texts[0]["text"].strip():
        _fail("ACTUAL_CONTENT_INVALID", "exactly one nonempty narrative text required")
    refs = [(index, row) for index, row in enumerate(content) if row.get("type") != "text"]
    if len(refs) != len(assets):
        _fail("ACTUAL_REFERENCE_COUNT_MISMATCH", "actual inputs differ from original bindings")
    originals, rows, numbered, counters = {}, [], {}, {kind: 0 for kind in _KINDS}
    # Asset declaration order is the intended actual wire order, never sorted by id.
    for (index, actual), asset in zip(refs, assets.values()):
        aid, kind = asset["asset_id"], asset["kind"]
        original = _original(asset, binding, now, expected_account_binding_sha256,
            provider_get_evidence, expected_continuation)
        originals[aid] = original
        expected = _asset_content(asset, original)
        if actual != expected:
            _fail("ACTUAL_REFERENCE_BINDING_MISMATCH", aid + " actual bytes/URL/role/order differ")
        counters[kind] += 1
        numbered[aid] = {"content_index": index, "reference_number": counters[kind],
            "reference_label": kind + str(counters[kind])}
        rows.append({"asset_id": aid, "kind": kind, "role": asset["role"],
            **numbered[aid], "sha256": asset["sha256"],
            "original_task_id": original["original_task_id"],
            "original_receipt_sha256": original["receipt_sha256"],
            "explicit_user_approval_sha256": original["approval_sha256"],
            "duration_seconds": original["duration_seconds"],
            "native_metadata_qualification": original["native"]["metadata_qualification"] if original["native"] else "not_applicable",
            "original_get_body_sha256": original["native"]["raw_body_sha256"] if original["native"] else None,
            "original_service_created_at": original["native"]["original_service_created_at"] if original["native"] else None,
            "provider_input_acceptance": "unknown"})
    mapped, voices = _entity_map(binding, assets, originals, numbered)
    suffix = render_reference_mapping(mapped, voices)
    if not texts[0]["text"].endswith(suffix):
        _fail("ACTUAL_PROMPT_MAPPING_MISSING", "actual prompt lacks its exact derived subject/material mapping")
    narrative = texts[0]["text"][:-len(suffix)]
    if hashlib.sha256(narrative.encode("utf-8")).hexdigest() != binding.get("narrative_text_sha256"):
        _fail("ACTUAL_NARRATIVE_CHANGED", "source narrative text differs from its frozen binding")
    # Imported lazily so this pure module can be used independently in preview work.
    from .creative_provider_preflight_v1 import preflight_media_request
    preflight = preflight_media_request(payload, provider_id=binding["provider_id"],
        reference_metadata=[{"content_index": row["content_index"], "duration_seconds": row["duration_seconds"]}
            for row in rows])
    if preflight.get("blocked"):
        _fail("PROVIDER_PREFLIGHT_INCOMPLETE", "actual provider capabilities / metadata are incomplete")
    return {"schema": VERSION + "/coverage", "input_mode": binding["mode"],
        "actual_payload_sha256": digest(payload), "binding_contract_sha256": digest(binding),
        "independent_current_continuation_sha256": digest(expected_continuation) if binding["mode"] == "first_frame" else None,
        "ordered_references": rows, "entity_asset_mapping": mapped, "voice_bindings": voices,
        "mapping_sha256": digest(mapped), "required_entities": deepcopy(binding["required_entities"]),
        "provider_preflight": preflight,
        "preserved_narrative_text_sha256": binding["narrative_text_sha256"],
        "actual_prompt_sha256": hashlib.sha256(texts[0]["text"].encode("utf-8")).hexdigest(),
        "original_bytes_checked": True, "explicit_user_approval_evidence_checked": True,
        "assistant_pixel_identity_verified": False, "voice_identity_guaranteed": False,
        "provider_input_acceptance": "unknown", "calls_authorized": False,
        "production_adopted": False, "new_paid_calls": 0,
        "media_status_after_save": "awaiting_human_review"}


def compile_reference_request(payload: dict, binding_contract: dict, *, now,
        expected_account_binding_sha256=None, provider_get_evidence=None,
        expected_continuation=None) -> dict:
    """Append actual reference inputs to a narrative-only payload, explicitly.

    An already attached payload is not silently reordered / reinterpreted.  Use
    ``validate_actual_reference_request`` to check an adapter's actual payload.
    Caller-owned creation fields, model and original text remain unchanged.
    ``expected_continuation`` for formal first_frame must come from independently
    frozen CURRENT program state, not by copying the asset's old continuation.
    Original source / reference text is preserved as the exact prefix; the only
    added text is the program-derived material/subject mapping suffix.
    """
    assets = _contract(binding_contract)
    actual = deepcopy(payload)
    if not isinstance(actual, dict) or not isinstance(actual.get("content"), list) \
        or any(not isinstance(row, dict) or row.get("type") != "text" for row in actual["content"]):
        _fail("ACTUAL_CONTENT_INVALID", "compiler requires text-only input; no silent reference replacement")
    originals, numbered, counters = {}, {}, {kind: 0 for kind in _KINDS}
    for asset in assets.values():
        original = _original(asset, binding_contract, _time(now, "verification time"),
            expected_account_binding_sha256, provider_get_evidence, expected_continuation)
        originals[asset["asset_id"]] = original
        counters[asset["kind"]] += 1
        numbered[asset["asset_id"]] = {"content_index": len(actual["content"]),
            "reference_number": counters[asset["kind"]],
            "reference_label": asset["kind"] + str(counters[asset["kind"]])}
        actual["content"].append(_asset_content(asset, original))
    texts = [row for row in actual["content"] if row.get("type") == "text"]
    if len(texts) != 1 or not isinstance(texts[0].get("text"), str):
        _fail("ACTUAL_CONTENT_INVALID", "one narrative text required")
    if hashlib.sha256(texts[0]["text"].encode("utf-8")).hexdigest() != binding_contract.get("narrative_text_sha256"):
        _fail("ACTUAL_NARRATIVE_CHANGED", "original narrative source hash missing or changed")
    mapped, voices = _entity_map(binding_contract, assets, originals, numbered)
    texts[0]["text"] += render_reference_mapping(mapped, voices)
    coverage = _coverage(actual, binding_contract, now=now,
        expected_account_binding_sha256=expected_account_binding_sha256,
        provider_get_evidence=provider_get_evidence, expected_continuation=expected_continuation)
    return {"payload": actual, "coverage": coverage, "calls_authorized": False,
        "new_paid_calls": 0, "production_adopted": False}


def validate_actual_reference_request(payload: dict, binding_contract: dict, *, now,
        expected_account_binding_sha256=None, provider_get_evidence=None,
        expected_continuation=None) -> dict:
    """Re-derive actual coverage and independent current-state match; no mutation."""
    return _coverage(payload, binding_contract, now=now,
        expected_account_binding_sha256=expected_account_binding_sha256,
        provider_get_evidence=provider_get_evidence, expected_continuation=expected_continuation)


def build_director_visual_messages(messages: list, binding_contract: dict,
        selected_asset_ids: list[str], *, now, expected_account_binding_sha256=None,
        provider_get_evidence=None, required_entities=None, expected_continuation=None) -> dict:
    """Append approved independent image_url inputs, keeping original full text.

    This gives the director actual image bytes rather than filenames.  It does
    not replace source / reference text, infer image subjects, approve images,
    turn a multi-view board into independent images, or submit to MiniMax.
    """
    if not isinstance(messages, list) or not messages or any(not isinstance(row, dict) for row in messages):
        _fail("DIRECTOR_MESSAGES_INVALID", "nonempty original messages required")
    assets = _contract(binding_contract)
    if (not isinstance(selected_asset_ids, list) or not selected_asset_ids
        or len(set(selected_asset_ids)) != len(selected_asset_ids)
        or any(aid not in assets for aid in selected_asset_ids)):
        _fail("DIRECTOR_SELECTION_INVALID", "select unique bound original images")
    chosen, originals, rows, numbered = {}, {}, [], {}
    for number, aid in enumerate(selected_asset_ids, 1):
        asset = assets[aid]
        if asset["kind"] != "image" or asset.get("independent_image") is not True:
            _fail("DIRECTOR_SELECTION_INVALID", "director inputs require declared independent images")
        original = _original(asset, binding_contract, _time(now, "verification time"),
            expected_account_binding_sha256, provider_get_evidence, expected_continuation)
        chosen[aid], originals[aid] = asset, original
        numbered[aid] = {"content_index": number, "reference_number": number,
            "reference_label": "image" + str(number)}
        rows.append({"asset_id": aid, "sha256": asset["sha256"], **numbered[aid],
            "original_task_id": original["original_task_id"],
            "original_receipt_sha256": original["receipt_sha256"],
            "explicit_user_approval_sha256": original["approval_sha256"]})
    selected_contract = deepcopy(binding_contract)
    selected_contract["entity_bindings"] = [row for row in binding_contract["entity_bindings"]
        if row.get("asset_id") in chosen]
    # Voice evidence is carried in source text; pictures alone never bind voices.
    selected_contract["voices"] = []
    selected_contract["required_entities"] = deepcopy(required_entities) if required_entities is not None else [
        row for row in binding_contract["required_entities"] if row["entity_type"] in {"actor", "scene"}]
    mapped, _ = _entity_map(selected_contract, chosen, originals, numbered)
    text = "已批准的独立图片，按本消息实际输入顺序对应下列主体；请据实际图片调整导演安排，保留完整正文与参考全文：\n" \
        + json.dumps(mapped, ensure_ascii=False, sort_keys=True)
    content = [{"type": "text", "text": text}]
    for aid in selected_asset_ids:
        reference = _asset_content(chosen[aid], originals[aid])
        content.append({"type": "image_url", "image_url": reference["image_url"]})
    actual = deepcopy(messages)
    actual.append({"role": "user", "content": content})
    return {"messages": actual, "coverage": {
        "schema": VERSION + "/director_visual_coverage",
        "original_messages_sha256": digest(messages), "actual_messages_sha256": digest(actual),
        "original_messages_preserved": actual[:-1] == messages,
        "multimodal_message_index": len(messages), "ordered_images": rows,
        "entity_asset_mapping": mapped, "mapping_sha256": digest(mapped),
        "required_visual_entities": deepcopy(selected_contract["required_entities"]),
        "assistant_pixel_identity_verified": False, "provider_input_acceptance": "unknown",
        "voice_identity_guaranteed": False, "calls_authorized": False,
        "production_adopted": False, "new_paid_calls": 0}}
