"""
app.py — Streamlit 管理后台入口

使用 st.navigation() API 自定义侧边栏，彻底控制中文标签。
"""

import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
from src.web.components.auth import render_login_page, is_logged_in, get_current_user, get_current_role, logout_user, has_permission

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STREAMLIT_LOG_PATH = PROJECT_ROOT / "data" / "logs" / "streamlit_combined.log"

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
    for item in LOCAL_SAMPLE_VIDEOS:
        path = PROJECT_ROOT / item["path"]
        if path.exists():
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
    st.info("默认使用正式版双角色主动说话格式：绿色动态背景 + 谁说话谁轻微放大/提亮。单人口播旧格式仍可在下方切换。上传浏览器默认后台运行，可打开调试模式显示窗口。")
    with st.form("auto_publish_form"):
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            keywords = st.text_input("关键词（生成脚本）", placeholder="励志,成长")
        with col_p2:
            title = st.text_input("视频标题（空则自动生成）", placeholder="自动生成")
        video_mode_label = st.selectbox(
            "视频格式",
            ["双角色主动说话正式版", "单人口播模板（旧格式）"],
            index=0,
            help="双角色正式版会使用 FramePack 人物素材、绿色动态背景和主动说话高亮效果。",
        )
        video_mode = {
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
    from src.platform_adapter.douyin_adapter import DouyinAdapter
    from src.services.comment_service import mark_comment_replied

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
    import os, shutil
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


def page_users():
    import pandas as pd
    from src.services.user_profile_service import list_users, set_user_role, set_whitelist, set_user_limits, set_user_password, create_user

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
                set_user_password(pw_nickname, new_password)
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
                if create_user(new_nickname, new_pass, new_role):
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


# ── 权限过滤：根据角色决定可见页面 ──────────────────────────
role = get_current_role()

pages = []
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
