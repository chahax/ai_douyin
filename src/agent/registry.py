# -*- coding: utf-8 -*-
"""
src/agent/registry.py — Skill 注册表

将项目能力注册为 Agent 可调用的 Skill。
每个 Skill 是 (name, description, callable) 三元组。

Agent 通过 skill_name 查找并调用。
"""

import asyncio
import json
from dataclasses import asdict
from typing import Any

from src.agent.skill_decorator import (
    ParamType,
    Skill,
    SkillParam,
    get_registered_skills,
)
from src.shared.logger import logger


# 旧的 Skill dataclass 已被 src/agent/skill_decorator.py:Skill 取代。
# 这里 re-export，保持外部 import 兼容。
__all__ = [
    "Skill",
    "SkillParam",
    "ParamType",
    "SKILLS",
    "SkillRegistry",
    "validate_params",
]


# ---------------------------------------------------------------------------
# Skill 定义
# ---------------------------------------------------------------------------

def _search_knowledge(query: str, top_k: int = 3, **kwargs) -> dict:
    """RAG 知识库检索"""
    from src.rag_engine.wisdom_retriever import WisdomRetriever
    try:
        retriever = WisdomRetriever()
        results = retriever.search_wisdom(query, top_k=top_k)
        return {
            "success": True,
            "count": len(results),
            "results": [
                {
                    "content": doc.page_content,
                    "source": doc.metadata.get("source_book", "未知"),
                    "theme": doc.metadata.get("theme", "未知"),
                }
                for doc in results
            ],
        }
    except Exception as exc:
        logger.exception("RAG search failed")
        return {"success": False, "error": str(exc)}


def _generate_presenter_video(
    keywords: str = "",
    text: str = "",
    text_file: str = "",
    input_mode: str = "keywords",
    title: str = "",
    tts_provider: str = "edge",
    character: str = "sonic_fox",
    character_position: str = "right_bottom",
    character_size: str = "medium",
    background_style: str = "anime",
    max_segments: int = 0,
    no_comfy_background: bool = False,
    output_dir: str = "data/videos",
    **kwargs,
) -> dict:
    """生成动漫数字人主讲视频（PresenterPipeline）"""
    from src.content_factory.presenter.models import PresenterRequest, INPUT_MODE_KEYWORDS
    from src.content_factory.presenter_pipeline import PresenterPipeline

    mode_map = {
        "keywords": INPUT_MODE_KEYWORDS,
        "article_direct": "article_direct",
        "article_extract": "article_extract",
    }
    mapped_mode = mode_map.get(input_mode, INPUT_MODE_KEYWORDS)

    request = PresenterRequest(
        keywords=keywords or "",
        text=text or "",
        text_file=text_file or "",
        input_mode=mapped_mode,
        title=title or keywords or "数字人主讲",
        voice="",
        tts_provider=tts_provider,
        character=character,
        character_position=character_position,
        character_size=character_size,
        background="",
        background_style=background_style,
        bgm="",
        output_dir=output_dir,
        audio_path="",
        max_segments=max_segments,
        use_comfy_background=not no_comfy_background,
    )

    pipeline = PresenterPipeline()
    result = pipeline.run(request)
    return {
        "success": result.success,
        "video_path": result.video_path if result.success else None,
        "work_dir": result.work_dir,
        "message": result.message,
    }


def _generate_audio(
    text: str = "",
    keywords: str = "",
    tts_provider: str = "edge",
    voice: str = "",
    bgm: str = "",
    bgm_volume: float = 0.2,
    output_dir: str = "data/videos",
    **kwargs,
) -> dict:
    """纯音频/TTS 生成（不生成视频）"""
    from src.services import QuickGenerationRequest, GenerationService

    service = GenerationService()
    request = QuickGenerationRequest(
        prompt=None,
        text=text or None,
        tts_provider=tts_provider,
        voice=voice or None,
        bgm=bgm or None,
        bgm_volume=bgm_volume,
        output_dir=output_dir,
        keywords=keywords or "",
    )
    outputs = service.run_quick_request(request)
    return {
        "success": bool(outputs),
        "audio_paths": outputs or [],
    }


def _publish_douyin_video(
    video_path: str,
    title: str,
    description: str = "",
    tags: str = "",
    **kwargs,
) -> dict:
    """发布视频到抖音"""
    from src.platform_adapter import DouyinAdapter
    from src.platform_adapter.models import PublishRequest

    adapter = DouyinAdapter()
    hashtags = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    request = PublishRequest(
        video_path=video_path,
        title=title,
        description=description,
        hashtags=hashtags,
    )
    result = adapter.publish_video(request)
    return {
        "success": result.success,
        "post_id": result.post_id,
        "publish_url": result.publish_url,
        "message": result.message,
    }


