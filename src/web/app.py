# -*- coding: utf-8 -*-
"""
app.py — Streamlit 管理后台入口

使用 st.navigation() API 自定义侧边栏，彻底控制中文标签。
"""

import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
from src.web.components.auth import render_login_page, get_current_user, get_current_role, logout_user, has_permission
from src.shared.logger import logger

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STREAMLIT_LOG_PATH = PROJECT_ROOT / "data" / "logs" / "streamlit_combined.log"

# 启动时确保所有数据库表已创建（包含记忆系统新表）
# 必须先导入所有模型，否则 Base.metadata 里没有对应表
from src.memory.models import UserProfile, ConversationSession, ConversationMessage  # noqa: F401
from src.memory.problem_memory import ConversationMemory, UserMemory, ProblemMemory  # noqa: F401
from src.scheduler.models import ScheduledTask, TaskExecution  # noqa: F401
from src.shared.database import init_db
init_db()

# 自动启动调度器 + Worker（静默启动，失败不影响主程序）
try:
    from src.scheduler.runner import start_scheduler
    start_scheduler()
except Exception:
    pass

# 首次启动时播种内置定时任务（如有问题调查 cron）
try:
    from src.shared.database import SessionLocal
    from src.scheduler.models import ScheduledTask, TaskType, TaskStatus, TriggerType
    with SessionLocal() as _sess:
        if not _sess.query(ScheduledTask).filter_by(name="investigate_problems_daily").first():
            _sess.add(ScheduledTask(
                name="investigate_problems_daily",
                description="每日扫描未解决问题，调用 LLM 生成调查摘要",
                task_type=TaskType.SCHEDULED.value,
                skill_name="investigate_problems",
                skill_params={"limit": 20},
                trigger_type=TriggerType.CRON.value,
                trigger_config={"expression": "37 9 * * *"},
                status=TaskStatus.PENDING.value,
                enabled=True,
                max_retries=1,
                retry_delay_seconds=300,
            ))
            _sess.commit()
except Exception:
    pass

# 调度管理页面
from src.scheduler.ui import page_scheduler

LOCAL_SAMPLE_VIDEOS = [
    {
        "title": "正式版主动说话高亮 v16",
        "path": "data/videos/dual_v16_green_active_speaker_official.mp4",
        "description": "正式功能样片：绿色动态背景 + 谁说话谁轻微放大/提亮，效果已接入 video_composer.py。",
        "tag": "正式版",
    },
    {
        "title": "绿色动态背景双角色 v15",
        "path": "data/videos/dual_v15_green_motion_bg.mp4",
        "description": "新测试版本：复用历史 FramePack 双角色人物素材，背景换成 bg_comfy_green_loop_motion.mp4。",
        "tag": "新测试",
    },
    {
        "title": "历史双角色 FramePack v14",
        "path": "data/videos/dual_v14_framepack_idle.mp4",
        "description": "候选历史版本：FramePack_oneclick 产出角色动作素材后，由当前项目合成双角色同屏视频。",
        "tag": "双角色候选",
    },
    {
        "title": "历史双角色绿色背景 v14",
        "path": "data/videos/dual_v14_healing_bg.mp4",
        "description": "候选历史版本：同一批双角色素材，替换为绿色治愈背景。",
        "tag": "双角色候选",
    },
    {
        "title": "历史双角色 v10",
        "path": "data/videos/dual_final_v10.mp4",
        "description": "较早的双角色成片候选，画面是两个人物同屏，适合回看当时确认过的构图方向。",
        "tag": "历史",
    },
    {
        "title": "头像对话混合版",
        "path": "data/videos/dual_final_mixed.mp4",
        "description": "更早的头像式双角色对话样片，偏对话感，但画面风格和后续 FramePack 路线不同。",
        "tag": "历史",
    },
    {
        "title": "主动说话高亮测试 v3",
        "path": "data/videos/test_viewer_green_dual_v3_active_speaker.mp4",
        "description": "当前推荐样片：浅绿色动态背景，谁说话谁轻微放大/提亮。",
        "tag": "推荐",
    },
    {
        "title": "近景双角色测试 v2",
        "path": "data/videos/test_viewer_green_dual_v2_close.mp4",
        "description": "浅绿色动态背景 + 更近角色构图，用来对比主动说话提示前后的观感。",
        "tag": "对比",
    },
    {
        "title": "初版双角色测试 v1",
        "path": "data/videos/test_viewer_green_dual_v1.mp4",
        "description": "第一版浅绿色背景双角色测试，角色相对更小。",
        "tag": "历史",
    },
]


