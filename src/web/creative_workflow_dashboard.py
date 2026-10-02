"""Small authenticated UI for the explicit v2 creative route."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

from src.content_factory.creative_calibration import calibration_status
from src.content_factory.creative_workflow_inputs import load_materials
from src.content_factory.creative_stage_debug import CreativeStageCommandService


ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "data" / "creative_workflows"


def _resume_argv(run_dir: Path, state: dict, manifest: dict) -> list[str]:
    """Rebuild the exact bound CLI invocation without claiming a new task."""
    files = manifest.get("files", {})
    driver = state.get("source_driver")
    argv = [
        sys.executable, str(ROOT / "scripts" / "run_creative_workflow.py"),
        "--source-driver", str(driver), "--title", str(manifest.get("title", "")),
        "--run-dir", str(run_dir), "--focus", str(state.get("creative_focus", "")),
        "--max-calls", str(state.get("max_calls")),
        "--max-total-tokens", str(state.get("max_total_tokens")),
        "--max-revisions", str(state.get("max_revisions")),
        "--max-contract-repairs", str(state.get("max_contract_repairs")),
        "--budget-policy-version", str(state.get("budget_policy_version")),
    ]
    if driver == "novel":
        argv.extend(("--novel", files["story_source"]["path"]))
        if "metadata" in files:
            argv.extend(("--metadata", files["metadata"]["path"]))
    elif driver == "reference_video":
        argv.extend(("--video", files["story_video"]["path"]))
        argv.extend(("--analysis", files["story_analysis"]["path"]))
        heading = manifest.get("scope", {}).get("analysis_scope_end_heading")
        if heading:
            argv.extend(("--analysis-end-heading", str(heading)))
    elif driver != "original":
        raise ValueError("任务故事来源无效，不能恢复")
    if "asset_library" in files:
        argv.extend(("--asset-library", files["asset_library"]["path"]))
    if "creative_brief" in files:
        argv.extend(("--brief", files["creative_brief"]["path"]))
    references = sorted(
        (key, value) for key, value in files.items() if key.startswith("reference_")
    )
    for _, binding in references:
        argv.extend(("--reference", binding["path"]))
    return argv


def _launch_detached(argv: list[str]) -> None:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        argv, cwd=ROOT, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def page_creative_workflow() -> None:
    st.title("剧本与视频创作工作台")
    st.caption("从创作简报推进到完整剧本、导演安排和逐段视频。必修问题在同一任务预算内返修；文本通过后生成视频候选，内容由用户人工审查。")
    calibration = calibration_status(RUNS)
    if calibration["stop_per_draft_assistant_review"]:
        st.info("前期校准已达标：日常文本稿不再要求逐稿助手复核；重大回归或来源、画风、角色模型变化时再针对性复核。")
    else:
        st.info(
            "当前处于前期校准：由助手审阅完整首稿，不需要第三审核模型或额外 Token。"
            f"连续无重大问题首稿 {calibration['consecutive_first_draft_passes']}/3；"
            "未达标前不能宣称独立复核稳定通过。"
        )
        if calibration.get("profile_mismatch_reviews", 0):
            st.info(
                f"有 {calibration['profile_mismatch_reviews']} 份旧流程首稿通过记录因模型、"
                "提示词或质量控制代码已变化而不再计入当前 3/3。"
            )
    driver_label = st.selectbox("故事来源", ["小说改编", "原视频分析驱动原创故事", "原创创作简报"])
    driver = {"小说改编": "novel", "原视频分析驱动原创故事": "reference_video", "原创创作简报": "original"}[driver_label]
    title = st.text_input("项目标题")
    focus = st.text_input("本次对照焦点（可选）")
    if driver == "novel":
        novel = st.text_input("已获取小说正文绝对路径")
        metadata = st.text_input("书籍元数据绝对路径（可选）")
        video = analysis = ""
    elif driver == "reference_video":
        video = st.text_input("原视频绝对路径")
        analysis = st.text_input("对应视频分析绝对路径")
        analysis_end_heading = st.text_input("分析范围终点标题（可选，标题之后不进入故事来源）")
        novel = metadata = ""
    if driver != "reference_video":
        analysis_end_heading = ""
    if driver == "original":
        novel = metadata = video = analysis = ""
    brief_path = st.text_input("创作简报 JSON 路径（原创必需，其他来源可选）")
    references = st.text_area("表达参考分析路径（可选，每行一个）")
    st.caption("参考材料只提供画面表达方法，不能作为小说情节或对白来源。")
    if st.button("创建并运行新版文本流程", type="primary"):
        try:
            ref_paths = [Path(line.strip()) for line in references.splitlines() if line.strip()]
            bundle = load_materials(
                source_driver=driver,
                title=title,
                novel_path=Path(novel) if novel else None,
                metadata_path=Path(metadata) if metadata else None,
                video_path=Path(video) if video else None,
                analysis_path=Path(analysis) if analysis else None,
                analysis_end_heading=analysis_end_heading,
                reference_paths=ref_paths,
                brief_path=Path(brief_path) if brief_path else None,
                asset_library_path=ROOT / "data/visual_asset_library/reusable_assets.json",
            )
            run_dir = RUNS / f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{driver}"
            argv = [sys.executable, str(ROOT / "scripts" / "run_creative_workflow.py"),
                    "--source-driver", driver, "--title", bundle.title,
                    "--run-dir", str(run_dir), "--focus", focus]
            for flag, value in (("--novel", novel), ("--metadata", metadata),
                                ("--video", video), ("--analysis", analysis)):
                if value:
                    argv.extend((flag, value))
            if brief_path:
                argv.extend(("--brief", brief_path))
            for path in ref_paths:
                argv.extend(("--reference", str(path)))
            if analysis_end_heading:
                argv.extend(("--analysis-end-heading", analysis_end_heading))
            # Detached process keeps the web request responsive. The run directory is the source of truth.
            _launch_detached(argv)
            st.session_state["creative_run_dir"] = str(run_dir)
            st.session_state["creative_selected_run"] = str(run_dir)
            st.success(f"已启动：{run_dir.name}")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            st.error(str(exc))
    if "creative_selected_run" not in st.session_state or (
        not st.session_state["creative_selected_run"] and st.session_state.get("creative_run_dir")
    ):
        st.session_state["creative_selected_run"] = st.session_state.get("creative_run_dir", "")
    recent = sorted(
        (path for path in RUNS.iterdir() if path.is_dir()
         and ((path / "state.json").exists() or (path / "LAUNCH_ERROR.json").exists())),
        key=lambda path: path.stat().st_mtime, reverse=True,
    )[:50] if RUNS.exists() else []
    options = [""] + [str(path) for path in recent]
    current = st.session_state["creative_selected_run"]
    if current and current not in options:
        options.insert(1, current)
    selected = st.selectbox(
        "查看已有任务", options, key="creative_selected_run",
        format_func=lambda value: Path(value).name if value else "请选择任务",
    )
    if selected:
        st.subheader("当前任务")
        st.code(selected)
        if st.button("刷新状态"):
            st.rerun()
        state_path = Path(selected) / "state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            st.caption(f"当前状态：{state.get('status', '待运行')} · 已发起调用：{state.get('calls_started', 0)}")
            with st.expander("执行与预算详情"):
                st.write({key: state.get(key) for key in (
                    "status", "source_driver", "budget_policy_version", "calls_started",
                    "reported_tokens", "contract_repairs_used", "format_repairs_used", "revision_rounds",
                    "assistant_review_required", "assistant_review_outcome", "assistant_revision_status",
                    "assistant_revision_round_index",
                    "assistant_revision_error", "workflow_profile_sha256", "input_profile_sha256",
                    "style_class", "review_reopen_reasons", "context_strategy", "last_error",
                    "unresolved_issues", "debug_breakpoint", "debug_feedback_status")})
            try:
                debug_service = CreativeStageCommandService(Path(selected))
                debug_snapshot = debug_service.inspect()
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                st.warning(f"阶段调试索引暂不可用：{exc}")
                debug_snapshot = {"stages": []}
            debug_stages = debug_snapshot["stages"]
            with st.expander("阶段调试与不可变版本", expanded=state.get("status") == "debug_breakpoint"):
                if debug_stages:
                    st.dataframe([
                        {
                            "阶段": row["stage_id"],
                            "角色": row["role"],
                            "有效性": row["validity"],
                            "版本数": row["version_count"],
                            "输出哈希": row["output_sha256"],
                        }
                        for row in debug_stages
                    ], hide_index=True, width="stretch")
                    stage_ids = [row["stage_id"] for row in debug_stages]
                    feedback_stage = st.selectbox(
                        "反馈责任阶段", stage_ids,
                        key=f"creative_debug_feedback_stage_{Path(selected).name}",
                    )
                    if st.button(
                        "比较该阶段最近两版",
                        disabled=next(row for row in debug_stages if row["stage_id"] == feedback_stage)["version_count"] < 2,
                        key=f"creative_debug_compare_{Path(selected).name}",
                    ):
                        try:
                            comparison = debug_service.compare(feedback_stage)
                            if comparison.get("output_identical"):
                                st.info("两版正文相同，输入版本不同。")
                            st.code(comparison["diff"], language="diff")
                            if comparison.get("input_diff"):
                                st.code(comparison["input_diff"], language="diff")
                        except (OSError, ValueError, RuntimeError) as exc:
                            st.error(f"版本比较失败：{exc}")
                    if st.checkbox("显示历史阶段版本（只读）", key=f"creative_debug_history_{Path(selected).name}"):
                        st.dataframe([
                            {"阶段": row["stage_id"], "执行序号": row["ordinal"],
                             "有效性": row["validity"], "输出哈希": row["output_sha256"]}
                            for row in debug_snapshot["history"] if row["validity"] == "historical"
                        ], hide_index=True, width="stretch")
                    feedback_disposition = st.selectbox(
                        "反馈类型", ("must_fix", "suggestion"),
                        format_func=lambda value: "必须修复" if value == "must_fix" else "建议",
                        key=f"creative_debug_feedback_kind_{Path(selected).name}",
                    )
                    feedback_message = st.text_area(
                        "反馈原话",
                        key=f"creative_debug_feedback_message_{Path(selected).name}",
                    )
                    selected_stage = next(row for row in debug_stages if row["stage_id"] == feedback_stage)
                    binding_key = f"creative_debug_displayed_{Path(selected).name}_{feedback_stage}"
                    displayed = st.session_state.get(binding_key, {
                        "input_sha256": selected_stage["input_sha256"],
                        "output_sha256": selected_stage["output_sha256"]})
                    submitted = st.button(
                        "绑定阶段反馈",
                        disabled=not feedback_message.strip(),
                        key=f"creative_debug_feedback_submit_{Path(selected).name}",
                    )
                    if submitted:
                        try:
                            receipt = debug_service.feedback(
                                feedback_stage,
                                feedback_message,
                                disposition=feedback_disposition,
                                expected_output_sha256=displayed["output_sha256"],
                                expected_input_sha256=displayed["input_sha256"],
                            )
                        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
                            st.error(f"反馈保存失败：{exc}")
                        else:
                            st.success(f"反馈已绑定：{receipt['feedback_id']}")
                            st.rerun()
                    else:
                        st.session_state[binding_key] = {
                            "input_sha256": selected_stage["input_sha256"],
                            "output_sha256": selected_stage["output_sha256"]}
                else:
                    st.caption("尚无已完成阶段；运行到首个断点后会显示版本。")
                terminal = state.get("status") in {
                    "media_handoff_pending_capability",
                    "reviewed_revision_media_handoff_pending_capability",
                }
                if st.button(
                    "运行下一阶段",
                    disabled=terminal,
                    key=f"creative_debug_next_{Path(selected).name}",
                ):
                    try:
                        manifest = json.loads(
                            (Path(selected) / "materials.json").read_text(encoding="utf-8")
                        )
                        argv = _resume_argv(Path(selected), state, manifest)
                        argv.append("--next-stage")
                        from src.content_factory.creative_execution_control import command
                        command(Path(selected), 'resume')
                        _launch_detached(argv)
                        st.success("已按原预算运行下一个尚未完成阶段。")
                    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
                        st.error(f"无法单步运行：{exc}")
                target_stage = st.text_input(
                    "运行到阶段（精确 stage_id）",
                    key=f"creative_debug_target_{Path(selected).name}",
                )
                if st.button(
                    "运行到此阶段",
                    disabled=terminal or not target_stage.strip(),
                    key=f"creative_debug_until_{Path(selected).name}",
                ):
                    try:
                        manifest = json.loads(
                            (Path(selected) / "materials.json").read_text(encoding="utf-8")
                        )
                        argv = _resume_argv(Path(selected), state, manifest)
                        argv.extend(("--stop-after-stage", target_stage.strip()))
                        _launch_detached(argv)
                        st.success(f"已设置断点：{target_stage.strip()}")
                    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
                        st.error(f"无法设置断点：{exc}")
            from src.web.creative_workbench_panel import render_workbench
            render_workbench(Path(selected), state, debug_stages, launch=_launch_detached,
                             resume_argv=_resume_argv)
            budget_blocked = any(
                marker in str(state.get("last_error", ""))
                for marker in ("预算已满", "预算不足", "调用预算已满")
            )
            if state.get("status") == "script_review_pending":
                st.info("正在等待助手阅读全文并核实审核意见。必修问题确认后才返修，可选建议不会自动改稿。")
                pending = state.get("pending_evidence_review", {})
                packet = Path(selected) / pending.get("packet", "")
                if packet.is_file():
                    with st.expander("当前剧本与审核意见"):
                        st.json(json.loads(packet.read_text(encoding="utf-8")))
                decision = Path(selected) / pending.get("decision", "")
                if st.button("继续已核实的任务", disabled=not decision.is_file()):
                    try:
                        manifest = json.loads((Path(selected) / "materials.json").read_text(encoding="utf-8"))
                        _launch_detached(_resume_argv(Path(selected), state, manifest))
                        st.success("已恢复原任务；流程会核对核实记录是否对应当前稿件。")
                    except (KeyError, OSError, ValueError) as exc:
                        st.error(f"无法恢复：{exc}")
            elif state.get("status") == "needs_attention" and budget_blocked:
                st.warning("当前任务已达到原预算上限；保留失败记录，不能从页面重置预算继续。")
            elif state.get("status") == "needs_attention":
                if st.button("恢复同一任务", type="primary"):
                    try:
                        manifest = json.loads(
                            (Path(selected) / "materials.json").read_text(encoding="utf-8")
                        )
                        _launch_detached(_resume_argv(Path(selected), state, manifest))
                        st.success("已按原材料、焦点和预算恢复同一任务；调用次数不会重置。")
                    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
                        st.error(f"无法恢复当前任务：{exc}")
            review_path = Path(selected) / "CALIBRATION_REVIEW.json"
            if review_path.exists():
                review = json.loads(review_path.read_text(encoding="utf-8"))
                if review.get("outcome") == "major_issues":
                    st.error("首份完整稿助手复核：存在主要质量问题；不能记为首稿无异常或视频通过。")
                elif review.get("outcome") == "passed":
                    st.success("助手文本复核：当前版本通过；不代表真实视频声画通过。")
                st.write({key: review.get(key) for key in (
                    "category", "outcome", "first_draft_no_major", "reviewed_at")})
            for index, filename in ((1, "ASSISTANT_REVISION_REVIEW.json"),
                                    (2, "ASSISTANT_REVISION_REVIEW__02.json")):
                revised_review_path = Path(selected) / filename
                if revised_review_path.exists():
                    revised_review = json.loads(revised_review_path.read_text(encoding="utf-8"))
                    if revised_review.get("outcome") == "major_issues":
                        st.error(f"助手第 {index} 轮返修复核：仍有主要质量问题。")
                    elif revised_review.get("outcome") == "passed":
                        st.success(f"助手第 {index} 轮返修复核通过；仍须核验媒体执行能力与真实视频。")
            if (Path(selected) / "PRODUCTION_DESIGN.json").is_file():
                if st.button("更新素材复用与下一步任务"):
                    try:
                        from src.content_factory.reusable_production import prepare_next_work
                        output = prepare_next_work(Path(selected), ROOT / "data/visual_asset_library/reusable_assets.json")
                        st.write(output["queue"])
                    except (OSError, ValueError, KeyError) as exc:
                        st.error(str(exc))
            for name in ("PRODUCTION_QUEUE.json", "REUSABLE_PREPRODUCTION.json", "PRODUCTION_DESIGN.json", "SCREENPLAY.md", "STORYBOARD.json", "EDITORIAL_REVIEW_PACKET.md",
                         "EXECUTION_DRAFT.json", "MEDIA_CAPABILITY_AUDIT.json",
                         "MEDIA_HANDOFF.json", "CALIBRATION_REVIEW.md",
                         "ASSISTANT_FEEDBACK.json", "ASSISTANT_REVISION_DRAFT.json",
                         "ASSISTANT_REVISION_REVIEW.md", "ASSISTANT_REVISION_REVIEW.json",
                         "ASSISTANT_FEEDBACK__02.json", "ASSISTANT_REVISION_DRAFT__02.json",
                         "ASSISTANT_REVISION_REVIEW__02.json",
                         "ASSISTANT_REVISED_ANALYSIS.json", "ASSISTANT_REVISED_DIRECTOR_BRIEF.json",
                         "ASSISTANT_REVISED_SCREENPLAY.md", "ASSISTANT_REVISED_STORYBOARD.json",
                         "ASSISTANT_REVISED_EXECUTION_DRAFT.json",
                         "ASSISTANT_REVISED_MEDIA_CAPABILITY_AUDIT.json",
                         "ASSISTANT_REVISED_MEDIA_HANDOFF.json",
                         "UNRESOLVED_DRAFT.md"):
                path = Path(selected) / name
                if path.exists():
                    with st.expander(name):
                        st.code(path.read_text(encoding="utf-8"), language="json" if name.endswith(".json") else "markdown")
        else:
            failure_path = Path(selected) / "LAUNCH_ERROR.json"
            if failure_path.exists():
                failure = json.loads(failure_path.read_text(encoding="utf-8"))
                st.error(failure.get("error", "任务启动失败"))
            else:
                st.info("任务启动中。")