def _sync_douyin_videos(page_limit: int = 5, **kwargs) -> dict:
    """同步抖音创作者后台视频列表"""
    from src.platform_adapter import DouyinAdapter

    adapter = DouyinAdapter()
    result = adapter.sync_videos(page_limit=page_limit)
    return {
        "success": True,
        "count": len(result.videos),
        "videos": [
            {"video_id": v.video_id, "title": v.title, "status": v.status.value}
            for v in result.videos
        ],
    }


def _fetch_comments(video_id: str = "", all_videos: bool = False, **kwargs) -> dict:
    """抓取视频评论"""
    from src.platform_adapter import DouyinAdapter
    from src.platform_adapter.models import CommentQuery

    adapter = DouyinAdapter()
    if all_videos:
        from src.services.video_service import get_videos
        videos = get_videos(status="published", limit=100)
        total = 0
        for v in videos:
            result = adapter.fetch_comments(CommentQuery(post_id=v["video_id"]))
            total += len(result.comments)
        return {"success": True, "total_comments": total}
    else:
        result = adapter.fetch_comments(CommentQuery(post_id=video_id))
        return {
            "success": True,
            "count": len(result.comments),
            "comments": [
                {"content": c.content, "like_count": c.like_count}
                for c in result.comments
            ],
        }


def _auto_reply_comments(video_id: str = "", all_videos: bool = False, **kwargs) -> dict:
    """自动回复评论"""
    from src.platform_adapter.auto_reply_service import AutoReplyService
    from src.services.video_service import get_videos

    service = AutoReplyService(session=None)
    if all_videos:
        videos = get_videos(status="published", limit=100)
        total_replied = total_skipped = total_failed = 0
        for v in videos:
            result = service.process_video(v["video_id"])
            total_replied += result.replied
            total_skipped += result.skipped
            total_failed += result.failed
        return {
            "success": True,
            "replied": total_replied,
            "skipped": total_skipped,
            "failed": total_failed,
        }
    else:
        result = service.process_video(video_id)
        return {
            "success": True,
            "replied": result.replied,
            "skipped": result.skipped,
            "failed": result.failed,
        }


def _get_user_preferences(**kwargs) -> dict:
    """读取用户偏好（不修改）"""
    from src.memory import MemoryManager
    with MemoryManager() as mm:
        prefs = mm.get_preferences()
        return {
            "success": True,
            "preferences": {
                "default_video_mode": prefs.default_video_mode,
                "default_tts_provider": prefs.default_tts_provider,
                "default_voice": prefs.default_voice,
                "default_character": prefs.default_character,
                "default_character_position": prefs.default_character_position,
                "default_character_size": prefs.default_character_size,
                "default_bgm_volume": prefs.default_bgm_volume,
                "preferred_topics": prefs.preferred_topics,
                "douyin_uid": prefs.douyin_uid,
                "douyin_nickname": prefs.douyin_nickname,
            },
        }


def _update_user_preferences(
    default_video_mode: str = "",
    default_tts_provider: str = "",
    default_voice: str = "",
    default_character: str = "",
    default_character_position: str = "",
    default_character_size: str = "",
    default_bgm_volume: float = 0.0,
    preferred_topics: list = None,
    **kwargs,
) -> dict:
    """更新用户偏好"""
    from src.memory import MemoryManager

    updates = {k: v for k, v in {
        "default_video_mode": default_video_mode,
        "default_tts_provider": default_tts_provider,
        "default_voice": default_voice,
        "default_character": default_character,
        "default_character_position": default_character_position,
        "default_character_size": default_character_size,
        "default_bgm_volume": default_bgm_volume,
        "preferred_topics": preferred_topics,
    }.items() if v}

    if not updates:
        return {"success": False, "error": "没有提供任何要更新的偏好字段"}

    with MemoryManager() as mm:
        prefs = mm.get_preferences()
        for key, value in updates.items():
            setattr(prefs, key, value)
        mm.update_preferences(prefs)
        return {"success": True, "updated": updates}