def _format_file_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def render_local_sample_videos() -> None:
    """展示本地生成的样片，方便在管理后台直接复盘视频版本。"""
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
                "description": "自动扫描 data/videos 下的最新本地视频。",
                "tag": "最新" if not available else "本地",
            }, path))

    for item in LOCAL_SAMPLE_VIDEOS:
        path = PROJECT_ROOT / item["path"]
        if path.exists() and path.resolve() not in seen_paths:
            available.append((item, path))

    st.markdown("---")
    st.subheader("🎞️ 本地样片预览")
    if not available:
        st.info("暂无本地样片。生成测试视频后会在这里显示。")
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

# ── 登录验证 ──────────────────────────────────────────────
if not render_login_page():
    st.stop()

# ── 当前用户信息 ──────────────────────────────────────────
role_names = {"superadmin": "超级管理员", "admin": "运营管理员", "editor": "运营编辑", "viewer": "查看者"}
user = get_current_user()
role = get_current_role()

# ── 页面函数（每个函数是一个"页面"）────────────────────────
def page_dashboard():
    import pandas as pd
    from src.services.video_service import count_videos
    from src.services.comment_service import count_comments, count_replied_comments, get_reply_rate
    from src.services.reply_history_service import get_recent_reply_stats
    from src.services.user_profile_service import list_users

    st.title("📊 数据看板")
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

    st.title("📹 视频管理")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("已发布", count_videos(status="published") or 0)
    with col2:
        st.metric("待审核", count_videos(status="pending_review") or 0)
    with col3:
        st.metric("总计", count_videos() or 0)

    render_local_sample_videos()

    st.markdown("---")
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        status_filter = st.selectbox("状态筛选", ["全部", "published", "pending_review", "failed"])
    with col_f2:
        search = st.text_input("标题搜索", "")
    status_val = None if status_filter == "全部" else status_filter
    videos = get_videos(status=status_val, limit=200)
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
        if st.button("🔄 同步视频列表", width='stretch'):
            with st.spinner("同步中，请稍候..."):
                try:
                    from src.platform_adapter.douyin_adapter import DouyinAdapter

                    adapter = DouyinAdapter()
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
        if st.button("💬 抓取所有视频评论", width='stretch'):
            videos = get_videos(status="published", limit=100)
            total = 0
            failed = 0
            with st.spinner("抓取中，请稍候..."):
                try:
                    from src.platform_adapter.douyin_adapter import DouyinAdapter
                    from src.platform_adapter.models import CommentQuery

                    adapter = DouyinAdapter()
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
    st.subheader("➕ 在线制作/发布")
    st.info("默认使用动漫数字人主讲格式：Edge-TTS + Sonic 角色层 + 动漫背景 + 字幕合成。双角色正式版和单人口播旧格式可在下方切换。上传浏览器默认后台运行，可打开调试模式显示窗口。")
    with st.form("auto_publish_form"):
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            keywords = st.text_input("关键词（生成脚本）", placeholder="励志,成长")
        with col_p2:
            title = st.text_input("视频标题（空则自动生成）", placeholder="自动生成")
        video_mode_label = st.selectbox(
            "视频格式",
            ["动漫数字人主讲", "双角色主动说话正式版", "单人口播模板（旧格式）"],
            index=0,
            help="动漫数字人主讲使用动画角色和 AI 生成背景。双角色正式版使用 FramePack 人物素材和主动说话高亮效果。",
        )
        video_mode = {
            "动漫数字人主讲": "presenter_anime",
            "双角色主动说话正式版": "dual_framepack_active",
            "单人口播模板（旧格式）": "single_template",
        }[video_mode_label]
        col_p3, col_p4 = st.columns(2)
        with col_p3:
            desc = st.text_input("视频描述", placeholder="描述（可选）")
        with col_p4:
            tags = st.text_input("话题标签", placeholder="励志,正能量（逗号分隔）")
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
            tts_provider = st.selectbox(
                "配音方式",
                ["edge", "gpt_sovits"],
                format_func=lambda x: {"edge": "Edge-TTS（兜底）", "gpt_sovits": "GPT-SoVITS"}[x],
                help="Edge-TTS 需要联网；GPT-SoVITS 可离线，但当前环境缺 torch，需修复后再用。",
            )
            st.caption("Edge-TTS 需要连接微软语音服务；本地离线声线建议后续走 GPT-SoVITS 克隆。")
        debug_mode = st.checkbox(
            "调试模式：显示浏览器窗口",
            value=False,
            help="勾选后，发布自动化会打开可见浏览器窗口，方便观察登录、上传、发布和审核确认页面。",
        )
        submit_label = "🚀 生成并调试发布" if debug_mode else "🚀 生成并后台发布"
        submitted = st.form_submit_button(submit_label, type="primary")
        if submitted and keywords:
            with st.spinner("生成中，请耐心等待..."):
                from src.services.auto_publish_service import AutoPublishService, AutoPublishRequest

                request = AutoPublishRequest(
                    keywords=keywords,
                    title=title or "",
                    description=desc or "",
                    hashtags=[t.strip() for t in tags.split(",") if t.strip()] if tags else [],
                    visibility=visibility,
                    tts_provider=tts_provider,
                    video_mode=video_mode,
                    publish_headless=not debug_mode,
                )
                service = AutoPublishService()
                result = service.publish(request)
            if result.success:
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

    st.title("💬 评论管理")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("总评论", count_comments() or 0)
    with col2:
        st.metric("已回复", count_replied_comments() or 0)
    with col3:
        unreplied = (count_comments() or 0) - (count_replied_comments() or 0)
        st.metric("未回复", unreplied)

    st.markdown("---")
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        video_options = {"全部": ""}
        videos = get_videos(status="published", limit=100)
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
    comments = get_comments(video_id=video_id or None, is_replied=is_replied, limit=200)
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
        st.info("暂无评论数据")


