# -*- coding: utf-8 -*-
"""
app.py — Streamlit 管理后台入口

使用 st.navigation() API 自定义侧边栏，彻底控制中文标签。
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
from src.web.components.auth import render_login_page, get_current_user, get_current_role, logout_user, has_permission
from src.web.components.ui import page_header
from src.shared.logger import logger

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STREAMLIT_LOG_PATH = PROJECT_ROOT / "data" / "logs" / "streamlit_combined.log"

# Registering navigation must happen before the asynchronous cookie component
# can stop a fresh browser session; otherwise Streamlit loses the requested
# pathname and redirects a refreshed subpage to the default home page.
st.set_page_config(page_title="Douyin Studio · 内容创作与运营", page_icon="✦", layout="wide")

LOCAL_SAMPLE_VIDEOS: tuple[dict[str, str], ...] = ()


def _format_file_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def render_local_sample_videos() -> None:
    """按需展示退役前的本地成片，不把它们标记为当前候选。"""
    st.markdown("---")
    st.subheader("🎞️ 历史成片归档")
    st.caption("这些文件来自已退役的视频路线，仅供追溯，不代表当前质量标准。")
    if not st.checkbox("显示退役前的本地成片", value=False, key="show_retired_video_samples"):
        return

    available = []
    seen_paths = set()
    videos_dir = PROJECT_ROOT / "data" / "videos"
    if videos_dir.exists():
        for path in sorted(videos_dir.glob("*.mp4"), key=lambda item: item.stat().st_mtime, reverse=True):
            rel_path = path.relative_to(PROJECT_ROOT).as_posix()
            seen_paths.add(path.resolve())
            available.append(({
                "title": path.stem,
                "path": rel_path,
                "description": "退役前保留的本地视频文件，仅供历史回看。",
                "tag": "历史归档",
            }, path))

    for item in LOCAL_SAMPLE_VIDEOS:
        path = PROJECT_ROOT / item["path"]
        if path.exists() and path.resolve() not in seen_paths:
            available.append((item, path))

    if not available:
        st.info("没有可回看的历史成片。")
        return

    selected_idx = st.selectbox(
        "选择样片",
        range(len(available)),
        format_func=lambda idx: f"{available[idx][0]['tag']} · {available[idx][0]['title']}",
        index=0,
    )
    sample, video_path = available[selected_idx]
    stat = video_path.stat()

    preview_col, info_col = st.columns([1, 2], vertical_alignment="top")
    with preview_col:
        st.video(str(video_path))
    with info_col:
        col_meta1, col_meta2, col_meta3 = st.columns(3)
        with col_meta1:
            st.metric("版本", sample["tag"])
        with col_meta2:
            st.metric("文件大小", _format_file_size(stat.st_size))
        with col_meta3:
            st.metric("更新时间", datetime.fromtimestamp(stat.st_mtime).strftime("%m-%d %H:%M"))
        st.caption(sample["description"])
        st.code(str(video_path), language="text")


def read_recent_publish_log(max_lines: int = 80) -> str:
    """Read recent backend logs for publish/generation troubleshooting."""
    if not STREAMLIT_LOG_PATH.exists():
        return "暂无后台日志。"

    try:
        lines = STREAMLIT_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"读取日志失败: {exc}"

    keywords = (
        "auto_publish_service",
        "generation_service",
        "tts_engine",
        "tts_providers",
        "rag_engine",
        "ERROR",
        "WARNING",
        "Traceback",
        "Edge-TTS",
        "GPT-SoVITS",
        "speech.platform.bing.com",
        "torch",
    )
    selected = [line for line in lines if any(keyword in line for keyword in keywords)]
    if not selected:
        selected = lines
    return "\n".join(selected[-max_lines:]) or "暂无相关日志。"

# ── 当前用户信息（认证完成后在导航区赋值）──────────────────
role_names = {"superadmin": "超级管理员", "admin": "运营管理员", "editor": "运营编辑", "viewer": "查看者"}
user = ""
role = "viewer"

# ── 页面函数（每个函数是一个"页面"）────────────────────────
def page_dashboard():
    import pandas as pd
    from src.services.video_service import count_videos
    from src.services.comment_service import count_comments, count_replied_comments, get_reply_rate
    from src.services.reply_history_service import get_recent_reply_stats
    from src.services.user_profile_service import list_users

    page_header(
        "运营看板",
        "查看视频内容表现、采集后台数据，并跟踪互动回复。",
        icon="◫",
        eyebrow="OPERATIONS OVERVIEW",
    )
    from src.web.content_performance_dashboard import render_content_performance
    render_content_performance()
    st.markdown('---')
    st.caption('以下为全部账号运营汇总。')
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("已发布视频", count_videos(status="published") or 0)
    with col2:
        st.metric("评论总数", count_comments() or 0)
    with col3:
        st.metric("已回复", count_replied_comments() or 0)
    with col4:
        rate = get_reply_rate() or 0
        st.metric("回复率", f"{rate:.1f}%")

    st.markdown("---")
    st.subheader("📈 近7天回复趋势")
    stats = get_recent_reply_stats(days=7)
    if stats:
        df = pd.DataFrame(stats, columns=["日期", "回复数"])
        st.line_chart(df.set_index("日期"))
    else:
        st.info("暂无数据")

    st.markdown("---")
    st.subheader("⚠️ 用户限流预警")
    users = list_users()
    warning_users = [u for u in users if u.get("daily_count", 0) >= u.get("daily_limit", 5) * 0.8]
    if warning_users:
        df_warn = pd.DataFrame(warning_users)
        st.dataframe(df_warn[["user_nickname", "daily_count", "daily_limit", "is_whitelist"]], width='stretch')
    else:
        st.success("所有用户均未接近限流上限")


def page_videos():
    import pandas as pd
    from src.services.video_service import get_videos, count_videos
    from src.services.comment_service import count_comments

    page_header(
        "视频管理",
        "同步已发布作品与反馈；新版逐段生成与成片审核请进入“视频制作”。",
        icon="▶",
        eyebrow="CONTENT LIBRARY",
    )
    from src.operations_accounts import AccountBindingRepository, AccountProfileRepository

    account_repository = AccountProfileRepository()
    account_profiles = account_repository.list_active()
    binding_repository = AccountBindingRepository(account_repository.db_path)
    account_bindings = {
        item.account_key: item for item in binding_repository.list_all()
    }
    trend_prefill = st.session_state.get("trend_publish_prefill", {})
    preferred_uuid = str(trend_prefill.get("account_uuid") or "")
    default_index = next(
        (
            index
            for index, item in enumerate(account_profiles)
            if item.account_uuid == preferred_uuid
        ),
        0,
    )
    if account_profiles:
        from src.web.components.account_scope import select_account_scope
        selected_uuid = select_account_scope(account_profiles, key='video_operation_account_scope', allow_all=False)
        selected_profile = next((item for item in account_profiles if item.account_uuid == selected_uuid), None)
        if selected_profile is None:
            st.info('请选择一个运营账号后查看作品或执行同步。')
            return
        selected_account_key = selected_profile.account_key
        selected_binding = account_bindings.get(selected_account_key)
    else:
        selected_account_key = ""
        selected_profile = None
        selected_binding = None
        st.error("尚未配置运营账号，请先到“抖音账号”创建并绑定账号。")
    account_ready = bool(selected_binding and selected_binding.status == "active")
    selected_account_uuid = selected_profile.account_uuid if selected_profile else ""
    from src.web.publish_run_dashboard import render_publish_runs
    render_publish_runs(selected_account_uuid)
    prefill_account_mismatch = bool(
        preferred_uuid and preferred_uuid != selected_account_uuid
    )
    if account_ready:
        st.success(
            f"即将使用 {selected_binding.display_identity} 抖音账号执行同步或发布。"
        )
    elif selected_profile:
        status_text = selected_binding.status if selected_binding else "未绑定"
        st.error(
            f"当前账号状态：{status_text}。请先到“抖音账号”登录、验真并确认绑定。"
        )
    if prefill_account_mismatch:
        st.error("当前选题卡属于另一个运营账号；请切回原账号，系统不会跨账号发布。")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("已发布", count_videos(status="published", account_uuid=selected_account_uuid) or 0)
    with col2:
        st.metric("待审核", count_videos(status="pending_review", account_uuid=selected_account_uuid) or 0)
    with col3:
        st.metric("总计", count_videos(account_uuid=selected_account_uuid) or 0)

    render_local_sample_videos()

    st.markdown("---")
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        status_filter = st.selectbox("状态筛选", ["全部", "published", "pending_review", "failed"])
    with col_f2:
        search = st.text_input("标题搜索", "")
    status_val = None if status_filter == "全部" else status_filter
    videos = get_videos(
        status=status_val,
        limit=200,
        account_uuid=selected_account_uuid,
    )
    if search:
        videos = [v for v in videos if search.lower() in v.get("title", "").lower()]
    if videos:
        rows = []
        for v in videos:
            comment_count = count_comments(video_id=v.get("video_id")) or 0
            rows.append({
                "video_id": v.get("video_id"),
                "标题": v.get("title", "")[:40],
                "状态": v.get("status", ""),
                "发布时间": (v.get("publish_time") or "")[:10],
                "播放": v.get("stats_views", 0),
                "点赞": v.get("stats_likes", 0),
                "评论": comment_count,
            })
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
    else:
        st.info("暂无视频数据")

    # 批量操作
    st.markdown("---")
    st.subheader("⚡ 批量操作")
    col_sync1, col_sync2 = st.columns(2)
    with col_sync1:
        if st.button("🔄 同步视频列表", width='stretch', disabled=not account_ready):
            with st.spinner("同步中，请稍候..."):
                try:
                    from src.platform_adapter.douyin_adapter import DouyinAdapter

                    adapter = DouyinAdapter.for_account(selected_account_key)
                    result = adapter.sync_videos(page_limit=5)
                    if result.success and result.videos:
                        st.success(f"同步成功！共 {len(result.videos)} 个视频")
                        st.rerun()
                    elif result.message:
                        st.warning(result.message)
                    else:
                        st.error("同步失败，请确认是否已登录（运行 python main.py douyin-login）")
                except Exception as e:
                    st.error(f"同步异常：{e}")
    with col_sync2:
        if st.button("💬 抓取所有视频评论", width='stretch', disabled=not account_ready):
            videos = get_videos(
                status="published",
                limit=100,
                account_uuid=selected_account_uuid,
            )
            total = 0
            failed = 0
            with st.spinner("抓取中，请稍候..."):
                try:
                    from src.platform_adapter.douyin_adapter import DouyinAdapter
                    from src.platform_adapter.models import CommentQuery

                    adapter = DouyinAdapter.for_account(selected_account_key)
                    for v in videos:
                        vid = v.get("video_id")
                        if vid:
                            try:
                                result = adapter.fetch_comments(CommentQuery(post_id=vid))
                                total += len(result.comments)
                            except Exception:
                                failed += 1
                    if total > 0 or failed == 0:
                        st.success(f"抓取完成，共 {total} 条评论" + (f"，{failed} 个视频失败" if failed else ""))
                    else:
                        st.warning("抓取失败，请确认是否已登录")
                    st.rerun()
                except Exception as e:
                    st.error(f"抓取异常：{e}")
                st.success(f"抓取完成，共 {total} 条评论")
                st.rerun()

    # 发布新视频
    st.markdown("---")
    st.subheader("视频生成流程重置中")
    st.warning(
        "原动漫数字人主讲、双角色 FramePack 和单人口播模板质量未达标，"
        "已退出生产入口。当前页面只保留历史参数查看，不允许生成或发布。"
    )
    try:
        from src.workflow.runtime import active_selections

        workflow_defaults = active_selections()
    except Exception as exc:
        logger.warning(f"读取工作流节点配置失败，在线制作使用兼容默认值: {exc}")
        workflow_defaults = {
            "video_pipeline": "disabled_pending_redesign",
            "tts": "edge",
        }
    with st.form("auto_publish_form"):
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            keywords = st.text_input(
                "关键词（生成脚本）",
                value=trend_prefill.get("keywords", ""),
                placeholder="励志,成长",
            )
        with col_p2:
            title = st.text_input(
                "视频标题（空则自动生成）",
                value=trend_prefill.get("title", ""),
                placeholder="自动生成",
            )
        video_mode_labels = ["已停用：等待新视频流程通过验收"]
        video_mode_by_label = {
            "已停用：等待新视频流程通过验收": "disabled_pending_redesign",
        }
        default_video_mode = workflow_defaults.get(
            "video_pipeline", "disabled_pending_redesign"
        )
        default_video_label = next(
            (
                label
                for label, implementation_id in video_mode_by_label.items()
                if implementation_id == default_video_mode
            ),
            "已停用：等待新视频流程通过验收",
        )
        video_mode_label = st.selectbox(
            "视频格式",
            video_mode_labels,
            index=video_mode_labels.index(default_video_label),
            help="旧路线已归档，等待新的镜头生成与验收规范。",
        )
        video_mode = video_mode_by_label[video_mode_label]
        col_p3, col_p4 = st.columns(2)
        with col_p3:
            desc = st.text_input(
                "视频描述",
                value=trend_prefill.get("description", ""),
                placeholder="描述（可选）",
            )
        with col_p4:
            tags = st.text_input(
                "话题标签",
                value=trend_prefill.get("tags", ""),
                placeholder="励志,正能量（逗号分隔）",
            )
        st.markdown(
            """
            <style>
            div[data-testid="stRadio"] label:first-of-type {
                opacity: 0.38;
                pointer-events: none;
                cursor: not-allowed;
            }
            div[data-testid="stRadio"] label:first-of-type * {
                color: rgba(49, 51, 63, 0.45) !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        col_visibility, col_tts = st.columns(2)
        with col_visibility:
            visibility_label = st.radio(
                "视频可见性",
                ["公开", "私密", "仅粉丝"],
                index=1,
                horizontal=True,
                help="公开发布暂时禁用，当前只允许选择私密或仅粉丝。",
            )
            visibility = {"私密": "private", "仅粉丝": "friends"}.get(visibility_label, "private")
        with col_tts:
            tts_choices = ["edge", "gpt_sovits"]
            default_tts = workflow_defaults.get("tts", "edge")
            tts_provider = st.selectbox(
                "配音方式",
                tts_choices,
                index=tts_choices.index(default_tts) if default_tts in tts_choices else 0,
                format_func=lambda x: {"edge": "Edge-TTS（兜底）", "gpt_sovits": "GPT-SoVITS"}[x],
                help="Edge-TTS 需要联网；GPT-SoVITS 可离线，但当前环境缺 torch，需修复后再用。",
            )
            st.caption("Edge-TTS 需要连接微软语音服务；本地离线声线建议后续走 GPT-SoVITS 克隆。")
        quality_profile = st.selectbox(
            "视频质量",
            ["publish", "preview", "master"],
            index=0,
            format_func=lambda value: {
                "preview": "预览（540×960 / 快）",
                "publish": "发布（1080×1920 / 推荐）",
                "master": "母版（1080×1920 / 慢）",
            }[value],
            help="发布档适合抖音上传；预览档用于快速确认；母版用于本地归档或二次剪辑。",
        )
        debug_mode = st.checkbox(
            "调试模式：显示浏览器窗口",
            value=False,
            help="勾选后，发布自动化会打开可见浏览器窗口，方便观察登录、上传、发布和审核确认页面。",
        )
        identity_confirmed = st.checkbox(
            (
                f"我确认本次发布使用 {selected_binding.display_identity}"
                if selected_binding
                else "请先绑定真实抖音账号"
            ),
            value=False,
            disabled=not account_ready,
        )
        submit_label = "视频生成与发布已停用"
        submitted = st.form_submit_button(
            submit_label,
            type="primary",
            disabled=True,
        )
        if submitted and keywords:
            with st.spinner("生成中，请耐心等待..."):
                from src.services.auto_publish_service import AutoPublishService, AutoPublishRequest

                request = AutoPublishRequest(
                    account_key=selected_account_key,
                    keywords=keywords,
                    title=title or "",
                    description=desc or "",
                    hashtags=[t.strip() for t in tags.split(",") if t.strip()] if tags else [],
                    visibility=visibility,
                    tts_provider=tts_provider,
                    video_mode=video_mode,
                    publish_headless=not debug_mode,
                    quality_profile=quality_profile,
                    trend_brief_id=trend_prefill.get("brief_id", ""),
                    trend_cluster_id=trend_prefill.get("cluster_id", ""),
                    hook_type=trend_prefill.get("hook_type", ""),
                    account_uuid=preferred_uuid or selected_account_uuid,
                    account_profile_version=int(
                        trend_prefill.get("account_profile_version", 0) or 0
                    ),
                    domain_strategy_id=trend_prefill.get("domain_strategy_id", ""),
                    strategy_version=trend_prefill.get("strategy_version", ""),
                    opportunity_id=trend_prefill.get("opportunity_id", ""),
                    opportunity_script_id=trend_prefill.get(
                        "opportunity_script_id", ""
                    ),
                    script_variant=trend_prefill.get("script_variant", ""),
                    presentation_type=trend_prefill.get("presentation_type", ""),
                    pacing=trend_prefill.get("pacing", ""),
                    publish_window=trend_prefill.get("publish_window", ""),
                    workflow_profile=trend_prefill.get("workflow_profile", ""),
                )
                service = AutoPublishService()
                result = service.publish(request)
            if result.success:
                st.session_state.pop("trend_publish_prefill", None)
                if result.post_id:
                    st.success(f"发布成功！视频ID: {result.post_id}")
                else:
                    st.success("发布已提交，作品可能仍在审核或作品管理页同步中。请稍后到抖音创作者中心人工确认。")
                if result.publish_url:
                    st.write(f"链接: {result.publish_url}")
                st.link_button(
                    "打开抖音创作者中心",
                    "https://creator.douyin.com/creator-micro/content/manage",
                    width='stretch',
                )
            else:
                st.error(f"发布失败: {result.message}")
                with st.expander("查看最近发布日志", expanded=True):
                    st.code(read_recent_publish_log(), language="text")
        elif submitted:
            st.warning("请输入关键词")

    with st.expander("最近发布日志", expanded=False):
        st.code(read_recent_publish_log(), language="text")


def page_comments():
    import pandas as pd
    from src.services.comment_service import get_comments, count_comments, count_replied_comments
    from src.services.video_service import get_videos

    page_header(
        "评论管理",
        "按视频和回复状态筛选互动，保持评论处理清晰可追踪。",
        icon="◌",
        eyebrow="COMMUNITY",
    )
    from src.operations_accounts import AccountBindingRepository, AccountProfileRepository

    account_repository = AccountProfileRepository()
    profiles = account_repository.list_active()
    if not profiles:
        st.info("请先在“抖音账号”创建运营账号。")
        return
    bindings = {
        item.account_key: item
        for item in AccountBindingRepository(account_repository.db_path).list_all()
    }
    from src.web.components.account_scope import select_account_scope
    selected_uuid = select_account_scope(profiles, key='comments_account_scope', allow_all=False)
    selected_profile = next((item for item in profiles if item.account_uuid == selected_uuid), None)
    if selected_profile is None:
        st.info('请选择运营账号后查看评论。')
        return
    selected_account_key = selected_profile.account_key
    selected_account_uuid = selected_profile.account_uuid
    selected_binding = bindings.get(selected_account_key)
    account_ready = bool(selected_binding and selected_binding.status == 'active')
    # Streamlit keeps imported service modules between page reruns. During a
    # live upgrade the cached module may predate this API, so refresh it once
    # before reading the creator-side totals.
    from src.services import content_performance as performance_service
    if not hasattr(performance_service, "latest_metric_totals"):
        from importlib import reload
        performance_service = reload(performance_service)
    platform_metrics = performance_service.latest_metric_totals(selected_account_uuid)
    detail_total = count_comments(account_uuid=selected_account_uuid) or 0
    platform_total = platform_metrics['comment_count']
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("后台评论计数", platform_total if platform_total is not None else "未采集")
    with col2:
        st.metric("已同步评论明细", detail_total)
    with col3:
        st.metric("已回复明细", count_replied_comments(account_uuid=selected_account_uuid) or 0)
    with col4:
        unreplied = (
            detail_total
        ) - (count_replied_comments(account_uuid=selected_account_uuid) or 0)
        st.metric("未回复明细", unreplied)

    if platform_total is not None and platform_total > detail_total:
        st.warning(
            f"抖音后台显示 {platform_total} 条评论，但本地只同步到 {detail_total} 条明细。"
            "后台计数用于表现分析；只有成功抓取到作者、正文和评论 ID 后，才会出现在下方评论列表。"
        )

    videos = get_videos(status="published", limit=100, account_uuid=selected_account_uuid)
    status_rows = []
    for video in videos:
        video_id_value = video.get('video_id') or ''
        synced = count_comments(video_id=video_id_value, account_uuid=selected_account_uuid) if video_id_value else 0
        backend = video.get('stats_comments')
        status_rows.append({
            '作品': (video.get('title') or '未知')[:42],
            '后台评论计数': backend,
            '已同步明细': synced,
            '同步状态': '已同步完整' if backend is not None and synced >= backend else ('等待同步' if backend else '暂无评论'),
        })
    if status_rows:
        st.dataframe(pd.DataFrame(status_rows), hide_index=True, width='stretch')

    if st.button('同步评论明细', key='comments_detail_sync', disabled=not account_ready):
        adapter = None
        successes, failures, fetched = 0, [], 0
        try:
            from src.platform_adapter.douyin_adapter import DouyinAdapter
            from src.platform_adapter.models import CommentQuery
            adapter = DouyinAdapter.for_account(selected_account_key)
            with st.spinner('正在逐条作品同步评论明细…'):
                for video in videos:
                    video_id_value = video.get('video_id')
                    if not video_id_value:
                        continue
                    result = adapter.fetch_comments(CommentQuery(post_id=video_id_value))
                    if result.success:
                        successes += 1
                        fetched += len(result.comments)
                    else:
                        failures.append(f"{video_id_value}: {result.message or result.status}")
            if failures:
                st.warning(f"已处理 {successes} 条作品，保存 {fetched} 条评论明细；{len(failures)} 条作品未成功。")
                with st.expander('查看同步失败原因', expanded=True):
                    for failure in failures:
                        st.text(failure)
            else:
                st.success(f"评论明细同步完成，保存 {fetched} 条。")
            if fetched:
                st.rerun()
        except Exception as exc:
            st.error(f"评论明细同步未完成：{exc}")
        finally:
            if adapter:
                adapter.close()

    st.markdown("---")
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        video_options = {"全部": ""}
        for v in videos:
            video_options[v.get("title", "未知")[:30]] = v.get("video_id", "")
        selected_video = st.selectbox("视频", list(video_options.keys()))
    with col_f2:
        replied_filter = st.selectbox("回复状态", ["全部", "已回复", "未回复"])
    with col_f3:
        search = st.text_input("搜索评论", "")

    video_id = video_options.get(selected_video, "")
    is_replied = None
    if replied_filter == "已回复":
        is_replied = 1
    elif replied_filter == "未回复":
        is_replied = 0
    comments = get_comments(
        video_id=video_id or None,
        is_replied=is_replied,
        account_uuid=selected_account_uuid,
        limit=200,
    )
    if search:
        comments = [c for c in comments if search.lower() in c.get("content", "").lower()]
    if comments:
        rows = []
        for c in comments:
            rows.append({
                "comment_id": c.get("comment_id"),
                "视频": (c.get("video_id") or "")[:15],
                "用户": c.get("user_nickname", ""),
                "评论内容": (c.get("content") or "")[:40],
                "是否回复": "✅" if c.get("is_replied") == 1 else "❌",
                "回复内容": (c.get("reply_content") or "")[:30],
                "时间": (c.get("created_at") or "")[:16],
            })
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
    else:
        if platform_total:
            st.info("后台已有评论计数，但评论正文、作者和评论 ID 尚未同步成功。")
        else:
            st.info("暂无评论数据")


def page_auto_reply():
    from src.platform_adapter.auto_reply_service import AutoReplyService
    from src.services.video_service import get_videos
    from src.services.reply_history_service import get_reply_history

    page_header(
        "评论回复建议",
        "只读抓取并生成回复建议；点赞、评论和关注不会自动执行。",
        icon="✦",
        eyebrow="AUTOMATION",
    )
    st.warning("外部互动已改为逐条人工确认。此页面不会自动发送任何评论。")
    from src.operations_accounts import AccountBindingRepository, AccountProfileRepository

    account_repository = AccountProfileRepository()
    profiles = account_repository.list_active()
    bindings = {
        item.account_key: item
        for item in AccountBindingRepository(account_repository.db_path).list_all()
    }
    ready_profiles = [
        item
        for item in profiles
        if bindings.get(item.account_key)
        and bindings[item.account_key].status == "active"
    ]
    if not ready_profiles:
        st.error("没有登录健康且已确认绑定的运营账号。")
        return
    from src.web.components.account_scope import select_account_scope
    selected_uuid = select_account_scope(ready_profiles, key='reply_account_scope', allow_all=False)
    profile = next((item for item in ready_profiles if item.account_uuid == selected_uuid), None)
    if profile is None:
        st.info('请选择一个登录健康的运营账号。')
        return
    account_key = profile.account_key
    video_options = {"请选择视频": ""}
    videos = get_videos(
        status="published",
        limit=100,
        account_uuid=profile.account_uuid,
    )
    for v in videos:
        video_options[f"{v.get('title', '未知')[:30]} ({v.get('video_id', '')[:8]})"] = v.get("video_id", "")
    selected = st.selectbox("选择视频", list(video_options.keys()))
    target_video_id = video_options.get(selected, "")

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        trigger_single = st.button("生成选中视频回复建议", width='stretch', type="primary")
    with col_btn2:
        trigger_all = st.button("生成全部视频回复建议", width='stretch')

    if trigger_single and target_video_id:
        with st.spinner("处理中..."):
            service = AutoReplyService(account_key)
            try:
                result = service.process_video(target_video_id)
            finally:
                service.close()
        st.success(f"完成：建议={len(result.actions)}，实际发送=0")
        for a in result.actions[:10]:
            st.text(f"  [{a.source}] {a.comment.content[:30]} → {a.reply_content[:20]}")

    if trigger_all:
        with st.spinner("处理中..."):
            service = AutoReplyService(account_key)
            videos = get_videos(
                status="published",
                limit=100,
                account_uuid=profile.account_uuid,
            )
            total_suggestions = 0
            try:
                for v in videos:
                    result = service.process_video(v.get("video_id", ""))
                    total_suggestions += len(result.actions)
            finally:
                service.close()
        st.success(f"全部完成：生成建议={total_suggestions}，实际发送=0")

    st.markdown("---")
    st.subheader("📋 最近的回复记录")
    history = get_reply_history(limit=20)
    if history:
        for h in history:
            badge = "🤖" if h.get("auto_generated") else "👤"
            st.text(f"{badge} [{h.get('user_nickname', '')}] {h.get('reply_content', '')[:40]} - {h.get('created_at', '')[:16]}")
    else:
        st.info("暂无回复历史")


def page_rules():
    import pandas as pd
    from src.services.reply_rules_service import get_rules, add_rule, update_rule, delete_rule

    page_header(
        "回复规则",
        "管理关键词、匹配方式与模型回复策略。",
        icon="⌁",
        eyebrow="RESPONSE POLICY",
    )
    with st.form("add_rule_form"):
        col1, col2 = st.columns(2)
        with col1:
            keyword = st.text_input("触发关键词")
        with col2:
            reply_template = st.text_input("回复模板")
        col3, col4, col5 = st.columns(3)
        with col3:
            match_type = st.selectbox("匹配方式", ["contains", "exact", "regex"])
        with col4:
            reply_type = st.selectbox("回复类型", ["fixed", "llm"],
                                     format_func=lambda x: {"fixed": "固定回复", "llm": "大模型生成"}[x])
        with col5:
            llm_model = st.text_input("大模型", value="qwen2.5:7b")
        enabled = st.checkbox("立即启用", value=True)
        submitted = st.form_submit_button("添加规则")
        if submitted and keyword and reply_template:
            rule_id = add_rule(keyword, reply_template, match_type, reply_type, llm_model or "", enabled)
            if rule_id:
                st.success(f"规则添加成功 (ID={rule_id})")
                st.rerun()
            else:
                st.error("添加失败")
        elif submitted:
            st.warning("关键词和回复模板不能为空")

    st.markdown("---")
    rules = get_rules()
    if rules:
        rows = [{"id": r.id, "关键词": r.keyword, "回复模板": r.reply_template[:40],
                 "匹配": r.match_type, "类型": r.reply_type, "模型": r.llm_model or "-",
                 "启用": "✅" if r.enabled else "❌"} for r in rules]
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
        st.subheader("🛠️ 操作")
        col_op1, col_op2 = st.columns([2, 1])
        with col_op1:
            op_rule_id = st.number_input("规则 ID", min_value=1, step=1, key="op_rule_id")
        with col_op2:
            op_action = st.selectbox("操作", ["启用", "禁用", "删除"])
        if st.button("执行操作"):
            rule = next((r for r in rules if r.id == op_rule_id), None)
            if rule:
                if op_action == "启用":
                    update_rule(op_rule_id, enabled=True)
                elif op_action == "禁用":
                    update_rule(op_rule_id, enabled=False)
                elif op_action == "删除":
                    delete_rule(op_rule_id)
                st.rerun()
    else:
        st.info("暂无规则，请先添加")


def page_blocked_words():
    import pandas as pd
    from src.services.blocked_words_service import get_blocked_words, add_blocked_word, remove_blocked_word, add_blocked_words_batch

    page_header(
        "违禁词管理",
        "维护发布与回复前的内容安全词库。",
        icon="!",
        eyebrow="CONTENT SAFETY",
    )
    col_add1, col_add2 = st.columns([3, 1])
    with col_add1:
        new_word = st.text_input("违禁词", placeholder="输入违禁词后点击添加")
    with col_add2:
        st.write("")
        if st.button("添加", width='stretch'):
            if new_word:
                if add_blocked_word(new_word):
                    st.success(f"已添加: {new_word}")
                    st.rerun()
                else:
                    st.info("已存在")
            else:
                st.warning("请输入违禁词")

    st.subheader("📥 批量导入")
    with st.form("batch_add_form"):
        batch_text = st.text_area("批量添加（每行一个违禁词）", height=100)
        submitted = st.form_submit_button("批量导入")
        if submitted and batch_text:
            words = [w.strip() for w in batch_text.strip().split("\n") if w.strip()]
            added = add_blocked_words_batch(words)
            st.success(f"成功添加 {added} 个违禁词")
            st.rerun()

    st.markdown("---")
    words = get_blocked_words()
    if words:
        rows = [{"id": w["id"], "违禁词": w["word"], "添加时间": (w.get("created_at") or "")[:10]} for w in words]
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
        col_del1, col_del2 = st.columns([2, 1])
        with col_del1:
            del_id = st.number_input("删除违禁词 ID", min_value=1, step=1, key="del_word_id")
        with col_del2:
            if st.button("🗑️ 删除", width='stretch'):
                if remove_blocked_word(del_id):
                    st.success("已删除")
                    st.rerun()
    else:
        st.info("暂无违禁词")


def page_books():
    from src.shared.config import settings
    from src.rag_engine.knowledge_importer import KnowledgeImporter
    import shutil
    from pathlib import Path

    page_header(
        "知识库",
        "同步书籍素材、检查向量库状态并管理内容来源。",
        icon="▤",
        eyebrow="KNOWLEDGE BASE",
    )

    # ── 当前已导入书籍 ──
    books_dir = Path(settings.BOOKS_DIR)
    st.subheader("已导入书籍")
    if books_dir.exists():
        files = [f for f in books_dir.iterdir() if f.is_file()]
        if files:
            for f in files:
                size_kb = f.stat().st_size // 1024
                st.text(f"  📄 {f.name} ({size_kb} KB)")
        else:
            st.info("书籍目录为空")
    else:
        st.info(f"书籍目录不存在: {books_dir}")

    # ── 同步配置 ──
    st.markdown("---")
    st.subheader("🔄 同步配置")

    source_dir = st.text_input(
        "源书籍目录",
        value=getattr(settings, "SYNC_BOOKS_SOURCE_DIR", "C:/data/books"),
        placeholder="例如 C:/data/books",
        help="从此目录同步书籍到本地书籍目录，然后自动导入 RAG 知识库",
    )

    col_sync, col_reimport = st.columns(2)

    with col_sync:
        if st.button("📥 同步并导入", width="stretch", type="primary"):
            if not source_dir:
                st.warning("请先输入源书籍目录")
            else:
                source_path = Path(source_dir)
                if not source_path.exists():
                    st.error(f"源目录不存在: {source_path}")
                else:
                    with st.spinner("同步中..."):
                        try:
                            # 同步文件
                            supported_ext = {".txt", ".epub", ".pdf"}
                            synced_files = []
                            for src in source_path.glob("*"):
                                if src.is_file() and src.suffix.lower() in supported_ext:
                                    dst = books_dir / src.name
                                    if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
                                        shutil.copy2(src, dst)
                                        synced_files.append(src.name)

                            st.success(f"同步完成: {len(synced_files)} 个文件" if synced_files else "无新文件需要同步")

                            # 立即导入
                            if synced_files:
                                with st.spinner("导入知识库中..."):
                                    importer = KnowledgeImporter()
                                    importer.import_books(str(books_dir))
                                    st.success(f"已导入: {', '.join(synced_files)}")
                                st.rerun()
                        except Exception as e:
                            st.error(f"同步失败: {e}")

    with col_reimport:
        if st.button("🔃 重新导入全部", width="stretch"):
            with st.spinner("重新导入中..."):
                try:
                    importer = KnowledgeImporter()
                    importer.import_books(str(books_dir))
                    st.success("全部书籍已重新导入知识库")
                    st.rerun()
                except Exception as e:
                    st.error(f"导入失败: {e}")

    # ── 知识库状态 ──
    st.markdown("---")
    st.subheader("📊 知识库状态")
    try:
        import sqlite3
        conn = sqlite3.connect("data/chroma_db/chroma.sqlite3")
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM embedding_metadata WHERE key="chroma:document"')
        chunk_count = cur.fetchone()[0]
        cur.execute('SELECT DISTINCT string_value FROM embedding_metadata WHERE key="source_book"')
        sources = [r[0] for r in cur.fetchall() if r[0]]
        conn.close()
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.metric("文档片段数", chunk_count)
        with col_c2:
            st.metric("来源书籍", len(sources))
        if sources:
            for src in sources:
                st.text(f"  📖 {src}")
    except Exception as e:
        st.warning(f"无法读取知识库状态: {e}")

    st.markdown("---")
    st.caption("💡 修改源书籍目录后需编辑 .env 文件中的 SYNC_BOOKS_SOURCE_DIR，重启后生效")


# ── 番茄视频人工审核 ──────────────────────────────────────────
def page_fanqie_video_reviews():
    from src.services.fanqie_review_service import decide_review, list_reviews

    page_header(
        "番茄视频审核",
        "逐镜头播放、完播计时与人工验收集中在同一审核工作区。",
        icon="✓",
        eyebrow="HUMAN REVIEW",
    )
    st.caption(
        "真实候选生成后进入待审核。无需密钥；候选哈希、播放计时、审核账号和决定会同时写入审核文件与闭环数据库。"
    )

    status_label = st.selectbox(
        "状态筛选", ["待审核", "已通过", "已驳回", "审计异常", "无效/缺产物", "全部"], index=0
    )
    status_map = {
        "待审核": "pending_review",
        "已通过": "approved",
        "已驳回": "rejected",
        "审计异常": "audit_error",
        "无效/缺产物": "invalid",
        "全部": None,
    }
    reviews = list_reviews(status_map[status_label], sync_database=True)
    if not reviews:
        st.info("当前没有符合条件的真实候选。空模板不会进入待审核列表。")
        return

    for item in reviews:
        if item["review_type"] == "smoke":
            type_name = "7 镜头样片"
        elif item["review_type"] == "full_video_v63":
            type_name = "V6.3 · 观感优先 19 段/32 微镜头整片"
        elif item["review_type"] == "full_video_v62":
            type_name = "V6.2 · 19 段/32 微镜头整片"
        else:
            type_name = "19 镜头整片"
        with st.expander(f"{type_name} · {item['status']} · {item['name']}", expanded=item["status"] == "pending_review"):
            st.code(item["path"], language="text")
            preview = Path(item["preview_path"]) if item["preview_path"] else None
            if preview and preview.is_file():
                st.image(str(preview), caption="审核联系表")
            video_paths = [Path(value) for value in item.get("video_paths", [])]
            if len(video_paths) == 1 and video_paths[0].is_file():
                st.video(str(video_paths[0]))
            elif video_paths:
                with st.expander(f"逐镜头播放（{len(video_paths)} 个）", expanded=True):
                    for index, video in enumerate(video_paths, start=1):
                        if video.is_file():
                            st.caption(f"镜头 {index} · {video.name}")
                            st.video(str(video))
            if item["reviewer"]:
                st.caption(f"审核人：{item['reviewer']} · 审核时间：{item['reviewed_at'] or '-'}")
            if item["notes"]:
                st.write(item["notes"])

            if item.get("validation_error"):
                st.error(f"该记录不能审核：{item['validation_error']}")
                continue
            if item["status"] == "audit_error":
                st.error(
                    "该最终决定缺少可信数据库事件，已禁止进入登记/发布链："
                    f"{item.get('database_error') or '未知审计错误'}"
                )
                continue
            if item["status"] != "pending_review":
                continue

            if item.get("database_status") != "queued":
                st.error(
                    "待审核状态未能写入闭环数据库，已禁止提交决定："
                    f"{item.get('database_error') or '未知数据库错误'}"
                )
                st.code(item.get("database_path") or "", language="text")
                continue
            st.success(
                "待审核审计事件已写入闭环数据库（尚未登记推广任务/视频任务） · event="
                f"{item.get('database_event_uuid') or '-'}"
            )

            state_prefix = f"fanqie_review_{item['review_sha256']}"
            start_key = f"{state_prefix}_playback_started"
            finish_key = f"{state_prefix}_playback_finished"
            required_seconds = float(item.get("required_playback_seconds") or 0)
            st.caption(f"完整播放计时要求：至少 {required_seconds:.2f} 秒")
            if start_key not in st.session_state:
                if st.button("开始完整播放计时", key=f"{state_prefix}_start"):
                    st.session_state[start_key] = datetime.now(timezone.utc).isoformat()
                    st.session_state.pop(finish_key, None)
                    st.rerun()
            else:
                started = datetime.fromisoformat(st.session_state[start_key])
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                if finish_key not in st.session_state:
                    if elapsed + 0.25 < required_seconds:
                        st.info(
                            f"已计时 {elapsed:.1f} 秒，还需约 "
                            f"{max(0.0, required_seconds - elapsed):.1f} 秒。播放完成后点击刷新。"
                        )
                        if st.button("刷新播放计时", key=f"{state_prefix}_refresh"):
                            st.rerun()
                    elif st.button("记录完整播放完成", key=f"{state_prefix}_finish", type="primary"):
                        st.session_state[finish_key] = datetime.now(timezone.utc).isoformat()
                        st.rerun()
                else:
                    finished = datetime.fromisoformat(st.session_state[finish_key])
                    actual = (finished - started).total_seconds()
                    st.success(f"完整播放已记录：{actual:.1f} 秒")

            playback_complete = finish_key in st.session_state
            confirmation_values = {}
            with st.expander("逐项人工审核（全部勾选后才能通过）", expanded=True):
                for check_key, detail in item.get("required_confirmations", {}).items():
                    label = str(detail.get("label") or check_key)
                    criteria = list(detail.get("criteria") or [])
                    if len(criteria) > 1:
                        st.caption(" · ".join(criteria))
                    confirmation_values[check_key] = st.checkbox(
                        label,
                        key=f"{state_prefix}_check_{check_key}",
                        disabled=not playback_complete,
                    )
            all_confirmed = bool(confirmation_values) and all(
                confirmation_values.values()
            )
            notes = st.text_area("审核备注", key=f"fanqie_review_notes_{item['name']}")
            approve_col, reject_col = st.columns(2)
            with approve_col:
                if st.button(
                    "通过", key=f"fanqie_review_approve_{item['name']}",
                    disabled=not (all_confirmed and playback_complete), type="primary",
                ):
                    try:
                        reviewer = get_current_user()
                        if not reviewer:
                            raise ValueError("当前登录账号无效，请重新登录")
                        decide_review(
                            item["path"], decision="approved",
                            reviewer=reviewer, notes=notes,
                            expected_review_sha256=item["review_sha256"],
                            confirmations=confirmation_values,
                            playback_started_at=st.session_state[start_key],
                            playback_finished_at=st.session_state[finish_key],
                        )
                        st.success("审核已通过并写入数据库审计；等待匹配推广任务后再原子登记，上传和回填仍关闭。")
                        st.rerun()
                    except (OSError, ValueError, RuntimeError) as exc:
                        st.error(f"保存审核结果失败：{exc}")
            with reject_col:
                if st.button("驳回", key=f"fanqie_review_reject_{item['name']}"):
                    try:
                        reviewer = get_current_user()
                        if not reviewer:
                            raise ValueError("当前登录账号无效，请重新登录")
                        decide_review(
                            item["path"], decision="rejected",
                            reviewer=reviewer, notes=notes,
                            expected_review_sha256=item["review_sha256"],
                        )
                        st.warning("已驳回，可按备注重新生成新的候选任务。")
                        st.rerun()
                    except (OSError, ValueError, RuntimeError) as exc:
                        st.error(f"保存审核结果失败：{exc}")


# ── 番茄批量抓取清单（Harness Engineering L5）────────────────
def page_fanqie_batch_queue():
    """展示 fanqie_batch_books 清单 + 状态 filter + 一键 Run。

    DB 表（fanqie_batch_books）字段见 src/platform_adapter/fanqie_batch.py。
    批量抓取不接受任意 book_names —— 必须先加书到 DB，再跑 Run。
    """
    page_header(
        "番茄批量清单",
        "维护受控抓取队列、筛选候选书目并追踪任务进度。",
        icon="≡",
        eyebrow="BATCH OPERATIONS",
    )
    from src.web.components.flow_graph import sequence_graph
    sequence_graph([
        ('选择素材', '按书名添加，或按榜单与分类条件筛选小说。', '操作指引'),
        ('确认清单', '检查候选书籍与章节数，确定此次采集范围。', '操作指引'),
        ('提交队列', '把待采集书籍交给后台逐项处理。', '操作指引'),
        ('检查结果', '查看成功、失败与跳过记录，再决定是否补采。', '操作指引'),
    ], key='batch_intro_graph', title='素材采集的四个步骤',
       description='先选素材、确认清单，再提交后台。点击节点或连线查看说明，实际执行仍由下方按钮触发。')

    # ── 顶部 metric ───────────────────────────────────────
    from src.platform_adapter.fanqie_batch import list_books
    from src.scheduler.models import FanqieBatchStatus

    all_books = list_books(limit=500)
    counts = {s.value: 0 for s in FanqieBatchStatus}
    for b in all_books:
        counts[b["status"]] = counts.get(b["status"], 0) + 1

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("总清单", len(all_books))
    col2.metric("待抓 pending", counts.get("pending", 0))
    col3.metric("抓取中 running", counts.get("running", 0))
    col4.metric("完成 done", counts.get("done", 0))
    col5.metric("失败 failed", counts.get("failed", 0))

    st.divider()

    # ── 一键清空清单（二次确认防误删） ──────────────────
    with st.expander("🗑 清空清单（危险操作，二次确认）", expanded=False):
        st.warning(
            f"⚠️ 当前共 **{len(all_books)}** 条记录。清空后无法恢复。"
            "注意：这只会删 DB 里的清单条目，**不会**删除 `data/fanqie_promotion/books/` 下已抓的章节文件。"
        )
        # 选择清空范围
        scope = st.radio(
            "清空范围",
            options=["全清（pending + running + done + failed + skipped）", "只清 pending", "只清 failed"],
            index=0,
            horizontal=True,
            key="clear_scope",
        )
        scope_map = {
            "全清（pending + running + done + failed + skipped）": None,
            "只清 pending": "pending",
            "只清 failed": "failed",
        }
        # 二次确认框：在页面顶层赋 key，让 streamlit 接受写入
        confirm_text = st.text_input(
            "在下方输入 `确定清空` 二次确认（防误删）",
            key="clear_confirm",
        )
        clear_clicked = st.button(
            "🚨 确认清空",
            type="primary",
            disabled=(confirm_text != "确定清空"),
            key="clear_confirm_btn",
        )
        if clear_clicked:
            from src.platform_adapter.fanqie_batch import clear_all_books
            result = clear_all_books(status_filter=scope_map[scope])
            st.success(
                f"✅ 已删 {result['deleted']} 条；当前剩余 {result['kept']} 条"
            )
            # 不清 confirm_text —— 确认按钮已 disabled，用户下次手动改文字即可
            st.rerun()

    st.divider()

    # ── filter + 表格 ─────────────────────────────────────
    status_filter = st.selectbox(
        "状态过滤",
        options=["all", "pending", "running", "done", "failed", "skipped"],
        index=0,
        help="默认 all；按状态过滤",
    )
    s = None if status_filter == "all" else status_filter
    books = list_books(status=s, limit=500)

    if not books:
        st.info(f"清单为空（filter={status_filter}）")
    else:
        # 表格（转中文）
        rows = []
        for b in books:
            status_icon = {
                "pending": "🟡 待抓",
                "running": "🔵 抓取中",
                "done": "✅ 完成",
                "failed": "❌ 失败",
                "skipped": "⏭ 跳过",
            }.get(b["status"], b["status"])
            rows.append({
                "ID": b["id"],
                "状态": status_icon,
                "书名": b["book_name"],
                "book_id": b["book_id"] or "-",
                "章数": f"{b['chapters_fetched']}/{b['chapters']}",
                "耗时": f"{b['duration_ms']/1000:.1f}s" if b.get("duration_ms") else "-",
                "重试": b.get("attempt_count", 0),
                "付费墙": "是" if b.get("paywall_hit") else "-",
                "加入时间": b["added_at"][:19] if b.get("added_at") else "-",
                "最后抓": b["last_fetched_at"][:19] if b.get("last_fetched_at") else "-",
                "备注": (b.get("note") or "")[:30],
            })
        st.dataframe(rows, width="stretch", hide_index=True)
        st.caption(f"共 {len(books)} 条")

    st.divider()

    # ── 加书表单 ─────────────────────────────────────────
    st.subheader("➕ 加书到清单")
    with st.form("add_books_form", clear_on_submit=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            book_names_raw = st.text_area(
                "书名（每行一本，支持 # 注释）",
                placeholder="我的6个超级奶爸\n被攻略的竟是我自己？\n# 全家恋爱脑（待评估）",
                height=120,
            )
        with col2:
            chapters = st.number_input("章数", min_value=1, max_value=50, value=5)
            interval_s = st.number_input("间隔(s)", min_value=5, max_value=600, value=30)
        note = st.text_input("备注", placeholder="可选")
        submit = st.form_submit_button("加入清单")

    if submit:
        if not book_names_raw.strip():
            st.error("请输入至少一个书名")
        else:
            from src.platform_adapter.fanqie_batch import add_books
            # 解析：每行一本，跳过空行和 # 注释
            names = []
            for line in book_names_raw.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                names.append(line)
            if not names:
                st.error("没有有效书名（全部是空行或注释）")
            else:
                result = add_books(names, chapters=chapters, interval_s=interval_s, note=note)
                st.success(
                    f"✅ 加书完成: added={result['added']}, "
                    f"skipped={result['skipped']}（已存在）"
                )
                st.rerun()

    st.divider()

    # ── 按筛选拉书（KolFilterArgs 7 类 + target_count）────────────
    st.subheader("按条件筛选素材")
    st.caption("每类单选；多选会返回 validation_error。")

    with st.form("kol_filter_form", clear_on_submit=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            ranking = st.selectbox(
                "榜单 (必填, 4 选 1)",
                options=["爆款榜", "阅读榜", "潜力榜", "全部内容"],
                index=0,
                help="切换 task-menu-second 切榜单",
            )
            status = st.selectbox(
                "连载状态 (单选)",
                options=[("全部", "all"), ("连载中", "serial"), ("已完结", "done")],
                format_func=lambda x: x[0],
                index=0,
            )[1]
            copyright = st.selectbox(
                "版权 (单选)",
                options=[("全部", "all"), ("番茄独家", "exclusive"), ("非独家", "non_exclusive")],
                format_func=lambda x: x[0],
                index=0,
            )[1]
        with col2:
            gender = st.selectbox(
                "性别 (单选)",
                options=[("全部", "all"), ("男频", "male"), ("女频", "female"), ("通用", "general")],
                format_func=lambda x: x[0],
                index=0,
            )[1]
            days = st.selectbox(
                "更新时间 (单选)",
                options=[("全部", "all"), ("近1天", "1d"), ("近5天", "5d"), ("近10天", "10d"), ("1个月内", "30d"), ("1个月以上", "30d+")],
                format_func=lambda x: x[0],
                index=0,
            )[1]
            word_count = st.selectbox(
                "字数 (单选)",
                options=[("全部", "all"), ("<100万", "<100"), ("100-150万", "100-150"),
                         ("150-200万", "150-200"), ("200-300万", "200-300"),
                         ("300-500万", "300-500"), (">500万", ">500")],
                format_func=lambda x: x[0],
                index=0,
            )[1]
        with col3:
            target_count = st.number_input("要抓几本 (target_count)", min_value=1, max_value=200, value=10)
            chapters = st.number_input("每本抓几章", min_value=1, max_value=50, value=20)
            category = st.text_input(
                "题材条件（JSON，可选）",
                value="",
                placeholder='{"mapping_id":7220798290399330363,"category_ids":"23"}',
                help="不填=全部；要选具体题材，参考达人中心页面的 .filter-item-kVRaXL value",
            )
        run_filter = st.form_submit_button("🎯 按筛选拉书（带筛选入库）", type="primary")

    if run_filter:
        from src.platform_adapter.fanqie_batch import add_books_from_kol_filtered
        from src.platform_adapter.fanqie_kol_filter import KolFilterArgs, FilterValidationError
        import json as _json
        # category: 字符串 → dict
        cat_dict = None
        if category.strip():
            try:
                cat_dict = _json.loads(category)
            except _json.JSONDecodeError as exc:
                st.error(f"❌ category JSON 解析失败: {exc}")
                st.stop()
        try:
            kol_args = KolFilterArgs(
                ranking=ranking, target_count=target_count,
                status=status, gender=gender, copyright=copyright,
                category=cat_dict, days=days, word_count=word_count,
            )
            kol_args.validate()
        except FilterValidationError as exc:
            st.error(f"❌ 校验失败: {exc}")
            st.stop()
        with st.spinner(f"扫 {ranking} + 6 类 filter + 滚到底拉 {target_count} 本..."):
            try:
                result = add_books_from_kol_filtered(
                    kol_args, chapters=chapters, interval_s=30,
                )
            except Exception as exc:
                st.error(f"❌ 失败: {type(exc).__name__}: {exc}")
                st.stop()
        st.success(
            f"✅ 拉书完成: scanned={result['scanned']}, unique={result['unique']}, "
            f"added={result['added']}, skipped={result['skipped']}"
        )
        st.json(result.get("filter_args", {}))
        st.rerun()

    st.divider()

    # ── 一键 Run ─────────────────────────────────────────
    st.subheader("▶️ 跑批量抓取")
    col1, col2 = st.columns(2)
    with col1:
        max_count = st.number_input("最多抓几本", min_value=1, max_value=100, value=5)
    with col2:
        run_interval = st.number_input("间隔(s)", min_value=5, max_value=600, value=30)

    col1, col2 = st.columns(2)
    with col1:
        run_sync = st.button(
            f"🚀 同步跑 {max_count} 本（阻塞）",
            type="primary",
            width="stretch",
            help="从 DB pending 状态的书开始跑，失败不中断",
        )
    with col2:
        run_enqueue = st.button(
            "提交后台采集队列",
            width="stretch",
            help="把 DB pending 状态的书入队，Worker 异步拉取",
        )

    if run_sync:
        with st.spinner(f"正在跑最多 {max_count} 本（间隔 {run_interval}s）..."):
            from src.platform_adapter.fanqie_batch import batch_fetch_sync, _summarize_report
            report = batch_fetch_sync(interval_s=run_interval, max_count=max_count)
            summary = _summarize_report(report)
            st.success(
                f"✅ 完成: {report.succeeded}/{report.total} 成功, "
                f"{report.failed} 失败, 耗时 {report.total_duration_ms/1000:.1f}s"
            )
            # 详细表
            rows = []
            for r in summary["results"]:
                rows.append({
                    "书名": r["book_name"],
                    "状态": "✅" if r["success"] else "❌",
                    "book_id": r["book_id"] or "-",
                    "章数": r["chapters_fetched"],
                    "耗时": f"{r['duration_ms']/1000:.1f}s",
                    "错误": r["error_message"][:50] if r["error_message"] else "-",
                })
            st.dataframe(rows, width="stretch", hide_index=True)
            st.rerun()

    if run_enqueue:
        with st.spinner("入队中..."):
            from src.platform_adapter.fanqie_batch import batch_enqueue_pending
            result = batch_enqueue_pending()
            st.success(
                f"✅ 入队完成: queued={result['queued']}/{result['total']}"
            )
            st.rerun()



def page_users():
    import pandas as pd
    from src.services.user_profile_service import list_users, set_user_role, set_whitelist, set_user_limits, set_user_password, create_user
    from src.web.components.auth import get_client_ip

    page_header(
        "用户管理",
        "维护角色、登录凭据、白名单和调用限额。",
        icon="◎",
        eyebrow="ACCESS CONTROL",
    )
    users = list_users()
    if users:
        rows = []
        for u in users:
            rows.append({
                "昵称": u.get("user_nickname", ""),
                "角色": role_names.get(u.get("role", ""), u.get("role", "")),
                "日限/已用": f"{u.get('daily_count', 0)}/{u.get('daily_limit', 5)}",
                "总限/已用": f"{u.get('total_count', 0)}/{u.get('total_limit', 50)}",
                "白名单": "✅" if u.get("is_whitelist") else "❌",
                "注册IP": u.get("registered_ip", "—") or "—",
            })
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
    else:
        st.info("暂无用户")

    st.markdown("---")
    st.subheader("🔧 修改角色")
    col_u1, col_u2, col_u3 = st.columns([2, 2, 1])
    with col_u1:
        target_nickname = st.text_input("用户昵称", key="role_nickname")
    with col_u2:
        new_role = st.selectbox("新角色", list(role_names.keys()), format_func=lambda x: role_names[x])
    with col_u3:
        if st.button("修改角色", width='stretch'):
            if target_nickname and set_user_role(target_nickname, new_role):
                st.success(f"已将 {target_nickname} 设为 {role_names[new_role]}")
                st.rerun()

    st.markdown("---")
    st.subheader("🔑 设置密码")
    col_pw1, col_pw2, col_pw3 = st.columns([2, 2, 1])
    with col_pw1:
        pw_nickname = st.text_input("用户昵称", key="pw_nickname")
    with col_pw2:
        new_password = st.text_input("新密码", type="password", key="new_password")
    with col_pw3:
        if st.button("设置密码", width='stretch'):
            if pw_nickname and new_password:
                set_user_password(pw_nickname, new_password, registered_ip=get_client_ip())
                st.success(f"密码已设置")
                st.rerun()
            else:
                st.warning("请填写昵称和密码")

    st.markdown("---")
    st.subheader("➕ 新建用户")
    col_new1, col_new2, col_new3, col_new4 = st.columns([2, 2, 2, 1])
    with col_new1:
        new_nickname = st.text_input("用户昵称", key="new_nickname")
    with col_new2:
        new_pass = st.text_input("密码", type="password", key="new_pass")
    with col_new3:
        new_role = st.selectbox("角色", list(role_names.keys()), index=3, format_func=lambda x: role_names[x])
    with col_new4:
        if st.button("创建", width='stretch'):
            if new_nickname and new_pass:
                if create_user(new_nickname, new_pass, new_role, registered_ip=get_client_ip()):
                    st.success(f"用户 {new_nickname} 创建成功")
                    st.rerun()
                else:
                    st.error("用户已存在")
            else:
                st.warning("请填写昵称和密码")

    st.markdown("---")
    st.subheader("⚙️ 用户限流与白名单")
    col_w1, col_w2, col_w3 = st.columns(3)
    with col_w1:
        wl_nickname = st.text_input("用户昵称", key="wl_nickname")
    with col_w2:
        wl_action = st.selectbox("操作", ["设为白名单", "取消白名单"])
    with col_w3:
        if st.button("应用", width='stretch'):
            if wl_nickname:
                set_whitelist(wl_nickname, wl_action == "设为白名单")
                st.success("设置成功")
                st.rerun()
    col_l1, col_l2, col_l3 = st.columns(3)
    with col_l1:
        limit_nickname = st.text_input("用户昵称", key="limit_nickname")
    with col_l2:
        daily_limit = st.number_input("每日上限", min_value=1, max_value=999, value=5, key="daily_limit")
    with col_l3:
        total_limit = st.number_input("累计上限", min_value=1, max_value=9999, value=50, key="total_limit")
    if st.button("设置限流", width='stretch'):
        if limit_nickname:
            set_user_limits(limit_nickname, daily_limit=daily_limit, total_limit=total_limit)
            st.success("限流设置成功")
            st.rerun()


def page_settings():
    from src.web.model_visuals import render_system_settings
    render_system_settings()


# ── 我的记忆（Phase 2 新增） ────────────────────────────────────
def page_memory():
    from src.memory import MemoryManager, MemoryLayerManager
    from src.memory.humane_recorder import (
        get_followup_reminders,
        get_session_sentiment_summary,
    )
    from src.shared.database import SessionLocal

    page_header(
        "我的记忆",
        "查看 Agent 记录的偏好、待跟进问题与情感线索。",
        icon="◉",
        eyebrow="PERSONAL MEMORY",
    )
    st.caption("偏好用于个性化回答；问题与跟进记录帮助继续未完成的工作，情感线索用于回顾对话。")

    user_id = get_current_user() or "default"

    # 1) 偏好列表
    st.subheader("📌 你的偏好")
    with SessionLocal() as sess:
        mlm = MemoryLayerManager(sess)
        prefs = mlm.get_user_memories(user_id)
    if prefs:
        for p in prefs:
            st.markdown(
                f"- **{p['memory_type']}** · `{p['key']}` = {p['value'][:120]}"
            )
    else:
        st.info("还没有记录到偏好。试试在对话里说「我习惯用 Edge TTS」之类的。")

    st.divider()

    # 2) 未解决问题
    st.subheader("❓ 未解决的问题")
    with SessionLocal() as sess:
        mlm = MemoryLayerManager(sess)
        problems = mlm.get_unresolved_problems(limit=10)
    if problems:
        for p in problems:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**#{p['id']}** {p['problem_text'][:120]}")
                if p.get("last_investigation_note"):
                    st.caption(f"🤖 LLM 调查方向：{p['last_investigation_note'][:200]}")
            with col2:
                st.caption(f"状态: {p['status']}")
                st.caption(f"调查次数: {p.get('investigation_count', 0)}")
            st.divider()
    else:
        st.info("无未解决问题。")

    st.divider()

    # 3) 待跟进事项
    st.subheader("📞 待跟进：之前提过的事，后来怎么样了？")
    reminders = get_followup_reminders(user_id=user_id, limit=5)
    if reminders:
        for r in reminders:
            st.markdown(
                f"- _{r['created_at'][:16] if r.get('created_at') else ''}_  "
                f"**{r['humane_summary']}**"
            )
            if r.get("sentiment"):
                st.caption(f"情感: {r['sentiment']}")
    else:
        st.info("暂无待跟进事项；对话整理后，相关记录会显示在这里。")

    st.divider()

    # 4) Sentiment 分布
    st.subheader("🎭 情感分布")
    with SessionLocal() as sess:
        mm = MemoryManager(sess)
        sess_obj = mm.get_or_create_active_session(user_id)
        summary = get_session_sentiment_summary(sess_obj.id)
    if summary:
        st.bar_chart(summary)
    else:
        st.info("暂无情感线索；完成对话整理后可查看分布。")


# ── Skill 监控页面 (Harness Engineering Layer 4 + 6) ──────────────
def page_skill_monitor():
    from src.web.skill_dashboard import page_skill_center
    page_skill_center()


# ── LLM 用量页面 (I-4) ─────────────────────────────────────────
def page_llm_usage():
    """I-4 LLM 成本与限流治理：用量 / 成本 / 缓存命中率 / QPS。"""
    from src.shared.database import SessionLocal
    from src.shared.llm_usage_log_model import LlmUsageLog
    from sqlalchemy import func, desc, Integer

    page_header(
        "模型用量",
        "追踪模型调用、Token、成本与缓存命中情况。",
        icon="∿",
        eyebrow="MODEL OBSERVABILITY",
    )
    st.caption("查看请求来自哪个业务、使用哪个模型，以及对应的词元与成本。统计包含缓存命中和限流记录。")

    with SessionLocal() as sess:
        from src.web.model_visuals import usage_graph
        from src.web.components.flow_graph import flow_graph
        pairs = sess.query(
            LlmUsageLog.caller, LlmUsageLog.model,
            func.count(LlmUsageLog.id).label("calls"),
            func.coalesce(func.sum(LlmUsageLog.prompt_tokens), 0).label("in_tok"),
            func.coalesce(func.sum(LlmUsageLog.completion_tokens), 0).label("out_tok"),
            func.coalesce(func.sum(LlmUsageLog.cost_usd), 0).label("cost"),
            func.coalesce(func.sum(func.cast(LlmUsageLog.cache_hit, Integer)), 0).label("hits"),
            func.coalesce(func.sum(func.cast(LlmUsageLog.rate_limited, Integer)), 0).label("limited"),
        ).group_by(LlmUsageLog.caller, LlmUsageLog.model).order_by(desc("calls")).limit(8).all()
        if pairs:
            nodes, edges = usage_graph(pairs)
            flow_graph(nodes, edges, key="model_usage_graph", title="谁在使用模型",
                       description="按记录数展示最多 8 组业务与模型关系；点击连线查看请求数、缓存、限流与成本。下方指标统计全部记录。")
        else:
            st.info("还没有模型请求记录。产生调用后，这里会显示业务与模型的关系图。")

        # 顶部 KPI
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            total_calls = sess.query(func.count(LlmUsageLog.id)).scalar() or 0
            st.metric("总调用次数", f"{total_calls:,}")
        with col2:
            total_tokens = sess.query(
                func.coalesce(func.sum(LlmUsageLog.prompt_tokens), 0)
                + func.coalesce(func.sum(LlmUsageLog.completion_tokens), 0)
            ).scalar() or 0
            st.metric("累计词元（Token）", f"{total_tokens:,}")
        with col3:
            total_cost = sess.query(func.coalesce(func.sum(LlmUsageLog.cost_usd), 0.0)).scalar() or 0.0
            st.metric("总成本 (USD)", f"${total_cost:.4f}")
        with col4:
            cache_hits = sess.query(func.count(LlmUsageLog.id)).filter(
                LlmUsageLog.cache_hit == True  # noqa: E712
            ).scalar() or 0
            hit_rate = (cache_hits / total_calls * 100) if total_calls else 0.0
            st.metric("缓存命中率", f"{hit_rate:.1f}%")

        st.divider()

        # 按 caller 聚合
        st.subheader("按调用方统计")
        rows = sess.query(
            LlmUsageLog.caller,
            func.count(LlmUsageLog.id).label("calls"),
            func.coalesce(func.sum(LlmUsageLog.prompt_tokens), 0).label("in_tok"),
            func.coalesce(func.sum(LlmUsageLog.completion_tokens), 0).label("out_tok"),
            func.coalesce(func.sum(LlmUsageLog.cost_usd), 0.0).label("cost"),
            func.coalesce(func.sum(LlmUsageLog.latency_ms), 0).label("latency_total"),
            func.coalesce(func.sum(func.cast(LlmUsageLog.cache_hit, Integer)), 0).label("hits"),
        ).group_by(LlmUsageLog.caller).order_by(desc("calls")).all()

        if rows:
            st.dataframe(
                {
                    "调用方": [r.caller or "(unknown)" for r in rows],
                    "调用次数": [r.calls for r in rows],
                    "输入词元": [int(r.in_tok) for r in rows],
                    "输出词元": [int(r.out_tok) for r in rows],
                    "成本 (USD)": [f"${float(r.cost):.4f}" for r in rows],
                    "平均延迟 (ms)": [
                        int(r.latency_total // r.calls) if r.calls else 0
                        for r in rows
                    ],
                    "缓存命中": [int(r.hits) for r in rows],
                },
                width="stretch",
            )
        else:
            st.info("暂无模型用量记录")

        st.divider()

        # 最近 N 条
        st.subheader("最近 20 条调用")
        recent = sess.query(LlmUsageLog).order_by(LlmUsageLog.id.desc()).limit(20).all()
        if recent:
            st.dataframe(
                {
                    "id": [r.id for r in recent],
                    "时间": [r.created_at.strftime("%m-%d %H:%M:%S") if r.created_at else "-" for r in recent],
                    "模型": [r.model for r in recent],
                    "调用方": [r.caller for r in recent],
                    "输入": [r.prompt_tokens or 0 for r in recent],
                    "输出": [r.completion_tokens or 0 for r in recent],
                    "成本": [f"${r.cost_usd:.4f}" if r.cost_usd else "-" for r in recent],
                    "延迟": [f"{r.latency_ms}ms" if r.latency_ms else "-" for r in recent],
                    "缓存": ["✓" if r.cache_hit else "" for r in recent],
                    "限流": ["✓" if r.rate_limited else "" for r in recent],
                },
                width="stretch",
            )


# ── AI 助手聊天页面 ─────────────────────────────────────────
def page_chat():
    page_header(
        "AI 助手",
        "用自然语言调度内容、运营和工作流能力。",
        icon="✦",
        eyebrow="COPILOT",
    )

    # 初始化 session state
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []  # list of {"role": "user"|"assistant", "content": str}
    if "pending_plan" not in st.session_state:
        st.session_state.pending_plan = None

    # ── 顶部：番茄批量抓取实时进度（AI 助手后台跑 fanqie_* 时） ──
    import time as _time
    from src.platform_adapter.fanqie_batch import read_progress, clear_progress
    _prog = read_progress()
    if _prog and _prog.get("running"):
        total = max(1, int(_prog.get("total", 0)))
        current = int(_prog.get("current", 0))
        ratio = min(1.0, current / total)
        phase = _prog.get("phase", "")
        phase_label = {"scan": "🔍 扫榜", "fetch": "📖 抓章节"}.get(phase, phase)
        status_text = _prog.get("status_text") or _prog.get("current_book") or ""
        book = _prog.get("current_book", "")
        succeeded = int(_prog.get("succeeded", 0))
        failed = int(_prog.get("failed", 0))
        headful = _prog.get("headful", False)
        eye = "👀 浏览器可见" if headful else "🕶 后台 headless"

        with st.container(border=True):
            st.markdown(
                f"### 🟢 番茄抓取进行中 · {phase_label}\n"
                f"**进度**：{current}/{total}　　"
                f"✅ {succeeded} 成功　❌ {failed} 失败　　{eye}"
            )
            st.progress(ratio, text=status_text or book or "...")
            if _prog.get("completed"):
                st.success("✅ 全部完成，可以收尾（30 秒后进度条自动消失）")
                _age = _time.time() - _time.mktime(
                    _time.strptime(_prog["updated_at"][:19], "%Y-%m-%dT%H:%M:%S")
                )
                if _age > 30:
                    clear_progress()
            # 注：AI 助手页面**不**自动 rerun（避免打断 chat_input 输入）
            # 想看实时进度请切到「任务调度」页（那边有 5 秒自动刷新）
            st.caption("💡 实时进度：切到「任务调度」页可看到自动刷新")

    # 侧边栏：会话管理
    with st.sidebar:
        from src.memory import MemoryManager
        current_user = get_current_user() or "default"

        st.markdown("### 💬 会话窗口")

        # ── 新建会话 ──
        if st.button("➕ 新建会话", width="stretch", type="primary", key="new_session"):
            with MemoryManager() as mm:
                # 创建新会话（自动归档旧的 active）
                mm.create_session(user_id=current_user, title="新会话")
            st.session_state.chat_history = []
            st.rerun()

        st.divider()

        # ── 会话列表（active + archived 都显示） ──
        with MemoryManager() as mm:
            active = mm.get_active_session(user_id=current_user)
            archived = mm.get_session_history(user_id=current_user, limit=20, status="archived")

            # 当前 active 会话高亮显示
            if active:
                st.markdown("**🟢 当前活跃**")
                cols = st.columns([3, 1])
                with cols[0]:
                    label = active.title or f"会话 #{active.id}"
                    st.caption(f"🟢 {label}（{len(mm.get_recent_messages(active.id, limit=500))} 条消息）")
                with cols[1]:
                    if st.button("📝", key=f"rename_active_{active.id}", help="重命名"):
                        st.session_state[f"show_rename_{active.id}"] = True
                # 归档当前活跃会话
                if st.button("📦 归档当前", key="archive_active", width="stretch"):
                    mm.archive_session(active.id)
                    mm.create_session(user_id=current_user, title="新会话")
                    st.session_state.chat_history = []
                    st.rerun()
                # 重命名输入框
                if st.session_state.get(f"show_rename_{active.id}"):
                    new_title = st.text_input("新标题", value=active.title, key=f"rename_input_{active.id}")
                    if st.button("保存", key=f"save_rename_{active.id}"):
                        mm.rename_session(active.id, new_title)
                        st.session_state[f"show_rename_{active.id}"] = False
                        st.rerun()
                st.divider()

            if archived:
                st.markdown(f"**📂 历史归档** ({len(archived)})")
                for sess in archived:
                    cols = st.columns([3, 1])
                    with cols[0]:
                        label = sess.title or f"会话 #{sess.id}"
                        ts = sess.updated_at.strftime("%m-%d %H:%M") if sess.updated_at else "-"
                        if st.button(
                            f"📄 {label}",
                            key=f"hist_{sess.id}",
                            width="stretch",
                            help=f"{ts} · 点击加载",
                        ):
                            # 加载这个归档会话到 chat_history（同时归档当前 active）
                            if active:
                                mm.archive_session(active.id)
                            # 复活它（status=active），方便后续 append_message 写到它
                            mm.session.query(ConversationSession).filter_by(id=sess.id).update(
                                {"status": "active", "archived_at": None}
                            )
                            mm.session.commit()
                            msgs = mm.get_recent_messages(sess.id, limit=200, include_system=True)
                            st.session_state.chat_history = [
                                {"role": m.role, "content": m.content}
                                for m in msgs if m.role in ("user", "assistant")
                            ]
                            st.rerun()
                    with cols[1]:
                        if st.button("🗑", key=f"del_{sess.id}", help="硬删除此会话及其消息"):
                            mm.delete_session(sess.id)
                            st.rerun()

        st.divider()
        if st.button("🧹 仅清空当前显示", width="stretch", help="不删 DB，只清 st.session_state"):
            st.session_state.chat_history = []
            st.rerun()

    # 展示聊天历史
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 用户输入
    user_input = st.chat_input("输入你的需求...")

    if user_input:
        # 追加用户消息
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        # 调用 Agent（带 UI 兜底：即便 agent 内部异常也展示友好提示）
        # P1：streaming 模式
        from src.agent import Agent
        from src.memory import MemoryManager
        current_user = get_current_user() or "default"
        agent = Agent(user_id=current_user)
        with MemoryManager() as mm:
            sess = mm.get_or_create_active_session(current_user)
        response = None
        try:
            with st.chat_message("assistant"):
                # 边生成边显示，content token 实时注入气泡
                accumulated = st.write_stream(agent.chat_stream(user_input, session_id=sess.id))
            # 流结束后取缓存的最终响应
            response = agent.last_streaming_response
            if response is None:
                # 兜底：万一流没设好 last_streaming_response
                response = type("R", (), {})()
                response.text = accumulated or ""
                response.needs_confirmation = False
                response.pending_plan = None
        except Exception as exc:
            # 极端兜底（Agent 自己的 _handle_chat_failure 也会再接一层）
            logger.exception("UI 层 Agent.chat_stream 失败")
            from src.agent.agent import FALLBACK_REPLY
            response = type("R", (), {})()
            response.text = FALLBACK_REPLY.format(reason=f"{type(exc).__name__}")
            response.needs_confirmation = False
            response.pending_plan = None

        # 追加 AI 回复
        st.session_state.chat_history.append({"role": "assistant", "content": response.text})

        # 如果有待确认计划，显示确认按钮
        if response.needs_confirmation and response.pending_plan:
            st.session_state.pending_plan = response.pending_plan
            plan = response.pending_plan
            cols = st.columns([1, 1])
            with cols[0]:
                if st.button("✅ 确认执行", type="primary", width="stretch"):
                    confirmed_response = agent.chat("确认", session_id=sess.id)
                    # 替换最后一条 AI 回复
                    st.session_state.chat_history[-1] = {"role": "assistant", "content": confirmed_response.text}
                    st.session_state.pending_plan = None
                    st.rerun()
            with cols[1]:
                if st.button("❌ 取消", width="stretch"):
                    cancel_response = agent.chat("取消", session_id=sess.id)
                    st.session_state.chat_history[-1] = {"role": "assistant", "content": cancel_response.text}
                    st.session_state.pending_plan = None
                    st.rerun()


# ── 重页面按需加载 ──────────────────────────────────────────
# Streamlit 会在每次交互时重跑入口脚本。页面模块如果在这里顶层导入，
# 即使用户只打开看板，也会等待 Seedance、趋势分析和工作流依赖全部加载。
def page_scheduler():
    from src.scheduler.runner import start_scheduler
    from src.scheduler.ui import page_scheduler as render_page

    start_scheduler()
    render_page()


def page_seedance_usage():
    from src.web.seedance_dashboard import page_seedance_usage as render_page

    render_page()


def page_upload_monitor():
    from src.web.publish_run_dashboard import page_upload_monitor as render_page
    render_page()


def page_douyin_accounts():
    from src.web.trend_dashboard import page_douyin_accounts as render_page
    render_page()


def page_trend_operations():
    from src.web.trend_dashboard import page_trend_operations as render_page

    render_page()


def page_workflow_nodes():
    from src.web.workflow_dashboard import page_workflow_nodes as render_page

    render_page()


# ── 权限过滤：根据角色决定可见页面 ──────────────────────────

was_authenticated = bool(get_current_user())
role = get_current_role()
oauth_callback_requested = bool(
    st.query_params.get("code") and st.query_params.get("state")
)

def page_video_production():
    from src.web.video_production_dashboard import page_video_production as render_page
    render_page()


def page_studio():
    from src.web.studio_home import render_studio_home
    render_studio_home(studio_destinations)


def page_creative_workflow():
    from src.web.creative_workflow_dashboard import page_creative_workflow as render_page
    render_page()


# Keep existing URLs so bookmarks and workflow links continue to work.
nav_spec = {
    "创作空间": [
        ("home", page_studio, "工作台", "space_dashboard", "viewer", None),
        ("accounts", page_douyin_accounts, "抖音账号", "manage_accounts", "viewer", "douyin-accounts"),
        ("research", page_trend_operations, "选题与剧本", "explore", "editor", None),
        ("creative_v2", page_creative_workflow, "双角色剧本", "theater_comedy", "editor", "creative-workflow"),
        ("production", page_video_production, "视频制作", "movie", "viewer", "video-production"),
        ("assistant", page_chat, "AI 助手", "auto_awesome", "viewer", None),
    ],
    "内容运营": [
        ("upload_monitor", page_upload_monitor, "上传实时监控", "upload", "viewer", "upload-monitor"),
        ("library", page_videos, "作品库", "video_library", "viewer", None),
        ("video_usage", page_seedance_usage, "视频用量与余额", "account_balance_wallet", "viewer", None),
        ("overview", page_dashboard, "运营看板", "monitoring", "viewer", None),
        ("comments", page_comments, "评论管理", "chat_bubble_outline", "viewer", None),
        ("replies", page_auto_reply, "回复建议", "quickreply", "editor", None),
        ("schedule", page_scheduler, "任务调度", "calendar_month", "editor", None),
    ],
    "资源与工具": [
        ("memory", page_memory, "我的记忆", "neurology", "viewer", None),
        ("books", page_books, "知识库", "menu_book", "admin", None),
        ("batch", page_fanqie_batch_queue, "批量抓取", "download", "editor", None),
        ("usage", page_llm_usage, "模型用量", "data_usage", "viewer", None),
        ("skills", page_skill_monitor, "技能中心", "build", "editor", None),
        ("workflow", page_workflow_nodes, "工作流编排", "account_tree", "admin", None),
    ],
    "管理设置": [
        ("rules", page_rules, "规则管理", "rule", "admin", None),
        ("words", page_blocked_words, "违禁词", "shield", "admin", None),
        ("users", page_users, "后台用户与权限", "group", "superadmin", None),
        ("settings", page_settings, "模型与系统设置", "settings", "superadmin", None),
    ],
}
nav_groups, studio_destinations = {}, {}
for group, entries in nav_spec.items():
    for key, function, title, icon, permission, url in entries:
        # On a newly refreshed browser the cookie component has not restored
        # the role yet. Register every route, hidden, so the current pathname
        # remains valid. The authenticated rerun applies the real permissions.
        if was_authenticated and not has_permission(role, permission):
            continue
        page = st.Page(function, title=title, icon=f":material/{icon}:",
                       url_path=url,
                       default=(key == "research" if oauth_callback_requested and has_permission(role, "editor") else key == "home"))
        nav_groups.setdefault(group, []).append(page)
        studio_destinations[key] = page

st.logo(str(PROJECT_ROOT / "src/web/components/studio_logo.svg"), size="large")

navigation = st.navigation(
    nav_groups,
    position="sidebar" if was_authenticated else "hidden",
    expanded=True,
)

# The route now exists even if cookie readback pauses this run. A session newly
# restored from a signed cookie reruns once to rebuild the visible, role-filtered
# navigation before any page function can execute.
if not render_login_page(configure_page=False):
    st.stop()

from src.web.components.ui import inject_app_theme
inject_app_theme()
user = get_current_user()
role = get_current_role()
if not was_authenticated:
    st.rerun()

with st.sidebar:
    from src.operations_accounts import AccountProfileRepository
    from src.web.components.account_scope import select_account_scope
    select_account_scope(AccountProfileRepository().list_active(status=None), key="global_account_scope", allow_unassigned=True)
    st.caption("汇总模式只用于查看；执行账号操作前需选择具体账号。")
    from html import escape
    st.markdown(f'<div class="studio-user"><span class="studio-avatar">{escape(str(user)[:1].upper())}</span>'
                f'<div>{escape(str(user))}<small>{escape(role_names.get(role, role))}</small></div></div>', unsafe_allow_html=True)
    if st.button("退出登录", icon=":material/logout:", width="stretch"):
        logout_user()
        st.rerun()
navigation.run()
