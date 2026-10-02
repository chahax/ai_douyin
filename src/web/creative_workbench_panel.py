"""Readable creative outputs and explicit controls over the shared command services."""

from pathlib import Path
import sys
import streamlit as st
from src.content_factory.creative_stage_contracts import read
from src.content_factory.creative_execution_control import command
from src.content_factory.creative_media_workbench import (
    inspect_media,
    register_candidate,
    media_feedback,
)
from src.content_factory.creative_quality_evidence import quality_report
from src.content_factory.creative_delivery import prepare_delivery

ROOT = Path(__file__).resolve().parents[2]


def render_workbench(run_dir, state, stages, *, launch, resume_argv):
    key = str(run_dir.resolve())
    with st.expander("创作正文与导演安排", expanded=True):
        prefix = (
            "ASSISTANT_REVISED_"
            if (run_dir / "ASSISTANT_REVISED_SCREENPLAY.md").exists()
            else ""
        )
        screenplay = run_dir / (prefix + "SCREENPLAY.md")
        if screenplay.is_file():
            st.markdown(screenplay.read_text(encoding="utf-8"))
        storyboard = run_dir / (prefix + "STORYBOARD.json")
        if storyboard.is_file():
            for shot in read(storyboard).get("shots", []):
                st.markdown("**" + str(shot.get("id", "镜头")) + "**")
                for field, label in (
                    ("composition", "构图"),
                    ("camera", "机位"),
                    ("start_state", "首态"),
                    ("visible_performance", "表演"),
                    ("dialogue_lock", "对白"),
                    ("end_state", "尾态"),
                ):
                    if shot.get(field) is not None:
                        st.write(label, shot[field])
        if not screenplay.exists() and not storyboard.exists():
            st.caption("正文会在完成对应阶段后显示。")
    with st.expander("推进与停止"):
        st.caption(
            "自动继续只推进文本阶段；媒体生成与发布各需单独明确执行。停止会阻止后续派发，保留已发出任务与预算。"
        )
        if st.button("停止后续派发", key=key + "stop"):
            command(run_dir, "stop")
            st.success("停止请求已保存；正在执行的调用仍保留回执。")
        terminal = state.get("status") in (
            "media_handoff_pending_capability",
            "reviewed_revision_media_handoff_pending_capability",
        )
        if st.button("自动继续到下一个审核门", disabled=terminal, key=key + "auto"):
            try:
                command(run_dir, "resume")
                launch(resume_argv(run_dir, state, read(run_dir / "materials.json")))
                st.success("按原任务与预算继续；遇到审核、未知调用或预算门会停止。")
            except (ValueError, OSError, KeyError) as exc:
                st.error(str(exc))
    with st.expander("媒体请求与人工反馈"):
        media_root = run_dir / ".creative_debug/media"
        if (media_root / "current_preview.json").is_file():
            chain = read(media_root / "current_preview.json")["chain_sha256"]
            preview = read(media_root / "previews" / (chain + ".json"))
            st.caption("请求预览对应同一份剧本、分镜和媒体交接版本。")
            st.json(preview["request"])
        if st.button("编译当前文本为媒体请求预览", key=key + "compile_media"):
            try:
                from scripts.compile_creative_seedance_segments import compile_run
                from src.content_factory.creative_stage_contracts import digest, persist
                from src.content_factory.creative_media_workbench import (
                    register_preview,
                )

                revised = (run_dir / "ASSISTANT_REVISED_MEDIA_HANDOFF.json").is_file()
                plan, receipt = compile_run(run_dir, revised=revised)
                path = media_root / "compiled" / (digest(plan) + ".json")
                persist(path, plan, immutable=True)
                persist(
                    path.with_name(path.stem + ".receipt.json"), receipt, immutable=True
                )
                prefix = "ASSISTANT_REVISED_" if revised else ""
                register_preview(
                    run_dir,
                    path,
                    source_paths={
                        name: run_dir / (prefix + file)
                        for name, file in (
                            ("script", "SCREENPLAY.json"),
                            ("storyboard", "STORYBOARD.json"),
                            ("capability", "MEDIA_CAPABILITY_AUDIT.json"),
                            ("handoff", "MEDIA_HANDOFF.json"),
                        )
                    },
                    text_gate=receipt["text_gate_status"],
                )
                st.success("已冻结当前请求预览；未提交媒体任务。")
            except (OSError, ValueError, KeyError) as exc:
                st.error(str(exc))
        prepared_plan = st.text_input(
            "已准备并确认的单段执行计划", key=key + "prepared_plan"
        )
        output_dir = st.text_input("本段独立保存目录", key=key + "segment_output")
        for label, operation in (
            ("查看本段实际请求", "preview"),
            ("明确生成本段视频", "submit"),
            ("续查已提交任务", "query"),
        ):
            if st.button(
                label,
                disabled=not prepared_plan or not output_dir,
                key=key + "segment_" + operation,
            ):
                launch(
                    [
                        sys.executable,
                        str(ROOT / "scripts/run_creative_seedance_segment.py"),
                        operation,
                        prepared_plan,
                        "--output-dir",
                        output_dir,
                    ]
                )
                st.success("已启动本段操作；候选保存成功后等待用户审核。")
        if output_dir and (Path(output_dir) / "receipt.json").is_file():
            receipt = read(Path(output_dir) / "receipt.json")
            st.write(
                {
                    field: receipt.get(field)
                    for field in (
                        "status",
                        "technical_status",
                        "content_status",
                        "task_id",
                    )
                }
            )
        candidate_path = st.text_input(
            "已保存候选回执路径", key=key + "candidate_receipt"
        )
        if st.button(
            "登记候选", disabled=not candidate_path.strip(), key=key + "register"
        ):
            try:
                register_candidate(run_dir, candidate_path)
                st.rerun()
            except (ValueError, OSError, KeyError) as exc:
                st.error(str(exc))
        try:
            candidates = inspect_media(run_dir)["current"]
        except (OSError, ValueError, KeyError) as exc:
            st.error(str(exc))
            candidates = []
        for candidate in candidates:
            st.write(candidate["segment_id"], candidate["content_status"])
            if candidate["stale_reason"]:
                st.warning(candidate["stale_reason"])
                continue
            st.video(candidate["video"]["path"])
            cid = candidate["candidate_id"]
            decision = st.selectbox(
                "用户审核决定", ("未决定", "通过", "不通过"), key=cid + "decision"
            )
            statement = st.text_area("用户审核原话", key=cid + "statement")
            timed = st.checkbox("反馈定位到秒点范围", key=cid + "timed")
            start = (
                st.number_input("反馈起始秒", min_value=0.0, key=cid + "start")
                if timed
                else None
            )
            end = (
                st.number_input(
                    "反馈结束秒", min_value=float(start or 0), key=cid + "end"
                )
                if timed
                else None
            )
            owners = ["暂未定位"] + [x["stage_id"] for x in stages]
            owner = st.selectbox("已有证据的最早责任阶段", owners, key=cid + "owner")
            evidence = st.text_area(
                "责任定位依据（引用实际剧本、分镜或请求字段）", key=cid + "evidence"
            )
            if st.button(
                "记录这份视频的人工决定",
                disabled=decision == "未决定" or not statement.strip(),
                key=cid + "review",
            ):
                try:
                    result = media_feedback(
                        run_dir,
                        cid,
                        "approved" if decision == "通过" else "rejected",
                        statement,
                        video_sha256=candidate["video"]["sha256"],
                        time_range=[start, end] if timed else None,
                        responsible_stage=owner if owner != "暂未定位" else None,
                        stage_output_sha256=next(
                            (
                                x["output_sha256"]
                                for x in stages
                                if x["stage_id"] == owner
                            ),
                            None,
                        ),
                        evidence=[{"user_evidence": evidence}]
                        if evidence.strip()
                        else None,
                    )
                    st.success(result["next_action"])
                    st.rerun()
                except (ValueError, RuntimeError, OSError) as exc:
                    st.error(str(exc))
            st.caption(
                "不通过且责任证据不足时保留待定位状态；明确定位后绑定责任阶段返修，重新生成仍需单独执行。"
            )
    with st.expander("交付、浏览器发布与运营回执"):
        review = st.text_input(
            "已人工批准的完整成片审核回执", key=key + "delivery_review"
        )
        account = st.text_input("发布运营账号 key", key=key + "delivery_account")
        account_uuid = st.text_input("发布运营账号 UUID", key=key + "delivery_uuid")
        title = st.text_input("成片发布标题", key=key + "delivery_title")
        description = st.text_area("成片简介", key=key + "delivery_description")
        if st.button(
            "生成发布交付预览",
            disabled=not all((review, account, account_uuid, title)),
            key=key + "delivery_prepare",
        ):
            try:
                result = prepare_delivery(
                    run_dir,
                    review,
                    account_key=account,
                    account_uuid=account_uuid,
                    title=title,
                    description=description,
                )
                st.session_state[key + "delivery"] = result["path"]
                st.json(result["delivery"])
            except (OSError, ValueError, KeyError) as exc:
                st.error(str(exc))
        selected = st.session_state.get(key + "delivery")
        if selected:
            st.caption(
                "发布会主动声明 AI 并读回剧情虚构说明；待核验保留提交锁，不能重复上传。"
            )
            for label, operation in (
                ("明确执行浏览器发布", "publish"),
                ("核验已提交作品", "verify-publish"),
                ("回接对应作品运营数据", "collect-operations"),
            ):
                if st.button(label, key=key + operation):
                    argv = [
                        sys.executable,
                        str(ROOT / "scripts/creative_workbench.py"),
                        str(run_dir),
                        operation,
                        "--delivery",
                        selected,
                        "--account-key",
                        read(selected)["account_key"],
                    ]
                    if operation == "publish":
                        argv.append("--execute")
                    launch(argv)
                    st.success("已启动独立下游操作；结果保存到交付目录。")
            folder = Path(selected).parent
            if (folder / "publish_receipt.json").exists():
                st.json(read(folder / "publish_receipt.json"))
            for path in sorted((folder / "operations").glob("*.json")):
                st.json(read(path))
    commands = sorted(
        (run_dir / ".creative_debug/commands").glob("*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    if commands:
        latest = read(commands[-1])
        if latest.get("status") == "failed":
            st.error("工作台操作未完成：" + latest.get("error", "未知错误"))
    with st.expander("创作质量与用量证据"):
        st.caption(
            "质量结论需要独立人工金标、冻结留出样本及重复评估。接口成功和开发回归不计质量通过。"
        )
        if st.button("汇总现有质量与用量证据", key=key + "quality"):
            try:
                st.json(quality_report(run_dir))
            except (OSError, ValueError, KeyError) as exc:
                st.error(str(exc))
