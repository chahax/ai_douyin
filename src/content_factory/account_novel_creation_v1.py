"""Local account/opportunity selection to an independently frozen novel workflow.

Preparation, preview and inspection never create a provider client. Explicit
execution uses the existing CreativeWorkflow budgets, stage receipts, dispatch
admission, usage accounting and unknown-response stop behavior.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .account_novel_selection_v1 import select_target_novel
from .account_novel_workflow_v1 import AccountNovelWorkflow, VERSION
from .creative_brief import brief_focus, load_brief
from .creative_workflow import (
    CREATE_REVIEW_PROFILE, CreativeWorkflow, _hash,
    _audit_review_source_absence_claims, _source_scope_audit,
)
from .creative_workflow_inputs import file_binding, load_materials, verify_binding

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "account_novel_creation/v1"
DEFAULT_REGISTRY = ROOT / "data/creative_workflows/_logical_tasks"


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_bytes(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))
    temporary.replace(path)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _code_bindings():
    # Freeze all creative helpers, not merely this subclass: recovery must not
    # dispatch through a silently changed validator, role client or state store.
    paths = list((ROOT / "src/content_factory").glob("creative*.py"))
    paths += [Path(__file__), Path(__file__).with_name("account_novel_workflow_v1.py"),
              Path(__file__).with_name("account_novel_selection_v1.py"),
              ROOT / "scripts/run_creative_workflow.py", ROOT / "config/creative_agent_models.json",
              ROOT / "src/shared/config.py"]
    return [file_binding(p) for p in sorted(set(paths))]


def _provider_protocol():
    """Read only non-secret runtime routing; credential rotation stays possible."""
    from src.shared.config import settings
    roles = {}
    for role, prefix, expected in (("writer", "WRITER_AGENT", ("minimax", "MiniMax-M3")),
                                   ("director", "DIRECTOR_AGENT", ("deepseek", "deepseek-flash"))):
        provider = getattr(settings, prefix + "_PROVIDER")
        model = getattr(settings, prefix + "_MODEL")
        base_url = getattr(settings, prefix + "_BASE_URL")
        parsed = urlsplit(base_url)
        if (parsed.scheme not in ("https", "http") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment):
            raise ValueError("模型服务URL不能包含凭据、查询参数或片段；未保存该URL")
        if (provider, model) != expected:
            raise ValueError("小说入口仅支持已核实的MiniMax创作/DeepSeek审查型号")
        roles[role] = {"provider": provider, "model": model, "base_url": base_url,
                       "api_style": "openai_chat_completions", "endpoint": "/chat/completions",
                       "max_retries": 0}
    return {"roles": roles, "timeout_seconds": settings.SCRIPT_LLM_TIMEOUT_SECONDS}


def _bundle(run_dir, binding):
    return load_materials(source_driver="novel", title=binding["title"],
                          novel_path=run_dir / "frozen/story_source.txt",
                          metadata_path=run_dir / "frozen/model_metadata.json")


def _verified(run_dir):
    run_dir = Path(run_dir).resolve()
    binding = _read(run_dir / "BINDING.json")
    if binding.get("schema") != SCHEMA or binding.get("run_dir") != str(run_dir):
        raise ValueError("创作绑定目录或版本不符")
    if _read(run_dir / ".account_novel_preparation.json").get("binding_sha256") != _digest(binding):
        raise ValueError("创作冻结绑定已改变")
    if binding["provider_protocol"] != _provider_protocol():
        raise ValueError("模型服务、协议或运行参数变化，停止恢复")
    for item in [*binding["files"].values(), *binding["code_bindings"]]:
        verify_binding(item)
    if binding["workflow"] != {"adapter": VERSION, "model_profile": CREATE_REVIEW_PROFILE,
                               "writer_prompt_version": "legacy", "review_policy_version": "legacy",
                               "production_protocol": "legacy", "retry_unconfirmed_transport": False}:
        raise ValueError("小说创作协议绑定不符")
    selection = _read(run_dir / "SELECTION.json")
    if selection.get("status") != "selected":
        raise ValueError("没有已选小说，不能进入完整创作")
    if binding["budget"]["max_revisions"] > 2:
        raise ValueError("小说整稿返修超过两轮")
    if file_binding(run_dir / "frozen/story_source.txt")["sha256"] != binding["source_span"]["sha256"]:
        raise ValueError("派生章节正文与原文区间身份不符")
    return binding, selection, _bundle(run_dir, binding)


def _prepare_account_novel_run(profile, opportunity, candidates, run_dir, *, now=None,
                              target_book_id=None, title=None, duration_seconds=None,
                              max_calls=20, max_total_tokens=500000, max_revisions=2,
                              max_contract_repairs=8, task_registry=None) -> dict:
    """Freeze one source and intent; duplicate directories cannot reset budgets."""
    run_dir = Path(run_dir).resolve()
    selection = select_target_novel(profile, opportunity, candidates, now=now, target_book_id=target_book_id)
    budget = {"max_calls": max_calls, "max_total_tokens": max_total_tokens,
              "max_revisions": max_revisions, "max_contract_repairs": max_contract_repairs,
              "budget_policy_version": "v5_20261001"}
    if (any(type(x) is not int for x in (max_calls, max_total_tokens, max_revisions, max_contract_repairs))
            or max_calls < 5 or max_total_tokens < 10000 or not 0 <= max_revisions <= 2 or max_contract_repairs < 0):
        raise ValueError("调用、用量或返修预算无效；整稿返修最多两轮")
    if (run_dir / "BINDING.json").exists():
        binding, prior, _ = _verified(run_dir)
        # Ignore only selection diagnostics which may include timestamps; all
        # selected identity/account/opportunity data must remain the same.
        if (prior != selection or binding["budget"] != budget
                or (title is not None and title != binding["title"])
                or (duration_seconds is not None and duration_seconds != binding["duration_seconds"])
                or (task_registry is not None and str(Path(task_registry).resolve()) != binding["task_registry"])):
            raise RuntimeError("恢复准备不能改变账号、机会、小说、来源或预算")
        return inspect_account_novel_run(run_dir)
    ignored = {".account_novel_preparation.json", ".account_novel_prepare.lock", "PREPARATION_HISTORY", "ENTRY_CONTEXT.json"}
    if run_dir.exists() and any(p.name not in ignored for p in run_dir.iterdir()):
        raise RuntimeError("准备目录已有文件，不能覆盖或重新领取预算")
    run_dir.mkdir(parents=True, exist_ok=True)
    _write(run_dir / "SELECTION.json", selection)
    if selection["status"] != "selected":
        _write(run_dir / "STATUS.json", {"status": selection["status"], "automatic_media_submit": False})
        return inspect_account_novel_run(run_dir)
    selected = selection["selected_book"]
    source = selected["source_text"]
    if len(source.strip()) < 200:
        raise ValueError("已授权章节正文不足 200 字")
    frozen = run_dir / "frozen"
    frozen.mkdir()
    (frozen / "story_source.txt").write_bytes(source.encode("utf-8"))
    _write(frozen / "metadata.json", selected["metadata"])
    _write(frozen / "authorization.json", selected["authorization"])
    _write(frozen / "account.json", selection["account"])
    _write(frozen / "opportunity.json", selection["opportunity"])
    # Metadata is evidence/selection context. Synopsis and unavailable later
    # chapters must never enter the writer's plot source through metadata.
    _write(frozen / "model_metadata.json", {"book_id": selected["book_id"],
                                           "book_name": selected["book_name"],
                                           "source_scope": selected.get("acquisition_scope"),
                                           "rule": "仅 story_source 是剧情、人物和对白来源；书名仅用于作品标识。"})
    title = title or selected["book_name"]
    from .account_novel_selection_v1 import _validate_context
    config = _validate_context(selection["account"], selection["opportunity"], now)
    duration_seconds = duration_seconds or [config["min_video_seconds"], config["max_video_seconds"]]
    brief = {"schema": "creative_brief/v1", "theme": f"改编目标小说《{selected['book_name']}》已授权章节的完整剧情片段",
             "title": title, "duration_seconds": duration_seconds, "duration_policy": "strict_range",
             "audience": json.dumps(selection["account"].get("target_audiences", []), ensure_ascii=False),
             "constraints": ["原文为人物、剧情、对白唯一来源；不得从热门视频、简介或未获取章节补写剧情。",
                             "先交代世界框架、时代日常、人物关系处境目标、空间前情。",
                             "逐段明确时间地点、所有在场人物动作神情视线、对白反应、因果及段首段尾状态。",
                             "重要对白前中后保留表演与反应窗口，动作对白自然重叠推进。",
                             "推广目标仅影响高光选择和表达；CTA仅可引用目标书名，不得编造原文情节。"],
             "avoid": ["占位符推广简报", "将机器文本审查写成人工或视频通过"]}
    _write(run_dir / "creative_brief.json", brief)
    normalized = load_brief(run_dir / "creative_brief.json")
    context = {"account": selection["account"], "opportunity": selection["opportunity"]}
    focus = (brief_focus(normalized) + "\n账号与选题仅供选择及表达，不能充当剧情或对白来源："
             + json.dumps(context, ensure_ascii=False, sort_keys=True))
    files = {"selection": file_binding(run_dir / "SELECTION.json"),
             "brief": file_binding(run_dir / "creative_brief.json")}
    for path in frozen.iterdir():
        files["frozen_" + path.name] = file_binding(path)
    for name, key in (("original_source", "material_path"), ("original_metadata", "metadata_path"),
                      ("original_authorization", "authorization_path")):
        if selected.get(key):
            files[name] = file_binding(Path(selected[key]))
            expected_key = {"original_source": "source_sha256", "original_metadata": "metadata_sha256",
                            "original_authorization": "authorization_sha256"}[name]
            if selected.get(expected_key) != files[name]["sha256"]:
                raise ValueError("选择后原始材料或授权身份变化，停止准备")
    workflow = {"adapter": VERSION, "model_profile": CREATE_REVIEW_PROFILE,
                "writer_prompt_version": "legacy", "review_policy_version": "legacy",
                "production_protocol": "legacy", "retry_unconfirmed_transport": False}
    binding = {"schema": SCHEMA, "run_dir": str(run_dir), "title": title,
               "selected_book_id": selected["book_id"], "duration_seconds": duration_seconds,
               "source_span": selected.get("source_span"), "budget": budget, "workflow": workflow,
               "provider_protocol": _provider_protocol(),
               "files": files, "creative_focus": focus, "code_bindings": _code_bindings(),
               "task_registry": str(Path(task_registry or DEFAULT_REGISTRY).resolve()),
               "automatic_media_submit": False, "created_at": datetime.now(timezone.utc).isoformat()}
    from scripts.run_creative_workflow import claim_logical_task
    binding["logical_task_id"] = claim_logical_task(_bundle(run_dir, binding), focus,
                                                  run_dir / "creative", registry=Path(binding["task_registry"]), **budget)
    _write(run_dir / ".account_novel_preparation.json", {"schema": SCHEMA, "scope": "local_preparation_only",
                                                         "binding_sha256": _digest(binding)})
    _write(run_dir / "BINDING.json", binding)
    _write(run_dir / "STATUS.json", {"status": "prepared", "automatic_media_submit": False})
    return inspect_account_novel_run(run_dir)


def prepare_account_novel_run(profile, opportunity, candidates, run_dir, **options) -> dict:
    """Resume local preparation in place while preserving every prior attempt."""
    run_dir = Path(run_dir).resolve()
    marker = run_dir / ".account_novel_preparation.json"
    if run_dir.exists() and any(run_dir.iterdir()) and not (run_dir / "BINDING.json").exists():
        if not marker.exists() or _read(marker).get("schema") != SCHEMA:
            raise RuntimeError("准备目录已有未识别文件，不能覆盖")
    run_dir.mkdir(parents=True, exist_ok=True)
    lock = run_dir / ".account_novel_prepare.lock"
    try:
        with lock.open("x", encoding="utf-8") as stream:
            json.dump({"schema": SCHEMA}, stream)
    except FileExistsError:
        raise RuntimeError("本地准备锁已存在，先核对原准备结果") from None
    try:
        if not (run_dir / "BINDING.json").exists():
            if (run_dir / "creative").exists():
                raise RuntimeError("已有创作目录但绑定缺失，停止恢复，不能重新领取预算")
            keep = {marker.name, lock.name, "PREPARATION_HISTORY", "ENTRY_CONTEXT.json"}
            prior = [p for p in run_dir.iterdir() if p.name not in keep]
            if prior:
                history = run_dir / "PREPARATION_HISTORY"
                history.mkdir(exist_ok=True)
                archive = history / f"attempt_{len(list(history.iterdir())) + 1:03}"
                archive.mkdir()
                for path in prior:
                    path.rename(archive / path.name)
            _write(marker, {"schema": SCHEMA, "scope": "local_preparation_only"})
        return _prepare_account_novel_run(profile, opportunity, candidates, run_dir, **options)
    except Exception as exc:
        # A failed attempt to change a *bound* task must not overwrite its state.
        if not (run_dir / "BINDING.json").exists():
            _write(run_dir / "STATUS.json", {"status": "needs_attention", "preparation_error": str(exc),
                                             "automatic_media_submit": False})
        raise
    finally:
        lock.unlink()


def preview_account_novel_run(run_dir, *, now=None) -> dict:
    run_dir = Path(run_dir).resolve()
    binding, selection, bundle = _verified(run_dir)
    # Recheck the original immutable opportunity's expiry without needing DB
    # access; entrypoints additionally re-read current account/opportunity rows.
    checked = select_target_novel(selection["account"], selection["opportunity"], [selection["selected_book"]],
                                  now=now, target_book_id=selection["selected_book"]["book_id"])
    if checked.get("status") != "selected" or checked.get("selected_book") != selection["selected_book"]:
        raise ValueError("冻结小说、授权或已选正文身份不再有效")
    kwargs = {**binding["budget"], **{k: v for k, v in binding["workflow"].items() if k != "adapter"},
              "creative_focus": binding["creative_focus"], "logical_task_id": binding["logical_task_id"]}
    return {"schema": SCHEMA, "run_dir": str(run_dir), "status": inspect_account_novel_run(run_dir)["status"],
            "binding": binding, "selection": selection, "material_payload": bundle.input_payload(),
            "workflow_kwargs": kwargs, "automatic_media_submit": False}


def execute_account_novel_run(run_dir, *, now=None, runner=None, validator=None) -> dict:
    run_dir = Path(run_dir).resolve()
    lock = run_dir / ".account_novel_execution.lock"
    try:
        with lock.open("x", encoding="utf-8") as stream:
            json.dump({"schema": SCHEMA, "automatic_unlock_after_crash": False}, stream)
    except FileExistsError:
        raise RuntimeError("账号小说执行锁已存在，先核对在途结果，不重复派发") from None
    try:
        if validator is not None:
            validator()
        preview = preview_account_novel_run(run_dir, now=now)
        binding = preview["binding"]
        current = inspect_account_novel_run(run_dir)
        if current["status"] == "machine_text_complete":
            return current
        # Reclaim uses the same task ID and budget, and detects registry edits.
        from scripts.run_creative_workflow import claim_logical_task
        bundle = _bundle(run_dir, binding)
        task_id = claim_logical_task(bundle, binding["creative_focus"], run_dir / "creative",
                                     registry=Path(binding["task_registry"]), **binding["budget"])
        if task_id != binding["logical_task_id"]:
            raise RuntimeError("逻辑创作任务身份不一致")
        if runner is None:
            workflow = AccountNovelWorkflow(run_dir / "creative", **preview["workflow_kwargs"])
            def validate_dispatch():
                preview_account_novel_run(run_dir, now=now)
                if validator is not None:
                    validator()
            workflow.pre_dispatch_validator = validate_dispatch
            state = workflow.run(bundle)
        else:
            state = runner(run_dir=run_dir / "creative", bundle=bundle, workflow_kwargs=preview["workflow_kwargs"])
        if not isinstance(state, dict) or not isinstance(state.get("status"), str):
            raise RuntimeError("完整创作器未返回有效状态")
        # Return values alone do not certify persisted work or complete files.
        saved_path = run_dir / "creative/state.json"
        if not saved_path.exists() or _read(saved_path) != state:
            raise RuntimeError("完整创作状态未持久保存或返回状态不一致")
        _write(run_dir / "STATUS.json", {"status": state["status"], "automatic_media_submit": False})
    except Exception as exc:
        _write(run_dir / "STATUS.json", {"status": "needs_attention", "error": str(exc),
                                         "automatic_media_submit": False})
        raise
    finally:
        lock.unlink()
    return inspect_account_novel_run(run_dir)


def inspect_account_novel_run(run_dir) -> dict:
    run_dir = Path(run_dir).resolve()
    selection = _read(run_dir / "SELECTION.json") if (run_dir / "SELECTION.json").exists() else None
    saved = _read(run_dir / "STATUS.json") if (run_dir / "STATUS.json").exists() else {}
    state = _read(run_dir / "creative/state.json") if (run_dir / "creative/state.json").exists() else None
    status = state.get("status") if state else saved.get("status", "unprepared")
    artifacts = {}
    artifact_error = None
    for name in ("SCREENPLAY.json", "SCREENPLAY.md", "STORYBOARD.json", "EDITORIAL_REVIEW_PACKET.json", "MEDIA_HANDOFF.json"):
        path = run_dir / "creative" / name
        if path.exists():
            try:
                artifacts[name] = file_binding(path)
            except (OSError, ValueError) as exc:
                artifact_error = str(exc)
    if state and status == "media_handoff_pending_capability":
        required = {"SCREENPLAY.json", "SCREENPLAY.md", "STORYBOARD.json", "EDITORIAL_REVIEW_PACKET.json", "MEDIA_HANDOFF.json"}
        try:
            if not required <= artifacts.keys():
                raise ValueError("完整剧本、分镜、复审或交接文件缺失")
            handoff = _read(run_dir / "creative/MEDIA_HANDOFF.json")
            script = _read(run_dir / "creative/SCREENPLAY.json")
            shots = _read(run_dir / "creative/STORYBOARD.json")
            review = _read(run_dir / "creative/EDITORIAL_REVIEW_PACKET.json")
            if (not script.get("beats") or not shots.get("shots")
                    or handoff.get("script_sha256") != _hash(script)
                    or handoff.get("shots_sha256") != _hash(shots)
                    or handoff.get("review_packet_sha256") != _hash(review)
                    or state.get("handoff_sha256") != _hash(handoff)
                    or handoff.get("automatic_submit") is not False):
                raise ValueError("完整产物结构或交接身份不符")
            # This verifier only reads receipts. Construct without __init__ so
            # local inspection never constructs provider clients.
            verifier = object.__new__(CreativeWorkflow)
            verifier.run_dir, verifier.state = run_dir / "creative", state
            verifier._validate_output_manifest(handoff=handoff)
            if (review.get("script_sha256") != _hash(script)
                    or review.get("shots_sha256") != _hash(shots)
                    or review.get("material_sha256") != state.get("material_sha256")):
                raise ValueError("同稿机器复审与最终产物绑定不符")
            checks = [row for row in state.get("stages", []) if row["name"].startswith("writer_check")]
            if not checks:
                raise ValueError("缺少同稿机器全文复审")
            check = _read(run_dir / "creative" / (checks[-1]["name"] + ".json"))["output"]
            selected_source = _read(run_dir / "creative/SELECTED_SOURCE.json")
            if (review.get("writer_check_sha256") != _hash(check)
                    or review.get("source_scope_audit") != _source_scope_audit(selected_source["text"], script, "novel")):
                raise ValueError("同源全文复审或原文范围身份不符")
            effective_issues, _ = _audit_review_source_absence_claims(check.get("issues", []), script, selected_source["text"])
            if any(issue.get("severity") in ("major", "blocking") for issue in effective_issues):
                raise ValueError("同稿机器复审仍有未解决主要问题")
            status = ("needs_text_attention" if review.get("source_scope_audit", {}).get("potential_overwide_start")
                      else "machine_text_complete")
        except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
            status = "incomplete_artifacts"
            saved = {**saved, "artifact_error": str(exc)}
    if artifact_error is not None:
        status = "incomplete_artifacts"
        saved = {**saved, "artifact_error": artifact_error}
    if saved.get("error"):
        status = "needs_attention"
    return {"schema": SCHEMA, "run_dir": str(run_dir), "status": status,
            "creative_status": state.get("status") if state else None,
            "human_approved": False,
            "legacy_assistant_review_pending": bool(state and state.get("assistant_review_required")),
            "creative_state": state, "selection": selection, "artifacts": artifacts,
            "error": saved.get("error"), "artifact_error": saved.get("artifact_error"),
            "automatic_media_submit": False}