def page_auto_reply():
    from src.platform_adapter.auto_reply_service import AutoReplyService
    from src.services.video_service import get_videos
    from src.services.reply_history_service import get_reply_history

    st.title("🤖 自动回复控制台")
    col1, col2 = st.columns(2)
    video_options = {"请选择视频": ""}
    videos = get_videos(status="published", limit=100)
    for v in videos:
        video_options[f"{v.get('title', '未知')[:30]} ({v.get('video_id', '')[:8]})"] = v.get("video_id", "")
    selected = st.selectbox("选择视频", list(video_options.keys()))
    target_video_id = video_options.get(selected, "")

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        trigger_single = st.button("🚀 执行自动回复（选中视频）", width='stretch', type="primary")
    with col_btn2:
        trigger_all = st.button("🚀 执行全部视频自动回复", width='stretch')

    if trigger_single and target_video_id:
        with st.spinner("处理中..."):
            service = AutoReplyService()
            result = service.process_video(target_video_id)
        st.success(f"完成：回复={result.replied}, 跳过={result.skipped}, 失败={result.failed}")
        for a in result.actions[:10]:
            st.text(f"  [{a.source}] {a.comment.content[:30]} → {a.reply_content[:20]}")

    if trigger_all:
        with st.spinner("处理中..."):
            service = AutoReplyService()
            videos = get_videos(status="published", limit=100)
            total_r, total_s, total_f = 0, 0, 0
            for v in videos:
                result = service.process_video(v.get("video_id", ""))
                total_r += result.replied
                total_s += result.skipped
                total_f += result.failed
        st.success(f"全部完成：回复={total_r}, 跳过={total_s}, 失败={total_f}")

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

    st.title("📝 自动回复规则管理")
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

    st.title("🚫 违禁词管理")
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

    st.title("📚 知识库管理")

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
        if st.button("📥 同步并导入", use_container_width=True, type="primary"):
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
        if st.button("🔃 重新导入全部", use_container_width=True):
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