def _fanqie_login(wait_for_enter: bool = True, **kwargs) -> dict:
    """打开番茄小说达人中心登录窗口"""
    from src.platform_adapter.fanqie_promotion import FanqiePromotionService
    fanqie = FanqiePromotionService()
    try:
        state = fanqie.open_login_window(url="", pause_seconds=900, wait_for_enter=wait_for_enter)
        return {"success": True, "state": asdict(state) if state else {}}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _fanqie_apply_promotion(
    content_type: str = "novel",
    book_name: str = "",
    alias: str = "",
    wait_for_login: bool = True,
    headless: bool = False,
    keep_open: bool = False,
    auto_submit: bool = True,
    publish_type: str = "AI数字人",
    **kwargs,
) -> dict:
    """申请番茄小说推广

    Args:
        content_type: 推广内容类型 novel/audio
        book_name: 目标小说名（空 = 取第一张书卡）
        alias: 推广别名（空 = 用番茄推荐别名）
        wait_for_login: 是否暂停等待用户登录
        headless: 无头模式
        keep_open: 提交后保持浏览器打开供人工确认
        auto_submit: 是否自动点击提交（False = 只填表让用户确认）
        publish_type: 发文类型偏好（"AI数字人" 等）
    """
    from src.platform_adapter.fanqie_promotion import FanqiePromotionService
    fanqie = FanqiePromotionService()
    try:
        task = fanqie.apply_promotion(
            content_type=content_type,
            book_name=book_name,
            alias=alias,
            wait_for_login=wait_for_login,
            headless=headless,
            keep_open=keep_open,
            auto_submit=auto_submit,
            publish_type=publish_type,
        )
        return {"success": True, "task": asdict(task)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _fanqie_fetch_book(book_name: str = "", chapters: int = 10, headless: bool = False, **kwargs) -> dict:
    """获取番茄小说章节内容"""
    from src.platform_adapter.fanqie_promotion import FanqiePromotionService
    fanqie = FanqiePromotionService()
    try:
        result = fanqie.fetch_book(book_name=book_name, chapters=chapters, headless=headless)
        return {"success": True, "result": asdict(result)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _fanqie_generate_video(
    book_name: str = "",
    alias: str = "",
    chapters: int = 10,
    max_segments: int = 0,
    no_comfy_background: bool = False,
    assets_only: bool = False,
    **kwargs,
) -> dict:
    """生成番茄小说推广视频"""
    from src.platform_adapter.fanqie_promotion import FanqiePromotionService
    fanqie = FanqiePromotionService()
    try:
        task = fanqie.generate_promo_video(
            task_file="",
            book_name=book_name,
            chapters=chapters,
            alias=alias,
            output_dir="data/videos",
            max_segments=max_segments,
            no_comfy_background=no_comfy_background,
            assets_only=assets_only,
        )
        return {"success": True, "task": asdict(task)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _fanqie_list_promotions(
    content_type: str = "novel",
    sync_to_tasks: bool = True,
    headless: bool = False,
    **kwargs,
) -> dict:
    """扫描番茄推广列表页，列出所有别名状态；可选择同步到 task.json。

    Args:
        content_type: 推广内容类型 novel/audio
        sync_to_tasks: 是否把状态写回 tasks/<id>/task.json
        headless: 无头模式
    """
    from src.platform_adapter.fanqie_promotion import FanqiePromotionService
    fanqie = FanqiePromotionService()
    try:
        result = fanqie.list_promotions(
            content_type=content_type,
            headless=headless,
            sync_to_tasks=sync_to_tasks,
        )
        return {"success": True, "result": result}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _fanqie_fetch_book(
    book_name: str = "",
    chapters: int = 10,
    headless: bool = True,
    **kwargs,
) -> dict:
    """抓取番茄小说内容。

    流程：达人中心搜索书名 → 跳转详情页 → 抓元数据 + 章节正文 → 保存 meta.json + chapters/ + material.txt。
    存储位置：data/fanqie_promotion/books/<book_id>_<书名>/。

    Args:
        book_name: 书名（必填）
        chapters: 抓取章节数（默认 10，含付费墙检测自动停止）
        headless: 无头模式
    """
    from src.platform_adapter.fanqie_promotion import FanqiePromotionService
    if not book_name.strip():
        return {"success": False, "error": "缺少 book_name"}
    fanqie = FanqiePromotionService()
    try:
        result = fanqie.fetch_book(
            book_name=book_name,
            chapters=chapters,
            headless=headless,
        )
        return {
            "success": True,
            "book_name": result.book_name,
            "book_id": result.book_id,
            "chapters_count": len(result.chapters),
            "material_path": result.material_path,
            "chapters_dir": result.chapters_dir,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _fanqie_list_books(**kwargs) -> dict:
    """列出已抓的所有番茄小说（扫 data/fanqie_promotion/books/）。"""
    from src.platform_adapter.fanqie_promotion import FanqiePromotionService
    fanqie = FanqiePromotionService()
    books = fanqie.list_books()
    return {"success": True, "count": len(books), "books": books}


def _douyin_warmup(
    account_id: str = "",
    mode: str = "daily",
    keyword: str = "",
    max_videos: int = 12,
    min_watch: int = 8,
    max_watch: int = 45,
    comment_probability: float = 0.0,
    like_probability: float = 0.0,
    headless: bool = False,
    **kwargs,
) -> dict:
    """运行抖音养号任务"""
    from src.platform_adapter.douyin_warmup import DouyinWarmupService
    warmup = DouyinWarmupService()
    try:
        result = warmup.run_warmup(
            account_id=account_id,
            mode=mode,
            keyword=keyword,
            min_watch=min_watch,
            max_watch=max_watch,
            max_videos=max_videos,
            duration_minutes=0,
            comment_probability=comment_probability,
            headless=headless,
            keep_open_on_blocked=True,
            start_url="",
            use_search=False,
            keep_open_after_run=False,
            no_comment_max_watch=10,
            duration_ratio_min=0.1,
            duration_ratio_max=2.0,
            like_probability=like_probability,
            max_likes=0,
            min_comment_opens=1,
            comment_scrolls=3,
            comment_like_probability=0.0,
            max_comment_likes=0,
        )
        return {
            "success": result.status == "completed",
            "status": result.status,
            "videos_seen": result.videos_seen,
            "log_path": result.log_path,
            "message": result.message,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _douyin_warmup_login(account_id: str = "", display_name: str = "", **kwargs) -> dict:
    """为养号账号打开登录窗口"""
    from src.platform_adapter.douyin_warmup import DouyinWarmupService
    warmup = DouyinWarmupService()
    try:
        account = warmup.open_login_window(
            account_id=account_id,
            display_name=display_name,
            url="https://www.douyin.com/",
            pause_seconds=900,
            wait_for_enter=True,
        )
        return {"success": True, "account": asdict(account)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _douyin_warmup_account_list(**kwargs) -> dict:
    """列出所有养号账号"""
    from src.platform_adapter.douyin_warmup import DouyinWarmupService
    warmup = DouyinWarmupService()
    try:
        accounts = warmup.list_accounts()
        return {"success": True, "accounts": [asdict(a) for a in accounts]}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _douyin_warmup_report(account_id: str = "", days: int = 7, **kwargs) -> dict:
    """查看养号报告"""
    from src.platform_adapter.douyin_warmup import DouyinWarmupService
    warmup = DouyinWarmupService()
    try:
        rows = warmup.report(account_id=account_id, days=days)
        return {"success": True, "rows": rows}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _import_knowledge(books_dir: str = "data/books", **kwargs) -> dict:
    """导入书籍到知识库（向量检索）"""
    from src.services import KnowledgeImportRequest, GenerationService
    service = GenerationService()
    try:
        ok = service.import_knowledge_base(KnowledgeImportRequest(books_dir=books_dir))
        return {"success": ok, "message": "导入成功" if ok else "导入失败"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _reply_single_comment(video_id: str = "", comment_id: str = "", content: str = "", headless: bool = False, **kwargs) -> dict:
    """回复单条评论"""
    from src.platform_adapter import DouyinAdapter
    adapter = DouyinAdapter()
    try:
        ok = adapter.reply_to_comment(video_id, comment_id, content)
        return {"success": ok, "message": "回复成功" if ok else "回复失败"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _open_upload_page(**kwargs) -> dict:
    """打开抖音上传页面"""
    from src.platform_adapter import DouyinAdapter
    adapter = DouyinAdapter()
    try:
        state = adapter.open_upload_page(url="", pause_seconds=600, wait_for_enter=True)
        return {"success": True, "state": asdict(state) if state else {}}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _run_bash_command(command: str = "", cwd: str = "", **kwargs) -> dict:
    """执行 Bash 命令，参数: command(str), cwd(str 默认项目根目录)"""
    import subprocess
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd or None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:500],
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _investigate_problems(limit: int = 20, **kwargs) -> dict:
    """
    扫描未解决问题，对每个问题调用 LLM 给出一句调查摘要，
    并把访问时间 / 次数更新到 ProblemMemory。
    适合由 cron 任务每天调用。
    """
    from src.memory.problem_memory import MemoryLayerManager
    from src.shared.llm_client import llm_client

    with MemoryLayerManager() as mlm:
        problems = mlm.get_unresolved_problems(limit=limit)
        if not problems:
            return {"success": True, "investigated": 0, "detail": "无未解决问题"}

        # 一次性批量提示 LLM
        lines = []
        for p in problems:
            lines.append(f"#{p['id']}: {p['problem_text'][:200]}")
        prompt_lines = "\n".join(lines)
        prompt = (
            "以下为用户未解决的问题，请逐条用一句话给出调查方向/可能的解决方案。"
            "输出格式：#<id>: <一句中文摘要>\n\n"
            f"{prompt_lines}"
        )

        try:
            response = llm_client.chat_completion_tracked(
                [
                    {"role": "system", "content": "你是 AI 助手，擅长排查技术问题。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                json_mode=False,
            )
        except Exception as exc:
            return {"success": False, "error": f"LLM 调用失败: {exc}"}

        # 逐行解析，#<id>: <note>
        import re
        notes = {}
        for line in response.splitlines():
            m = re.match(r"#?(\d+)\s*[:：]\s*(.+)", line.strip())
            if m:
                notes[int(m.group(1))] = m.group(2).strip()[:480]

        investigated = 0
        for p in problems:
            note = notes.get(p["id"], "(未生成摘要)")
            mlm.investigate_problem(p["id"], note=note)
            investigated += 1

        return {
            "success": True,
            "investigated": investigated,
            "summary": notes,
        }


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------

SKILLS: list[Skill] = [
    Skill(
        name="rag_search",
        description="从知识库检索相关段落，参数: query(str), top_k(int 默认3)",
        func=_search_knowledge,
        requires_confirmation=False,
    ),
    Skill(
        name="generate_presenter_video",
        description="生成动漫数字人主讲视频，参数: keywords/text/text_file, input_mode, title, tts_provider, character, background_style, max_segments, no_comfy_background",
        func=_generate_presenter_video,
        requires_confirmation=True,
    ),
    Skill(
        name="generate_audio",
        description="纯音频/TTS 生成（不生成视频），参数: text/keywords, tts_provider, voice, bgm, bgm_volume",
        func=_generate_audio,
        requires_confirmation=True,
    ),
    Skill(
        name="publish_douyin",
        description="发布视频到抖音，参数: video_path, title, description, tags",
        func=_publish_douyin_video,
        requires_confirmation=True,
    ),
    Skill(
        name="sync_douyin_videos",
        description="同步抖音创作者后台视频列表，参数: page_limit(int 默认5)",
        func=_sync_douyin_videos,
        requires_confirmation=False,
    ),
    Skill(
        name="fetch_comments",
        description="抓取视频评论，参数: video_id(str) 或 all_videos(bool)",
        func=_fetch_comments,
        requires_confirmation=False,
    ),
    Skill(
        name="auto_reply_comments",
        description="自动回复视频评论，参数: video_id(str) 或 all_videos(bool)",
        func=_auto_reply_comments,
        requires_confirmation=True,
    ),
    Skill(
        name="get_user_preferences",
        description="读取当前用户偏好设置",
        func=_get_user_preferences,
        requires_confirmation=False,
    ),
    Skill(
        name="update_user_preferences",
        description="更新用户偏好，参数: default_video_mode, default_tts_provider, preferred_topics 等",
        func=_update_user_preferences,
        requires_confirmation=True,
    ),
    # ── 番茄小说推广 ──────────────────────────────────────────────
    Skill(
        name="fanqie_login",
        description="打开番茄小说达人中心登录窗口，参数: wait_for_enter(bool 默认True)",
        func=_fanqie_login,
        requires_confirmation=False,
    ),
    Skill(
        name="fanqie_apply_promotion",
        description="申请番茄小说推广，参数: content_type(novel/audio), book_name, alias, headless, auto_submit(bool 默认True), publish_type(默认AI数字人)",
        func=_fanqie_apply_promotion,
        requires_confirmation=True,
    ),
    Skill(
        name="fanqie_fetch_book",
        description="获取番茄小说章节内容，参数: book_name, chapters(int 默认10), headless",
        func=_fanqie_fetch_book,
        requires_confirmation=False,
    ),
    Skill(
        name="fanqie_generate_video",
        description="生成番茄小说推广视频，参数: book_name, alias, chapters, max_segments, no_comfy_background, assets_only",
        func=_fanqie_generate_video,
        requires_confirmation=True,
    ),
    Skill(
        name="fanqie_list_promotions",
        description="扫描番茄推广列表页，列出所有别名状态并同步到 task.json，参数: content_type(novel/audio), sync_to_tasks(bool 默认True), headless",
        func=_fanqie_list_promotions,
        requires_confirmation=False,
    ),
    Skill(
        name="fanqie_fetch_book",
        description="抓取番茄小说内容（搜索书名 + 抓元数据 + 抓章节正文）。参数: book_name(必填, 书名), chapters(int 默认10), headless(bool)。返回: book_id / chapters_count / material_path",
        func=_fanqie_fetch_book,
        requires_confirmation=False,
    ),
    Skill(
        name="fanqie_list_books",
        description="列出已抓的所有番茄小说（扫 data/fanqie_promotion/books/ 下的 meta.json）",
        func=_fanqie_list_books,
        requires_confirmation=False,
    ),
    # ── 抖音养号 ─────────────────────────────────────────────────
    Skill(
        name="douyin_warmup",
        description="运行抖音养号任务，参数: account_id, mode(daily/pre-publish/post-publish), keyword, max_videos, min_watch, max_watch, comment_probability, like_probability, headless",
        func=_douyin_warmup,
        requires_confirmation=True,
    ),
    Skill(
        name="douyin_warmup_login",
        description="为养号账号打开抖音登录窗口，参数: account_id, display_name",
        func=_douyin_warmup_login,
        requires_confirmation=False,
    ),
    Skill(
        name="douyin_warmup_account_list",
        description="列出所有养号账号，返回账号列表",
        func=_douyin_warmup_account_list,
        requires_confirmation=False,
    ),
    Skill(
        name="douyin_warmup_report",
        description="查看养号报告，参数: account_id, days(int 默认7)",
        func=_douyin_warmup_report,
        requires_confirmation=False,
    ),
    # ── 知识库 ──────────────────────────────────────────────────
    Skill(
        name="import_knowledge",
        description="导入书籍到知识库，参数: books_dir(str 默认data/books)",
        func=_import_knowledge,
        requires_confirmation=True,
    ),
    # ── 评论与上传 ────────────────────────────────────────────────
    Skill(
        name="reply_single_comment",
        description="回复单条评论，参数: video_id, comment_id, content, headless",
        func=_reply_single_comment,
        requires_confirmation=True,
    ),
    Skill(
        name="open_upload_page",
        description="打开抖音上传页面（可见浏览器，用户手动上传）",
        func=_open_upload_page,
        requires_confirmation=False,
    ),
    # ── 系统 ──────────────────────────────────────────────────
    Skill(
        name="run_bash_command",
        description="执行 Bash 命令，参数: command(str), cwd(str 可选)",
        func=_run_bash_command,
        requires_confirmation=False,
    ),
    # ── 记忆管理 ─────────────────────────────────────────────
    Skill(
        name="investigate_problems",
        description="扫描未解决问题，调用 LLM 生成调查摘要并更新 ProblemMemory，参数: limit(int 默认20)",
        func=_investigate_problems,
        requires_confirmation=False,
    ),
]


class SkillRegistry:
    """Skill 注册表，提供 name → Skill 查找和参数 introspection

    Skills 来源：
      1. 模块级 SKILLS 列表（老的 imperative 注册，22 条）
      2. 通过 @skill 装饰器注册的 Skills（src/agent/skill_decorator.py）

    同名时装饰器版本覆盖列表版本，方便渐进迁移。
    """

    def __init__(self):
        from src.agent.skill_decorator import _derive_from_signature

        self._skills: dict[str, Skill] = {}
        # 老路径：先放 SKILLS 列表；如果老 Skill 没有 params schema，
        # 自动从函数签名 derive（保证 **kwargs 兼容老代码）。
        for s in SKILLS:
            if not s.params:
                s.params = _derive_from_signature(s.func)
            self._skills[s.name] = s
        # 装饰器路径：覆盖同名
        decorator_skills = get_registered_skills()
        for s in decorator_skills:
            if s.name in self._skills:
                logger.info(
                    "Skill '%s' 被装饰器版本覆盖（替代老 SKILLS 列表中的实现）",
                    s.name,
                )
            self._skills[s.name] = s

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list_all(self) -> list[Skill]:
        return list(self._skills.values())

    def get_skill_descriptions(self) -> str:
        """生成所有 Skill 的描述，按 category 分组，markdown 友好。"""
        from collections import defaultdict
        by_category: dict[str, list[Skill]] = defaultdict(list)
        for s in self._skills.values():
            by_category[s.category].append(s)

        parts: list[str] = []
        for category in sorted(by_category.keys()):
            parts.append(f"## {category}")
            for s in by_category[category]:
                # 必填参数
                required = [p for p in s.params if p.required]
                # 可选参数（吸收器不显示）
                optional = [
                    p
                    for p in s.params
                    if not p.required and not p.is_absorber()
                ]
                sig_parts: list[str] = []
                for p in required:
                    sig_parts.append(f"{p.name}: <{p.type.value}>")
                for p in optional:
                    if p.default is None or p.default == "":
                        sig_parts.append(f"{p.name}?: <{p.type.value}>")
                    else:
                        sig_parts.append(
                            f"{p.name}?=<{p.type.value} default={p.default!r}>"
                        )
                sig = ", ".join(sig_parts) if sig_parts else ""
                parts.append(
                    f"- **{s.name}**({sig}) [{'需要确认' if s.requires_confirmation else '无需确认'}]"
                )
                parts.append(f"    {s.description}")
                if s.examples:
                    parts.append(
                        "    examples: " + " | ".join(s.examples)
                    )
            parts.append("")
        return "\n".join(parts)

    def call(self, name: str, kwargs: dict) -> dict:
        """调用指定 Skill，返回 SkillResult.to_dict()。

        Harness Engineering Layer 3: 编排 + Layer 4: 反馈 + Layer 6: 持续改进。
          - 参数 schema 校验（Layer 5: 关 1）
          - 幂等性检查（Layer 5: 关 2）
          - 重试循环（exponential backoff，retry_on 决定哪些 code 触发）
          - 超时熔断（threading.Thread.join(timeout=)）
          - 失败自动落盘 ProblemMemory（Layer 4: 反馈）
          - 触发 fire-and-forget LLM 错误诊断（Layer 6: 持续改进）

        老 Skill 返回裸 dict 会被 coerce_to_skill_result 归一化。
        """
        import time
        from src.agent.skill_result import SkillResult, coerce_to_skill_result, SKILL_ERROR_CODES

        skill = self.get(name)
        if not skill:
            return SkillResult.err(
                "not_found", f"未知 Skill: {name}",
                error={"retryable": False, "type": "UnknownSkill"},
            ).to_dict()

        # 关 1: 参数 schema 校验
        is_valid, err, code = validate_params(skill, kwargs)
        if not is_valid:
            logger.warning("Skill %s 参数校验失败: %s", name, err)
            return SkillResult.err(
                "validation_error", err,
                error={"code": code, "retryable": False},
                skill=name,
            ).to_dict()

        # 关 2: 幂等性检查（仅对声明 idempotent=True 的 Skill）
        if skill.idempotent:
            dup = self._check_idempotent(name, kwargs)
            if dup:
                return SkillResult.ok(
                    data={"deduplicated": True, "previous_result": dup},
                    message=f"检测到重复执行（之前结果：{dup}）",
                    skill=name,
                ).to_dict()

        # 重试循环 + 超时熔断
        attempts = max(1, skill.retries + 1)
        last_result: SkillResult | None = None
        for attempt in range(attempts):
            start = time.time()
            try:
                raw = self._invoke_with_timeout(skill, kwargs)
            except TimeoutError as exc:
                last_result = SkillResult.err(
                    "timeout",
                    f"Skill {name} 超时 (>{skill.timeout_s}s)",
                    error={"type": "TimeoutError", "message": str(exc), "retryable": True},
                    skill=name,
                )
            except Exception as exc:
                last_result = SkillResult.err(
                    "skill_error",
                    f"{type(exc).__name__}: {exc}"[:300],
                    error={
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "retryable": False,
                    },
                    skill=name,
                )
            else:
                # 成功
                duration = int((time.time() - start) * 1000)
                result = coerce_to_skill_result(name, raw)
                result.skill = name
                result.duration_ms = duration
                result.attempts = attempt + 1
                # 幂等缓存：成功后写入，下次同样 kwargs 命中
                if skill.idempotent:
                    self._save_idempotent(name, kwargs, result.to_dict())
                return result.to_dict()

            # 失败：决定是否重试
            if (
                attempt < attempts - 1
                and last_result is not None
                and last_result.code in skill.retry_on
            ):
                backoff = self._backoff_seconds(attempt, skill.retry_backoff)
                logger.info(
                    "Skill %s 失败 (%s)，%ss 后重试 (%d/%d)",
                    name, last_result.code, backoff, attempt + 1, attempts,
                )
                time.sleep(backoff)
                continue
            break

        # 失败终态
        if last_result is not None:
            # 标记是否耗尽重试
            if skill.retries > 0 and last_result.code in skill.retry_on:
                last_result.code = "max_retries_exceeded"
            last_result.attempts = attempts
            last_result.duration_ms = int((time.time() - start) * 1000) if 'start' in dir() else 0
            # 自动落盘 ProblemMemory + 触发错误诊断
            self._save_to_problem_memory(name, kwargs, last_result)
            return last_result.to_dict()

        return SkillResult.err("skill_error", "未知失败", skill=name).to_dict()

    def _invoke_with_timeout(self, skill, kwargs: dict):
        """在子线程跑 Skill，超时抛 TimeoutError。

        daemon=True：进程退出时强制终止。
        """
        if skill.timeout_s <= 0:
            return skill.func(**kwargs)

        import threading
        result_box: dict = {}
        exc_box: dict = {}

        def run():
            try:
                result_box["v"] = skill.func(**kwargs)
            except BaseException as e:  # noqa: BLE001
                exc_box["e"] = e

        t = threading.Thread(target=run, daemon=True, name=f"Skill[{skill.name}]")
        t.start()
        t.join(timeout=skill.timeout_s)
        if t.is_alive():
            # 超时（线程继续在后台跑；daemon 进程结束会强制终止）
            raise TimeoutError(f"Skill timed out after {skill.timeout_s}s")
        if "e" in exc_box:
            raise exc_box["e"]
        return result_box.get("v")

    def _backoff_seconds(self, attempt: int, mode: str) -> float:
        """指数退避：1s, 2s, 4s, 8s...；固定：2s。"""
        if mode == "fixed":
            return 2.0
        # exponential
        return float(2 ** attempt)

    def _check_idempotent(self, name: str, kwargs: dict) -> dict | None:
        """幂等性检查：返回之前的执行结果（如果有），否则 None。

        默认实现：根据 (name, json.dumps(kwargs, sort_keys=True)) 在短期缓存里查。
        子类可以重写。
        """
        if not hasattr(self, "_idempotent_cache"):
            self._idempotent_cache: dict[str, dict] = {}
        import hashlib
        import time
        key = self._idempotent_key(name, kwargs)
        cached = self._idempotent_cache.get(key)
        if cached and time.time() - cached.get("ts", 0) < 300:
            return cached.get("result")
        return None

    def _save_idempotent(self, name: str, kwargs: dict, result: dict) -> None:
        """存幂等结果。"""
        if not hasattr(self, "_idempotent_cache"):
            self._idempotent_cache: dict[str, dict] = {}
        import time
        key = self._idempotent_key(name, kwargs)
        self._idempotent_cache[key] = {"ts": time.time(), "result": result}

    def _idempotent_key(self, name: str, kwargs: dict) -> str:
        import hashlib
        payload = f"{name}:{json.dumps(kwargs, sort_keys=True, ensure_ascii=False)}"
        return name + ":" + hashlib.md5(payload.encode("utf-8")).hexdigest()[:12]

    def _save_to_problem_memory(
        self, skill_name: str, kwargs: dict, result: SkillResult
    ) -> None:
        """Skill 失败时触发 fire-and-forget 错误诊断。

        Harness Engineering Layer 6: 持续改进。
        注：写 ProblemMemory 表留给 agent.py 层（它有 session_id 上下文），
        registry 层只触发 error_reviewer + 写日志。

        任何异常都不会抛给调用方。
        """
        # 1) 写日志（必有，便于排查）
        logger.warning(
            "Skill %s 失败: code=%s message=%s attempts=%d kwargs=%s",
            skill_name, result.code, result.message[:200],
            result.attempts, json.dumps(kwargs, ensure_ascii=False)[:200],
        )

        # 2) fire-and-forget LLM 错误诊断（Layer 6: 持续改进）
        #    异步跑 asyncio loop；不阻塞主流程
        try:
            from src.agent.error_reviewer import error_reviewer
            import threading

            def _run_review():
                try:
                    asyncio.run(
                        error_reviewer.review_skill_failure_async(
                            skill_name=skill_name,
                            skill_kwargs=kwargs,
                            result=result,
                        )
                    )
                except Exception:
                    logger.exception("error_reviewer 失败")

            t = threading.Thread(target=_run_review, daemon=True, name=f"error-review[{skill_name}]")
            t.start()
        except Exception as exc:
            logger.debug(f"启动 error_reviewer 失败: {exc}")


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------


def validate_params(
    skill: Skill, kwargs: dict
) -> tuple[bool, str | None, str | None]:
    """
    按 Skill 的 params schema 校验 kwargs。
    返回 (is_valid, error_message, error_code)。

    错误码：
      PARAM_MISSING  必填参数缺失
      PARAM_TYPE     类型不匹配
      PARAM_RANGE    数值超界
      PARAM_UNKNOWN  未知参数（且没有 **kwargs 吸收器）
      PARAM_CHOICE   CHOICE 类型值不在 choices 列表中
    """
    schema: dict[str, SkillParam] = {p.name: p for p in skill.params}
    has_absorber = any(p.is_absorber() for p in skill.params)

    # 1. 必填参数检查
    for name, p in schema.items():
        if p.required and name not in kwargs:
            return (
                False,
                f"missing required param: {name}",
                "PARAM_MISSING",
            )

    # 2. 未知 key 检查（除非有吸收器）
    for key in kwargs:
        if key not in schema and not has_absorber:
            return (
                False,
                f"unknown param: {key}",
                "PARAM_UNKNOWN",
            )

    # 3. 类型 / 取值范围 / choices 检查
    for key, value in kwargs.items():
        p = schema.get(key)
        if p is None:
            continue  # 吸收器，不校验
        is_valid, code = _check_value(p, value)
        if not is_valid:
            return (
                False,
                f"param {key} validation failed (value={value!r})",
                code,
            )
    return True, None, None


def _check_value(p: SkillParam, value: Any) -> tuple[bool, str | None]:
    """单个参数的取值检查。返回 (is_valid, error_code)。"""
    # 类型检查
    if p.type == ParamType.STRING and not isinstance(value, str):
        return False, "PARAM_TYPE"
    if p.type == ParamType.INT and not isinstance(value, int):
        return False, "PARAM_TYPE"
    if p.type == ParamType.FLOAT and not isinstance(value, (int, float)):
        return False, "PARAM_TYPE"
    if p.type == ParamType.BOOL and not isinstance(value, bool):
        return False, "PARAM_TYPE"
    if p.type == ParamType.LIST and not isinstance(value, list):
        return False, "PARAM_TYPE"
    if p.type == ParamType.DICT and not isinstance(value, dict):
        return False, "PARAM_TYPE"
    # CHOICE
    if p.type == ParamType.CHOICE and p.choices:
        if value not in p.choices:
            return False, "PARAM_CHOICE"
    # 范围
    if p.type in (ParamType.INT, ParamType.FLOAT):
        if p.min_value is not None and value < p.min_value:
            return False, "PARAM_RANGE"
        if p.max_value is not None and value > p.max_value:
            return False, "PARAM_RANGE"
    return True, None
