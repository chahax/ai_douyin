"""
src/scheduler/ui.py — Streamlit 调度管理页面

整合到 app.py 导航中，作为一个子页面。
在 app.py 中注册方式：
  pages.append(st.Page(src.scheduler.ui.page_scheduler, title="任务调度", icon="📋"))
"""

import streamlit as st
import uuid
from datetime import datetime

from src.scheduler import (
    ScheduledTask,
    TaskExecution,
    TaskQueue,
    TaskStatus,
    TaskType,
)
from src.shared.database import SessionLocal


def page_scheduler():
    st.title("📋 任务调度")

    tab_names = ["仪表板", "定时任务", "任务队列", "执行记录", "错误诊断"]
    tabs = st.tabs(tab_names)

    with tabs[0]:
        _render_dashboard()
    with tabs[1]:
        _render_scheduled_tasks()
    with tabs[2]:
        _render_task_queue()
    with tabs[3]:
        _render_execution_history()
    with tabs[4]:
        _render_error_dashboard()


# ── Phase 3: 错误诊断仪表板 ───────────────────────────────────

_SEVERITY_BADGES = {
    "critical": "🔴 critical",
    "high": "🟠 high",
    "medium": "🟡 medium",
    "low": "🟢 low",
}

_CATEGORY_BADGES = {
    "transient": "瞬时",
    "config": "配置",
    "external_api": "外部 API",
    "logic": "逻辑",
    "resource": "资源",
    "auth": "鉴权",
    "data": "数据",
}


def _render_error_dashboard():
    """Phase 3: 显示 LLM 错误诊断。"""
    from src.memory.error_review_model import ErrorReview
    from sqlalchemy import desc

    st.subheader("🔍 LLM 错误诊断")
    st.caption("由 ErrorReviewer 调 LLM 生成的结构化诊断。")

    # 严重未解决 banner
    with SessionLocal() as sess:
        critical_count = (
            sess.query(ErrorReview)
            .filter(
                ErrorReview.severity.in_(["critical", "high"]),
                ErrorReview.resolved_at.is_(None),
            )
            .count()
        )
    if critical_count > 0:
        st.error(f"⚠️ 当前有 {critical_count} 条 high/critical 级未解决错误")

    # 最近 20 条按 cluster_key 分组
    with SessionLocal() as sess:
        rows = (
            sess.query(ErrorReview)
            .order_by(desc(ErrorReview.last_seen_at))
            .limit(20)
            .all()
        )
    if not rows:
        st.info("暂无错误诊断记录。Worker / Agent 失败时会自动写入。")
        return

    # 按 cluster_key 分组显示
    by_cluster: dict[str, list] = {}
    for r in rows:
        by_cluster.setdefault(r.cluster_key or "(无 cluster)", []).append(r)

    for cluster_key, items in by_cluster.items():
        first = items[0]
        sev_badge = _SEVERITY_BADGES.get(first.severity, first.severity)
        cat_badge = _CATEGORY_BADGES.get(first.category, first.category)
        is_recurring = "🔁 recurring" if first.is_recurring else ""

        with st.expander(
            f"{sev_badge} · {cat_badge} · ×{first.occurrence_count} · {cluster_key[:60]} {is_recurring}"
        ):
            st.markdown(f"**📝 一句话描述**")
            st.write(first.summary or "（无）")
            st.markdown(f"**🔍 根因假设**")
            st.write(first.root_cause or "（无）")
            st.markdown(f"**💡 建议修复**")
            st.write(first.suggested_fix or "（无）")
            st.markdown(
                f"_原始错误_: `{first.error_type}: {first.error_message[:200]}`"
            )
            st.caption(
                f"首次: {first.first_seen_at} · 最近: {first.last_seen_at} · "
                f"source={first.source} · location={first.location}"
            )
            if first.context_extra:
                with st.expander("上下文 (JSON)"):
                    try:
                        import json
                        st.json(json.loads(first.context_extra))
                    except Exception:
                        st.text(first.context_extra[:500])
            if not first.resolved_at:
                if st.button(
                    f"✅ 标记已解决 (#{first.id})",
                    key=f"resolve_{first.id}",
                ):
                    with SessionLocal() as sess:
                        row = (
                            sess.query(ErrorReview)
                            .filter_by(id=first.id)
                            .first()
                        )
                        if row:
                            from datetime import datetime
                            row.resolved_at = datetime.utcnow()
                            sess.commit()
                    st.rerun()