# ── 番茄批量抓取清单（Harness Engineering L5）────────────────
def page_fanqie_batch_queue():
    """展示 fanqie_batch_books 清单 + 状态 filter + 一键 Run。

    DB 表（fanqie_batch_books）字段见 src/platform_adapter/fanqie_batch.py。
    批量抓取不接受任意 book_names —— 必须先加书到 DB，再跑 Run。
    """
    st.title("📋 番茄批量抓取清单")
    st.caption("Harness Engineering L5: 批量抓取必须先加书到清单（受控）")

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
        st.dataframe(rows, use_container_width=True, hide_index=True)
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
            use_container_width=True,
            help="从 DB pending 状态的书开始跑，失败不中断",
        )
    with col2:
        run_enqueue = st.button(
            "📤 入队到 TaskQueue（Worker 异步跑）",
            use_container_width=True,
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
            st.dataframe(rows, use_container_width=True, hide_index=True)
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

    st.title("👥 用户管理")
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
    from src.shared.config import settings
    st.title("⚙️ 系统设置")
    st.subheader("🔑 大模型配置")
    col1, col2 = st.columns(2)
    with col1:
        st.text_input("模型来源", value=settings.LLM_PROVIDER, disabled=True)
    with col2:
        st.text_input("模型名称", value=settings.OLLAMA_MODEL or "", disabled=True)
    st.text_input("接口地址", value=settings.OLLAMA_BASE_URL or "", disabled=True)
    st.markdown("---")
    st.subheader("🎙️ TTS 配置")
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        st.text_input("TTS Provider", value=settings.TTS_PROVIDER, disabled=True)
    with col_t2:
        st.text_input("GPT-SoVITS SDK Root", value=settings.GPT_SOVITS_SDK_ROOT or "", disabled=True)
    st.markdown("---")
    st.caption("系统配置通过 .env 文件管理，如需修改请编辑 .env 后重启应用")


# ── 我的记忆（Phase 2 新增） ────────────────────────────────────
def page_memory():
    from src.memory import MemoryManager, MemoryLayerManager
    from src.memory.humane_recorder import (
        get_followup_reminders,
        get_session_sentiment_summary,
    )
    from src.shared.database import SessionLocal

    st.title("🧠 我的记忆")
    st.caption("Agent 记得的关于你的偏好、问题、情感与待跟进事项。")

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
        st.info("无待跟进事项。LLM 异步分类会标记 needs_followup=True 的对话。")

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
        st.info("还没有情感数据。让 LLM 分类跑一会儿再来看看。")


# ── Skill 监控页面 (Harness Engineering Layer 4 + 6) ──────────────
def page_skill_monitor():
    """Skill 调用监控：失败率 / 耗时 / 错误码分布 / 热门失败 / ProblemMemory 摘要。

    数据源：
      - ErrorReview 表（error_reviewer 落库的诊断）
      - ConversationMessage.tool_success / tool_error（agent 层记录的工具调用）
    """
    st.header("Skill 监控")
    st.caption("Harness Engineering Layer 4 + 6：Skill 调用反馈 + 持续改进")

    # 1) Skill 总览
    st.subheader("Skill 列表")
    try:
        from src.agent.registry import SkillRegistry
        reg = SkillRegistry()
        skills = reg.list_all()

        # 表格
        rows = []
        for s in skills:
            row = {
                "Skill": s.name,
                "分类": s.category,
                "需确认": "是" if s.requires_confirmation else "否",
                "超时(s)": s.timeout_s,
                "重试": s.retries,
                "幂等": "是" if s.idempotent else "否",
                "参数": len(s.params),
            }
            rows.append(row)
        st.dataframe(rows, use_container_width=True)
    except Exception as exc:
        st.error(f"加载 Skill 列表失败: {exc}")

    st.divider()

    # 2) 错误诊断（ErrorReview 表）
    st.subheader("错误诊断（ErrorReview）")
    try:
        from src.memory.error_review_model import ErrorReview
        from src.shared.database import SessionLocal
        from datetime import datetime, timedelta

        with SessionLocal() as sess:
            # 最近 7 天
            cutoff = datetime.utcnow() - timedelta(days=7)
            reviews = (
                sess.query(ErrorReview)
                .filter(ErrorReview.last_seen_at >= cutoff)
                .order_by(ErrorReview.occurrence_count.desc())
                .limit(50)
                .all()
            )

            if not reviews:
                st.info("最近 7 天无 Skill 失败记录")
            else:
                # 聚合：按 cluster_key 统计
                from collections import Counter
                cluster_counts = Counter()
                for r in reviews:
                    cluster_counts[r.cluster_key] += r.occurrence_count

                # 热门失败 Top 10
                st.write("**热门失败模式（按 cluster_key）**")
                cluster_rows = []
                for cluster, count in cluster_counts.most_common(10):
                    cluster_rows.append({"cluster_key": cluster, "发生次数": count})
                st.dataframe(cluster_rows, use_container_width=True)

                # 详细列表
                with st.expander("详细诊断（最近 50 条）"):
                    detail_rows = []
                    for r in reviews:
                        detail_rows.append({
                            "Skill": r.location.replace("skill:", ""),
                            "code": r.error_type,
                            "severity": r.severity,
                            "category": r.category,
                            "次数": r.occurrence_count,
                            "首次": r.first_seen_at.strftime("%Y-%m-%d %H:%M") if r.first_seen_at else "",
                            "最后": r.last_seen_at.strftime("%Y-%m-%d %H:%M") if r.last_seen_at else "",
                            "summary": (r.summary or "")[:80],
                            "建议修复": (r.suggested_fix or "")[:80],
                        })
                    st.dataframe(detail_rows, use_container_width=True)
    except Exception as exc:
        st.error(f"加载 ErrorReview 失败: {exc}")

    st.divider()

    # 3) 工具调用摘要（来自 ConversationMessage）
    st.subheader("近期工具调用")
    try:
        from src.memory import MemoryManager
        mm = MemoryManager()
        from datetime import datetime, timedelta

        with mm.session as sess:
            from src.memory.models import ConversationMessage
            cutoff = datetime.utcnow() - timedelta(days=7)
            calls = (
                sess.query(ConversationMessage)
                .filter(
                    ConversationMessage.skill_name.isnot(None),
                    ConversationMessage.created_at >= cutoff,
                )
                .order_by(ConversationMessage.created_at.desc())
                .limit(50)
                .all()
            )

            if not calls:
                st.info("最近 7 天无工具调用记录")
            else:
                from collections import Counter
                success_count = sum(1 for c in calls if c.tool_success)
                failure_count = sum(1 for c in calls if not c.tool_success)
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("总调用", len(calls))
                with col2:
                    st.metric("成功", success_count)
                with col3:
                    st.metric("失败", failure_count,
                             delta=f"-{failure_count}" if failure_count else None,
                             delta_color="inverse")

                # 失败详情
                with st.expander("最近 50 次工具调用详情"):
                    call_rows = []
                    for c in calls:
                        call_rows.append({
                            "Skill": c.skill_name or "",
                            "状态": "✅" if c.tool_success else "❌",
                            "错误": (c.tool_error or "")[:80],
                            "时间": c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else "",
                        })
                    st.dataframe(call_rows, use_container_width=True)
    except Exception as exc:
        st.error(f"加载工具调用记录失败: {exc}")


# ── LLM 用量页面 (I-4) ─────────────────────────────────────────
def page_llm_usage():
    """I-4 LLM 成本与限流治理：用量 / 成本 / 缓存命中率 / QPS。"""
    from src.shared.database import SessionLocal
    from src.shared.llm_usage_log_model import LlmUsageLog
    from sqlalchemy import func, desc

    st.title("📊 LLM 用量")
    st.caption("I-4 LLM 成本与限流治理：每次 LLM 调用 1 条记录。")

    with SessionLocal() as sess:
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
            st.metric("总 token", f"{total_tokens:,}")
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
                    "输入 token": [int(r.in_tok) for r in rows],
                    "输出 token": [int(r.out_tok) for r in rows],
                    "成本 (USD)": [f"${float(r.cost):.4f}" for r in rows],
                    "平均延迟 (ms)": [
                        int(r.latency_total // r.calls) if r.calls else 0
                        for r in rows
                    ],
                    "缓存命中": [int(r.hits) for r in rows],
                },
                use_container_width=True,
            )
        else:
            st.info("暂无 LLM 用量记录")

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
                use_container_width=True,
            )


