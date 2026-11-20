"""One web route for new-source writer review and natural-director production text."""
from __future__ import annotations

import importlib
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

import streamlit as st

from src.web.components.auth import get_current_role, has_permission
from src.web import novel_agent_panel_v9 as history

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "data/novel_adaptation/natural_v10"
CLI = ROOT / "scripts/run_natural_director_v10.py"
STATUSES = {"upstream_writer_revision_required": "完整剧本存在上游问题，需先返修并重新全文审核",
            "awaiting_local_completion": "恢复尝试已有记录但未确认完成，保留原记录并停止派发",
            "campaign_review_required": "等待本批原生结果与五轮复盘，不继续派发",
            "round_limit_exhausted": "已达本次测试轮数上限", "budget_exhausted": "原总调用或用量预算已到",
            "needs_attention": "已保存停点，查看原问题与请求身份",
            "text_ready_for_production": "机器文本与全部实际请求审核完成，视频仍待独立授权和人工审核"}


def _runtime():
    return importlib.import_module("src.content_factory.natural_director_pipeline_v10")


def _editor():
    if not has_permission(get_current_role(), "editor"):
        raise PermissionError("准备与运行文本流程需要编辑权限")


def prepare_source(source_run_dir, *, authorization_path, source_path=None,
                   acquisition_receipt=None, title=None, scope=None, source_kind="novel", brief=None):
    _editor()
    from scripts.run_natural_director_v10 import _check_authorization_file
    from src.content_factory import visual_storytelling_v1 as pacing
    authorization = _check_authorization_file(authorization_path).resolve()
    return pacing.prepare_source(Path(source_run_dir).resolve(), runtime=_runtime(), authorization_path=authorization,
        source_path=Path(source_path).resolve() if source_path else None,
        acquisition_receipt=Path(acquisition_receipt).resolve() if acquisition_receipt else None,
        title=title or None, scope=scope or None, source_kind=source_kind, brief=brief)


def _admit(view):
    if (view.get("dispatch_blocked") or view.get("blockers") or view.get("pending_call")
            or view.get("status") not in {"prepared", "running", "needs_full_revision", "text_ready_for_director"}):
        raise RuntimeError("任务存在停止或未决条件，请查看原记录，不能重复启动")


def _execution_active(*folders):
    """Only check lock existence; opening mutable state can block Windows replace."""
    return any((Path(folder) / name).exists() for folder in folders
               for name in (".execution.lock", ".graph_driver.lock"))


def _require_idle(*folders):
    if _execution_active(*folders):
        raise RuntimeError("任务正在执行，等待原执行锁释放后刷新，不能重复启动")


def _last_immutable_checkpoint(folder):
    """Presentation snapshot only: never follow active artifacts or read state.json."""
    run = Path(folder).resolve()
    for path in sorted(run.glob("STATE_*.json"), reverse=True):
        if not re.fullmatch(r"STATE_\d{5}\.json", path.name) or path.resolve().parent != run:
            continue
        try:
            raw = path.read_bytes()
            value = json.loads(raw)
        except (OSError, ValueError, UnicodeError):
            continue
        if not isinstance(value, dict):
            continue
        fields = ("schema", "status", "stage", "calls_started", "rounds_started",
                  "known_reported_tokens", "reported_tokens", "pending_call", "halt_reason")
        return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                "checkpoint_summary": {key: value[key] for key in fields if key in value},
                "presentation_only": True, "current_state_verified": False}
    return None


def _render_inflight(folder):
    st.write("状态：", "正在执行，等待原任务完成")
    st.code(str(folder), language=None)
    st.caption("执行期间只显示最后完整不可变检查点和原日志；检查点摘要不代表当前状态已核验。锁释放后刷新查看正式记录。")
    snapshot = _last_immutable_checkpoint(folder)
    if snapshot:
        st.json(snapshot)
    else:
        st.info("尚无完整不可变检查点，保留原任务等待结果。")