# ── 仪表板 ────────────────────────────────────────────────────

def _render_dashboard():
    st.subheader("概览")

    with SessionLocal() as sess:
        total_tasks = sess.query(ScheduledTask).filter_by(enabled=True).count()
        pending = sess.query(TaskExecution).filter_by(status=TaskStatus.PENDING.value).count()
        running = sess.query(TaskExecution).filter_by(status=TaskStatus.RUNNING.value).count()
        completed = sess.query(TaskExecution).filter_by(status=TaskStatus.COMPLETED.value).count()
        failed = sess.query(TaskExecution).filter_by(status=TaskStatus.FAILED.value).count()

    cols = st.columns(5)
    cols[0].metric("活跃任务", total_tasks)
    cols[1].metric("排队中", pending)
    cols[2].metric("运行中", running)
    cols[3].metric("已完成", completed)
    cols[4].metric("失败", failed)

    # 启动/停止 Worker 和调度器
    col_start, col_stop = st.columns(2)
    with col_start:
        if st.button("▶ 启动调度器 + Worker", use_container_width=True):
            _start_scheduler()
            st.rerun()
    with col_stop:
        if st.button("⏹ 停止调度器 + Worker", use_container_width=True):
            _stop_scheduler()
            st.rerun()

    # 最近的执行
    st.divider()
    st.subheader("最近执行")
    with SessionLocal() as sess:
        recent = (
            sess.query(TaskExecution)
            .order_by(TaskExecution.created_at.desc())
            .limit(10)
            .all()
        )

    if recent:
        data = []
        for e in recent:
            task_name = e.task.name if e.task else f"task_id={e.task_id}"
            data.append({
                "执行ID": e.execution_uuid[:8],
                "任务": task_name,
                "状态": _status_badge(e.status),
                "耗时(秒)": e.duration_seconds or "-",
                "时间": e.created_at.strftime("%m-%d %H:%M") if e.created_at else "-",
            })
        st.dataframe(data, use_container_width=True, hide_index=True)
    else:
        st.info("暂无执行记录")


# ── 定时任务 ────────────────────────────────────────────────

def _render_scheduled_tasks():
    st.subheader("定时任务")
    col_new, col_cg, _ = st.columns([1, 1, 3])
    with col_new:
        if st.button("+ 新建任务", use_container_width=True):
            st.session_state["show_new_task"] = True
    with col_cg:
        if st.button("📊 CodeGraph 周更", use_container_width=True):
            _create_codegraph_weekly_task()
            st.success("CodeGraph 周更任务已创建！每周日凌晨 3 点执行 codegraph init -i")
            st.rerun()

    if st.session_state.get("show_new_task"):
        _render_new_task_form()
        if st.button("取消"):
            st.session_state["show_new_task"] = False
            st.rerun()

    # 任务列表
    with SessionLocal() as sess:
        tasks = (
            sess.query(ScheduledTask)
            .order_by(ScheduledTask.created_at.desc())
            .all()
        )

    if not tasks:
        st.info("暂无定时任务，点击「新建任务」创建第一个")
        return

    for task in tasks:
        with st.container():
            cols = st.columns([1, 2, 1, 1, 1, 1])
            cols[0].write(f"**{task.name}**")
            cols[1].write(task.description or "—")
            cols[2].write(f"`{task.skill_name}`")
            cols[3].write(f"触发: {task.trigger_type}")
            enabled = cols[4].toggle("启用", value=bool(task.enabled), key=f"tog_{task.id}")
            if enabled != bool(task.enabled):
                _toggle_task(task.id, enabled)
                st.rerun()
            if cols[5].button("入队", key=f"eq_{task.id}", use_container_width=True):
                _enqueue_task(task.id)
                st.success(f"任务已入队: {task.name}")

            st.divider()


