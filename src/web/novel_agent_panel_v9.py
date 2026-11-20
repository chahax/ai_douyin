"""Unified v9 novel/original workflow with final-request quality review; no media dispatch."""
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
RUNS = ROOT / "data/novel_adaptation/agent_v9"
ACQUISITIONS = ROOT / "data/novel_adaptation/acquisitions_v9"
SOURCE_ROOTS = (ROOT / "data/fanqie_promotion/books", ROOT / "data/novel_platform_trials",
                ROOT / "data/novel_adaptation/acquisitions_v1", ACQUISITIONS)
VERSION = "novel_agent_pipeline/v9"
LEGACY_SCHEMAS = {
    "novel_adaptation_pipeline/v1": "novel_adaptation_pipeline_v1",
    "novel_adaptation_production/v2": "novel_adaptation_production_v2",
    "novel_plaintext_pipeline/v3": "novel_plaintext_pipeline_v3",
    "novel_agent_pipeline/v5": "novel_agent_pipeline_v5",
    "novel_agent_pipeline/v6": "novel_agent_pipeline_v6",
    "novel_agent_pipeline/v7": "novel_agent_pipeline_v7",
    "novel_agent_pipeline/v8": "novel_agent_pipeline_v8",
}
ALLOWED_START = {"prepared", "running", "needs_full_revision"}
STAGES = {"writer_full": "MiniMax 完整创作", "review_full": "DeepSeek 场记与同源全文审核",
          "clarify_full": "问题核实与同稿全文复审", "director_full": "导演分段与表演设计",
          "director_review": "导演、分段及最终实际请求整包审核", "complete": "制作交接完成"}
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
        return importlib.import_module("src.content_factory.novel_agent_pipeline_v9"), False
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
            json.dump({"owner": "novel_agent_web_v9", "automatic_media_submit": False}, handle)
    except FileExistsError:
        raise RuntimeError("原后台任务已经提交，请刷新原记录，不能重复启动") from None
    spawned = False
    try:
        # Admission is checked again after winning the lock, not only in the UI.
        _admit(pipeline.inspect(run))
        preview = pipeline.preview(run)
        if preview.get("dispatch_blocked") or preview.get("blockers"):
            raise RuntimeError("请求预览显示停止条件，后台任务没有启动")
        argv = [sys.executable, str(ROOT / "scripts/run_novel_agent_v9.py"),
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
    argv = [sys.executable, str(ROOT / "scripts/run_novel_agent_v9.py"), "fetch",
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


def prepare_quality_revision(run_dir, *, parent_run, brief=None):
    """Prepare explicit v9 revision; runtime owns parent eligibility, budget and claim."""
    _editor()
    run = Path(run_dir).resolve()
    pipeline, legacy = _runtime(run)
    if legacy:
        raise RuntimeError("新质量修订不能覆盖历史冻结任务")
    if brief is not None and not isinstance(brief, dict):
        raise ValueError("新创作要求必须是完整对象")
    kwargs = {"parent_run": Path(parent_run).resolve()}
    if brief is not None:
        kwargs["brief"] = brief
    return pipeline.prepare_quality_revision(run, **kwargs)


def prepare_known_director_continuation(run_dir, *, parent_run):
    """Explicit frozen-parent continuation, never an automatic retry or new quota."""
    _editor()
    run = Path(run_dir).resolve()
    pipeline, legacy = _runtime(run)
    if legacy:
        raise RuntimeError("新导演续修不能覆盖旧冻结任务")
    return pipeline.prepare_known_director_continuation(run, parent_run=Path(parent_run).resolve())


def prepare_source(run_dir, *, source_kind, source_path=None, acquisition_receipt=None,
                   title=None, scope=None, target_duration_seconds=180, book_id=None):
    """Web/CLI/background share the v9 prepare API without registry overrides."""
    _editor()
    if source_kind not in {"novel", "original"}:
        raise ValueError("未知故事来源")
    if type(target_duration_seconds) is not int or not 60 <= target_duration_seconds <= 900:
        raise ValueError("目标时长须为60–900秒")
    if source_kind == "original" and acquisition_receipt:
        raise ValueError("原创剧情只接受用户创作简报正文")
    run = Path(run_dir).resolve()
    pipeline, legacy = _runtime(run)
    if legacy or (run / "BINDING.json").exists():
        raise RuntimeError("当前任务已冻结，请查看原任务；不能覆盖或迁移")
    return pipeline.prepare(run, source_kind=source_kind,
        source_path=Path(source_path).resolve() if source_path else None,
        acquisition_receipt=Path(acquisition_receipt).resolve() if acquisition_receipt else None,
        title=title or None, scope=scope or None, book_id=book_id or None,
        brief={"target_duration_seconds": target_duration_seconds})


def recover_projection(run_dir):
    """Restore local state only; pending request admission is checked afterwards."""
    _editor()
    run = Path(run_dir).resolve()
    pipeline, legacy = _runtime(run)
    if legacy:
        raise RuntimeError("历史冻结任务只能查看，不能通过 v9 恢复或迁移")
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
                "PRODUCTION_HANDOFF*.md", "OUTPUT_MANIFEST.json", "EPISODE.json",
                "QUALITY*.json", "VIDEO_REQUEST*.json", "VIDEO_REQUEST*.md",
                "FINAL_REQUEST*.json", "FINAL_REQUEST*.md")
    paths = set()
    for pattern in patterns:
        for path in run.glob(pattern):
            if path.is_file() and path.resolve().is_relative_to(run):
                paths.add(path)
    return sorted(paths, key=lambda path: path.name)


def _outputs(run, report, preview):
    st.write("状态：", STATUSES.get(report.get("status"), report.get("status", "未知")))
    state = report.get("state") or {}
    stage = report.get("stage") or state.get("stage") or "尚未启动"
    st.write("当前阶段：", STAGES.get(stage, stage))
    source = report.get("source") or {}
    if source:
        st.write("故事：", source.get("title") or source.get("book_name") or "未知")
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
    for path in files:
        with st.expander(path.name, expanded=path.name == "SCREENPLAY.md"):
            st.code(str(path.resolve()), language=None)
            if path.suffix == ".md":
                st.markdown(path.read_text(encoding="utf-8"))
            else:
                st.json(_read(path))
    _log(run / "execution.log", "后台文本日志")


def _acquisition_section(editor, state, prefix):
    key = prefix + "_acquisition"
    state.setdefault(key, str(ACQUISITIONS / uuid4().hex))
    with st.expander("获取小说正文", expanded=False):
        st.caption("采集器遇到登录或验证即保存停点，也可直接选择已有正文。")
        name = st.text_input("小说名称", key=prefix + "_fetch_name")
        book_id = st.text_input("书籍 ID（已知时填写）", key=prefix + "_fetch_id")
        chapters = int(st.number_input("本次获取章节数", min_value=1, max_value=100, value=1,
                                        key=prefix + "_chapters"))
        job = Path(state[key])
        if st.button("获取正文", disabled=not editor or job.exists(), key=prefix + "_fetch"):
            try:
                launch_acquisition(job, book_name=name, book_id=book_id, chapters=chapters)
                st.success("采集已提交一次，请刷新查看原回执。")
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
        receipt = job / "source/RECEIPT.json"
        if receipt.is_file():
            st.code(str(receipt), language=None)
            st.json(_read(receipt))
        _log(job / "acquisition.log", "采集日志")
        if job.exists() and st.button("建立新的采集工作区", disabled=not editor, key=prefix + "_new_fetch"):
            state[key] = str(ACQUISITIONS / uuid4().hex)
            st.rerun()


def _run_section(run, *, editor, prefix):
    with st.expander("创作、整包审核与交接", expanded=True):
        st.code(str(run), language=None)
        st.button("刷新原任务状态与产物", key=prefix + "_refresh")
        try:
            pipeline, legacy = _runtime(run)
            report = pipeline.inspect(run)
            if report.get("status") == "unprepared":
                return
            if legacy:
                st.info("历史冻结任务只读；原版本、停止证据和消耗保留，不迁移或派发。")
            if report.get("projection_recovery_available") is True and not legacy:
                if st.button("恢复本地状态记录（不调用模型）", disabled=not editor, key=prefix + "_recover"):
                    report = recover_projection(run)
                    st.success("已恢复本地状态，未派发请求。")
            preview = pipeline.preview(run)
            record = report.get("state") or {}
            disabled = (not editor or legacy or report.get("dispatch_blocked")
                        or report.get("status") not in ALLOWED_START or report.get("blockers")
                        or report.get("pending_call") or report.get("pending") or record.get("pending_call")
                        or (run / ".web_launch.lock").exists() or (run / "LAST_LAUNCH.json").exists())
            if st.button("后台运行至最终请求审核与交接", disabled=bool(disabled), key=prefix + "_execute"):
                launch_text(run)
                st.success("后台任务已提交，请刷新查看完整稿、导演与全部实际请求审核。")
            _outputs(run, report, preview)
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
            st.error(str(exc))


def page_story_workflow(source_kind="novel"):
    if source_kind not in {"novel", "original"}:
        raise ValueError("未知故事来源")
    original = source_kind == "original"
    prefix = "novel_agent_v9_" + source_kind
    st.title("原创剧情" if original else "小说改编")
    st.caption("来源与简报 → 完整剧本 → 互动表演与导演分段 → 最终实际提示词 → DeepSeek同源整包审核")
    st.info("新任务共用 v9 质量流程：MiniMax创作、DeepSeek审核信息推进、动作神情、具体视线、可见镜头与自然排时。这里只生成文本及请求预览，视频仍需授权和用户人工审片。")
    editor = has_permission(get_current_role(), "editor")
    state = st.session_state
    state.setdefault(prefix + "_run", str(RUNS / source_kind / uuid4().hex))
    if not original:
        _acquisition_section(editor, state, prefix)
    with st.expander("选择来源并冻结要求", expanded=True):
        choices = {} if original else {item["path"]: item for item in discover_sources(SOURCE_ROOTS)}
        selected = ""
        if not original:
            selected = st.selectbox("已保存小说或采集回执", [""] + list(choices), key=prefix + "_saved",
                format_func=lambda path: "请选择" if not path else f"{choices[path]['title']} · {choices[path]['status']} · {path}")
        text = st.text_area("创作简报全文（或使用下面的正文文件）", key=prefix + "_brief") if original else ""
        if original:
            st.caption("请说明人物关系、当前处境、目标、冲突和希望观众理解的变化；简报作为来源全文冻结，与小说使用同一编剧和最终请求审核链。")
        manual = st.text_input("创作简报正文绝对路径" if original else "或填写采集回执 / 正文绝对路径", key=prefix + "_source")
        title = st.text_input("本次项目标题", key=prefix + "_title")
        scope = st.text_input("实际章节 / 选段范围" if not original else "简报范围", value="用户创作简报全文" if original else "", key=prefix + "_scope")
        target = int(st.number_input("目标成片时长（秒）", min_value=60, max_value=900, value=180, key=prefix + "_duration"))
        run = Path(st.text_input("任务保存位置 / 原任务位置", key=prefix + "_run")).resolve()
        if st.button("准备与冻结输入（不调用模型）", disabled=not editor, key=prefix + "_prepare"):
            try:
                _editor()
                if (run / "BINDING.json").exists():
                    raise ValueError("任务已经冻结，请查看原任务，不能重新准备或覆盖")
                if text.strip() and manual.strip():
                    raise ValueError("创作简报全文和正文路径请选择一种")
                path = None
                receipt = None
                book_id = None
                if original and text.strip():
                    inputs = ROOT / "data/novel_adaptation/original_inputs_v9"
                    inputs.mkdir(parents=True, exist_ok=True)
                    path = inputs / (uuid4().hex + ".txt")
                    with path.open("x", encoding="utf-8") as handle:
                        handle.write(text)
                elif manual.strip() or selected:
                    chosen = Path(manual.strip() or selected).resolve()
                    if not original and selected and not manual.strip() and choices[selected]["kind"] == "metadata":
                        bridge = import_saved_book(chosen, ACQUISITIONS / uuid4().hex)
                        receipt = Path(bridge["receipt_path"])
                        book_id = choices[selected].get("book_id")
                    elif not original and chosen.suffix.lower() == ".json":
                        receipt = chosen
                    else:
                        path = chosen
                else:
                    raise ValueError("请填写创作简报或选择已保存的来源全文")
                result = prepare_source(run, source_kind=source_kind, source_path=path,
                    acquisition_receipt=receipt, title=title, scope=scope,
                    target_duration_seconds=target, book_id=book_id)
                st.json(result)
                st.success("来源与质量规范已冻结；请检查状态后单独启动文本流程。")
            except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
                st.error(str(exc))
    with st.expander("显式承接历史质量修订", expanded=False):
        st.caption("仅准备已获授权的独立质量修订；后端核对父来源、永久claim、原消耗和剩余预算，不以新目录重领容量。")
        parent = st.text_input("原任务绝对路径", key=prefix + "_parent")
        change_brief = st.checkbox("为这次质量修订冻结新的创作要求", key=prefix + "_change_brief")
        revision_brief = None
        if change_brief:
            st.caption("只更新这次明确修订的创作要求；父稿、原审核、历史消耗和剩余预算保持。")
            revision_target = int(st.number_input("修订目标成片时长（秒）", min_value=60, max_value=900,
                                                  value=120, key=prefix + "_revision_duration"))
            revision_max = int(st.number_input("修订容许最大时长（秒）", min_value=revision_target,
                                               max_value=900, value=max(revision_target, 135),
                                               key=prefix + "_revision_max"))
            audience_goal = st.text_area("希望观众理解的内容与节奏要求", key=prefix + "_revision_goal")
            requirements = st.text_area("其他明确修订要求（每行一项）", key=prefix + "_revision_requirements")
            revision_brief = {"source_kind": source_kind, "target_duration_seconds": revision_target,
                "max_duration_seconds": revision_max, "duration_tolerance_seconds": revision_max - revision_target,
                "audience_goal": audience_goal, "requirements": [row.strip() for row in requirements.splitlines() if row.strip()]}
        if st.button("准备质量修订（不调用模型）", disabled=not editor or not parent.strip(), key=prefix + "_revision"):
            try:
                st.json(prepare_quality_revision(run, parent_run=parent, brief=revision_brief))
            except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
                st.error(str(exc))
    with st.expander("承接已核验的 v8 导演停点", expanded=False):
        st.caption("仅对后端确认原生结束、结果与用量已知的导演停点准备独立续修；继承完整稿、同稿审查和实际剩余容量。无法确认完整JSON的记录保持停止，不手补原文或盲重派。")
        known_parent = st.text_input("原 v8 导演停点任务绝对路径", key=prefix + "_known_parent")
        if st.button("准备已知导演续修（不调用模型）", disabled=not editor or not known_parent.strip(), key=prefix + "_known_continuation"):
            try:
                st.json(prepare_known_director_continuation(run, parent_run=known_parent))
            except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
                st.error(str(exc))
    _run_section(run, editor=editor, prefix=prefix)
    if not editor:
        st.caption("当前为查看权限，准备和启动需要编辑权限。")


def page_novel_adaptation():
    page_story_workflow("novel")


def page_original_story():
    page_story_workflow("original")


def legacy_creative_records(run_dir):
    """Local presentation only: no provider clients, resume commands, or media actions."""
    run = Path(run_dir).resolve()
    allowed = (ROOT / 'data/creative_workflows').resolve()
    if not allowed.is_relative_to(ROOT.resolve()) or not run.is_relative_to(allowed) or not run.is_dir():
        raise ValueError('只允许读取本项目 data/creative_workflows 内的历史任务目录。')
    records = {}
    for name in ("state.json", "materials.json", "MANIFEST.json", "manifest.json", "LAUNCH_ERROR.json"):
        path = run / name
        if path.is_file() and path.resolve().is_relative_to(run):
            records[name] = _read(path)
    files = set(artifact_files(run))
    for pattern in ("*.md", "stage_*/*.md", "stages/*/*.md"):
        files.update(path for path in run.glob(pattern) if path.is_file() and path.resolve().is_relative_to(run))
    return {"status": "legacy_read_only", "dispatch_blocked": True, "automatic_media_submit": False,
            "run_dir": str(run), "original_records": records, "artifact_files": sorted(files)}


def page_legacy_creative_records():
    st.title("历史创作记录")
    st.caption("保留旧任务浏览；本页不创建、恢复、迁移或派发旧流程。原任务恢复须使用原绑定入口。")
    root = ROOT / "data/creative_workflows"
    recent = sorted((p for p in root.iterdir() if p.is_dir() and (p / "state.json").is_file()),
                    key=lambda p: p.stat().st_mtime, reverse=True)[:50] if root.is_dir() else []
    selected = st.selectbox("选择历史任务", [""] + [str(p) for p in recent], key="creative_v9_history_selected")
    manual = st.text_input("或填写原任务绝对路径", key="creative_v9_history_path",help='仅支持本项目 data/creative_workflows 内的历史任务。')
    if manual.strip() or selected:
        try:
            report = legacy_creative_records(manual.strip() or selected)
            st.code(report["run_dir"], language=None)
            st.json(report["original_records"])
            for path in report["artifact_files"]:
                with st.expander(path.name):
                    st.code(str(path), language=None)
                    if path.suffix.lower() == ".md":
                        st.markdown(path.read_text(encoding="utf-8"))
                    else:
                        st.json(_read(path))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            st.error(str(exc))