def launch_source(source_run_dir, run_dir, *, authorization_path):
    """Background is a thin CLI wrapper; all actual dispatch is admitted by runtime."""
    _editor()
    from scripts.run_natural_director_v10 import _check_authorization_file
    authorization = _check_authorization_file(authorization_path).resolve()
    source, run = Path(source_run_dir).resolve(), Path(run_dir).resolve()
    _require_idle(source, run)
    runtime = _runtime()
    _admit(runtime.inspect_source(source))
    marker = source / ".natural_web_launch.lock"
    receipt_path = source / "NATURAL_LAST_LAUNCH.json"
    if receipt_path.exists():
        raise RuntimeError("原后台任务已提交，请刷新原记录，不能重复启动")
    try:
        with marker.open("x", encoding="utf-8") as handle:
            json.dump({"owner": "natural_director_web_v10", "automatic_media_submit": False}, handle)
    except FileExistsError:
        raise RuntimeError("原后台任务已提交，请刷新原记录，不能重复启动") from None
    spawned = False
    try:
        _require_idle(source, run)
        _admit(runtime.inspect_source(source))
        _require_idle(source, run)
        _admit(runtime.preview_source(source))
        _require_idle(source, run)
        argv = [sys.executable, str(CLI), "source-execute", "--source-run-dir", str(source),
                "--run-dir", str(run), "--authorization-path", str(authorization)]
        log = source / "natural_execution.log"
        with log.open("ab") as output:
            process = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output,
                stderr=output, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        spawned = True
        receipt = {"pid": process.pid, "command": argv, "log_path": str(log),
                   "automatic_retry": False, "automatic_media_submit": False}
        with receipt_path.open("x", encoding="utf-8") as handle:
            json.dump(receipt, handle, ensure_ascii=False, indent=2)
        return receipt
    except Exception:
        if not spawned:
            marker.unlink(missing_ok=True)
        raise


def artifact_files(folder):
    run = Path(folder).resolve()
    if _execution_active(run):
        return []
    paths = set(history.artifact_files(run))
    for pattern in ("NATURAL*.md", "EXTRACT*.json", "EXTRACTION*.json", "FINAL_REVIEW*.json", "FINAL_REQUEST*.json"):
        paths.update(p for p in run.glob(pattern) if p.is_file() and p.resolve().is_relative_to(run))
    return sorted(paths)


def _render_records(source, run):
    runtime = None
    for label, folder, method in (("编剧与同源全文审核", source, "inspect_source"),
                                  ("自然导演、忠实整理与最终请求整包审核", run, "inspect")):
        with st.expander(label, expanded=True):
            if _execution_active(source, run):
                _render_inflight(folder)
                continue
            runtime = runtime or _runtime()
            report = getattr(runtime, method)(folder)
            status = report.get("status", "未知")
            st.write("状态：", STATUSES.get(status, status))
            st.code(str(folder), language=None)
            st.json(report)
            if _execution_active(source, run):
                _render_inflight(folder)
                continue
            for path in artifact_files(folder):
                if _execution_active(source, run):
                    _render_inflight(folder)
                    break
                with st.expander(path.name):
                    st.code(str(path), language=None)
                    if path.suffix == ".md":
                        st.markdown(path.read_text(encoding="utf-8"))
                    else:
                        st.json(history._read(path))
    history._log(source / "natural_execution.log", "后台文本日志")


def _render_legacy_records(folder):
    run = Path(folder).resolve()
    if _execution_active(run):
        _render_inflight(run)
        history._log(run / "natural_execution.log", "原任务日志")
        return
    runtime, _ = history._runtime(run)
    history._outputs(run, runtime.inspect(run), runtime.preview(run))