def _render_new_task_form():
    with st.form("new_task", clear_on_submit=True):
        st.markdown("### 新建定时任务")
        name = st.text_input("任务名称", placeholder="每日早 9 点生成视频")
        description = st.text_area("描述（可选）")
        skill_name = st.selectbox(
            "Skill",
            [
                "generate_presenter_video",
                "generate_audio",
                "sync_douyin_videos",
                "fetch_comments",
                "auto_reply_comments",
                "douyin_warmup",
                "rag_search",
            ],
        )
        trigger_type = st.selectbox(
            "触发类型",
            [
                ("cron", "Cron 表达式（如 0 9 * * *）"),
                ("interval", "间隔（每 N 小时/分钟）"),
            ],
            format_func=lambda x: x[1],
        )

        cron_expr = ""
        interval_minutes = 60

        if trigger_type[0] == "cron":
            cron_expr = st.text_input(
                "Cron 表达式",
                value="0 9 * * *",
                placeholder="分 时 日 月 周（如 0 9 * * *）",
            )
        else:
            interval_minutes = st.number_input("间隔（分钟）", min_value=1, value=60)

        max_retries = st.number_input("失败重试次数", min_value=0, max_value=5, value=0)

        params_json = st.text_area(
            "Skill 参数（JSON）",
            value="{}",
            placeholder='{"keywords": "励志"}',
        )

        submitted = st.form_submit_button("创建任务")
        if submitted:
            import json
            try:
                params = json.loads(params_json) if params_json.strip() else {}
            except json.JSONDecodeError:
                st.error("JSON 格式错误")
                return

            trigger_config = {}
            if trigger_type[0] == "cron":
                trigger_config = {"expression": cron_expr}
            else:
                trigger_config = {"minutes": interval_minutes}

            _create_task(
                name=name,
                description=description,
                skill_name=skill_name,
                trigger_type=trigger_type[0],
                trigger_config=trigger_config,
                max_retries=max_retries,
                skill_params=params,
            )
            st.session_state["show_new_task"] = False
            st.success("任务创建成功")
            st.rerun()


# ── 任务队列 ────────────────────────────────────────────────

def _render_task_queue():
    st.subheader("任务队列")
    col_refresh, _ = st.columns([1, 4])
    with col_refresh:
        if st.button("🔄 刷新", use_container_width=True):
            st.rerun()

    with SessionLocal() as sess:
        pending = (
            sess.query(TaskExecution)
            .filter_by(status=TaskStatus.PENDING.value)
            .order_by(TaskExecution.created_at.asc())
            .all()
        )
        running = (
            sess.query(TaskExecution)
            .filter_by(status=TaskStatus.RUNNING.value)
            .all()
        )

    st.markdown(f"**排队中** ({len(pending)})")
    if pending:
        for e in pending[:20]:
            task_name = e.task.name if e.task else f"task_id={e.task_id}"
            cols = st.columns([2, 1, 1, 1])
            cols[0].write(task_name)
            cols[1].write(f"`{e.execution_uuid[:8]}`")
            cols[2].write(f"重试 {e.attempt} 次" if e.is_retry else f"第 {e.attempt} 次")
            cols[3].write(e.created_at.strftime("%H:%M:%S") if e.created_at else "-")
    else:
        st.info("队列空闲，无排队任务")

    st.divider()
    st.markdown(f"**运行中** ({len(running)})")
    if running:
        for e in running:
            task_name = e.task.name if e.task else f"task_id={e.task_id}"
            st.info(f"🔄 {task_name} — {e.execution_uuid[:8]}")
    else:
        st.info("无运行中任务")


# ── 执行记录 ────────────────────────────────────────────────

def _render_execution_history():
    st.subheader("执行记录")
    col_filter, col_limit, _ = st.columns([2, 1, 3])
    with col_filter:
        status_filter = st.selectbox(
            "状态筛选",
            ["全部", TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.PENDING.value, TaskStatus.RUNNING.value],
        )
    with col_limit:
        limit = st.selectbox("条数", [20, 50, 100], index=0)

    with SessionLocal() as sess:
        q = sess.query(TaskExecution).order_by(TaskExecution.created_at.desc())
        if status_filter != "全部":
            q = q.filter_by(status=status_filter)
        executions = q.limit(limit).all()

    for e in executions:
        with st.container():
            task_name = e.task.name if e.task else f"task_id={e.task_id}"
            cols = st.columns([2, 1, 1, 1, 1])
            cols[0].write(f"**{task_name}**")
            cols[1].write(_status_badge(e.status))
            cols[2].write(f"{e.duration_seconds}s" if e.duration_seconds else "-")
            cols[3].write(e.created_at.strftime("%m-%d %H:%M") if e.created_at else "-")
            if e.status == TaskStatus.FAILED.value:
                with cols[4]:
                    with st.expander("错误"):
                        st.code(e.error_message or "无")
            else:
                with cols[4]:
                    with st.expander("结果"):
                        st.json(e.result or {})