# ── AI 助手聊天页面 ─────────────────────────────────────────
def page_chat():
    st.title("🤖 AI 助手")

    # 初始化 session state
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []  # list of {"role": "user"|"assistant", "content": str}
    if "pending_plan" not in st.session_state:
        st.session_state.pending_plan = None

    # 侧边栏：历史会话
    with st.sidebar:
        st.subheader("📂 历史会话")
        from src.memory import MemoryManager
        with MemoryManager() as mm:
            history = mm.get_session_history(limit=10, status="archived")
            for sess in history:
                label = sess.title or f"会话 {sess.id}"
                if st.button(label, use_container_width=True, key=f"hist_{sess.id}"):
                    msgs = mm.get_recent_messages(sess.id, limit=100, include_system=True)
                    st.session_state.chat_history = [
                        {"role": m.role, "content": m.content}
                        for m in msgs if m.role in ("user", "assistant")
                    ]
                    st.rerun()

        st.divider()
        if st.button("🗑️ 清除当前对话", use_container_width=True):
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
        with st.spinner("思考中..."):
            from src.agent import Agent
            from src.memory import MemoryManager

            current_user = get_current_user() or "default"
            agent = Agent(user_id=current_user)
            with MemoryManager() as mm:
                sess = mm.get_or_create_active_session(current_user)
            try:
                response = agent.chat(user_input, session_id=sess.id)
            except Exception as exc:
                # 极端兜底（Agent 自己的 _handle_chat_failure 也会再接一层）
                logger.exception("UI 层 Agent.chat 失败")
                from src.agent.agent import FALLBACK_REPLY
                response = type("R", (), {})()
                response.text = FALLBACK_REPLY.format(reason=f"{type(exc).__name__}")
                response.needs_confirmation = False
                response.pending_plan = None

            # 追加 AI 回复
            st.session_state.chat_history.append({"role": "assistant", "content": response.text})
            with st.chat_message("assistant"):
                st.markdown(response.text)

            # 如果有待确认计划，显示确认按钮
            if response.needs_confirmation and response.pending_plan:
                st.session_state.pending_plan = response.pending_plan
                plan = response.pending_plan
                cols = st.columns([1, 1])
                with cols[0]:
                    if st.button("✅ 确认执行", type="primary", use_container_width=True):
                        confirmed_response = agent.chat("确认", session_id=sess.id)
                        # 替换最后一条 AI 回复
                        st.session_state.chat_history[-1] = {"role": "assistant", "content": confirmed_response.text}
                        st.session_state.pending_plan = None
                        st.rerun()
                with cols[1]:
                    if st.button("❌ 取消", use_container_width=True):
                        cancel_response = agent.chat("取消", session_id=sess.id)
                        st.session_state.chat_history[-1] = {"role": "assistant", "content": cancel_response.text}
                        st.session_state.pending_plan = None
                        st.rerun()


