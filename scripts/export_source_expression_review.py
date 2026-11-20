"""Export source-bound review materials without changing source review decisions."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.trend_intelligence.content_analysis.artifacts import (
    read_json, sha256, transcript_evidence, validate_expression, verify_expression_evidence,
)
from src.trend_intelligence.content_analysis.local import _media_evidence
from src.trend_intelligence.sample_gate import LIKE_KINDS
from src.trend_intelligence.media_evidence import build_expression_patterns

BJT = timezone(timedelta(hours=8))
DEFAULT_OUTPUT = ROOT / "data/qa/source_expression_run_20260909/review"
LIMITATION = "仅导出复核材料；模型归纳未据此获得语义通过。抽样帧及ASR不证明连续动作、真实声线、语气或口型匹配。"
MODE_LABELS = {"prop_demonstration": "实物示范", "conflict_drama": "冲突对白／角色表演（见音画范围）", "direct_explanation": "直接讲解",
               "question_answer": "知识问答", "case_reenactment": "角色重演", "screen_demonstration": "屏幕操作",
               "text_cards": "文字卡片", "interview": "访谈", "mixed": "混合表达", "unknown": "待确认"}


def _existing_review(path: Path, artifact_sha: str, source_sha: str) -> dict:
    """Display a separate, exactly bound decision without making a new one."""
    review_path = path.with_name("semantic_review.json")
    if not review_path.is_file():
        return {"decision": "not_reviewed", "reason": "没有绑定当前版本的独立审核"}
    try:
        review = read_json(review_path)
        if (review.get("schema") != "source_expression_semantic_review/v1"
                or review.get("artifact_sha256") != artifact_sha
                or review.get("source_video_sha256") != source_sha
                or Path(review.get("artifact_path", "")).resolve() != path.resolve()
                or review.get("decision") not in {"passed", "passed_with_limits"}
                or review.get("blocked_for_script_generation") is not False):
            return {"decision": "not_reviewed", "reason": "已有审核未完整绑定当前可用版本"}
        reviewed_at = _bjt(review["reviewed_at"])
        scope = review.get("review_scope")
        scope = scope if isinstance(scope, dict) else {}
        viewed = review.get("viewed_frames")
        viewed_count = len(viewed) if isinstance(viewed, list) else scope.get("actual_frames_viewed")
        return {"decision": review["decision"], "path": str(review_path.resolve()),
                "sha256": sha256(review_path), "reviewed_at_bjt": reviewed_at,
                "reviewer": review.get("reviewer"), "method": review.get("method"),
                "viewed_frame_count": viewed_count,
                "limits": review.get("limitations") or review.get("review_limits") or review.get("scope_limitations") or [],
                "notes": review.get("nonblocking_notes") or review.get("findings") or []}
    except (OSError, ValueError, TypeError, KeyError):
        return {"decision": "not_reviewed", "reason": "审核记录不完整或不可解析"}


def _note_text(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("text") or value.get("finding") or json.dumps(value, ensure_ascii=False))
    return str(value)


def _claim_text(claim: dict, evidence: list[dict]) -> str:
    lookup = {row["id"]: row for row in evidence}
    refs = []
    for ref in claim.get("evidence_ids") or []:
        item = lookup.get(ref)
        refs.append(f"{ref} {item['start_seconds']:.2f}–{item['end_seconds']:.2f}秒" if item else ref)
    return str(claim.get("text") or "") + ("（证据：" + "；".join(refs) + "）" if refs else "")


def _date(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("missing recorded created_at")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("recorded timestamp has no timezone")
    return result


def _bjt(value: str) -> str:
    return _date(value).astimezone(BJT).isoformat(timespec="seconds")


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _atomic_json(path: Path, value: dict) -> None:
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2))


def _bound_rejection(path: Path, artifact_sha: str, rejection_root: Path) -> str:
    """Inspect decisions read-only; never create a rejection registry entry."""
    marker = rejection_root / f"{artifact_sha}.json"
    if marker.is_file():
        value = read_json(marker)
        if value.get("artifact_sha256") != artifact_sha or value.get("decision") != "failed":
            return "semantic rejection registry invalid"
        return "semantic rejection registry: failed"
    review = path.with_name("semantic_review.json")
    if review.is_file():
        value = read_json(review)
        if value.get("artifact_sha256") == artifact_sha:
            if value.get("decision") == "failed" or value.get("blocked_for_script_generation"):
                return "bound semantic review: failed"
    return ""


def _source_rows(manifest: dict) -> list[dict]:
    if manifest.get("schema") != "research_local_media/v1":
        raise ValueError("requires research_local_media/v1 manifest")
    items = {item["item_id"]: item for item in manifest.get("items") or []}
    if len(items) != len(manifest.get("items") or []):
        raise ValueError("duplicate source items in manifest")
    selection = manifest.get("selection") or list(items.values())
    selected_ids = [item["item_id"] for item in selection]
    if not selected_ids or len(set(selected_ids)) != len(selected_ids):
        raise ValueError("manifest requires a nonempty unique selection")
    result = []
    for selected in selection:
        source = {**selected, **items.get(selected["item_id"], {})}
        if selected.get("video_id") != source.get("video_id"):
            raise ValueError("selected source video identity differs from downloaded item")
        result.append(source)
    return result


def _verify_source(row: dict, manifest: dict) -> dict:
    video = Path(row["video"]).resolve()
    if sha256(video) != row.get("source_video_sha256"):
        raise ValueError("downloaded original source hash changed")
    receipt_path = Path(row["acquisition_receipt"])
    if sha256(receipt_path) != row.get("acquisition_receipt_sha256"):
        raise ValueError("acquisition receipt hash changed")
    receipt = read_json(receipt_path)
    if (receipt.get("schema") != "source_media_receipt/v1" or not receipt.get("identity_confirmed") or
            any(receipt.get(key) != row.get(key) for key in ("item_id", "video_id", "source_video_sha256")) or
            any(receipt.get(key) != manifest.get(key) for key in ("account_uuid", "collection_run_id")) or
            Path(receipt.get("video", "")).resolve() != video):
        raise ValueError("acquisition receipt does not bind this account/batch/original")
    return receipt


def _metrics(database: Path | None, manifest: dict) -> tuple[dict, list[str]]:
    if database is None or not database.is_file():
        return {}, []
    try:
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as connection:
            connection.row_factory = sqlite3.Row
            records = connection.execute("""SELECT o.item_id, o.metric_value, o.metric_kind,
                o.collected_at, i.title FROM trend_observations o
                JOIN trend_collection_runs r ON r.run_id=o.run_id
                JOIN trend_items i ON i.item_id=o.item_id
                WHERE o.run_id=? AND r.account_uuid=?""",
                (manifest["collection_run_id"], manifest["account_uuid"])).fetchall()
    except sqlite3.Error as exc:
        return {}, [f"同批指标不可读：{type(exc).__name__}"]
    result = {}
    for record in records:
        row = result.setdefault(record["item_id"], {"title": record["title"], "observations": []})
        if record["metric_kind"] in LIKE_KINDS and type(record["metric_value"]) is int and record["metric_value"] >= 0:
            row["observations"].append({"value": record["metric_value"], "kind": record["metric_kind"],
                                         "collected_at": record["collected_at"]})
    for row in result.values():
        observed = row["observations"]
        if observed:
            row["likes"] = {"value": min(item["value"] for item in observed),
                            "kind": "likes", "source": "same_account_collection_run_observations",
                            "method": "minimum confirmed same-source observations, matching sample gate", "observations": observed}
    return result, []


def _index_candidates(analysis_root: Path) -> tuple[dict, list[str]]:
    result, warnings = {}, []
    if not analysis_root.is_dir():
        return result, warnings
    for path in analysis_root.rglob("qwen*.json"):
        if path.name.startswith("qwen_response_"):
            continue
        try:
            payload = read_json(path)
            if payload.get("schema") != "local_qwen_frame_analysis/v2":
                continue
            request_path = next((parent / "request.json" for parent in path.parents
                                 if parent.is_relative_to(analysis_root) and (parent / "request.json").is_file()), None)
            if request_path is None:
                continue
            request = read_json(request_path)
            source_sha = (request.get("parameters") or {}).get("source_sha256")
            if not source_sha:
                continue
            result.setdefault(source_sha, []).append({"path": path.resolve(), "payload": payload,
                                                     "request_path": request_path.resolve(), "request": request})
        except (OSError, ValueError, TypeError, KeyError):
            warnings.append(f"候选工件当前不可解析：{path.resolve()}")
    return result, warnings


def _validate_candidate(candidate: dict, row: dict, rejection_root: Path) -> dict:
    path, payload, request = candidate["path"], candidate["payload"], candidate.get("request")
    original = Path(row["video"]).resolve()
    if request is not None:
        if Path(request.get("source_video_path", "")).resolve() != original:
            raise ValueError("request source path does not identify the selected original")
    elif not candidate.get("explicit_manifest_binding"):
        raise ValueError("candidate has neither an analysis request nor explicit manifest binding")
    created = _date(payload.get("created_at"))
    if payload.get("source_video_sha256") != row["source_video_sha256"]:
        raise ValueError("Qwen source hash does not identify the selected original")
    if ((candidate.get("request_path") and (candidate["request_path"].parent / "failed.json").is_file()) or
            (path.parent / "failed.json").is_file()):
        raise ValueError("attempt has recorded failure")
    artifact_sha = sha256(path)
    rejection = _bound_rejection(path, artifact_sha, rejection_root)
    if rejection:
        raise ValueError(rejection)
    manifest_path = Path(payload["frame_manifest_path"])
    frames = read_json(manifest_path)
    if Path(frames.get("source_video_path", "")).resolve() != original:
        raise ValueError("frame manifest identifies a different original path")
    explicit_transcript = candidate.get("transcript_path")
    transcript_path = Path(explicit_transcript or payload.get("transcript_path") or path.parent / "transcript.json")
    if not transcript_path.is_file() and candidate.get("request_path") and not explicit_transcript:
        transcript_path = candidate["request_path"].parent / "transcript.json"
    transcript = read_json(transcript_path)
    request_view = SimpleNamespace(local_video_path=str(original), qwen_analysis_path=str(path),
                                   transcript_path=str(transcript_path), duration_seconds=frames["duration_seconds"])
    media = _media_evidence(request_view, payload, transcript)
    duration = float(media["duration_seconds"])
    expression = payload["answer"]["expression_analysis"]
    validate_expression(expression, expression.get("evidence") or [], duration)
    verify_expression_evidence(expression, frames, transcript, visual_batches=payload.get("batches") or [],
                               observation_review=payload.get("observation_review"))
    times = media["visual"]["sample_times_seconds"]
    if (not times or times != sorted(set(times)) or times[0] > 1 or times[-1] < duration-min(3, duration/2) or
            len(times) < min(4, max(1, math.ceil(duration)))):
        raise ValueError("sampled frames do not cover source beginning and ending")
    audio = media["audio"]
    if (audio.get("status") not in {"transcribed", "verified_no_speech"} or
            not 0 <= audio.get("coverage_start_seconds", -1) <= .1 or
            not duration-.25 <= audio.get("coverage_end_seconds", -1) <= duration+.25):
        raise ValueError("audio evidence does not cover complete original")
    # Inputs are written atomically by the toolchain; catch a concurrent rewrite
    # instead of exporting one artifact's metadata and another one's content.
    if sha256(path) != artifact_sha:
        raise ValueError("Qwen artifact changed during review export")
    return {"path": path, "payload": payload, "frames": frames, "expression": expression,
            "transcript": transcript, "transcript_path": transcript_path.resolve(), "media": media,
            "created_at": created, "artifact_sha256": artifact_sha}


def _claim_refs(value: object) -> list[str]:
    if isinstance(value, dict):
        own = list(value.get("evidence_ids") or [])
        return own + [ref for key, child in value.items() if key != "evidence" for ref in _claim_refs(child)]
    if isinstance(value, list):
        return [ref for child in value for ref in _claim_refs(child)]
    return []


def representative_frames(frames: list[dict], expression: dict, budget: int = 12) -> list[dict]:
    if not frames or budget < 4:
        raise ValueError("contact sheet needs frames and a budget of at least 4")
    ordered = sorted(frames, key=lambda row: row["time_seconds"])
    ids, chosen = {row["id"]: row for row in ordered}, []
    def add(frame):
        if frame["id"] not in {row["id"] for row in chosen} and len(chosen) < budget:
            chosen.append(frame)
    add(ordered[0])
    add(ordered[-1])
    # Guarantee distinct time positions, then prioritize claims and their turns.
    add(ordered[(len(ordered)-1)//3])
    add(ordered[(len(ordered)-1)*2//3])
    for ref in _claim_refs(expression.get("core_message")) + _claim_refs(expression.get("conflict")) + _claim_refs(expression):
        if ref in ids:
            add(ids[ref])
    while len(chosen) < min(budget, len(ordered)):
        remaining = [row for row in ordered if row["id"] not in {item["id"] for item in chosen}]
        add(max(remaining, key=lambda row: min(abs(row["time_seconds"]-item["time_seconds"]) for item in chosen)))
    return sorted(chosen, key=lambda row: row["time_seconds"])


def _sheet(path: Path, frames: list[dict], video_id: str) -> None:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    width, height, columns, padding = 320, 450, min(4, len(frames)), 12
    sheet = Image.new("RGB", (columns*width, math.ceil(len(frames)/columns)*height+42), "#151922")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=17)
    draw.text((12, 11), f"Source {video_id} | sampled review material", font=font, fill="white")
    for index, frame in enumerate(frames):
        content = Path(frame["path"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != frame["sha256"]:
            raise ValueError("frame changed before contact-sheet rendering")
        original = Image.open(io.BytesIO(content)).convert("RGB")
        tile = ImageOps.contain(original, (width-padding*2, height-52))
        x, y = (index%columns)*width, (index//columns)*height+42
        sheet.paste(tile, (x+(width-tile.width)//2, y+(height-45-tile.height)//2))
        draw.text((x+padding, y+height-36), f"{frame['id']}  {frame['time_seconds']:.3f}s", font=font, fill="white")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    sheet.save(temporary, format="PNG")
    temporary.replace(path)


def _link(label: str, path: str | Path) -> str:
    return f"[{label}](<{Path(path).resolve().as_posix()}>)"


def _md(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def export_review(manifest_path: str | Path, *, output_root: str | Path = DEFAULT_OUTPUT,
                  analysis_root: str | Path = ROOT / "data/video_analysis/trend",
                  database: str | Path | None = ROOT / "data/trend_intelligence.db",
                  rejection_root: str | Path = ROOT / "data/video_analysis/semantic_rejections",
                  frame_budget: int = 12) -> dict:
    manifest_path, output_root, analysis_root = Path(manifest_path).resolve(), Path(output_root).resolve(), Path(analysis_root).resolve()
    manifest = read_json(manifest_path)
    sources = _source_rows(manifest)
    metrics, warnings = _metrics(Path(database) if database else None, manifest)
    candidates, candidate_warnings = _index_candidates(analysis_root)
    warnings.extend(candidate_warnings)
    rows, verified_candidates = [], {}
    for position, source in enumerate(sources, 1):
        metric = metrics.get(source["item_id"], {})
        row = {"position": position, "item_id": source["item_id"], "video_id": source["video_id"],
               "title": metric.get("title") or source.get("title", ""), "source_url": source.get("source_url", ""),
               "status": "pending_analysis", "semantic_status": "not_reviewed_by_exporter",
               "likes": metric.get("likes"), "issues": [], "excluded_candidates": []}
        # A known likes field is permitted; a displayed number with no kind is not.
        if row["likes"] is None and source.get("metric_kind") in LIKE_KINDS and type(source.get("metric_value")) is int:
            row["likes"] = {"value": source["metric_value"], "kind": "likes", "source": "manifest_explicit_metric"}
        rows.append(row)
        if not source.get("video"):
            row["status"], row["issues"] = "pending_original", ["selected original is not acquired"]
            continue
        try:
            receipt = _verify_source(source, manifest)
            row.update(source_video_path=str(Path(source["video"]).resolve()), source_video_sha256=source["source_video_sha256"],
                       duration_seconds=receipt.get("duration_seconds"), acquired_at_bjt=_bjt(source["acquired_at"]) if source.get("acquired_at") else None)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            row["status"], row["issues"] = "invalid_original", [str(exc)]
            continue
        valid = []
        available_candidates = list(candidates.get(source["source_video_sha256"], []))
        if source.get("qwen"):
            explicit_path = Path(source["qwen"]).resolve()
            # Explicit workflow inputs may live in a separate repair folder.
            # The manifest+receipt bind the original; the actual frame manifest,
            # ASR and optional observation-review graph must still validate.
            available_candidates = [candidate for candidate in available_candidates if candidate["path"] != explicit_path]
            try:
                available_candidates.append({"path": explicit_path, "payload": read_json(explicit_path),
                                             "explicit_manifest_binding": True,
                                             "transcript_path": source.get("transcript")})
            except (OSError, ValueError, TypeError) as exc:
                row["excluded_candidates"].append({"path": str(explicit_path), "reason": str(exc)})
        for candidate in available_candidates:
            try:
                valid.append(_validate_candidate(candidate, source, Path(rejection_root)))
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                row["excluded_candidates"].append({"path": str(candidate["path"]), "reason": str(exc)})
        if not valid:
            if row["excluded_candidates"]:
                row["status"] = "no_eligible_candidate"
            continue
        selected = max(valid, key=lambda item: (item["created_at"], str(item["path"])))
        expression, frames = selected["expression"], selected["frames"]["frames"]
        file_id = "".join(character for character in source["video_id"] if character.isalnum() or character in "-_")
        if not file_id:
            raise ValueError("source video ID cannot form a safe review filename")
        folder = output_root / f"{position:02d}_{file_id}"
        selected_frames = representative_frames(frames, expression, frame_budget)
        try:
            _sheet(folder / "contact_sheet.png", selected_frames, source["video_id"])
            asr = transcript_evidence(selected["transcript"])
            transcript_text = "\n".join(f"[{entry['id']} {entry['start_seconds']:.3f}–{entry['end_seconds']:.3f}s] {entry['text']}" for entry in asr)
            _atomic_text(folder / "asr_full.txt", transcript_text or "已由原工件记录无语音；此导出没有执行声音审核。")
            rejection = _bound_rejection(selected["path"], selected["artifact_sha256"], Path(rejection_root))
            if rejection:
                raise ValueError("candidate was rejected during export: " + rejection)
            row.update(status="candidate_ready_for_review", core_message=expression["core_message"],
                       expression_modes=expression["expression_modes"], visual_expression=expression["visual_expression"],
                       audio_expression=expression["audio_expression"], conflict=expression["conflict"],
                       uncertainties=expression.get("uncertainties") or [],
                       analyzed_at_bjt=selected["created_at"].astimezone(BJT).isoformat(),
                       qwen_artifact_path=str(selected["path"]), qwen_artifact_sha256=selected["artifact_sha256"],
                       transcript_artifact_path=str(selected["transcript_path"]), asr_text_path=str(folder / "asr_full.txt"),
                       observation_review=selected["payload"].get("observation_review"),
                       frame_manifest_path=selected["payload"]["frame_manifest_path"],
                       sampled_frame_count=len(frames), contact_sheet_path=str(folder / "contact_sheet.png"),
                       contact_sheet_frames=[{key: frame[key] for key in ("id", "time_seconds", "path", "sha256")} for frame in selected_frames],
                       graph_validation="source_receipt_request_frames_transcript_audio_hashes_and_exact_evidence_verified")
            row["existing_review"] = _existing_review(selected["path"], selected["artifact_sha256"], source["source_video_sha256"])
            verified_candidates[row["item_id"]] = selected
            row["evidence"] = expression.get("evidence") or []
            _atomic_json(folder / "source_review.json", row)
        except (OSError, ValueError, TypeError) as exc:
            row["status"], row["issues"] = "review_export_failed", [str(exc)]
    result = {"schema": "source_expression_review_materials/v1", "exported_at_bjt": datetime.now(BJT).isoformat(),
              "account_uuid": manifest.get("account_uuid"), "collection_run_id": manifest.get("collection_run_id"),
              "manifest_path": str(manifest_path), "manifest_sha256": sha256(manifest_path), "scope": LIMITATION,
              "selection_count": len(rows), "candidate_count": sum(row["status"] == "candidate_ready_for_review" for row in rows),
              "warnings": warnings, "sources": rows}
    reviewed = [row for row in rows if row["status"] == "candidate_ready_for_review"
                and row.get("existing_review", {}).get("decision") in {"passed", "passed_with_limits"}]
    result["reviewed_candidate_count"] = len(reviewed)
    result["all_selected_sources_reviewed"] = len(reviewed) == len(rows)
    result["expression_patterns"] = None
    if rows and result["all_selected_sources_reviewed"] and all(row.get("likes") for row in rows):
        cohort = []
        for row in rows:
            selected = verified_candidates[row["item_id"]]
            cohort.append(SimpleNamespace(
                observation=SimpleNamespace(item_id=row["item_id"], metric_kind="likes", metric_value=row["likes"]["value"]),
                analysis=SimpleNamespace(status="completed", media_access_mode="local_media_authorized",
                    media_evidence=selected["media"], expression_analysis=selected["expression"],
                    item_id=row["item_id"], video_id=row["video_id"], analysis_id=row["qwen_artifact_sha256"]),
                relevance=0))
        result["expression_patterns"] = build_expression_patterns(cohort)
        for pattern in result["expression_patterns"]["patterns"]:
            pattern.pop("average_account_relevance", None)
        covered = {sid for pattern in result["expression_patterns"]["patterns"] for sid in pattern["source_item_ids"]}
        if covered != {row["item_id"] for row in rows}:
            result["expression_patterns"] = None
            result["warnings"].append("比较时媒体复验未覆盖全部来源；不发布不完整的高点赞对照。")
    result["reviewed_expression_summary"] = [
        {"mode": mode, "source_ids": [row["item_id"] for row in reviewed
                                       if mode in {item["mode"] for item in row["expression_modes"]}]}
        for mode in sorted({item["mode"] for row in reviewed for item in row["expression_modes"]})]
    lines = ["# 原视频核心与表达分析结果", "", LIMITATION, "", f"导出时间（北京时间）：{result['exported_at_bjt']}", "",
             f"同批所选原片：{len(rows)} 条；完整机器候选：{result['candidate_count']} 条；已有当前版本独立复核：{len(reviewed)} 条。", "",
             "下列审核状态来自另行保存且与当前分析版本完全匹配的记录。导出程序没有替代看片审核。", "",
             ("全部来源已有独立表达复核，可进入同批高点赞表达对照。" if result["all_selected_sources_reviewed"] else
              "这是阶段结果：完整高点赞表达对照仍待全部所选来源复核，不能将未审来源视作没有某种表达。"), "",
             "发布时间、获取时间、分析时间分别保存；本报告没有使用文件修改时间推断完成。", "",
             "| 序号 | 原片ID | 点赞数 | 机器分析 | 独立表达复核 | 核心表达 |", "| --- | --- | ---: | --- | --- | --- |"]
    for row in rows:
        decision = row.get("existing_review", {}).get("decision", "not_reviewed")
        decision_label = {"passed": "已复核", "passed_with_limits": "已复核，须保留限制"}.get(decision, "待审核／需修订")
        lines.append(f"| {row['position']} | {row['video_id']} | {row['likes']['value'] if row['likes'] else '未知'} | {_md(row['status'])} | {decision_label} | {_md((row.get('core_message') or {}).get('text'))} |")
    if result["expression_patterns"]:
        patterns = result["expression_patterns"]
        lines.extend(["", "## 同批高点赞表达对照", "", patterns["comparison_method"] + "。" + patterns["interpretation"], "",
                      "同一视频可以包含多种方式，各行不能相加成100%；冲突对白可能是文本角色扮演，具体画面范围见逐条证据。采样排序、点赞份额与创作贡献是不同概念，本报告不提供创作贡献百分比。", "",
                      "| 表达方式 | 全部样本支持 | 高点赞组支持 | 其余组支持 | 高点赞组来源ID |",
                      "| --- | --- | --- | --- | --- |"])
        for pattern in patterns["patterns"]:
            for group in pattern["metric_groups"]:
                lines.append(f"| {MODE_LABELS.get(pattern['mode'], pattern['mode'])} | {pattern['support_video_count']}/{len(rows)} | {group['high_group_support']}/{group['high_group_size']}（≥{group['high_group_threshold']:,}赞） | {group['comparison_group_support']}/{group['comparison_group_size']} | {', '.join(group['high_source_item_ids']) or '无'} |")
    for row in rows:
        review = row.get("existing_review") or {}
        lines.extend(["", f"## {row['position']:02d} · {_md(row['title']) or row['video_id']}", "", f"机器状态：{row['status']}；既有独立审核：{review.get('decision', '待审核／需修订')}。", ""])
        if row.get("source_url"):
            lines.append(f"[原片页面]({row['source_url']})")
        if row["status"] == "candidate_ready_for_review":
            lines.extend(["", f"核心：{row['core_message']['text']}", "",
                          "方式：" + "、".join(MODE_LABELS.get(item["mode"], item["mode"]) for item in row["expression_modes"]), "",
                          f"人物冲突：{row['conflict'].get('status', 'unknown')}。", "",
                          "画面如何表达：", "", *["- " + _claim_text(claim, row["evidence"]) for claim in row["visual_expression"]], "",
                          "语句如何表达（根据转写，不代表已核对实际语气）：", "",
                          *["- " + _claim_text(claim, row["evidence"]) for claim in row["audio_expression"]], "",
                          "叙事推进：", "",
                          *[f"- {label}：" + _claim_text(row["conflict"].get(key) or {}, row["evidence"])
                            for key, label in (("trigger", "触发"), ("opposition", "阻碍"), ("stakes", "代价"),
                                               ("turning_point", "转折"), ("resolution", "结尾"))
                            if (row["conflict"].get(key) or {}).get("text")], "",
                          f"分析记录时间：{row['analyzed_at_bjt']}；已分析抽样帧 {row['sampled_frame_count']} 张。", "",
                          _link("完整ASR文字", row["asr_text_path"]) + " · " + _link("原始转写工件", row["transcript_artifact_path"]) + " · " + _link("Qwen原始分析", row["qwen_artifact_path"]), "",
                          f"![{row['video_id']} 抽样复核材料](<{Path(row['contact_sheet_path']).as_posix()}>)", ""])
            if review.get("path"):
                lines.extend([_link("查看绑定当前版本的独立审核", review["path"]), "",
                              f"审核记录时间（北京时间）：{review['reviewed_at_bjt']}。", "",
                              (f"独立审核记录的实际查看帧数：{review['viewed_frame_count']}；其余已抽帧由模型分析。" if review.get("viewed_frame_count") is not None else
                               "实际看片范围与继承的前轮审核见独立审核记录；上面的抽帧总数是机器分析覆盖数。"), "",
                              "审核限制与具体意见：", "",
                              *["- " + _note_text(note) for note in [*review["limits"], *review["notes"]]], ""])
            lines.extend(["仍不能确认：", "", *["- " + str(note) for note in row["uncertainties"]], ""])
        for issue in row["issues"]:
            lines.append(f"- {_md(issue)}")
        if row["excluded_candidates"]:
            lines.append("- 已排除候选：" + "；".join(_md(item["reason"]) for item in row["excluded_candidates"]))
    _atomic_json(output_root / "summary.json", result)
    _atomic_text(output_root / "review.md", "\n".join(lines) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--analysis-root", type=Path, default=ROOT / "data/video_analysis/trend")
    parser.add_argument("--database", type=Path, default=ROOT / "data/trend_intelligence.db")
    parser.add_argument("--rejection-root", type=Path, default=ROOT / "data/video_analysis/semantic_rejections")
    parser.add_argument("--frame-budget", type=int, default=12)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    result = export_review(args.manifest, output_root=args.output_root, analysis_root=args.analysis_root,
                           database=args.database, rejection_root=args.rejection_root, frame_budget=args.frame_budget)
    print(json.dumps({"selection_count": result["selection_count"], "candidate_count": result["candidate_count"],
                      "review_path": str(args.output_root.resolve() / "review.md"), "scope": LIMITATION}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