# ── 辅助函数 ────────────────────────────────────────────────

def _status_badge(status: str) -> str:
    emoji = {
        TaskStatus.PENDING.value: "⏳",
        TaskStatus.RUNNING.value: "🔄",
        TaskStatus.COMPLETED.value: "✅",
        TaskStatus.FAILED.value: "❌",
        TaskStatus.CANCELLED.value: "🚫",
    }
    return f"{emoji.get(status, '❓')} {status}"


def _start_scheduler():
    try:
        from src.scheduler.runner import start_scheduler as _do_start
        _do_start()
        st.success("调度器 + Worker 已启动")
    except Exception as exc:
        st.error(f"启动失败: {exc}")


def _stop_scheduler():
    try:
        from src.scheduler.runner import stop_scheduler as _do_stop
        _do_stop()
        st.success("调度器已停止")
    except Exception as exc:
        st.error(f"停止失败: {exc}")


def _toggle_task(task_id: int, enabled: bool):
    with SessionLocal() as sess:
        task = sess.query(ScheduledTask).filter_by(id=task_id).first()
        if task:
            task.enabled = enabled
            task.updated_at = datetime.utcnow()
            sess.commit()


def _enqueue_task(task_id: int):
    with TaskQueue() as q:
        result = q.enqueue(task_id)
    return result


def _create_task(
    name: str,
    description: str,
    skill_name: str,
    trigger_type: str,
    trigger_config: dict,
    max_retries: int,
    skill_params: dict,
) -> ScheduledTask:
    task = ScheduledTask(
        task_uuid=uuid.uuid4().hex,
        name=name,
        description=description,
        skill_name=skill_name,
        skill_params=skill_params,
        task_type=TaskType.SCHEDULED.value,
        trigger_type=trigger_type,
        trigger_config=trigger_config,
        max_retries=max_retries,
        enabled=True,
        status=TaskStatus.PENDING.value,
    )
    with SessionLocal() as sess:
        sess.add(task)
        sess.commit()
        sess.refresh(task)
        # 注册到 APScheduler（如果调度器在运行）
        try:
            from src.scheduler.runner import scheduler_instance
            if scheduler_instance:
                scheduler_instance.add_task(task)
        except Exception:
            pass
    return task


def _create_codegraph_weekly_task():
    """创建 CodeGraph 周更任务：每周日凌晨 3 点执行 `codegraph init -i`。

    Open-source 注意：npx/codegraph 的实际路径由用户在环境里决定，
    所以这里探测常见位置；找不到就跳过创建，让用户在 UI 里手动配置。
    """
    from pathlib import Path
    # 检查是否已存在同名任务
    with SessionLocal() as sess:
        existing = sess.query(ScheduledTask).filter(
            ScheduledTask.name == "CodeGraph 周更"
        ).first()
        if existing:
            return

    # 探测 codegraph 可执行文件（不写死个人路径）
    codegraph_cmd = _detect_codegraph_command()
    if not codegraph_cmd:
        # 探测失败，不创建任务；UI 已有提示
        return

    project_root = str(Path(__file__).resolve().parents[2])  # 运行时自动算
    _create_task(
        name="CodeGraph 周更",
        description="每周日凌晨 3 点重建代码索引，保持 CodeGraph 图谱新鲜",
        skill_name="run_bash_command",
        trigger_type="cron",
        trigger_config={"expression": "0 3 * * 0"},  # 每周日 3:00
        max_retries=1,
        skill_params={
            "command": codegraph_cmd,
            "cwd": project_root,
        },
    )


def _detect_codegraph_command() -> str | None:
    """探测 codegraph 命令。优先用 `codegraph`（PATH 里），其次 `npx codegraph`。"""
    import shutil
    if shutil.which("codegraph"):
        return "codegraph init -i"
    if shutil.which("npx"):
        return "npx -y codegraph init -i"
    return None
