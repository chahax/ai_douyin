"""Explicit direct-platform novel text trial; no invented account/opportunity."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.content_factory.account_novel_creation_v1 import (  # noqa: E402
    _code_bindings, _digest, _provider_protocol, _read, _write,
)
from src.content_factory.account_novel_selection_v1 import _body  # noqa: E402
from src.content_factory.account_novel_workflow_v1 import AccountNovelWorkflow  # noqa: E402
from src.content_factory.creative_brief import brief_focus, normalize_brief  # noqa: E402
from src.content_factory.creative_workflow import (  # noqa: E402
    CREATE_REVIEW_PROFILE, CreativeWorkflow, _hash, _source_scope_audit,
    _audit_review_source_absence_claims,
)
from src.content_factory.creative_workflow_inputs import (  # noqa: E402
    file_binding, load_materials, verify_binding,
)
from scripts.run_creative_workflow import claim_logical_task, TASK_REGISTRY  # noqa: E402

SCHEMA = "novel_platform_text_trial/v1"
AUTHORIZATION = ROOT / "data/novel_platform_trials/20261016_v1/AUTHORIZATION_AND_SCOPE.json"
BUDGET = {"max_calls": 20, "max_total_tokens": 500000, "max_revisions": 2,
          "max_contract_repairs": 8, "budget_policy_version": "v5_20261001"}


def _path(raw, parent):
    path = Path(raw)
    if path.is_absolute():
        return path.resolve()
    return ((ROOT / path) if (ROOT / path).exists() else (parent / path)).resolve()


def _immutable(path, value):
    if path.exists():
        if _read(path) != value:
            raise RuntimeError(f"原生回执冲突，拒绝覆盖 {path.name}")
    else:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)


class NativeEvidenceWorkflow(AccountNovelWorkflow):
    """Preserve actual successful and rejected provider envelopes in this run."""

    def _call_model(self, role, messages, **kwargs):
        ordinal = self.state["calls_started"]
        request = {"schema": "novel_trial_native_request/v1", "call_ordinal": ordinal,
                   "stage": self._active_stage_name, "role": role,
                   "messages": messages, "parameters": kwargs}
        _immutable(self.run_dir / f"NATIVE_REQUEST_{ordinal:03}.json", request)
        try:
            result = super()._call_model(role, messages, **kwargs)
        except Exception as exc:
            _immutable(self.run_dir / f"NATIVE_RESPONSE_{ordinal:03}.json", {
                "schema": "novel_trial_native_response/v1", "call_ordinal": ordinal,
                "stage": self._active_stage_name, "status": "error",
                "provider_dispatch_started": getattr(exc, "provider_dispatch_started", None),
                "error": str(exc), "response_text": getattr(exc, "response_text", None),
                "response_payload": getattr(exc, "response_payload", None),
                "response_metadata": {**(getattr(exc, "response_metadata", None) or {}), "call_ordinal": ordinal},
            })
            raise
        _immutable(self.run_dir / f"NATIVE_RESPONSE_{ordinal:03}.json", {
            "schema": "novel_trial_native_response/v1", "call_ordinal": ordinal,
            "stage": self._active_stage_name, "status": "response_received",
            "response_text": result.text, "response_payload": result.response_payload,
            "response_metadata": result.metadata,
        })
        return result


def _bundle(run, binding):
    return load_materials(source_driver="novel", title=binding["book_name"],
                          novel_path=run / "frozen/story_source.txt",
                          metadata_path=run / "frozen/model_metadata.json")


def verify(run_dir):
    run = Path(run_dir).resolve()
    binding = _read(run / "BINDING.json")
    if (binding.get("schema") != SCHEMA or binding.get("run_dir") != str(run)
            or _read(run / "BINDING_ANCHOR.json").get("sha256") != _digest(binding)):
        raise ValueError("直取文本任务冻结身份不符")
    if binding["budget"] != BUDGET or binding["provider_protocol"] != _provider_protocol():
        raise ValueError("预算或模型服务协议变化，停止派发")
    for item in [*binding["files"].values(), *binding["code_bindings"]]:
        verify_binding(item)
    if file_binding(run / "frozen/story_source.txt")["sha256"] != binding["source_span"]["sha256"]:
        raise ValueError("冻结章节正文身份不符")
    return binding, _bundle(run, binding)


def prepare(acquisition_result, run_dir, *, authorization=AUTHORIZATION, task_registry=TASK_REGISTRY,
            duration_seconds=None):
    run = Path(run_dir).resolve()
    acquisition_result, authorization = Path(acquisition_result).resolve(), Path(authorization).resolve()
    duration_seconds = duration_seconds or [45, 180]
    if (run / "BINDING.json").exists():
        bound, _ = verify(run)
        if (bound["files"]["acquisition"]["path"] != str(acquisition_result)
                or bound["files"]["authorization"]["path"] != str(authorization)
                or bound["duration_seconds"] != duration_seconds
                or bound["task_registry"] != str(Path(task_registry).resolve())):
            raise RuntimeError("恢复不能更换采集来源、授权、时长或任务登记")
        return inspect(run)
    if run.exists() and any(run.iterdir()):
        raise RuntimeError("直取文本任务目录已有文件；不得覆盖或换目录重领预算")
    acquisition_binding = file_binding(acquisition_result)
    authorization_binding = file_binding(authorization)
    receipt, auth = _read(acquisition_result), _read(authorization)
    if (receipt.get("status") != "source_saved" or receipt.get("model_calls") != 0
            or auth.get("schema") != "novel_platform_trial_authorization/v1"
            or auth.get("source_mode") != "fanqie_platform_direct_selection"
            or "完整剧本创作与必要文本审查" not in auth.get("scope", [])):
        raise ValueError("缺少已保存平台来源或本轮明确文本处理授权")
    source = receipt["source"]
    book_id = str(source.get("book_id", "")).strip()
    material = _path(source["material_path"], acquisition_result.parent)
    metadata_path = material.parent / "meta.json"
    metadata_raw, native_raw = metadata_path.read_bytes(), material.read_bytes()
    metadata = json.loads(metadata_raw.decode("utf-8-sig"))
    if (not book_id or str(metadata.get("book_id")) != book_id
            or str(receipt.get("verified_detail_book_id")) != book_id
            or metadata.get("book_name") != source.get("book_name") or not source.get("chapters")):
        raise ValueError("书籍ID、标题、已获取章节或真实详情来源不一致")
    saved_at = datetime.fromisoformat(receipt["saved_at_utc"].replace("Z", "+00:00"))
    if saved_at.tzinfo is None or saved_at.date().isoformat() != auth["date"]:
        raise ValueError("本轮采集时间与授权日期不符")
    body, span, chapters = _body(native_raw.decode("utf-8-sig"), metadata)
    if len(body.strip()) < 200 or not chapters:
        raise ValueError("平台实际章节正文不足或缺少可靠章节范围")
    protocol = _provider_protocol()
    brief = normalize_brief({"schema": "creative_brief/v1", "theme": f"改编《{source['book_name']}》已获取正文中的完整剧情片段",
        "duration_seconds": duration_seconds, "duration_policy": "flexible",
        "constraints": ["仅story_source提供人物、剧情和对白，简介与未获取后续章节不得补写剧情。",
            "完整说明世界框架、时代日常、人物关系处境目标、空间及前情。",
            "每段明确时间地点、所有在场人物动作神情视线、对白反应、因果及段首尾状态。",
            "重要对白前中后保留表演与反应时间，动作与对白自然重叠。",
            "本轮为用户委托的平台来源文本改编试跑，不声称推广申请、版权许可或视频批准。"],
        "avoid": ["凭空添加原文对白", "只列台词的占位稿", "把接口成功写成人工审美通过"]})
    run.mkdir(parents=True)
    frozen = run / "frozen"
    frozen.mkdir()
    (frozen / "native_material.txt").write_bytes(native_raw)
    (frozen / "story_source.txt").write_bytes(body.encode("utf-8"))
    (frozen / "native_metadata.json").write_bytes(metadata_raw)
    _write(frozen / "model_metadata.json", {"book_id": book_id, "book_name": source["book_name"],
        "scope": "仅已获取章节，不代表整书；书名仅作身份标识。"})
    _write(frozen / "authorization.json", auth)
    _write(frozen / "acquisition.json", receipt)
    _write(run / "creative_brief.json", brief)
    files = {"acquisition": acquisition_binding, "authorization": authorization_binding,
             "original_source": file_binding(material), "original_metadata": file_binding(metadata_path),
             "brief": file_binding(run / "creative_brief.json")}
    if (files["original_source"]["sha256"] != hashlib.sha256(native_raw).hexdigest()
            or files["original_metadata"]["sha256"] != hashlib.sha256(metadata_raw).hexdigest()):
        raise ValueError("读取后原始来源变化，停止冻结")
    for path in frozen.iterdir():
        files["frozen_" + path.name] = file_binding(path)
    for index, row in enumerate(source["chapters"], 1):
        chapter = _path(row["file"], material.parent)
        if chapter.read_bytes().decode("utf-8-sig").strip() not in body:
            raise ValueError("原生章节文件与合并正文不一致")
        files[f"chapter_{index:03}"] = file_binding(chapter)
    binding = {"schema": SCHEMA, "run_dir": str(run), "book_id": book_id, "book_name": source["book_name"],
        "source_mode": "fanqie_platform_direct_selection", "source_span": span, "chapters": chapters,
        "duration_seconds": duration_seconds, "budget": BUDGET, "provider_protocol": protocol,
        "workflow": {"model_profile": CREATE_REVIEW_PROFILE, "writer_prompt_version": "legacy",
                     "review_policy_version": "legacy", "production_protocol": "legacy", "retry_unconfirmed_transport": False},
        "creative_focus": brief_focus(brief), "files": files,
        "code_bindings": [*_code_bindings(), file_binding(Path(__file__))],
        "task_registry": str(Path(task_registry).resolve()), "automatic_media_submit": False,
        "authorization_basis": "本轮用户明确文本处理委托；不据此声称平台版权许可或推广资格"}
    binding["logical_task_id"] = claim_logical_task(_bundle(run, binding), binding["creative_focus"],
        run / "creative", registry=Path(binding["task_registry"]), **BUDGET)
    _write(run / "BINDING_ANCHOR.json", {"schema": SCHEMA, "sha256": _digest(binding)})
    _write(run / "BINDING.json", binding)
    _write(run / "STATUS.json", {"status": "prepared"})
    return inspect(run)


def preview(run_dir):
    binding, bundle = verify(run_dir)
    return {**inspect(run_dir), "binding": binding, "material_payload": bundle.input_payload(),
            "workflow_kwargs": {**binding["budget"], **binding["workflow"],
                                "creative_focus": binding["creative_focus"], "logical_task_id": binding["logical_task_id"]}}


def execute(run_dir, *, clients=None):
    run = Path(run_dir).resolve()
    lock = run / ".novel_trial_execution.lock"
    try:
        with lock.open("x", encoding="utf-8") as stream:
            json.dump({"schema": SCHEMA, "automatic_unlock_after_crash": False}, stream)
    except FileExistsError:
        raise RuntimeError("直取文本任务执行锁已存在，核对原在途请求，不重新派发") from None
    try:
        info = preview(run)
        if info["status"] == "machine_text_complete":
            return info
        binding, bundle = verify(run)
        task_id = claim_logical_task(bundle, binding["creative_focus"], run / "creative",
            registry=Path(binding["task_registry"]), **BUDGET)
        if task_id != binding["logical_task_id"]:
            raise RuntimeError("逻辑任务身份变化")
        workflow = NativeEvidenceWorkflow(run / "creative", clients=clients, **info["workflow_kwargs"])
        workflow.pre_dispatch_validator = lambda: verify(run)
        state = workflow.run(bundle)
        _write(run / "STATUS.json", {"status": state["status"]})
    except Exception as exc:
        _write(run / "STATUS.json", {"status": "needs_attention", "error": str(exc)})
        raise
    finally:
        lock.unlink()
    return inspect(run)


def inspect(run_dir):
    run = Path(run_dir).resolve()
    saved = _read(run / "STATUS.json") if (run / "STATUS.json").exists() else {}
    state = _read(run / "creative/state.json") if (run / "creative/state.json").exists() else None
    status = state["status"] if state else saved.get("status", "unprepared")
    artifacts, error = {}, saved.get("error")
    try:
        for name in ("SCREENPLAY.json", "SCREENPLAY.md", "STORYBOARD.json", "EDITORIAL_REVIEW_PACKET.json", "MEDIA_HANDOFF.json"):
            path = run / "creative" / name
            if path.exists():
                artifacts[name] = file_binding(path)
        if status == "media_handoff_pending_capability":
            creative = run / "creative"
            script, shots = _read(creative / "SCREENPLAY.json"), _read(creative / "STORYBOARD.json")
            handoff, packet = _read(creative / "MEDIA_HANDOFF.json"), _read(creative / "EDITORIAL_REVIEW_PACKET.json")
            verifier = object.__new__(CreativeWorkflow)
            verifier.run_dir, verifier.state = creative, state
            verifier._validate_output_manifest(handoff=handoff)
            if (not script.get("beats") or not shots.get("shots") or handoff.get("automatic_submit") is not False
                    or handoff.get("script_sha256") != _hash(script) or handoff.get("shots_sha256") != _hash(shots)
                    or handoff.get("review_packet_sha256") != _hash(packet) or state["handoff_sha256"] != _hash(handoff)):
                raise ValueError("完整剧本、分镜或复审交接身份不符")
            source = _read(creative / "SELECTED_SOURCE.json")["text"]
            checks = [row for row in state["stages"] if row["name"].startswith("writer_check")]
            check = _read(creative / (checks[-1]["name"] + ".json"))["output"]
            issues, _ = _audit_review_source_absence_claims(check["issues"], script, source)
            if (packet["script_sha256"] != _hash(script) or packet["shots_sha256"] != _hash(shots)
                    or packet["material_sha256"] != state["material_sha256"]
                    or packet["writer_check_sha256"] != _hash(check)
                    or packet["source_scope_audit"] != _source_scope_audit(source, script, "novel")
                    or any(row["severity"] in ("blocking", "major") for row in issues)):
                raise ValueError("同源完整文本复审未完成或存在主要问题")
            status = "needs_text_attention" if packet["source_scope_audit"]["potential_overwide_start"] else "machine_text_complete"
    except (ValueError, KeyError, IndexError, TypeError, OSError, RuntimeError) as exc:
        status, error = "incomplete_artifacts", str(exc)
    if saved.get("error"):
        status = "needs_attention"
    return {"schema": SCHEMA, "run_dir": str(run), "status": status,
            "creative_status": state["status"] if state else None, "creative_state": state,
            "artifacts": artifacts, "error": error, "human_approved": False,
            "automatic_media_submit": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "preview", "execute", "inspect"))
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--acquisition-result", type=Path)
    parser.add_argument("--authorization", type=Path, default=AUTHORIZATION)
    parser.add_argument("--duration-min", type=int, default=45)
    parser.add_argument("--duration-max", type=int, default=180)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            if args.acquisition_result is None:
                parser.error("prepare需要--acquisition-result")
            result = prepare(args.acquisition_result, args.run_dir, authorization=args.authorization,
                             duration_seconds=[args.duration_min, args.duration_max])
        else:
            result = {"preview": preview, "execute": execute, "inspect": inspect}[args.command](args.run_dir)
    except Exception as exc:
        result = {**inspect(args.run_dir), "status": "needs_attention", "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"prepared", "machine_text_complete"} else 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