def page_story_workflow(source_kind="novel"):
    if source_kind not in {"novel", "original"}:
        raise ValueError("未知来源类型")
    original = source_kind == "original"
    prefix = "natural_director_v10_" + source_kind
    st.title("原创剧情" if original else "小说改编")
    st.caption("完整剧本与同源审核 → MiniMax自然导演 → DeepSeek忠实整理 → 全部实际请求整包审核")
    st.info("新任务共用自然文本导演流程。编剧审核完成后直接进入自然导演，不再让编剧生成重复的重型导演JSON。只输出文本与请求预览，实际视频由用户人工审核。")
    st.caption("已知完整结果若遇本地状态投影故障，或全文审核的重复问题包装故障，系统核验证据后各自动恢复一次；未知、截断和未决请求保持停止，不重复派发。")
    editor = has_permission(get_current_role(), "editor")
    state = st.session_state
    if not original:
        history._acquisition_section(editor, state, prefix)
    if prefix + "_workspace" not in state:
        state[prefix + "_workspace"] = str(RUNS / source_kind / uuid4().hex)
    workspace = Path(st.text_input("本次任务保存位置", key=prefix + "_workspace")).resolve()
    source, natural = workspace / "writer", workspace / "director"
    authorization = st.text_input("本任务已登记授权记录绝对路径", key=prefix + "_authorization")
    st.caption("每个新来源核对自己的授权、轮数与总预算；当前渡口的两批五轮授权不能用于其他来源。旧消耗、失败和未知请求保留。")
    with st.expander("来源与创作要求", expanded=True):
        choices = {} if original else {item["path"]: item for item in history.discover_sources(history.SOURCE_ROOTS)}
        selected = ""
        if not original:
            selected = st.selectbox("已保存小说 / 采集回执", [""] + list(choices), key=prefix + "_saved",
                format_func=lambda value: "请选择" if not value else f"{choices[value]['title']} · {choices[value]['status']} · {value}")
        raw = st.text_area("原创简报全文（或使用下方文件）", key=prefix + "_text") if original else ""
        path_text = st.text_input("创作简报正文绝对路径" if original else "已获取小说正文 / 采集回执绝对路径", key=prefix + "_source")
        title = st.text_input("项目标题", key=prefix + "_title")
        scope = st.text_input("实际来源范围", value="创作简报全文" if original else "", key=prefix + "_scope")
        target = int(st.number_input("参考成片时长（秒）", min_value=4, max_value=900, value=120, key=prefix + "_duration"))
        st.caption("按有效内容结束：对白、必要动作和关键反应完成即收段；普通回看随对白并行，不额外留空尾。参考时长不用于补动作凑秒。")
        st.caption("逐句按说话状态核对发音量、声音时长与必要停连；情绪尽量随对白显现，台词后默认不加停留。估时不替代实际声音审查。")
        st.caption("新任务统一采用视觉叙事规范：开场信息、可见情绪、动作对白并行、关系互动、来源环境、光影动机与镜头连续；编剧到最终提示词共同审核。成片仍需人工验收。")
        goal = st.text_area("希望观众理解的内容与节奏要求", key=prefix + "_goal")
        if st.button("准备与冻结新来源（不调用模型）", disabled=not editor, key=prefix + "_prepare"):
            try:
                _editor()
                from scripts.run_natural_director_v10 import _check_authorization_file
                _check_authorization_file(authorization)
                chosen = path_text.strip() or selected
                if bool(raw.strip()) == bool(chosen):
                    raise ValueError("请选择填写全文或使用一个实际来源文件")
                path = Path(chosen).resolve() if chosen else None
                if raw.strip():
                    inputs = ROOT / "data/novel_adaptation/natural_v10_inputs"
                    inputs.mkdir(parents=True, exist_ok=True)
                    path = inputs / (uuid4().hex + ".txt")
                    with path.open("x", encoding="utf-8") as handle:
                        handle.write(raw)
                receipt = path if not original and path.suffix.lower() == ".json" else None
                if not original and selected and not path_text.strip() and choices[selected]["kind"] == "metadata":
                    bridge = history.import_saved_book(path, history.ACQUISITIONS / uuid4().hex)
                    receipt = Path(bridge["receipt_path"])
                report = prepare_source(source, authorization_path=authorization,
                    source_path=None if receipt else path, acquisition_receipt=receipt,
                    title=title, scope=scope, source_kind=source_kind,
                    brief={"source_kind": source_kind, "target_duration_seconds": target, "audience_goal": goal})
                st.json(report)
                st.success("来源、创作要求及专属授权已冻结。")
            except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
                st.error(str(exc))
    if st.button("后台运行完整文本流程", disabled=not editor or not authorization.strip(), key=prefix + "_execute"):
        try:
            st.json(launch_source(source, natural, authorization_path=authorization))
            st.success("后台已提交一次，编剧全文审查后统一进入自然导演及最终请求审核。")
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
            st.error(str(exc))
    st.button("刷新原任务状态", key=prefix + "_refresh")
    try:
        _render_records(source, natural)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        st.error(str(exc))
    with st.expander("查看旧版本记录", expanded=False):
        st.caption("旧 v7/v8/v9 冻结只读查看，不能由本页新建或重新派发旧重JSON导演。")
        old = st.text_input("旧任务绝对路径", key=prefix + "_history")
        if old.strip():
            try:
                _render_legacy_records(old)
            except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
                st.error(str(exc))


def page_novel_adaptation():
    page_story_workflow("novel")


def page_original_story():
    page_story_workflow("original")
