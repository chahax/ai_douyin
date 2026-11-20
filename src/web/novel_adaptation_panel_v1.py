"""Standalone novel adaptation page; no account or opportunity database."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import streamlit as st

from src.content_factory.novel_adaptation_acquisition_v1 import discover_sources, import_saved_book
from src.web.components.auth import get_current_role, has_permission

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "data/novel_adaptation/plaintext_v3"
ACQUISITIONS = ROOT / "data/novel_adaptation/acquisitions_v1"
SOURCE_ROOTS = (ROOT / "data/fanqie_promotion/books",
                ROOT / "data/novel_platform_trials", ACQUISITIONS)
STAGES = {"analysis": "背景、角色与故事线分析", "adaptation_plan": "高潮选择与改编规划",
          "screenplay": "完整剧本", "writer": "MiniMax完整创作稿", "writer_full": "MiniMax完整创作稿",
          "review_full": "DeepSeek全文审核",
          "review": "DeepSeek同稿全文复审", "complete": "文本导演交接"}
STATUSES = {"unprepared": "尚未准备", "prepared": "准备完成",
            "running": "文本创作中", "text_ready_for_director": "剧本与机器全文复审已完成，待后续导演制作",
            "needs_attention": "已停止，请查看问题记录", "blocked": "当前任务禁止继续派发",
            "legacy_dispatch_blocked": "历史试跑已停止；保留原消耗，当前仅可预览",
            "evidence_invalid": "来源或运行证据校验未通过",
            "content_revision_exhausted": "内容返修次数已用完，已保存停点",
            "needs_full_revision": "等待有界整稿返修",
            "incomplete_artifacts": "产物或绑定校验未通过"}


def _editor():
    if not has_permission(get_current_role(), "editor"):
        raise PermissionError("启动采集或文本创作需要编辑权限")


def _spawn(argv, log_path):
    with log_path.open("ab") as handle:
        process = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=handle, stderr=handle,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {"pid": process.pid, "command": argv, "log_path": str(log_path),
            "automatic_media_submit": False}


def _runtime(run_dir):
    """Select by frozen binding, never upgrade or dispatch a legacy task."""
    binding = Path(run_dir) / "BINDING.json"
    if binding.is_file():
        value = json.loads(binding.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("冻结任务绑定格式无效，不能迁移或派发")
        schema = value.get("schema")
    else:
        schema = "novel_plaintext_pipeline/v3"
    if schema == "novel_plaintext_pipeline/v3":
        from src.content_factory import novel_plaintext_pipeline_v3 as pipeline
        return pipeline, False
    if schema == "novel_adaptation_pipeline/v1":
        from src.content_factory import novel_adaptation_pipeline_v1 as pipeline
        return pipeline, True
    if schema == "novel_adaptation_production/v2":
        from src.content_factory import novel_adaptation_production_v2 as pipeline
        return pipeline, True
    raise ValueError("未知的冻结任务版本；仅保留原记录，不能迁移或派发")


def launch_text(run_dir) -> dict:
    """An exclusive web submission; pending and terminal tasks never respawn."""
    _editor()
    run = Path(run_dir).resolve()
    pipeline, legacy = _runtime(run)
    if legacy:
        raise RuntimeError("历史版本任务在本页只读，不能重新派发或迁移；请查看原记录")
    report = pipeline.inspect(run)
    allowed = {"prepared", "running", "needs_full_revision"}
    if report.get("dispatch_blocked") or report.get("status") not in allowed:
        raise RuntimeError("任务未准备、已结束或存在停止条件；请查看原记录")
    if (report.get("pending_call") or report.get("pending") or report.get("blockers")
            or (report.get("state") or {}).get("pending_call") is not None):
        raise RuntimeError("任务存在未决调用或阻断条件，不能重复启动")
    pipeline.preview(run)
    marker = run / ".web_launch.lock"
    if (run / "LAST_LAUNCH.json").exists():
        raise RuntimeError("原后台任务已经提交，请刷新其记录；不重复启动")
    try:
        with marker.open("x", encoding="utf-8") as handle:
            json.dump({"owner": "novel_adaptation_web", "automatic_media_submit": False}, handle)
    except FileExistsError:
        raise RuntimeError("原后台任务已经提交，请刷新其记录；不重复启动") from None
    argv = [sys.executable, str(ROOT / "scripts/run_novel_plaintext_v3.py"),
            "execute", "--run-dir", str(run)]
    try:
        receipt = _spawn(argv, run / "execution.log")
    except Exception:
        marker.unlink()
        raise
    with (run / "LAST_LAUNCH.json").open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2)
    return receipt


def launch_acquisition(job_dir, *, book_name, book_id="", chapters=1) -> dict:
    _editor()
    if not str(book_name).strip() or type(chapters) is not int or not 1 <= chapters <= 100:
        raise ValueError("请填写书名，章节数须为 1–100")
    job = Path(job_dir).resolve()
    job.mkdir(parents=True, exist_ok=False)
    output = job / "source"
    argv = [sys.executable, str(ROOT / "scripts/run_novel_adaptation_v1.py"), "fetch",
            "--output-dir", str(output), "--book-name", book_name,
            "--chapters", str(chapters)]
    if book_id:
        argv.extend(["--book-id", str(book_id)])
    try:
        receipt = _spawn(argv, job / "acquisition.log")
    except Exception as exc:
        with (job / "LAUNCH_ERROR.json").open("x", encoding="utf-8") as handle:
            json.dump({"status": "launch_failed", "error": str(exc), "automatic_retry": False},
                      handle, ensure_ascii=False, indent=2)
        raise
    receipt["receipt_path"] = str(output / "RECEIPT.json")
    with (job / "LAST_LAUNCH.json").open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2)
    return receipt


def _log(path: Path, label: str):
    if path.is_file():
        with st.expander(label):
            st.code(str(path), language=None)
            st.code(path.read_text(encoding="utf-8", errors="replace")[-16000:])


def scope_label(scope) -> str:
    if not isinstance(scope, dict):
        return str(scope or "未知")
    parts = []
    if scope.get("acquired_chapters") is not None:
        parts.append(f"已保存 {scope['acquired_chapters']} 章")
    if scope.get("chapter_titles"):
        parts.append("、".join(str(item) for item in scope["chapter_titles"]))
    if scope.get("scope_note"):
        parts.append(str(scope["scope_note"]))
    if "start_character" in scope or "end_character" in scope:
        parts.append(f"本次选段范围 {scope.get('start_character', 0)}–{scope.get('end_character', '正文末尾')}")
    return "；".join(parts) or "仅当前已保存正文，未确认全书范围"


def _outputs(run: Path, report: dict):
    st.write("状态：", STATUSES.get(report.get("status"), report.get("status", "未知")))
    stage = report.get("stage")
    if stage:
        st.write("当前阶段：", STAGES.get(stage, stage))
    source = report.get("source") or {}
    if source:
        st.write("小说：", source.get("title", ""))
        st.write("正文范围：", scope_label(source.get("scope")))
    if report.get("blockers"):
        st.warning("；".join(str(item) for item in report["blockers"]))
    tokens = report.get("reported_tokens")
    usage = (f"{tokens} tokens" if tokens is not None else
             f"未知（已确认累计 {report.get('known_reported_tokens', '未知')} tokens）")
    st.caption(f"本入口新增调用 {report.get('calls_started', 0)} 次 · 用量 {usage} · 人工采用尚未确认")
    history = report.get("state") or {}
    legacy = report.get("legacy_consumption") or {
        "calls_started": history.get("legacy_calls_started", 0),
        "reported_tokens": history.get("legacy_reported_tokens"),
    }
    if legacy.get("calls_started"):
        st.caption(f"历史任务保留 {legacy['calls_started']} 次调用、"
                   f"{legacy.get('reported_tokens', '未知')} tokens；停止记录与原预算继续有效。")
    if "combined_calls_started" in report:
        st.caption(f"含历史累计 {report['combined_calls_started']} 次调用、"
                   f"已确认 {report.get('combined_known_reported_tokens', '未知')} tokens。")
    with st.expander("完整运行记录与产物位置"):
        st.json(report)
    # Only display accepted artifacts from a fully reverified completion report.
    if report.get("status") == "text_ready_for_director":
        artifacts = report.get("artifacts", [])
        if isinstance(artifacts, dict):
            artifacts = artifacts.values()
        for item in artifacts:
            path = Path(item["path"] if isinstance(item, dict) else item)
            if not path.is_absolute():
                path = run / path
            if path.name == "SCREENPLAY.md" and path.is_file():
                with st.expander("完整阅读剧本", expanded=True):
                    st.code(str(path.resolve()), language=None)
                    st.markdown(path.read_text(encoding="utf-8"))
            elif path.name == "FULL_TEXT_REVIEW.json" and path.is_file():
                with st.expander("DeepSeek全文审核结果", expanded=True):
                    st.code(str(path.resolve()), language=None)
                    st.json(json.loads(path.read_text(encoding="utf-8")))
    _log(run / "execution.log", "后台文本日志")


def page_novel_adaptation():
    st.title("小说改编")
    st.caption("获取正文 → 背景、角色与故事线 → 高潮选择与改编规划 → 完整剧本 → 全文复审")
    st.info("改编可重写对白、合并场景和压缩支线，须保留主线与关键因果。本页推进到文本导演交接，不生成视频。")
    st.caption("新任务由 MiniMax 输出完整原生文本，DeepSeek 对照正文全文审核；无需填写来源哈希或逐句引用。机器通过不等于人工采用。")
    editor = has_permission(get_current_role(), "editor")
    state = st.session_state
    if "novel_adaptation_run" not in state:
        state["novel_adaptation_run"] = str(RUNS / uuid4().hex)
    if "novel_adaptation_fetch_job" not in state:
        state["novel_adaptation_fetch_job"] = str(ACQUISITIONS / uuid4().hex)

    with st.expander("1. 获取正文", expanded=True):
        st.caption("采集使用项目采集器自己的登录窗口；独立 Chrome 的登录态不会自动共享。遇到登录或验证即保存停点，请查看采集回执。")
        book_name = st.text_input("小说名称", key="novel_adaptation_fetch_name")
        book_id = st.text_input("书籍 ID（已知时填写）", key="novel_adaptation_fetch_id")
        chapters = int(st.number_input("本次获取章节数", min_value=1, max_value=100, value=1))
        job = Path(state["novel_adaptation_fetch_job"])
        if st.button("获取正文（打开采集器窗口）", disabled=not editor or job.exists()):
            try:
                launch_acquisition(job, book_name=book_name, book_id=book_id, chapters=chapters)
                st.success("已提交一次采集，请刷新查看采集回执和日志。")
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
        receipt = job / "source/RECEIPT.json"
        if receipt.is_file():
            result = json.loads(receipt.read_text(encoding="utf-8"))
            if result.get("status") == "source_saved":
                st.success("正文已保存，可以在下方选择本次采集回执。")
            else:
                st.warning("采集未成功，已停止；需要在采集器窗口处理登录、验证或记录中的错误。")
            with st.expander("本次采集回执"):
                st.code(str(receipt), language=None)
                st.json(result)
        _log(job / "acquisition.log", "采集日志")
        if job.exists() and st.button("建立新的采集工作区", disabled=not editor):
            state["novel_adaptation_fetch_job"] = str(ACQUISITIONS / uuid4().hex)
            st.rerun()

    with st.expander("2. 选择已保存正文并准备", expanded=True):
        candidates = discover_sources(SOURCE_ROOTS)
        choices = {item["path"]: item for item in candidates}
        selected = st.selectbox("已保存小说或采集回执", [""] + list(choices),
                                format_func=lambda p: "请选择" if not p else
                                f"{choices[p]['title']} · {choices[p]['status']} · {p}")
        manual = st.text_input("或填写采集回执 / 纯正文绝对路径", key="novel_adaptation_source_path")
        title = st.text_input("本次改编标题（可选）", key="novel_adaptation_title")
        scope = st.text_input("实际章节 / 选段范围（纯正文必填）", key="novel_adaptation_scope")
        run = Path(st.text_input("任务保存位置 / 原任务位置", key="novel_adaptation_run")).resolve()
        if st.button("准备与冻结输入（不调用模型）", disabled=not editor):
            try:
                pipeline, legacy = _runtime(run)
                if legacy:
                    raise RuntimeError("已有历史任务只能查看；不能用新流程覆盖原冻结或重新派发")
                path = Path(manual or selected).resolve()
                kwargs = {"title": title or None, "scope": scope or None}
                if not (manual or selected):
                    raise ValueError("请选择已保存正文或填写实际文件路径")
                if selected and not manual and choices[selected]["kind"] == "metadata":
                    bridge = import_saved_book(path, ACQUISITIONS / uuid4().hex)
                    kwargs["acquisition_receipt"] = Path(bridge["receipt_path"])
                elif path.suffix.lower() == ".json":
                    kwargs["acquisition_receipt"] = path
                else:
                    kwargs["source_path"] = path
                result = pipeline.prepare(run, **kwargs)
                if result.get("dispatch_blocked"):
                    st.warning("准备记录已保存，当前存在阻断条件；请查看原记录，本次不启动创作。")
                else:
                    st.success("已保存准备结果；下一步检查范围并启动文本创作。")
                with st.expander("准备记录"):
                    st.json(result)
            except (ValueError, RuntimeError, OSError, KeyError) as exc:
                st.error(str(exc))

    with st.expander("3. 文本创作与结果", expanded=True):
        st.code(str(run), language=None)
        st.button("刷新原任务状态与产物")
        try:
            pipeline, legacy = _runtime(run)
            report = pipeline.inspect(run)
            if report.get("status") != "unprepared":
                if legacy:
                    st.info("当前为历史冻结版本，仅查看原状态和产物；本页不会迁移或重新派发。")
                with st.expander("冻结范围与请求预览（不调用模型）"):
                    st.json(pipeline.preview(run))
                disabled = (not editor or legacy or report.get("dispatch_blocked", False)
                            or report.get("status") not in {"prepared", "needs_full_revision", "running"}
                            or (run / ".web_launch.lock").exists())
                if st.button("后台生成完整剧本并全文复审", disabled=disabled):
                    launch_text(run)
                    st.success("后台文本任务已提交，请刷新查看阶段和产物。")
                _outputs(run, report)
        except (ValueError, RuntimeError, OSError, KeyError) as exc:
            st.error(str(exc))
    if not editor:
        st.caption("当前只有查看权限；获取正文、准备和创作需编辑权限。")
