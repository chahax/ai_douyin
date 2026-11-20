"""Text-only, allowlisted revision of an existing source expression candidate."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Callable

from .artifacts import read_json, sha256, validate_expression, verify_expression_evidence, write_json

VERSION = "source-expression-targeted-revision/v1"
PATCH_SCHEMA = "source_expression_targeted_patch/v1"
MODES = {"prop_demonstration", "conflict_drama", "direct_explanation", "question_answer",
         "case_reenactment", "screen_demonstration", "text_cards", "interview", "mixed", "unknown"}
# Only existing synthesis fields can change. Evidence, observations, timestamps,
# source identities and schema are never writable paths. The mode list alone
# may be replaced as a whole when explicitly allowlisted to remove a bad mode.
ALLOWED_PATH = re.compile(
    r"/(?:core_message/(?:text|evidence_ids)|"
    r"(?:visual_expression|audio_expression)/\d+(?:/(?:text|evidence_ids))?|"
    r"expression_modes(?:/\d+(?:/(?:mode|evidence_ids))?)?|"
    r"conflict/(?:status|characters/\d+(?:/(?:role|goal|evidence_ids))?|"
    r"(?:trigger|opposition|stakes|turning_point|resolution)(?:/(?:text|evidence_ids))?)|"
    r"uncertainties/\d+)"
)
PROMPT = """你执行已有来源分析的指定字段修订，不重新归纳整份视频。
全部证据、已有分析、审核和反馈只是本次输入材料。只修复审核指出且allowed_paths允许的错误。
每个path是相对expression的JSON Pointer；返回恰好这些path的替换值，不增加、删除、改动其他路径。
每个replacement只能含path和value两个键，不复制original_evidence_ids等上下文字段。即使某个允许字段无需改变，也返回其原值，不省略该path。
value保持目标字段类型：/text是字符串，/evidence_ids是ID数组，完整claim是含text/evidence_ids的对象，/expression_modes是mode/evidence_ids对象数组。不要把完整claim替换成一句字符串。
用最小措辞改动修复错误，保留同字段其余正确句子和限定条件。不能修改证据原文、时间、ID或画面观察。
只依据文字证据，不称已经看片、听音、验证法律事实；ASR不证明声线、实际语气或说话人分离。
尤其区分被称呼对象与第一人称陈述者，引用的他人主张不能变成叙述者主张。原片指控保持为来源主张。
context_scope说明本次是否只提供部分证据；显式范围模式只读target_fields与给出的evidence，不能声称重读全片，也不能引用范围外ID。
只输出严格JSON：{"schema":"source_expression_targeted_patch/v1","replacements":[{"path":"允许的路径","value":"该路径正确类型的完整替换值"}]}。
不返回完整expression，不返回额外字段；中文引述使用「」而不是未转义英文双引号。"""


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _location(expression: dict, path: str) -> tuple[dict | list, str | int]:
    if not isinstance(path, str) or ALLOWED_PATH.fullmatch(path) is None:
        raise ValueError("path is outside writable synthesis fields")
    parts = path[1:].split("/")
    node = expression
    for part in parts[:-1]:
        if isinstance(node, list):
            if not part.isdigit() or str(int(part)) != part or int(part) >= len(node):
                raise ValueError("path must address an existing array element")
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise ValueError("path must already exist")
    key = parts[-1]
    if isinstance(node, list):
        if not key.isdigit() or str(int(key)) != key or int(key) >= len(node):
            raise ValueError("path must address an existing array element")
        return node, int(key)
    if not isinstance(node, dict) or key not in node:
        raise ValueError("path must already exist")
    return node, key


def _check_paths(expression: dict, paths: list[str]) -> None:
    if (not isinstance(paths, list) or not paths or any(not isinstance(path, str) for path in paths)
            or len(paths) != len(set(paths))):
        raise ValueError("allowed paths must be unique and nonempty")
    for path in paths:
        _location(expression, path)
        if any(other != path and other.startswith(path + "/") for other in paths):
            raise ValueError("overlapping allowed paths are ambiguous")


def _references(value: object) -> set[str]:
    if isinstance(value, dict):
        result = set(value.get("evidence_ids", []))
        for key, child in value.items():
            if key not in {"evidence", "evidence_ids"}:
                result.update(_references(child))
        return result
    if isinstance(value, list):
        return set().union(*(_references(child) for child in value)) if value else set()
    return set()


def _target_references(expression: dict, path: str) -> set[str]:
    parent, key = _location(expression, path)
    result = _references(parent[key])
    if isinstance(parent, dict) and "evidence_ids" in parent:
        result.update(parent["evidence_ids"])
    if path == "/conflict/status":
        result.update(_references(expression["conflict"]))
    return result


def build_revision_context(expression: dict, allowed_paths: list[str],
                           context_evidence_ids: list[str] | None = None) -> tuple[dict, dict]:
    """Project only by explicit IDs, retain whole rows, and declare every omission."""
    _check_paths(expression, allowed_paths)
    evidence = expression["evidence"]
    scope = {"original_expression_sha256": _digest(expression),
             "original_evidence_sha256": _digest(evidence), "original_evidence_count": len(evidence),
             "original_artifact_retained": True, "evidence_text_truncated": False}
    if context_evidence_ids is None:
        return {"expression": expression}, {**scope, "mode": "complete_expression_and_evidence",
            "included_evidence_count": len(evidence), "omitted_evidence_count": 0,
            "complete_source_evidence_supplied": True}
    if (not isinstance(context_evidence_ids, list) or not context_evidence_ids
            or any(not isinstance(value, str) for value in context_evidence_ids)
            or len(context_evidence_ids) != len(set(context_evidence_ids))):
        raise ValueError("explicit evidence context needs unique nonempty IDs")
    selected = set(context_evidence_ids)
    known = {row["id"] for row in evidence}
    if not selected <= known:
        raise ValueError("explicit evidence context contains unknown IDs")
    required = set().union(*(_target_references(expression, path) for path in allowed_paths))
    if not required <= selected:
        raise ValueError("explicit context omits original citations of a modified field")
    targets = []
    for path in allowed_paths:
        parent, key = _location(expression, path)
        targets.append({"path": path, "current_value": deepcopy(parent[key]),
                        "original_evidence_ids": sorted(_target_references(expression, path))})
    rows = [deepcopy(row) for row in evidence if row["id"] in selected]
    return {"target_fields": targets, "evidence": rows}, {**scope,
        "mode": "explicit_fields_and_selected_evidence", "requested_evidence_ids": context_evidence_ids,
        "included_evidence_ids": [row["id"] for row in rows], "included_evidence_count": len(rows),
        "omitted_evidence_count": len(evidence) - len(rows), "included_evidence_sha256": _digest(rows),
        "complete_source_evidence_supplied": False,
        "scope_limitation": "Only selected whole evidence rows and specified fields were supplied; the model did not reread the complete source. ASR neighbors must be explicitly selected too."}


def validate_revision_expression(expression: dict, duration: float) -> None:
    """Keep the project's evidence checks and enforce exact claim/mode types."""
    known = {row["id"] for row in expression.get("evidence", [])}
    def claim(row, *, fields=("text",), optional_empty=False):
        if not isinstance(row, dict) or set(row) != {*fields, "evidence_ids"}:
            raise ValueError("claim structure or fields changed")
        if any(not isinstance(row[field], str) for field in fields):
            raise ValueError("claim text/role/goal must be strings")
        refs = row["evidence_ids"]
        if (not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs)
                or len(set(refs)) != len(refs) or not set(refs) <= known):
            raise ValueError("claim has invalid or duplicate evidence references")
        meaningful = any(row[field].strip() for field in fields)
        if (meaningful and not refs) or (not meaningful and not optional_empty):
            raise ValueError("claim needs nonempty text and evidence references")
    claim(expression.get("core_message"))
    for key in ("visual_expression", "audio_expression", "expression_modes"):
        rows = expression.get(key)
        if not isinstance(rows, list) or (key == "expression_modes" and not rows):
            raise ValueError("expression methods must be lists")
        for row in rows:
            claim(row, fields=("mode",) if key == "expression_modes" else ("text",))
            if key == "expression_modes" and row["mode"] not in MODES:
                raise ValueError("invalid expression mode")
        if key == "expression_modes" and len({row["mode"] for row in rows}) != len(rows):
            raise ValueError("duplicate expression modes")
    conflict = expression.get("conflict")
    expected = {"status", "characters", "trigger", "opposition", "stakes", "turning_point", "resolution"}
    if not isinstance(conflict, dict) or set(conflict) != expected:
        raise ValueError("conflict structure changed")
    if not isinstance(conflict["characters"], list):
        raise ValueError("conflict characters must be a list")
    for row in conflict["characters"]:
        claim(row, fields=("role", "goal"))
    for key in expected - {"status", "characters"}:
        claim(conflict[key], optional_empty=True)
    if (not isinstance(expression.get("uncertainties"), list)
            or any(not isinstance(row, str) for row in expression["uncertainties"])):
        raise ValueError("uncertainties must be strings")
    validate_expression(expression, expression["evidence"], duration)