# ── 权限过滤：根据角色决定可见页面 ──────────────────────────
role = get_current_role()

pages = []
if has_permission(role, "viewer"):
    pages.append(st.Page(page_chat, title="AI 助手", icon="🤖"))
if has_permission(role, "viewer"):
    pages.append(st.Page(page_memory, title="我的记忆", icon="🧠"))
if has_permission(role, "viewer"):
    pages.append(st.Page(page_llm_usage, title="LLM 用量", icon="📊"))
if has_permission(role, "editor"):
    pages.append(st.Page(page_skill_monitor, title="Skill 监控", icon="🛠️"))
if has_permission(role, "editor"):
    pages.append(st.Page(page_fanqie_batch_queue, title="批量抓取", icon="📋"))
if has_permission(role, "editor"):
    pages.append(st.Page(page_scheduler, title="任务调度", icon="📋"))
if has_permission(role, "viewer"):
    pages.append(st.Page(page_dashboard, title="看板", icon="📊"))
if has_permission(role, "viewer"):
    pages.append(st.Page(page_videos, title="视频", icon="📹"))
if has_permission(role, "viewer"):
    pages.append(st.Page(page_comments, title="评论", icon="💬"))
if has_permission(role, "editor"):
    pages.append(st.Page(page_auto_reply, title="自动回复", icon="🤖"))
if has_permission(role, "admin"):
    pages.append(st.Page(page_rules, title="规则管理", icon="📝"))
if has_permission(role, "admin"):
    pages.append(st.Page(page_blocked_words, title="违禁词", icon="🚫"))
if has_permission(role, "admin"):
    pages.append(st.Page(page_books, title="知识库", icon="📚"))
if has_permission(role, "superadmin"):
    pages.append(st.Page(page_users, title="用户管理", icon="👥"))
if has_permission(role, "superadmin"):
    pages.append(st.Page(page_settings, title="系统设置", icon="⚙️"))

# ── 渲染导航 ──────────────────────────────────────────────
st.navigation(pages, position="sidebar", expanded=False).run()

# ── 顶部用户信息 ──────────────────────────────────────────
with st.sidebar:
    st.success(f"👤 {user}  ({role_names.get(role, role)})")
    if st.button("🔐 抖音登录/重新登录", width='stretch'):
        with st.spinner("已打开抖音登录窗口。登录完成后，请直接关闭浏览器窗口..."):
            try:
                from src.platform_adapter.douyin_adapter import DouyinAdapter
                from src.shared.config import settings

                adapter = DouyinAdapter()
                adapter.open_login_window_until_closed(
                    url=settings.DOUYIN_CREATOR_BASE_URL,
                    timeout_seconds=1800,
                )
                st.success("抖音登录窗口已关闭，登录态已保存。")
            except Exception as exc:
                st.error(f"打开抖音登录窗口失败：{exc}")
    if st.button("🚪 退出登录", width='stretch'):
        logout_user()
        st.rerun()
