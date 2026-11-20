"""Read-only original-image intake for the independent production adapter.

This module does not inspect pixels, frames or audio, approve media, contact a
provider, or generate anything.  Metadata compatibility is deliberately distinct
from original human approval, provider portrait eligibility and visual quality.
Legacy whole-segment approval without explicit subject mappings stays pending.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from . import creative_reference_compiler_v4 as compiler

VERSION = "creative_reference_intake/v5"
_SHA = re.compile(r"[0-9a-f]{64}")
_ACTOR_FIELDS = ("gender_presentation", "age_presentation", "appearance", "wardrobe")


class ReferenceIntakeError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def _fail(code, detail):
    raise ReferenceIntakeError(code, detail)


def _within(path, roots):
    try:
        resolved = Path(path).resolve()
    except (TypeError, ValueError, OSError):
        _fail("ORIGINAL_EVIDENCE_MISSING", "original evidence path is invalid")
    if not roots or not any(resolved.is_relative_to(Path(root).resolve()) for root in roots):
        _fail("EVIDENCE_OUTSIDE_ALLOWED_ROOT", "original evidence path is outside the declared source roots")
    return resolved


def file_binding(path, *, allowed_roots):
    resolved = _within(path, allowed_roots)
    try:
        data = resolved.read_bytes()
    except OSError:
        _fail("ORIGINAL_EVIDENCE_MISSING", "original evidence file is unavailable")
    if not data:
        _fail("ORIGINAL_EVIDENCE_EMPTY", "original evidence file is empty")
    return {"path": str(resolved), "sha256": hashlib.sha256(data).hexdigest()}


def _read(binding, roots, *, json_object=False):
    if not isinstance(binding, dict) or not _SHA.fullmatch(str(binding.get("sha256", ""))):
        _fail("ORIGINAL_EVIDENCE_MISSING", "path and exact SHA are required")
    actual = file_binding(binding.get("path", ""), allowed_roots=roots)
    if actual["sha256"] != binding["sha256"]:
        _fail("ORIGINAL_BYTES_CHANGED", "original evidence SHA does not match")
    raw = Path(actual["path"]).read_bytes()
    if not json_object:
        return raw
    try:
        obj = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        _fail("ORIGINAL_EVIDENCE_INVALID", "evidence must be a complete JSON object")
    if not isinstance(obj, dict):
        _fail("ORIGINAL_EVIDENCE_INVALID", "evidence must be a complete JSON object")
    return obj


def _manifest_profiles(manifest):
    profiles, scenes = {}, {}
    for actor in manifest.get("actors", []):
        aid = actor["id"]
        if aid in profiles:
            _fail("FIXED_MANIFEST_INVALID", "duplicate actor identity")
        value = {}
        for field in _ACTOR_FIELDS:
            item = actor.get("profile", {}).get(field, {})
            if item.get("status") != "known" or not isinstance(item.get("value"), str) or not item["value"]:
                _fail("FIXED_MANIFEST_INVALID", "current cast needs four known profile attributes")
            value[field] = item["value"]
        profiles[aid] = value
    for scene in manifest.get("scenes", []):
        sid = scene["id"]
        if sid in scenes:
            _fail("FIXED_MANIFEST_INVALID", "duplicate scene identity")
        spec = {field: scene[field]["value"] for field in ("setting", "appearance")
            if isinstance(scene.get(field), dict) and scene[field].get("status") == "known"
            and isinstance(scene[field].get("value"), str)}
        if not spec and isinstance(scene.get("description"), str) and scene["description"]:
            spec = {"description": scene["description"]}
        if not spec:
            _fail("FIXED_MANIFEST_INVALID", "current scene needs a known frozen specification")
        scenes[sid] = spec
    if not profiles or not scenes:
        _fail("FIXED_MANIFEST_INVALID", "actors and scenes are required")
    return profiles, scenes


def _image_mime(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    _fail("INTAKE_IMAGE_BYTES_INVALID", "original bytes are not a supported image signature")


def _origin(candidate, roots):
    raw = _read(candidate.get("receipt"), roots, json_object=True)
    data = _read({"path": candidate.get("local_path"), "sha256": candidate.get("sha256")}, roots)
    mime = candidate.get("mime_type", "image/png")
    if candidate.get("kind", "image") != "image" or _image_mime(data) != mime:
        _fail("INTAKE_IMAGE_BYTES_INVALID", "only original independent images or service-native tails are adapted")
    task = raw.get("task_id")
    provider = raw.get("provider_id", raw.get("provider"))
    service = raw.get("service_result", raw.get("final", raw.get("latest_response")))
    if (not isinstance(service, dict) or service.get("id") != task
            or service.get("status") != "succeeded" or not task or not provider
            or service.get("model", raw.get("model")) != raw.get("model")):
        _fail("ORIGINAL_TASK_BINDING_INVALID", "receipt and complete original service result must match")
    artifact_key = candidate.get("artifact_key", "last_frame")
    if "artifacts" in raw:
        artifact = raw.get("artifacts", {}).get(artifact_key, {})
        if (raw.get("source") != "generation_service_original"
                or artifact.get("path") != candidate["local_path"]
                or artifact.get("sha256") != candidate["sha256"]
                or artifact.get("kind") != "image" or artifact.get("mime_type") != mime):
            _fail("ORIGINAL_TASK_BINDING_INVALID", "canonical original artifact binding is invalid")
    else:
        if (artifact_key != "last_frame" or raw.get("last_frame_source") != "generation_service_original"
                or raw.get("last_frame") != candidate["local_path"]
                or raw.get("last_frame_sha256") != candidate["sha256"]
                or raw.get("technical_status") != "succeeded"):
            _fail("ORIGINAL_TASK_BINDING_INVALID", "legacy image must be an exact saved service-original tail")
        artifact = {"path": candidate["local_path"], "sha256": candidate["sha256"],
            "kind": "image", "mime_type": mime, "service_content_key": "last_frame_url"}
    content_key = artifact.get("service_content_key")
    if not isinstance(service.get("content", {}).get(content_key), str) or not service["content"][content_key]:
        _fail("ORIGINAL_SERVICE_RESULT_MISSING", "original service content evidence is missing")
    normalized = {"schema": "creative_intake_original_image/v5", "task_id": task,
        "provider_id": provider, "model": raw.get("model"), "status": "succeeded",
        "source": "generation_service_original", "service_result": deepcopy(service),
        "artifacts": {artifact_key: deepcopy(artifact)},
        "intake_provenance": {"source_receipt": deepcopy(candidate["receipt"]),
            "normalization_is_visual_inspection": False}}
    account = raw.get("provider_account_binding_sha256")
    if account:
        normalized["provider_account_binding_sha256"] = account
    return raw, normalized


def _selection(candidate, roots, task, receipt_sha):
    binding = candidate.get("adoption")
    if not binding:
        return None, "missing", ["EXPLICIT_ADOPTION_MISSING"]
    approval = _read(binding, roots, json_object=True)
    source = approval.get("decision_source", approval.get("selection_source"))
    if source == "delegated_assistant_selection":
        if (approval.get("asset_sha256") != candidate["sha256"]
                or approval.get("original_task_id") != task
                or not isinstance(approval.get("authorization"), dict)
                or not approval["authorization"].get("user_statement")):
            _fail("DELEGATED_SELECTION_BINDING_INVALID", "delegated choice must bind original bytes and task")
        return approval, "delegated_selection", ["DELEGATED_SELECTION_NOT_EXPLICIT_ASSET_APPROVAL"]
    if source != "explicit_user_statement":
        return approval, "unconfirmed", ["EXPLICIT_ADOPTION_SOURCE_MISSING"]
    if approval.get("decision") == "rejected":
        return approval, "historical_rejected", ["ORIGINAL_ASSET_REJECTED"]
    if approval.get("decision") != "approved" or not approval.get("user_statement"):
        return approval, "unconfirmed", ["EXPLICIT_ADOPTION_MISSING"]
    if approval.get("schema") == "media_user_review/v1":
        # This proves the whole original segment was adopted, not the current
        # actor-to-pixel mapping.  The historical source receipt may be mutable;
        # candidate identity and original tail correspondence remain explicit.
        identity = approval.get("candidate_identity", {})
        if (identity.get("identifiers", {}).get("task_id") != task
                or identity.get("raw_tail_sha256") != candidate["sha256"]
                or approval.get("raw_tail_sha256") != candidate["sha256"]):
            _fail("EXPLICIT_ADOPTION_BINDING_INVALID", "original whole-segment approval does not bind this tail")
        return approval, "historical_segment_approved", ["CURRENT_SUBJECT_MAPPING_MISSING"]
    if (approval.get("asset_id") != candidate["asset_id"]
            or approval.get("asset_sha256") != candidate["sha256"]
            or approval.get("original_task_id") != task
            or approval.get("original_receipt_sha256") != receipt_sha):
        _fail("EXPLICIT_ADOPTION_BINDING_INVALID", "approval must bind original asset, task and receipt")
    return approval, "historical_explicit_asset_approved", []


def _subject_checks(approval, profiles, scenes):
    rows = approval.get("subject_mappings", []) if approval else []
    if not isinstance(rows, list) or not rows:
        return [], "unknown", ["CURRENT_SUBJECT_MAPPING_MISSING"]
    keys, reasons = set(), []
    if approval.get("all_visual_subjects_mapped") is not True:
        reasons.append("COMPLETE_VISUAL_SUBJECT_COVERAGE_UNKNOWN")
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("subject_key"), str)
                or not row["subject_key"] or row["subject_key"] in keys
                or row.get("entity_type") not in {"actor", "scene"}
                or not isinstance(row.get("description"), str) or not row["description"].strip()):
            _fail("SUBJECT_MAPPING_INVALID", "subject mappings must be unique, explicit visual subjects")
        keys.add(row["subject_key"])
        eid = row.get("entity_id")
        if row["entity_type"] == "actor":
            if eid not in profiles:
                reasons.append("CURRENT_CAST_ENTITY_MISMATCH")
            elif row.get("profile") != profiles[eid]:
                reasons.append("CURRENT_CAST_PROFILE_MISMATCH")
        elif eid not in scenes:
            reasons.append("CURRENT_SCENE_ENTITY_MISMATCH")
        elif row.get("scene_spec") != scenes[eid]:
            reasons.append("CURRENT_SCENE_SPEC_MISMATCH")
    # A scene label on an uninspected portrait tail cannot turn it into a pure
    # background.  Explicit coverage and portrait declarations are mandatory.
    actors = any(row["entity_type"] == "actor" for row in rows)
    if approval.get("contains_portrait") is not actors:
        reasons.append("PORTRAIT_SUBJECT_COVERAGE_UNKNOWN")
    return deepcopy(rows), "mismatch" if reasons else "metadata_matches_current_manifest", reasons


def inspect_candidate(candidate, fixed_manifest, *, allowed_roots, now=None):
    """Return a sanitized reusable metadata index; never return signed URLs."""
    profiles, scenes = _manifest_profiles(fixed_manifest)
    aid = candidate.get("asset_id")
    if not isinstance(aid, str) or not aid:
        _fail("ASSET_ID_INVALID", "asset_id is required")
    result = {"asset_id": aid, "status": "pending", "reasons": [],
        "original": {key: deepcopy(candidate.get(key)) for key in ("local_path", "sha256", "receipt", "adoption")},
        "new_generation_calls": 0, "media_content_inspected": False,
        "provider_portrait_eligibility": "not_checked", "provider_input_acceptance": "unknown",
        "historical_approval_is_current_cast_approval": False}
    try:
        raw, origin = _origin(candidate, allowed_roots)
        result.update(original_task_id=origin["task_id"], provider_id=origin["provider_id"],
            model=origin["model"], original_bytes_verified=True,
            original_service_created_at=origin["service_result"].get("created_at"))
        approval, category, reasons = _selection(candidate, allowed_roots, origin["task_id"], candidate["receipt"]["sha256"])
        result["adoption_category"] = category
        subjects, cast, subject_reasons = _subject_checks(approval, profiles, scenes)
        result.update(subjects=subjects, cast_compatibility=cast)
        result["reasons"] = list(dict.fromkeys(reasons + subject_reasons))
        if category == "historical_rejected" or any("MISMATCH" in reason for reason in result["reasons"]):
            result["status"] = "rejected_for_current_source"
        elif not result["reasons"]:
            result["status"] = "metadata_ready_for_compiler"
        if approval:
            result["historical_user_statement"] = approval.get("user_statement")
            result["historical_reviewed_at"] = approval.get("reviewed_at")
            result["historical_source_receipt_sha256"] = approval.get("source_receipt_sha256")
            result["current_receipt_differs_from_historical_review_snapshot"] = bool(
                approval.get("source_receipt_sha256") and approval["source_receipt_sha256"] != candidate["receipt"]["sha256"])
    except ReferenceIntakeError as error:
        result.update(status="rejected_for_current_source", reasons=[error.code], original_bytes_verified=False)
    return result


def build_inventory(candidates, fixed_manifest, *, allowed_roots, now=None):
    """Inspect only caller-supplied candidates; no directory or network scan."""
    ids = [row.get("asset_id") for row in candidates]
    if len(ids) != len(set(ids)):
        _fail("ASSET_ID_DUPLICATE", "candidate asset identities must be unique")
    profiles, scenes = _manifest_profiles(fixed_manifest)
    entries = [inspect_candidate(row, fixed_manifest, allowed_roots=allowed_roots, now=now) for row in candidates]
    ready = [row for row in entries if row["status"] == "metadata_ready_for_compiler"]
    matched = {(sub["entity_type"], sub["entity_id"]) for row in ready for sub in row["subjects"]}
    required = [("actor", aid) for aid in profiles] + [("scene", sid) for sid in scenes]
    return {"schema": VERSION, "fixed_manifest_sha256": compiler.digest(fixed_manifest),
        "entries": entries, "required_entities": [{"entity_type": kind, "entity_id": eid,
            "status": "metadata_reference_available" if (kind, eid) in matched else "pending_original_compatible_reference"}
            for kind, eid in required], "ready_asset_ids": [row["asset_id"] for row in ready],
        "complete_identity_assets_available": all(item in matched for item in required),
        "actual_reference_request_compiled": False, "visual_identity_verified": False,
        "new_generation_calls": 0, "media_calls": 0, "publishing_calls": 0}


def discover_legacy_tail_candidates(asset_directories, *, allowed_roots):
    """Read explicitly listed receipt directories, without recursive traversal."""
    found = []
    for directory in asset_directories:
        directory = _within(directory, allowed_roots)
        source = directory / "receipt.json"
        receipt_binding = file_binding(source, allowed_roots=allowed_roots)
        receipt = _read(receipt_binding, allowed_roots, json_object=True)
        if not receipt.get("last_frame"):
            continue
        asset = file_binding(receipt["last_frame"], allowed_roots=allowed_roots)
        approval_path = directory / "receipt.human_review.json"
        found.append({"asset_id": "original_tail_" + receipt["task_id"],
            "kind": "image", "role": "reference_image", "mime_type": _image_mime(Path(asset["path"]).read_bytes()),
            "local_path": asset["path"], "sha256": receipt.get("last_frame_sha256"),
            "receipt": receipt_binding, "artifact_key": "last_frame",
            "adoption": file_binding(approval_path, allowed_roots=allowed_roots) if approval_path.exists() else None})
    return found


def _save_exclusive(path, value):
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    with Path(path).open("xb") as output:
        output.write(data)
    return {"path": str(Path(path).resolve()), "sha256": hashlib.sha256(data).hexdigest()}


def build_binding_contract(candidates, fixed_manifest, *, selected_asset_ids, output_dir,
        allowed_roots, provider_id, model, mode="multimodal_reference",
        input_account_binding_sha256=None, narrative_text=None, now=None):
    """Adapt exact explicit approvals into v4; pending/delegated assets block.

    Original receipt/adoption files are never changed.  New local wrappers retain
    their source path/SHA.  Provider GET qualification is separately consumed by
    compiler_v4, and is not fabricated here.  Formal continuation is intentionally
    excluded because current source-prefix binding belongs to the video adapter.
    """
    if mode != "multimodal_reference":
        _fail("INTAKE_MODE_UNSUPPORTED", "formal continuation needs an independent current binding")
    if not selected_asset_ids or len(selected_asset_ids) != len(set(selected_asset_ids)):
        _fail("SELECTED_ASSETS_INVALID", "selected asset IDs must be unique and nonempty")
    inventory = build_inventory(candidates, fixed_manifest, allowed_roots=allowed_roots, now=now)
    by_id = {row["asset_id"]: row for row in candidates}
    reports = {row["asset_id"]: row for row in inventory["entries"]}
    for aid in selected_asset_ids:
        if aid not in reports or reports[aid]["status"] != "metadata_ready_for_compiler":
            _fail("SELECTED_REFERENCE_NOT_COMPATIBLE", "selected reference lacks complete current-source metadata")
    selected_subjects = {(row["entity_type"], row["entity_id"]) for aid in selected_asset_ids for row in reports[aid]["subjects"]}
    required = [{"entity_type": row["entity_type"], "entity_id": row["entity_id"]} for row in inventory["required_entities"]]
    if any((row["entity_type"], row["entity_id"]) not in selected_subjects for row in required):
        _fail("REQUIRED_ENTITY_BINDING_MISSING", "selected set must cover every current actor and scene")
    originals = {}
    for aid in selected_asset_ids:
        _, origin = _origin(by_id[aid], allowed_roots)
        contains_actor = any(row["entity_type"] == "actor" for row in reports[aid]["subjects"])
        # Native portrait trust is account/provider-specific.  An explicitly
        # approved non-portrait environment image does not inherit that rule;
        # retain its actual generator rather than relabelling it as Ark.
        if contains_actor and origin["provider_id"] != provider_id:
            _fail("ORIGINAL_PROVIDER_MISMATCH", "native portrait original belongs to another provider")
        originals[aid] = origin
    output = Path(output_dir).resolve()
    _within(output, allowed_roots)
    # Never overwrite a previous normalization or create a partial directory
    # for a known pending source.
    output.mkdir(parents=True, exist_ok=False)
    assets, mappings = [], []
    for index, aid in enumerate(selected_asset_ids):
        candidate = by_id[aid]
        origin = originals[aid]
        origin_binding = _save_exclusive(output / f"{index:02d}_original_receipt.json", origin)
        origin_binding.update(provider_id=origin["provider_id"], task_id=origin["task_id"], artifact_key=candidate.get("artifact_key", "last_frame"))
        old_adoption = _read(candidate["adoption"], allowed_roots, json_object=True)
        subjects = [{key: row[key] for key in ("subject_key", "entity_type", "entity_id", "description")} for row in reports[aid]["subjects"]]
        normalized_approval = {"schema": "creative_intake_adoption/v5", "decision": "approved",
            "decision_source": "explicit_user_statement", "user_statement": old_adoption["user_statement"],
            "asset_id": aid, "asset_sha256": candidate["sha256"], "original_task_id": origin["task_id"],
            "original_receipt_sha256": origin_binding["sha256"], "subject_mappings": subjects,
            "intake_provenance": {"original_adoption": deepcopy(candidate["adoption"]),
                "original_receipt": deepcopy(candidate["receipt"]), "decision_created_by_adapter": False}}
        approval_binding = _save_exclusive(output / f"{index:02d}_original_adoption.json", normalized_approval)
        native = any(row["entity_type"] == "actor" for row in subjects)
        assets.append({"asset_id": aid, "kind": "image", "role": "reference_image",
            "local_path": candidate["local_path"], "sha256": candidate["sha256"],
            "mime_type": candidate.get("mime_type", "image/png"), "original": origin_binding,
            "approval": approval_binding, "subjects": subjects, "independent_image": True,
            "eligibility": {"route": "native_generated_portrait" if native else "non_portrait"}})
        for sub in subjects:
            mappings.append({"binding_id": aid + ":" + sub["subject_key"], "asset_id": aid,
                "subject_key": sub["subject_key"], "entity_type": sub["entity_type"], "entity_id": sub["entity_id"]})
    contract = {"schema": compiler.BINDING_SCHEMA, "provider_id": provider_id, "model": model,
        "mode": mode, "assets": assets, "entity_bindings": mappings, "required_entities": required,
        "voices": [{"actor_id": actor["id"], "status": "unbound", "reason": "no actual audio reference"} for actor in fixed_manifest["actors"]],
        "intake": {"version": VERSION, "fixed_manifest_sha256": inventory["fixed_manifest_sha256"],
            "selection_kind": "historical_explicit_asset_approval", "visual_identity_verified": False}}
    if input_account_binding_sha256 is not None:
        contract["input_account_binding_sha256"] = input_account_binding_sha256
    if narrative_text is not None:
        contract["narrative_text_sha256"] = hashlib.sha256(narrative_text.encode()).hexdigest()
    _save_exclusive(output / "REFERENCE_BINDING.json", contract)
    return contract