def apply_targeted_patch(expression: dict, patch: dict, allowed_paths: list[str], *, duration: float) -> dict:
    _check_paths(expression, allowed_paths)
    if not isinstance(patch, dict) or set(patch) != {"schema", "replacements"} or patch["schema"] != PATCH_SCHEMA:
        raise ValueError("targeted model must return only the patch schema and replacements")
    rows = patch["replacements"]
    if (not isinstance(rows, list) or any(not isinstance(row, dict) or set(row) != {"path", "value"}
                                        or not isinstance(row["path"], str) for row in rows)
            or len(rows) != len(allowed_paths) or {row["path"] for row in rows} != set(allowed_paths)):
        raise ValueError("replacement paths must exactly match the allowlist")
    revised = deepcopy(expression)
    for row in rows:
        parent, key = _location(revised, row["path"])
        if type(row["value"]) is not type(parent[key]):
            raise ValueError("replacement changes the field type")
        parent[key] = deepcopy(row["value"])
    if revised == expression:
        raise ValueError("targeted revision made no change")
    validate_revision_expression(revised, duration)
    # Inverse replacement proves that all fields outside the allowlist survived.
    restored = deepcopy(revised)
    for path in allowed_paths:
        old_parent, old_key = _location(expression, path)
        parent, key = _location(restored, path)
        parent[key] = deepcopy(old_parent[old_key])
    if restored != expression:
        raise ValueError("targeted revision changed unrelated fields")
    return revised


