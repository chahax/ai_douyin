"""Novel Agent v6 workspace, from saved source to director production handoff."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import streamlit as st

from src.content_factory.novel_adaptation_acquisition_v1 import discover_sources, import_saved_book
from src.web.components.auth import get_current_role, has_permission

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "data/novel_adaptation/agent_v6"
ACQUISITIONS = ROOT / "data/novel_adaptation/acquisitions_v6"
SOURCE_ROOTS = (ROOT / "data/fanqie_promotion/books", ROOT / "data/novel_platform_trials",
                ROOT / "data/novel_adaptation/acquisitions_v1", ACQUISITIONS)
VERSION = "novel_agent_pipeline/v6"
LEGACY_SCHEMAS = {
    "novel_adaptation_pipeline/v1": "novel_adaptation_pipeline_v1",
    "novel_adaptation_production/v2": "novel_adaptation_production_v2",
    "novel_plaintext_pipeline/v3": "novel_plaintext_pipeline_v3",
    "novel_agent_pipeline/v5": "novel_agent_pipeline_v5",
}
ALLOWED_START = {"prepared", "running", "needs_full_revision"}
STAGES = {"writer_full": "MiniMax 完整创作", "review_full": "DeepSeek 场记与同源全文审核",
          "clarify_full": "问题核实与同稿全文复审", "director_full": "导演分段与表演设计",
          "director_review": "导演全文审核", "complete": "制作交接完成"}
STATUSES = {
    "unprepared": "尚未准备", "prepared": "准备完成", "running": "文本流程进行中",
    "needs_full_revision": "等待有界整稿返修", "needs_attention": "已停止，请查看问题记录",
    "text_ready_for_director": "机器文本完成，待导演制作",
    "text_ready_for_production": "导演剧本及制作交接已完成，待后续制作",
    "content_revision_exhausted": "完整稿返修上限已到，已保存停点",
    "director_revision_exhausted": "导演稿返修上限已到，已保存停点",
    "legacy_dispatch_blocked": "原任务停止条件继续有效，当前仅可查看",
    "evidence_invalid": "输入或运行证据校验未通过", "incomplete_artifacts": "产物完整性校验未通过",
    "blocked": "当前任务禁止继续派发", "legacy_read_only": "历史离线诊断，只读查看",
}


def _pairs(rows):
    result = {}
    for key, value in rows:
        if key in result:
            raise ValueError("记录含重复字段，不能判断任务版本")
        result[key] = value
    return result


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_pairs)


def _editor():
    if not has_permission(get_current_role(), "editor"):
        raise PermissionError("获取正文、准备和启动文本流程需要编辑权限")


class _LegacyDiagnostics:
    """v4 is a local diagnostic, with no dispatch API to upgrade or resume."""
    @staticmethod
    def inspect(run_dir):
        run = Path(run_dir)
        values = {}
        for name in ("BINDING.json", "STATE.json", "state.json", "RESULT.json", "GATE_DECISION.json"):
            path = run / name
            if path.is_file():
                values[name] = _read(path)
        return {"status": "legacy_read_only", "dispatch_blocked": True,
                "automatic_media_submit": False, "original_records": values}

    preview = inspect


def _runtime(run_dir):
    """Route by the immutable binding; all old versions remain read only here."""
    import importlib
    binding = Path(run_dir) / "BINDING.json"
    if binding.is_file():
        value = _read(binding)
        if not isinstance(value, dict):
            raise ValueError("冻结任务绑定格式无效，不能迁移或派发")
        schema = value.get("schema") or value.get("schema_version")
    else:
        schema = VERSION
    if schema == VERSION:
        return importlib.import_module("src.content_factory.novel_agent_pipeline_v6"), False
    if schema in LEGACY_SCHEMAS:
        return importlib.import_module("src.content_factory." + LEGACY_SCHEMAS[schema]), True
    if schema in {"novel_logic_workflow/v4", "novel_logic_workflow_v4", "novel_logic/v4"}:
        return _LegacyDiagnostics, True
    raise ValueError("未知的冻结任务版本；保留原记录，不能迁移或派发")


def _spawn(argv, log_path):
    with log_path.open("ab") as handle:
        process = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=handle, stderr=handle,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {"pid": process.pid, "command": argv, "log_path": str(log_path),
            "automatic_media_submit": False, "automatic_retry": False}


def _admit(report):
    state = report.get("state") or {}
    if report.get("dispatch_blocked") or report.get("status") not in ALLOWED_START:
        raise RuntimeError("任务未准备、已结束或存在停止条件；请查看原记录")
    if (report.get("pending_call") or report.get("pending") or state.get("pending_call")
            or report.get("blockers")):
        raise RuntimeError("任务有未决请求或阻断条件，只能查看原请求结果，不能重复启动")


def launch_text(run_dir):
    """One hidden process per web submission, including races and unknown starts."""
    _editor()
    run = Path(run_dir).resolve()
    pipeline, legacy = _runtime(run)
    if legacy:
        raise RuntimeError("历史版本在本页只读；不能重新派发或迁移")
    _admit(pipeline.inspect(run))
    marker = run / ".web_launch.lock"
    if (run / "LAST_LAUNCH.json").exists():
        raise RuntimeError("原后台任务已经提交，请刷新原记录，不能重复启动")
    try:
        with marker.open("x", encoding="utf-8") as handle:
            json.dump({"owner": "novel_agent_web_v6", "automatic_media_submit": False}, handle)
    except FileExistsError:
        raise RuntimeError("原后台任务已经提交，请刷新原记录，不能重复启动") from None
    spawned = False
    try:
        # Admission is checked again after winning the lock, not only in the UI.
        _admit(pipeline.inspect(run))
        preview = pipeline.preview(run)
        if preview.get("dispatch_blocked") or preview.get("blockers"):
            raise RuntimeError("请求预览显示停止条件，后台任务没有启动")
        argv = [sys.executable, str(ROOT / "scripts/run_novel_agent_v6.py"),
                "execute", "--run-dir", str(run)]
        receipt = _spawn(argv, run / "execution.log")
        spawned = True
        with (run / "LAST_LAUNCH.json").open("x", encoding="utf-8") as handle:
            json.dump(receipt, handle, ensure_ascii=False, indent=2)
        return receipt
    except Exception:
        if not spawned:
            marker.unlink(missing_ok=True)
        # After a process has been created, keep the marker even if receipt
        # storage fails; its outcome must be inspected rather than respawned.
        raise


def launch_acquisition(job_dir, *, book_name, book_id="", chapters=1):
    _editor()
    if not str(book_name).strip() or type(chapters) is not int or not 1 <= chapters <= 100:
        raise ValueError("请填写书名，章节数须为 1–100 的整数")
    job = Path(job_dir).resolve()
    job.mkdir(parents=True, exist_ok=False)
    argv = [sys.executable, str(ROOT / "scripts/run_novel_agent_v6.py"), "fetch",
            "--output-dir", str(job / "source"), "--book-name", book_name.strip(),
            "--chapters", str(chapters)]
    if book_id:
        argv += ["--book-id", str(book_id)]
    try:
        receipt = _spawn(argv, job / "acquisition.log")
        receipt["receipt_path"] = str(job / "source/RECEIPT.json")
        with (job / "LAST_LAUNCH.json").open("x", encoding="utf-8") as handle:
            json.dump(receipt, handle, ensure_ascii=False, indent=2)
        return receipt
    except Exception as exc:
        with (job / "LAUNCH_ERROR.json").open("x", encoding="utf-8") as handle:
            json.dump({"status": "launch_failed", "error": str(exc), "automatic_retry": False},
                      handle, ensure_ascii=False, indent=2)
        raise


def prepare_continuation(run_dir, *, parent_run):
    """Explicit local continuation preparation, never a budget override or dispatch."""
    _editor()
    run, parent = Path(run_dir).resolve(), Path(parent_run).resolve()
    value = _read(parent / "BINDING.json")
    if not isinstance(value, dict) or value.get("schema") != "novel_agent_pipeline/v5":
        raise ValueError("此续行入口只接受明确的 v5 格式停点；其他历史任务保留原入口")
    pipeline, legacy = _runtime(run)
    if legacy:
        raise RuntimeError("新 v6 目录不能覆盖历史冻结任务")
    return pipeline.prepare_continuation(run, parent_run=parent)


def recover_projection(run_dir):
    """Restore local state only; pending request admission is checked afterwards."""
    _editor()
    run = Path(run_dir).resolve()
    pipeline, legacy = _runtime(run)
    if legacy:
        raise RuntimeError("历史冻结任务只能查看，不能通过 v6 恢复或迁移")
    report = pipeline.inspect(run)
    if report.get("projection_recovery_available") is not True:
        raise RuntimeError("当前没有已核实可恢复的本地状态，保留原停止记录")
    return pipeline.recover_projection(run)


def scope_label(value):
    if not isinstance(value, dict):
        return str(value or "仅已保存选段，未取得全书")
    parts = []
    if value.get("acquired_chapters") is not None:
        parts.append(f"已保存 {value['acquired_chapters']} 章")
    parts.extend(str(item) for item in value.get("chapter_titles", []))
    if value.get("scope_note"):
        parts.append(str(value["scope_note"]))
    return "；".join(parts) or "仅已保存选段，未取得全书"


def _log(path, label):
    if path.is_file():
        with st.expander(label):
            st.code(str(path), language=None)
            st.code(path.read_text(encoding="utf-8", errors="replace")[-16000:])


def artifact_files(run_dir):
    """Only presentation artifacts inside this run; never native thinking/envelopes."""
    run = Path(run_dir).resolve()
    patterns = ("DRAFT_*.md", "SCREENPLAY.md", "FULL_TEXT_REVIEW.json", "REVIEW_*.json",
                "SCENE_LEDGER*.json", "ADJUDICATION*.json", "DISPOSITION*.json", "GATE*.json",
                "DIRECTOR*.md", "DIRECTOR*.json", "PRODUCTION_HANDOFF*.json",
                "PRODUCTION_HANDOFF*.md", "OUTPUT_MANIFEST.json", "EPISODE.json")
    paths = set()
    for pattern in patterns:
        for path in run.glob(pattern):
            if path.is_file() and path.resolve().is_relative_to(run):
                paths.add(path)
    return sorted(paths, key=lambda path: path.name)


def inherited_draft_file(run_dir, report):
    """Read the exact audited v5 draft without copying or editing its evidence."""
    if report.get("schema") != VERSION or report.get("status") in {"evidence_invalid", "incomplete_artifacts"}:
        return None
    binding = Path(run_dir) / "BINDING.json"
    if not binding.is_file():
        return None
    continuation = _read(binding).get("continuation")
    if not continuation:
        return None
    parent = Path(continuation["parent_run"]).resolve()
    evidence = continuation["writer"]["file"]
    path = Path(evidence["path"]).resolve()
    if not path.is_relative_to(parent) or not path.match("DRAFT_*.md"):
        raise ValueError("承接完整稿的原文件位置无效")
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != evidence["sha256"]:
        raise ValueError("承接完整稿的原文件内容已变")
    return path


def _outputs(run, report, preview):
    st.write("状态：", STATUSES.get(report.get("status"), report.get("status", "未知")))
    state = report.get("state") or {}
    stage = report.get("stage") or state.get("stage") or "尚未启动"
    st.write("当前阶段：", STAGES.get(stage, stage))
    source = report.get("source") or {}
    if source:
        st.write("小说：", source.get("title") or source.get("book_name") or "未知")
        st.write("正文范围：", scope_label(source.get("scope") or report.get("scope")))
    if report.get("blockers"):
        st.warning("；".join(str(item) for item in report["blockers"]))
    calls = report.get("calls_started", state.get("calls_started", 0))
    tokens = report.get("reported_tokens")
    known = report.get("known_reported_tokens", state.get("known_reported_tokens", "未知"))
    st.caption(f"本版本已启动 {calls} 次实际调用；用量 " +
               (f"{tokens} tokens" if tokens is not None else f"已确认 {known} tokens，完整用量见原记录"))
    if report.get("combined_calls_started") is not None:
        st.caption(f"含原版本累计 {report['combined_calls_started']} 次调用、已确认 "
                   f"{report.get('combined_known_reported_tokens', '未知')} tokens；"
                   f"原预算承接后剩余 {preview.get('remaining_calls', '未知')} 次调用。")
    if report.get("pending_call") or state.get("pending_call"):
        st.warning("存在未决请求；保留原请求身份，不重新提交。")
        st.json(report.get("pending_call") or state.get("pending_call"))
    with st.expander("原任务状态、预算与停止证据"):
        st.code(str(run), language=None)
        st.json(report)
        st.json(preview)
    files = artifact_files(run)
    if files:
        st.caption("下列文件包含历次完整稿和审核结果；保存成功不表示内容通过，采用状态以本稿放行决定为准。")
    inherited = inherited_draft_file(run, report)
    if inherited is not None and inherited not in files:
        with st.expander("原 v5 完整创作稿（保留原文件与原审核）", expanded=True):
            st.code(str(inherited), language=None)
            st.markdown(inherited.read_text(encoding="utf-8"))
    for path in files:
        with st.expander(path.name, expanded=path.name == "SCREENPLAY.md"):
            st.code(str(path.resolve()), language=None)
            if path.suffix == ".md":
                st.markdown(path.read_text(encoding="utf-8"))
            else:
                st.json(_read(path))
    _log(run / "execution.log", "后台文本日志")


def page_novel_adaptation():
    st.title("小说改编")
    st.caption("获取正文 → 背景、角色、主线与高潮 → 完整剧本 → 场记与全文审核 → 问题核实 → 导演分段与制作交接")
    st.info("新任务使用 v6 文本流程；MiniMax 创作、DeepSeek 同源全文审核。当前页面推进至导演制作交接，视频另按人工审核流程执行。")
    editor = has_permission(get_current_role(), "editor")
    state = st.session_state
    if "novel_agent_v6_run" not in state:
        state["novel_agent_v6_run"] = str(RUNS / uuid4().hex)
    if "novel_agent_v6_acquisition" not in state:
        state["novel_agent_v6_acquisition"] = str(ACQUISITIONS / uuid4().hex)

    with st.expander("1. 获取正文", expanded=True):
        st.caption("采集器使用自己的登录窗口，遇到登录或验证会保存停点。也可直接使用下方已保存正文。")
        book_name = st.text_input("小说名称", key="novel_agent_v6_fetch_name")
        book_id = st.text_input("书籍 ID（已知时填写）", key="novel_agent_v6_fetch_id")
        chapters = int(st.number_input("本次获取章节数", min_value=1, max_value=100, value=1))
        job = Path(state["novel_agent_v6_acquisition"])
        if st.button("获取正文", disabled=not editor or job.exists()):
            try:
                launch_acquisition(job, book_name=book_name, book_id=book_id, chapters=chapters)
                st.success("已提交一次采集；请刷新查看回执和日志。")
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
        receipt = job / "source/RECEIPT.json"
        if receipt.is_file():
            value = _read(receipt)
            if value.get("status") == "source_saved":
                st.success("正文已保存，可在下方选择本次采集回执。")
            else:
                st.warning("采集未完成，请查看原回执中的登录、验证或错误停点。")
            with st.expander("采集回执"):
                st.code(str(receipt), language=None)
                st.json(value)
        _log(job / "acquisition.log", "采集日志")
        if job.exists() and st.button("建立新的采集工作区", disabled=not editor):
            state["novel_agent_v6_acquisition"] = str(ACQUISITIONS / uuid4().hex)
            st.rerun()

    with st.expander("2. 选择正文并准备", expanded=True):
        choices = {item["path"]: item for item in discover_sources(SOURCE_ROOTS)}
        selected = st.selectbox("已保存小说或采集回执", [""] + list(choices),
                                format_func=lambda path: "请选择" if not path else
                                f"{choices[path]['title']} · {choices[path]['status']} · {path}")
        manual = st.text_input("或填写采集回执 / 正文绝对路径", key="novel_agent_v6_source")
        title = st.text_input("本次改编标题（可选）", key="novel_agent_v6_title")
        scope = st.text_input("实际章节 / 选段范围（纯正文必填）", key="novel_agent_v6_scope")
        target_duration = int(st.number_input("目标成片时长（秒）", min_value=60, max_value=900,
                                              value=180, key="novel_agent_v6_duration"))
        run = Path(st.text_input("任务保存位置 / 原任务位置", key="novel_agent_v6_run")).resolve()
        if st.button("准备与冻结输入（不调用模型）", disabled=not editor):
            try:
                _editor()
                pipeline, legacy = _runtime(run)
                if legacy:
                    raise RuntimeError("历史版本只能查看原记录，不能迁移或覆盖")
                if (run / "BINDING.json").exists():
                    raise RuntimeError("当前任务已经冻结，请查看并继续原任务")
                if not (manual or selected):
                    raise ValueError("请选择已保存正文或填写实际路径")
                path = Path(manual or selected).resolve()
                kwargs = {"title": title or None, "scope": scope or None,
                          "brief": {"target_duration_seconds": target_duration}}
                if selected and not manual and choices[selected]["kind"] == "metadata":
                    result = import_saved_book(path, ACQUISITIONS / uuid4().hex)
                    kwargs["acquisition_receipt"] = Path(result["receipt_path"])
                    kwargs["book_id"] = choices[selected].get("book_id") or None
                elif path.suffix.lower() == ".json":
                    kwargs["acquisition_receipt"] = path
                else:
                    kwargs["source_path"] = path
                prepared = pipeline.prepare(run, **kwargs)
                if prepared.get("dispatch_blocked"):
                    st.warning("已保存准备记录；原停止或预算条件仍有效，本次不会启动创作。")
                else:
                    st.success("准备完成，可检查范围并启动文本及导演流程。")
                st.json(prepared)
            except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
                st.error(str(exc))
        st.caption("已有 v5 任务因辅助场记格式停止时，可明确选择原任务承接；旧稿、原审查和实际消耗保留，剩余预算沿用原范围。")
        parent_run = st.text_input("原 v5 停点任务位置（续行时填写）", key="novel_agent_v6_parent")
        if st.button("从原 v5 停点准备 v6（不调用模型）", disabled=not editor or not parent_run.strip()):
            try:
                prepared = prepare_continuation(run, parent_run=parent_run)
                st.success("已保存 v6 承接记录；原始稿件和审核没有重新派发，请查看剩余预算和当前阶段。")
                st.json(prepared)
            except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
                st.error(str(exc))

    with st.expander("3. 创作、审查与导演交接", expanded=True):
        st.code(str(run), language=None)
        st.button("刷新原任务状态与产物")
        try:
            pipeline, legacy = _runtime(run)
            report = pipeline.inspect(run)
            if report.get("status") != "unprepared":
                if legacy:
                    st.info("当前是历史冻结版本，仅查看原状态与产物；不会迁移或重新派发。")
                if report.get("projection_recovery_available") is True and not legacy:
                    st.info("已核实有完整本地快照可恢复；恢复后会重新检查原阶段与未决请求，本操作不调用模型。")
                    if st.button("恢复本地状态记录（不调用模型）", disabled=not editor):
                        report = recover_projection(run)
                        st.success("已恢复本地状态记录，未派发模型请求。")
                preview = pipeline.preview(run)
                state_record = report.get("state") or {}
                disabled = (not editor or legacy or report.get("dispatch_blocked", False)
                            or report.get("status") not in ALLOWED_START or report.get("blockers")
                            or report.get("pending_call") or report.get("pending")
                            or state_record.get("pending_call") or (run / ".web_launch.lock").exists()
                            or (run / "LAST_LAUNCH.json").exists())
                if st.button("后台运行至导演制作交接", disabled=bool(disabled)):
                    launch_text(run)
                    st.success("后台任务已提交；请刷新查看完整稿、审核和导演交接。")
                _outputs(run, report, preview)
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
            st.error(str(exc))
    if not editor:
        st.caption("当前为查看权限；获取正文、准备和启动流程需要编辑权限。")