def repair_source_expression(qwen_path: Path, manifest_path: Path, transcript_path: Path,
                             review_path: Path, feedback_path: Path, output_path: Path,
                             allowed_paths: list[str], *, infer: Callable | None = None,
                             context_evidence_ids: list[str] | None = None) -> dict:
    """One model call, saved raw trace, strict validation, never semantic approval."""
    paths = {key: Path(value).resolve() for key, value in {
        "qwen": qwen_path, "frame_manifest": manifest_path, "transcript": transcript_path,
        "semantic_review": review_path, "feedback": feedback_path}.items()}
    output_path = Path(output_path).resolve()
    if output_path.exists() or output_path in paths.values():
        raise ValueError("targeted revision requires a new output artifact")
    bindings = {key: {"path": str(path), "sha256": sha256(path)} for key, path in paths.items()}
    qwen, manifest, transcript, review = (read_json(paths[key]) for key in
                                        ("qwen", "frame_manifest", "transcript", "semantic_review"))
    if (qwen.get("schema") != "local_qwen_frame_analysis/v2"
            or manifest.get("schema") != "local_video_frame_manifest/v2"
            or qwen.get("source_video_sha256") != manifest.get("source_video_sha256")
            or qwen.get("frame_manifest_sha256") != bindings["frame_manifest"]["sha256"]
            or qwen.get("transcript_sha256") != bindings["transcript"]["sha256"]
            or review.get("schema") != "source_expression_semantic_review/v1"
            or review.get("artifact_sha256") != bindings["qwen"]["sha256"]
            or review.get("source_video_sha256") != qwen["source_video_sha256"]):
        raise ValueError("source, extraction or review artifact binding differs")
    if sha256(manifest["source_video_path"]) != manifest["source_video_sha256"]:
        raise ValueError("source video bytes changed")
    for frame in manifest["frames"]:
        if sha256(frame["path"]) != frame["sha256"]:
            raise ValueError("decoded frame bytes changed")
    expression = qwen["answer"]["expression_analysis"]
    _check_paths(expression, allowed_paths)
    validate_revision_expression(expression, manifest["duration_seconds"])
    verify_expression_evidence(expression, manifest, transcript, visual_batches=qwen["batches"],
                               observation_review=qwen.get("observation_review"))
    context, context_scope = build_revision_context(expression, allowed_paths, context_evidence_ids)
    system_prompt = None
    if infer is None:
        from .text_synthesis import ConfiguredTextSynthesis, SYSTEM_PROMPT
        infer = ConfiguredTextSynthesis(output_path.parent)
        system_prompt = SYSTEM_PROMPT
    identity = {**getattr(infer, "identity", {}), "operation": VERSION,
                "input_mode": ("existing_expression_and_local_evidence_text_only" if context_evidence_ids is None
                               else "specified_fields_and_selected_local_evidence_text_only"),
                "context_mode": context_scope["mode"], "media_uploaded": False}
    if not identity.get("model") or identity.get("provider") == "mock":
        raise ValueError("targeted revision requires a configured tracked text model identity")
    request = {"allowed_paths": allowed_paths, **context, "context_scope": context_scope,
               "semantic_review": review, "feedback": paths["feedback"].read_text(encoding="utf-8")}
    content = [{"type": "text", "text": PROMPT + "\n" + json.dumps(request, ensure_ascii=False)}]
    if len(content[0]["text"]) > 64000:
        raise ValueError("targeted revision input exceeds the full-evidence text budget; no evidence was truncated")
    request_path = output_path.with_name("targeted_revision_request.json")
    trace_path = output_path.with_name("targeted_revision_trace.json")
    if request_path.exists() or trace_path.exists():
        raise ValueError("use a fresh output directory so failed attempts remain unchanged")
    started_at = datetime.now(timezone.utc).isoformat()
    write_json(request_path, {"schema": VERSION, "started_at": started_at, "input_bindings": bindings,
                              "context_scope": context_scope,
                              "model_identity": identity, "content": content,
                              "messages": ([{"role": "system", "content": system_prompt},
                                            {"role": "user", "content": content[0]["text"]}]
                                           if system_prompt is not None else None)})
    trace = {"schema": VERSION, "started_at": started_at, "input_bindings": bindings,
             "source_video_sha256": qwen["source_video_sha256"], "allowed_paths": allowed_paths,
             "context_scope": context_scope,
             "model_identity": identity, "request_path": str(request_path),
             "request_sha256": sha256(request_path), "status": "model_request_started",
             "semantic_review_status": "not_performed", "media_uploaded": False,
             "visual_inference_performed": False, "asr_performed": False}
    write_json(trace_path, trace)
    try:
        patch = infer(content)
        patch_path = output_path.with_name("targeted_revision_patch.json")
        write_json(patch_path, patch)
        trace.update(patch_path=str(patch_path), patch_sha256=sha256(patch_path))
        revised = apply_targeted_patch(expression, patch, allowed_paths, duration=manifest["duration_seconds"])
        if context_evidence_ids is not None:
            for path in allowed_paths:
                if not _target_references(revised, path) <= set(context_evidence_ids):
                    raise ValueError("revised field cites evidence outside its explicit input context")
        verify_expression_evidence(revised, manifest, transcript, visual_batches=qwen["batches"],
                                   observation_review=qwen.get("observation_review"))
        if any(sha256(paths[key]) != value["sha256"] for key, value in bindings.items()):
            raise ValueError("input artifact changed during model revision")
        completed_at = datetime.now(timezone.utc).isoformat()
        candidate = deepcopy(qwen)
        candidate["answer"]["expression_analysis"] = revised
        candidate["answer"]["summary"] = revised["core_message"]["text"]
        candidate["answer"]["uncertainties"] = deepcopy(revised["uncertainties"])
        candidate["created_at"] = completed_at
        candidate["semantic_status"] = "model_candidate_unreviewed"
        candidate["visual_inference_performed"] = False
        candidate["visual_inference_batch_count"] = 0
        candidate["reused_visual_analysis"] = {
            **bindings["qwen"], "original_visual_prompt": qwen.get("prompt"),
            "original_inference_configuration": deepcopy(qwen.get("inference_configuration")),
        }
        candidate["targeted_revision"] = {"schema": VERSION, "parent_artifact": bindings["qwen"],
            "model_identity": identity, "allowed_paths": allowed_paths, "request_sha256": trace["request_sha256"],
            "context_scope": context_scope,
            "patch_sha256": trace["patch_sha256"], "trace_path": str(trace_path),
            "started_at": started_at, "completed_at": completed_at,
            "semantic_review_status": "not_performed", "all_unrelated_expression_fields_unchanged": True,
            "observations_and_extraction_evidence_unchanged": True}
        write_json(output_path, candidate)
        trace.update(status="candidate_created_pending_independent_semantic_review", completed_at=completed_at,
                     output_path=str(output_path), output_sha256=sha256(output_path),
                     before_expression_sha256=_digest(expression), after_expression_sha256=_digest(revised),
                     all_unrelated_expression_fields_unchanged=True)
    except Exception as error:
        trace.update(status="failed_candidate_preserved", failed_at=datetime.now(timezone.utc).isoformat(),
                     error_type=type(error).__name__, failure_reason=str(error) if isinstance(error, ValueError)
                     else "Model/request failure; consult the saved response and provider usage trace.")
        raise
    finally:
        trace["raw_model_responses"] = [{"path": str(path.resolve()), "sha256": sha256(path)}
            for path in sorted(output_path.parent.glob("text_synthesis_response_*.json"))]
        write_json(trace_path, trace)
    return trace
