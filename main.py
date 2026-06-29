# -*- coding: utf-8 -*-
import argparse
import json
import sys
from dataclasses import asdict

from src.platform_adapter import DouyinAdapter
from src.platform_adapter.browser_session import BrowserSession, build_default_browser_session_config
from src.platform_adapter.douyin_warmup import DouyinWarmupService
from src.platform_adapter.fanqie_promotion import FanqiePromotionService
from src.platform_adapter.models import PublishRequest
from src.services import (
    AutoPublishRequest,
    AutoPublishService,
    GenerationRequest,
    GenerationService,
    KnowledgeImportRequest,
    QuickGenerationRequest,
)
from src.content_factory.presenter import DEFAULT_SONIC_FOX_CHARACTER, INPUT_MODES, PresenterRequest
from src.content_factory.presenter_pipeline import PresenterPipeline
from src.content_factory.presenter.scene_planner import ScenePlanner
from src.shared.config import settings
from src.shared.database import init_db, SessionLocal
from src.shared.logger import logger
from src.shared.migration import ensure_migrated

# 启动时检查 DB 是否已通过 Alembic 迁移到位。
# 全新环境：先 `alembic upgrade head`；老环境：先 `alembic stamp head`。
# 失败时 strict=True 直接 sys.exit(1)；设 INIT_DB_FALLBACK=1 跳过。
if not ensure_migrated(strict=True):
    sys.exit(1)

# 必须先导入所有模型，否则 Base.metadata 里没有对应表
from src.memory.models import UserProfile, ConversationSession, ConversationMessage  # noqa: F401
from src.memory.problem_memory import ConversationMemory, UserMemory, ProblemMemory  # noqa: F401
from src.scheduler.models import ScheduledTask, TaskExecution, TaskType, TaskStatus, TriggerType  # noqa: F401

# init_db 现在是 noop（迁移走 Alembic），保留调用以维持向后兼容
init_db()

# 首次启动时播种内置定时任务（每日未解决问题调查）
try:
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


service = GenerationService()
DEFAULT_BGM_PATH = service.default_bgm_path


def build_parser():
    parser = argparse.ArgumentParser(description="WisdomAI - Life Inspiration Audio Generator")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    gen_parser = subparsers.add_parser("generate", help="Generate audio from topic or random book wisdom")
    gen_parser.add_argument("--book", type=str, help="Specific book filename (optional, random mode only)")
    gen_parser.add_argument("--topic", type=str, help="Topic for RAG search")
    gen_parser.add_argument("--count", type=int, default=1, help="Number of audios to generate")
    gen_parser.add_argument("--tts-provider", type=str, default="edge", choices=["edge", "gpt_sovits"], help="TTS provider")
    gen_parser.add_argument("--voice", type=str, help="Voice ID or reference audio path")

    quick_parser = subparsers.add_parser("quick", help="Generate by prompt in one command")
    quick_parser.add_argument("--prompt", type=str, help="Prompt/topic text (optional if --text is provided)")
    quick_parser.add_argument("--text", type=str, help="Direct text input (skips script generation)")
    quick_parser.add_argument("--bgm", type=str, help=f"Background music file path (default: {DEFAULT_BGM_PATH})")
    quick_parser.add_argument("--bgm-volume", type=float, default=0.2, help="BGM volume (0.0-1.0)")
    quick_parser.add_argument("--output-dir", type=str, help="Archive output directory")
    quick_parser.add_argument("--tts-provider", type=str, default="edge", choices=["edge", "gpt_sovits"], help="TTS provider")
    quick_parser.add_argument("--voice", type=str, help="Voice ID or reference audio path")
    quick_parser.add_argument("--count", type=int, default=1, help="Number of audios to generate")
    quick_parser.add_argument("--keep-temp", action="store_true", help="Keep temp file in original output dir")
    quick_parser.add_argument("--no-merge", action="store_true", help="Do not merge sentences into one file")
    quick_parser.add_argument("--keywords", type=str, help="Required keywords, comma separated")
    quick_parser.add_argument("--emotion-type", type=str, help="Emotion type")
    quick_parser.add_argument("--positive-energy-type", type=str, help="Positive energy type")
    quick_parser.add_argument("--target-audience", type=str, help="Target audience")

    presenter_parser = subparsers.add_parser("presenter", help="Generate an offline digital presenter video")
    presenter_parser.add_argument("--keywords", type=str, default="", help="Keywords/topic for script generation")
    presenter_parser.add_argument("--text", type=str, default="", help="Direct presenter script text")
    presenter_parser.add_argument("--text-file", type=str, default="", help="Article/script text file path")
    presenter_parser.add_argument("--input-mode", type=str, default="keywords", choices=INPUT_MODES, help="Input mode: keywords, article_direct, or article_extract")
    presenter_parser.add_argument("--title", type=str, default="", help="On-screen title")
    presenter_parser.add_argument("--character", type=str, default=DEFAULT_SONIC_FOX_CHARACTER, help="Character id or asset path. Default: Sonic fox video layer")
    presenter_parser.add_argument("--character-position", type=str, default="right_bottom", choices=["right_bottom", "left_bottom", "center_bottom"], help="Character placement on the canvas")
    presenter_parser.add_argument("--character-size", type=str, default="medium", choices=["small", "medium", "large"], help="Character display size")
    presenter_parser.add_argument("--background", type=str, default="", help="Background image/video path")
    presenter_parser.add_argument("--background-style", type=str, default="anime", choices=["anime", "existing", "gradient"], help="Default background style when --background is omitted")
    presenter_parser.add_argument("--audio", type=str, default="", help="Use an existing audio file and skip TTS")
    presenter_parser.add_argument("--bgm", type=str, default="", help="Optional BGM path")
    presenter_parser.add_argument("--output-dir", type=str, default="data/videos", help="Output directory for final mp4")
    presenter_parser.add_argument("--tts-provider", type=str, default="edge", choices=["edge", "gpt_sovits"], help="TTS provider")
    presenter_parser.add_argument("--voice", type=str, default="", help="Voice ID or reference audio path")
    presenter_parser.add_argument("--max-segments", type=int, default=0, help="Maximum number of presenter segments. 0 means no truncation")
    presenter_parser.add_argument("--no-comfy-background", action="store_true", help="Use local fallback anime backgrounds without ComfyUI")

    presenter_assets_parser = subparsers.add_parser("presenter-assets", help="Generate presenter script, segment audio, and background images without composing video")
    presenter_assets_parser.add_argument("--keywords", type=str, default="", help="Keywords/topic for script generation")
    presenter_assets_parser.add_argument("--text", type=str, default="", help="Direct presenter script text")
    presenter_assets_parser.add_argument("--text-file", type=str, default="", help="Article/script text file path")
    presenter_assets_parser.add_argument("--input-mode", type=str, default="keywords", choices=INPUT_MODES, help="Input mode: keywords, article_direct, or article_extract")
    presenter_assets_parser.add_argument("--title", type=str, default="", help="On-screen title")
    presenter_assets_parser.add_argument("--character", type=str, default=DEFAULT_SONIC_FOX_CHARACTER, help="Character id or asset path. Default: Sonic fox video layer")
    presenter_assets_parser.add_argument("--background", type=str, default="", help="Background image/video path")
    presenter_assets_parser.add_argument("--background-style", type=str, default="anime", choices=["anime", "existing", "gradient"], help="Default background style when --background is omitted")
    presenter_assets_parser.add_argument("--tts-provider", type=str, default="edge", choices=["edge", "gpt_sovits"], help="TTS provider hint for script generation")
    presenter_assets_parser.add_argument("--voice", type=str, default="", help="Voice ID or reference audio path")
    presenter_assets_parser.add_argument("--max-segments", type=int, default=0, help="Maximum number of presenter segments. 0 means no truncation")
    presenter_assets_parser.add_argument("--audio", type=str, default="", help="Use an existing audio file and skip TTS")
    presenter_assets_parser.add_argument("--no-comfy-background", action="store_true", help="Use fast local fallback images instead of production ComfyUI backgrounds")

    debug_bg_parser = subparsers.add_parser("debug-background-plan", help="Analyze text and show matched background scene plan")
    debug_bg_parser.add_argument("--text", type=str, required=True, help="Chinese segment text to analyze")

    fanqie_login_parser = subparsers.add_parser("fanqie-login", help="Open Fanqie KOL center and save browser login state")
    fanqie_login_parser.add_argument("--url", type=str, default="", help="Target URL to open")
    fanqie_login_parser.add_argument("--pause-seconds", type=int, default=900, help="How long to keep the browser open")
    fanqie_login_parser.add_argument("--wait-for-enter", action="store_true", help="Keep browser open until Enter is pressed")

    fanqie_apply_parser = subparsers.add_parser("fanqie-promo-apply", help="Apply for one Fanqie promotion task with saved browser login state")
    fanqie_apply_parser.add_argument("--type", type=str, default="novel", choices=["novel", "audio"], help="Promotion content type")
    fanqie_apply_parser.add_argument("--book-name", type=str, default="", help="Optional target novel name. Default uses first available item")
    fanqie_apply_parser.add_argument("--alias", type=str, default="", help="Promotion alias to fill. Empty = use first recommended alias")
    fanqie_apply_parser.add_argument("--no-wait-login", action="store_true", help="Do not pause for manual login before applying")
    fanqie_apply_parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    fanqie_apply_parser.add_argument("--keep-open", action="store_true", help="Keep browser open after submitting for manual check")
    fanqie_apply_parser.add_argument("--no-auto-submit", action="store_true", help="Fill modal only, do not click submit (let user confirm in browser)")
    fanqie_apply_parser.add_argument("--publish-type", type=str, default="AI数字人", help="发文类型（preferred list first match wins），默认 AI数字人")
    fanqie_apply_parser.add_argument("--max-alias-attempts", type=int, default=5, help="撞名时最多尝试的推荐别名个数")

    fanqie_fetch_parser = subparsers.add_parser("fanqie-book-fetch", help="Search Fanqie novel and fetch first chapters")
    fanqie_fetch_parser.add_argument("--book-name", type=str, required=True, help="Novel name")
    fanqie_fetch_parser.add_argument("--chapters", type=int, default=10, help="Chapter count to fetch")
    fanqie_fetch_parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")

    fanqie_list_parser = subparsers.add_parser("fanqie-promo-list", help="Scan Fanqie promotion-list page and sync alias status to task.json")
    fanqie_list_parser.add_argument("--type", type=str, default="novel", choices=["novel", "audio"], help="Promotion content type")
    fanqie_list_parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    fanqie_list_parser.add_argument("--no-sync", action="store_true", help="List only, do not write back to task.json")

    fanqie_books_parser = subparsers.add_parser("fanqie-list-books", help="List all books already fetched (scan data/fanqie_promotion/books/)")

    # ── 番茄批量抓取（DB 清单驱动） ──
    fanqie_batch_add = subparsers.add_parser("fanqie-batch-add", help="Add books to batch fetch queue (DB)")
    fanqie_batch_add.add_argument("--book-names", type=str, nargs="+", required=True, help="Book names to add")
    fanqie_batch_add.add_argument("--chapters", type=int, default=5, help="Chapters per book (default 5)")
    fanqie_batch_add.add_argument("--interval-s", type=int, default=30, help="Seconds between books (default 30)")
    fanqie_batch_add.add_argument("--note", type=str, default="", help="Note about why these books")

    fanqie_batch_list = subparsers.add_parser("fanqie-batch-list", help="List batch fetch queue (DB)")
    fanqie_batch_list.add_argument("--status", type=str, default="all",
                                   choices=["all", "pending", "running", "done", "failed", "skipped"],
                                   help="Filter by status (default: all)")
    fanqie_batch_list.add_argument("--limit", type=int, default=200, help="Max rows to return (default 200)")

    fanqie_batch_run = subparsers.add_parser("fanqie-batch-run", help="Run batch fetch from DB pending (NO book_names)")
    fanqie_batch_run.add_argument("--interval-s", type=float, default=30.0, help="Override interval seconds (default 30)")
    fanqie_batch_run.add_argument("--max-count", type=int, default=10, help="Max books to run (default 10)")

    fanqie_batch_enqueue = subparsers.add_parser("fanqie-batch-enqueue", help="Enqueue all DB pending to TaskQueue")
    fanqie_batch_seed = subparsers.add_parser("fanqie-batch-seed", help="Seed DB from config/fanqie_batch_books.yaml")

    fanqie_video_parser = subparsers.add_parser("fanqie-promo-video", help="Generate a Fanqie novel promotion presenter video")
    fanqie_video_parser.add_argument("--task-file", type=str, default="", help="Task JSON from fanqie-promo-apply")
    fanqie_video_parser.add_argument("--book-name", type=str, default="", help="Novel name if no task file is provided")
    fanqie_video_parser.add_argument("--alias", type=str, default="", help="Promotion alias if no task file is provided")
    fanqie_video_parser.add_argument("--chapters", type=int, default=10, help="Chapter count to fetch when material is missing")
    fanqie_video_parser.add_argument("--output-dir", type=str, default="data/videos", help="Output directory for final video")
    fanqie_video_parser.add_argument("--max-segments", type=int, default=0, help="Maximum presenter segments. 0 means no truncation")
    fanqie_video_parser.add_argument("--no-comfy-background", action="store_true", help="Use local fallback backgrounds instead of ComfyUI")
    fanqie_video_parser.add_argument("--assets-only", action="store_true", help="Generate script/audio/background assets only, skip final video")

    import_parser = subparsers.add_parser("import-knowledge", help="Import books into the vector knowledge base")
    import_parser.add_argument("--books-dir", type=str, default=service.default_books_dir, help="Books directory to import")

    login_parser = subparsers.add_parser("douyin-login", help="Open Douyin in a visible browser and keep it paused")
    login_parser.add_argument("--url", type=str, default=settings.DOUYIN_HOME_URL, help="Target URL to open")
    login_parser.add_argument("--pause-seconds", type=int, default=600, help="How long to keep the browser open")
    login_parser.add_argument("--wait-for-enter", action="store_true", help="Keep browser open until Enter is pressed")

    warmup_login_parser = subparsers.add_parser("douyin-warmup-login", help="Open a per-account Douyin warmup browser for manual login")
    warmup_login_parser.add_argument("--account-id", type=str, required=True, help="Local account id, e.g. douyin_novel_01")
    warmup_login_parser.add_argument("--display-name", type=str, default="", help="Human readable account name")
    warmup_login_parser.add_argument("--url", type=str, default=settings.DOUYIN_HOME_URL, help="Target login URL")
    warmup_login_parser.add_argument("--pause-seconds", type=int, default=900, help="How long to keep the browser open")
    warmup_login_parser.add_argument("--wait-for-enter", action="store_true", help="Keep browser open until Enter is pressed")

    warmup_parser = subparsers.add_parser("douyin-warmup", help="Run low-frequency random Douyin browsing for one account")
    warmup_parser.add_argument("--account-id", type=str, required=True, help="Local account id created by douyin-warmup-login")
    warmup_parser.add_argument("--mode", type=str, default="daily", choices=["daily", "pre-publish", "post-publish"], help="Warmup mode")
    warmup_parser.add_argument("--keyword", type=str, default="", help="Search keyword. Random default if omitted")
    warmup_parser.add_argument("--url", type=str, default="", help="Start URL. Default: https://www.douyin.com/jingxuan")
    warmup_parser.add_argument("--use-search", action="store_true", help="Use keyword search page instead of recommend page")
    warmup_parser.add_argument("--min-watch", type=int, default=8, help="Minimum watch seconds per video")
    warmup_parser.add_argument("--max-watch", type=int, default=45, help="Maximum watch seconds per video. 0 means no cap when duration is detected")
    warmup_parser.add_argument("--no-comment-max-watch", type=int, default=10, help="Max watch seconds when no comment entry is detected")
    warmup_parser.add_argument("--duration-ratio-min", type=float, default=0.1, help="Minimum watch ratio of video duration when duration is detected")
    warmup_parser.add_argument("--duration-ratio-max", type=float, default=2.0, help="Maximum watch ratio of video duration when duration is detected")
    warmup_parser.add_argument("--max-videos", type=int, default=12, help="Maximum videos in one session")
    warmup_parser.add_argument("--duration-minutes", type=int, default=0, help="Optional total duration limit. 0 means use max-videos only")
    warmup_parser.add_argument("--comment-probability", type=float, default=0.0, help="Probability to open comments for viewing only, 0-1")
    warmup_parser.add_argument("--min-comment-opens", type=int, default=1, help="Minimum comment panels to open per session")
    warmup_parser.add_argument("--comment-scrolls", type=int, default=3, help="Scroll count inside each opened comment panel")
    warmup_parser.add_argument("--comment-like-probability", type=float, default=0.0, help="Probability to like visible comments, 0-1. Default 0 disables comment likes")
    warmup_parser.add_argument("--max-comment-likes", type=int, default=0, help="Maximum comment likes in one warmup session. Default 0 disables comment likes")
    warmup_parser.add_argument("--like-probability", type=float, default=0.0, help="Probability to like a video, 0-1. Default 0 disables likes")
    warmup_parser.add_argument("--max-likes", type=int, default=0, help="Maximum likes in one warmup session. Default 0 disables likes")
    warmup_parser.add_argument("--close-on-blocked", action="store_true", help="Close browser immediately when login/captcha/security check is detected")
    warmup_parser.add_argument("--keep-open", action="store_true", help="Keep browser open after warmup until Enter is pressed")
    warmup_parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")

    warmup_report_parser = subparsers.add_parser("douyin-warmup-report", help="Show recent Douyin warmup logs for one account")
    warmup_report_parser.add_argument("--account-id", type=str, required=True, help="Local account id")
    warmup_report_parser.add_argument("--days", type=int, default=7, help="Report days")

    warmup_account_parser = subparsers.add_parser("douyin-warmup-account", help="Manage Douyin warmup account metadata")
    warmup_account_parser.add_argument("action", choices=["list", "show", "set"], help="Account metadata action")
    warmup_account_parser.add_argument("--account-id", type=str, default="", help="Local account id")
    warmup_account_parser.add_argument("--display-name", type=str, default="", help="Human readable account name")
    warmup_account_parser.add_argument("--douyin-uid", type=str, default="", help="Douyin uid or public id")
    warmup_account_parser.add_argument("--login-name", type=str, default="", help="Masked login name, e.g. 138****1234")
    warmup_account_parser.add_argument("--phone-hint", type=str, default="", help="Masked phone hint")
    warmup_account_parser.add_argument("--purpose", type=str, default="", help="Account purpose, e.g. novel_promotion")
    warmup_account_parser.add_argument("--status", type=str, default="", choices=["", "active", "paused", "disabled"], help="Account status")
    warmup_account_parser.add_argument("--notes", type=str, default="", help="Account notes")
    warmup_account_parser.add_argument("--keywords", type=str, default="", help="Warmup keywords, comma separated")

    upload_page_parser = subparsers.add_parser(
        "douyin-upload-page",
        help="Open Douyin creator upload page, click 上传视频, and keep browser paused",
    )
    upload_page_parser.add_argument("--url", type=str, default=settings.DOUYIN_UPLOAD_URL, help="Upload page URL")
    upload_page_parser.add_argument("--pause-seconds", type=int, default=600, help="How long to keep the browser open")
    upload_page_parser.add_argument("--wait-for-enter", action="store_true", help="Keep browser open until Enter is pressed")

    publish_parser = subparsers.add_parser("douyin-publish", help="Publish a video to Douyin via browser automation")
    publish_parser.add_argument("--video", type=str, required=True, help="Path to video file")
    publish_parser.add_argument("--title", type=str, required=True, help="Video title")
    publish_parser.add_argument("--desc", type=str, default="", help="Video description")
    publish_parser.add_argument("--tags", type=str, default="", help="Hashtags, comma separated, e.g. '励志,成长,正能量'")
    publish_parser.add_argument("--cover", type=str, default=None, help="Cover image path (optional)")
    publish_parser.add_argument("--interactive", action="store_true", help="Step-by-step mode, wait for confirmation at each step")
    publish_parser.add_argument("--wait-for-enter", action="store_true", help="Keep browser open after publish until Enter is pressed")

    sync_parser = subparsers.add_parser("douyin-sync", help="Sync published videos from Douyin creator dashboard")
    sync_parser.add_argument("--page-limit", type=int, default=5, help="Maximum number of pages to sync (default: 5)")
    sync_parser.add_argument("--interactive", action="store_true", help="Step-by-step mode, wait for confirmation at each step")
    sync_parser.add_argument("--wait-for-enter", action="store_true", help="Keep browser open after sync until Enter is pressed")
    sync_parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (no visible window)")

    # 评论抓取命令
    comments_parser = subparsers.add_parser("douyin-fetch-comments", help="Fetch comments for a specific video or all published videos")
    comments_parser.add_argument("--video-id", type=str, default=None, help="Specific video ID to fetch comments for")
    comments_parser.add_argument("--all", action="store_true", help="Fetch comments for all published videos in database")
    comments_parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (no visible window)")

    # 评论回复命令
    reply_parser = subparsers.add_parser("douyin-reply-comment", help="Reply to a specific comment")
    reply_parser.add_argument("--video-id", type=str, required=True, help="Video ID")
    reply_parser.add_argument("--comment-id", type=str, required=True, help="Comment ID to reply to")
    reply_parser.add_argument("--content", type=str, required=True, help="Reply content text")
    reply_parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (no visible window)")

    # 自动回复命令
    auto_reply_parser = subparsers.add_parser("auto-reply", help="Auto-reply to comments on a video")
    auto_reply_parser.add_argument("--video-id", type=str, default=None, help="Specific video ID to process")
    auto_reply_parser.add_argument("--all", action="store_true", help="Process all published videos in database")
    auto_reply_parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (no visible window)")

    auto_parser = subparsers.add_parser("auto-publish", help="Generate script + TTS + BGM + compose video + publish to Douyin in one command")
    auto_parser.add_argument("--keywords", type=str, required=True, help="Keywords to generate script (RAG search)")
    auto_parser.add_argument("--title", type=str, default="", help="Video title (auto-generated if empty)")
    auto_parser.add_argument("--desc", type=str, default="", help="Video description")
    auto_parser.add_argument("--tags", type=str, default="", help="Hashtags, comma separated, e.g. '励志,成长,正能量'")
    auto_parser.add_argument("--template", type=str, default="", help="Template video path")
    auto_parser.add_argument("--bgm", type=str, default="", help="BGM file path (use default if empty)")
    auto_parser.add_argument("--bgm-volume", type=float, default=0.2, help="BGM volume (0.0-1.0)")
    auto_parser.add_argument("--output-dir", type=str, default="data/videos", help="Output directory for generated videos")
    auto_parser.add_argument("--interactive", action="store_true", help="Step-by-step mode, wait for confirmation at each step")
    auto_parser.add_argument("--wait-for-enter", action="store_true", help="Keep browser open after publish until Enter is pressed")

    return parser


def _auto_generate_title(keywords: str) -> str:
    """根据关键字自动生成标题"""
    if not keywords:
        return "智慧语录"
    # 简单处理：取第一个关键字 + 固定后缀
    first_keyword = keywords.split(",")[0].strip()
    return f"【{first_keyword}】智慧语录"


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "generate":
        request = GenerationRequest(
            book=args.book,
            topic=args.topic,
            tts_provider=args.tts_provider,
            voice=args.voice,
        )
        results = service.run_batch_generation(request, count=args.count)
        if not results:
            logger.error("Generate command failed with no outputs.")
            sys.exit(1)

        for result in results:
            for path in result.audio_paths:
                print(path)
        return

    if args.command == "quick":
        if not args.text and not args.prompt and not args.keywords:
            logger.error("quick command requires at least one of --prompt, --keywords, or --text.")
            sys.exit(1)

        request = QuickGenerationRequest(
            prompt=args.prompt,
            text=args.text,
            tts_provider=args.tts_provider,
            voice=args.voice,
            count=args.count,
            bgm=args.bgm,
            bgm_volume=args.bgm_volume,
            output_dir=args.output_dir,
            keep_temp=args.keep_temp,
            no_merge=args.no_merge,
            keywords=args.keywords or "",
            emotion_type=args.emotion_type or "",
            positive_energy_type=args.positive_energy_type or "",
            target_audience=args.target_audience or "",
        )
        outputs = service.run_quick_request(request)
        if not outputs:
            logger.error("Quick command failed with no outputs.")
            sys.exit(1)

        logger.info("Quick command completed.")
        for path in outputs:
            print(path)
        return

    if args.command == "presenter":
        if not args.text and not args.text_file and not args.keywords:
            logger.error("presenter command requires --keywords, --text, or --text-file.")
            sys.exit(1)

        input_mode = args.input_mode
        if (args.text or args.text_file) and not args.keywords and input_mode == "keywords":
            input_mode = "article_direct"

        presenter = PresenterPipeline()
        request = PresenterRequest(
            keywords=args.keywords or "",
            text=args.text or "",
            text_file=args.text_file or "",
            input_mode=input_mode,
            title=args.title or args.keywords or "",
            voice=args.voice or "",
            tts_provider=args.tts_provider,
            character=args.character,
            character_position=args.character_position,
            character_size=args.character_size,
            background=args.background or "",
            background_style=args.background_style,
            bgm=args.bgm or "",
            output_dir=args.output_dir,
            audio_path=args.audio or "",
            max_segments=args.max_segments,
            use_comfy_background=not args.no_comfy_background,
        )
        result = presenter.run(request)
        if not result.success:
            logger.error(f"数字人主讲视频生成失败: {result.message}")
            sys.exit(1)
        logger.info(f"数字人主讲视频生成成功: {result.video_path}")
        logger.info(f"工作目录: {result.work_dir}")
        print(result.video_path)
        return

    if args.command == "presenter-assets":
        if not args.text and not args.text_file and not args.keywords:
            logger.error("presenter-assets command requires --keywords, --text, or --text-file.")
            sys.exit(1)

        input_mode = args.input_mode
        if (args.text or args.text_file) and not args.keywords and input_mode == "keywords":
            input_mode = "article_direct"

        presenter = PresenterPipeline()
        request = PresenterRequest(
            keywords=args.keywords or "",
            text=args.text or "",
            text_file=args.text_file or "",
            input_mode=input_mode,
            title=args.title or args.keywords or "",
            voice=args.voice or "",
            tts_provider=args.tts_provider,
            character=args.character,
            background=args.background or "",
            background_style=args.background_style,
            audio_path=args.audio or "",
            max_segments=args.max_segments,
            use_comfy_background=not args.no_comfy_background,
        )
        result = presenter.run_assets_preview(request)
        if not result.success:
            logger.error(f"数字人文字和背景图预览生成失败: {result.message}")
            sys.exit(1)
        logger.info(f"数字人文字和背景图预览生成成功: {result.work_dir}")
        print(result.work_dir)
        return

    if args.command == "debug-background-plan":
        planner = ScenePlanner()
        prompt, plan = planner.plan(args.text)
        print(json.dumps({"prompt": prompt, "plan": plan}, ensure_ascii=False, indent=2))
        return

    if args.command == "fanqie-login":
        fanqie = FanqiePromotionService()
        try:
            state = fanqie.open_login_window(
                url=args.url or "",
                pause_seconds=args.pause_seconds,
                wait_for_enter=args.wait_for_enter,
            )
        except Exception as exc:
            logger.error(f"番茄登录窗口失败: {exc}")
            sys.exit(1)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return

    if args.command == "fanqie-promo-apply":
        fanqie = FanqiePromotionService()
        try:
            task = fanqie.apply_promotion(
                content_type=args.type,
                book_name=args.book_name or "",
                alias=args.alias or "",
                wait_for_login=not args.no_wait_login,
                headless=args.headless,
                auto_submit=not args.no_auto_submit,
                publish_type=args.publish_type,
                keep_open=args.keep_open,
                max_alias_attempts=args.max_alias_attempts,
            )
        except Exception as exc:
            logger.error(f"番茄推广申请失败: {exc}")
            sys.exit(1)
        print(json.dumps(asdict(task), ensure_ascii=False, indent=2))
        return

    if args.command == "fanqie-book-fetch":
        fanqie = FanqiePromotionService()
        try:
            result = fanqie.fetch_book(
                book_name=args.book_name,
                chapters=args.chapters,
                headless=args.headless,
            )
        except Exception as exc:
            logger.error(f"番茄小说内容获取失败: {exc}")
            sys.exit(1)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return

    if args.command == "fanqie-promo-video":
        fanqie = FanqiePromotionService()
        try:
            task = fanqie.generate_promo_video(
                task_file=args.task_file or "",
                book_name=args.book_name or "",
                chapters=args.chapters,
                alias=args.alias or "",
                output_dir=args.output_dir,
                max_segments=args.max_segments,
                no_comfy_background=args.no_comfy_background,
                assets_only=args.assets_only,
            )
        except Exception as exc:
            logger.error(f"番茄推广视频生成失败: {exc}")
            sys.exit(1)
        print(json.dumps(asdict(task), ensure_ascii=False, indent=2))
        return

    if args.command == "fanqie-promo-list":
        fanqie = FanqiePromotionService()
        try:
            result = fanqie.list_promotions(
                content_type=args.type,
                headless=args.headless,
                sync_to_tasks=not args.no_sync,
            )
        except Exception as exc:
            logger.error(f"番茄推广列表扫描失败: {exc}")
            sys.exit(1)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "fanqie-list-books":
        fanqie = FanqiePromotionService()
        books = fanqie.list_books()
        print(json.dumps(books, ensure_ascii=False, indent=2))
        return

    if args.command == "fanqie-batch-add":
        from src.platform_adapter.fanqie_batch import add_books
        result = add_books(
            book_names=args.book_names,
            chapters=args.chapters,
            interval_s=args.interval_s,
            note=args.note,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "fanqie-batch-list":
        from src.platform_adapter.fanqie_batch import list_books
        s = None if args.status == "all" else args.status
        books = list_books(status=s, limit=args.limit)
        print(json.dumps({"count": len(books), "books": books}, ensure_ascii=False, indent=2))
        return

    if args.command == "fanqie-batch-run":
        from src.platform_adapter.fanqie_batch import batch_fetch_sync, _summarize_report
        report = batch_fetch_sync(interval_s=args.interval_s, max_count=args.max_count)
        print(json.dumps(_summarize_report(report), ensure_ascii=False, indent=2))
        return

    if args.command == "fanqie-batch-enqueue":
        from src.platform_adapter.fanqie_batch import batch_enqueue_pending
        result = batch_enqueue_pending()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "fanqie-batch-seed":
        from src.platform_adapter.fanqie_batch import seed_from_yaml
        result = seed_from_yaml()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "import-knowledge":
        ok = service.import_knowledge_base(KnowledgeImportRequest(books_dir=args.books_dir))
        if not ok:
            sys.exit(1)
        return

    if args.command == "douyin-login":
        adapter = DouyinAdapter()
        try:
            state = adapter.open_login_window(
                url=args.url,
                pause_seconds=args.pause_seconds,
                wait_for_enter=args.wait_for_enter,
            )
        except Exception as exc:
            logger.error(str(exc))
            sys.exit(1)

        logger.info("浏览器会话已结束。")
        logger.info(f"登录态文件: {state.storage_state_path}")
        logger.info(f"用户数据目录: {state.user_data_dir}")
        print(state.storage_state_path)
        return

    if args.command == "douyin-warmup-login":
        warmup_service = DouyinWarmupService()
        try:
            account = warmup_service.open_login_window(
                account_id=args.account_id,
                display_name=args.display_name or "",
                url=args.url,
                pause_seconds=args.pause_seconds,
                wait_for_enter=args.wait_for_enter,
            )
        except Exception as exc:
            logger.error(str(exc))
            sys.exit(1)

        logger.info(f"养号账号登录窗口已结束: {account.account_id}")
        logger.info(f"登录状态: {account.login_status}")
        logger.info(f"浏览器用户目录: {account.browser_profile_dir}")
        print(json.dumps(asdict(account), ensure_ascii=False, indent=2))
        return

    if args.command == "douyin-warmup":
        warmup_service = DouyinWarmupService()
        try:
            result = warmup_service.run_warmup(
                account_id=args.account_id,
                mode=args.mode,
                keyword=args.keyword or "",
                min_watch=args.min_watch,
                max_watch=args.max_watch,
                max_videos=args.max_videos,
                duration_minutes=args.duration_minutes,
                comment_probability=args.comment_probability,
                headless=args.headless,
                keep_open_on_blocked=not args.close_on_blocked,
                start_url=args.url or "",
                use_search=args.use_search,
                keep_open_after_run=args.keep_open,
                no_comment_max_watch=args.no_comment_max_watch,
                duration_ratio_min=args.duration_ratio_min,
                duration_ratio_max=args.duration_ratio_max,
                like_probability=args.like_probability,
                max_likes=args.max_likes,
                min_comment_opens=args.min_comment_opens,
                comment_scrolls=args.comment_scrolls,
                comment_like_probability=args.comment_like_probability,
                max_comment_likes=args.max_comment_likes,
            )
        except Exception as exc:
            logger.error(f"养号任务失败: {exc}")
            sys.exit(1)

        logger.info(f"养号任务完成: {result.status}, videos_seen={result.videos_seen}")
        logger.info(f"日志: {result.log_path}")
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        if result.status not in {"completed"}:
            sys.exit(1)
        return

    if args.command == "douyin-warmup-report":
        warmup_service = DouyinWarmupService()
        try:
            rows = warmup_service.report(account_id=args.account_id, days=args.days)
        except Exception as exc:
            logger.error(str(exc))
            sys.exit(1)
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    if args.command == "douyin-warmup-account":
        warmup_service = DouyinWarmupService()
        try:
            if args.action == "list":
                accounts = warmup_service.list_accounts()
                print(json.dumps([asdict(item) for item in accounts], ensure_ascii=False, indent=2))
                return

            if not args.account_id:
                logger.error("show/set 需要指定 --account-id")
                sys.exit(1)

            if args.action == "show":
                account = warmup_service.get_account(args.account_id)
                print(json.dumps(asdict(account), ensure_ascii=False, indent=2))
                return

            keywords = None
            if args.keywords:
                keywords = [item.strip() for item in args.keywords.split(",") if item.strip()]
            account = warmup_service.update_account(
                account_id=args.account_id,
                display_name=args.display_name or "",
                douyin_uid=args.douyin_uid or "",
                login_name=args.login_name or "",
                phone_hint=args.phone_hint or "",
                purpose=args.purpose or "",
                status=args.status or "",
                notes=args.notes or "",
                keywords=keywords,
            )
            print(json.dumps(asdict(account), ensure_ascii=False, indent=2))
            return
        except Exception as exc:
            logger.error(str(exc))
            sys.exit(1)

    if args.command == "douyin-upload-page":
        adapter = DouyinAdapter()
        try:
            state = adapter.open_upload_page(
                url=args.url,
                pause_seconds=args.pause_seconds,
                wait_for_enter=args.wait_for_enter,
            )
        except Exception as exc:
            logger.error(str(exc))
            sys.exit(1)

        logger.info("上传页浏览器会话已结束。")
        logger.info(f"登录态文件: {state.storage_state_path}")
        logger.info(f"用户数据目录: {state.user_data_dir}")
        print(state.storage_state_path)
        return

    if args.command == "douyin-publish":
        adapter = DouyinAdapter()
        hashtags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
        request = PublishRequest(
            video_path=args.video,
            title=args.title,
            description=args.desc,
            hashtags=hashtags,
            cover_path=args.cover,
        )
        result = adapter.publish_video(request, interactive=args.interactive)
        if result.success:
            logger.info(f"发布成功: {result.message}")
            logger.info(f"视频ID: {result.post_id}")
            logger.info(f"链接: {result.publish_url}")
            print(result.publish_url or result.post_id)
            if args.wait_for_enter:
                logger.info("浏览器保持打开，按回车键关闭...")
                try:
                    input()
                except (EOFError, OSError):
                    pass
        else:
            logger.error(f"发布失败: {result.message}")
            sys.exit(1)
        return

    if args.command == "douyin-sync":
        if args.headless:
            session_config = build_default_browser_session_config()
            session_config.headless = True
            adapter = DouyinAdapter(session=BrowserSession(session_config))
        else:
            adapter = DouyinAdapter()
        result = adapter.sync_videos(page_limit=args.page_limit, interactive=args.interactive)
        if result.videos:
            logger.info(f"同步成功: {result.message}")
            for v in result.videos:
                logger.info(f"  [{v.status.value}] {v.title} (id: {v.video_id})")
            # 输出JSON列表供其他程序使用
            print(json.dumps([
                {"video_id": v.video_id, "title": v.title, "status": v.status.value, "publish_time": v.publish_time}
                for v in result.videos
            ], ensure_ascii=False, indent=2))
        else:
            logger.warning("未同步到任何视频，请确认是否已登录")
        if args.wait_for_enter:
            logger.info("浏览器保持打开，按回车键关闭...")
            try:
                input()
            except (EOFError, OSError):
                pass
        return

    if args.command == "douyin-fetch-comments":
        from src.services.video_service import get_videos
        from src.platform_adapter.models import CommentQuery

        if args.headless:
            session_config = build_default_browser_session_config()
            session_config.headless = True
            adapter = DouyinAdapter(session=BrowserSession(session_config))
        else:
            adapter = DouyinAdapter()

        target_ids = []
        if args.video_id:
            target_ids = [args.video_id]
        elif args.all:
            videos = get_videos(status="published", limit=100)
            target_ids = [v["video_id"] for v in videos if v.get("video_id")]
        else:
            logger.error("请指定 --video-id 或 --all")
            sys.exit(1)

        total = 0
        for vid in target_ids:
            logger.info(f"抓取评论: {vid}")
            result = adapter.fetch_comments(CommentQuery(post_id=vid))
            count = len(result.comments)
            total += count
            logger.info(f"  → {count} 条评论已保存")
            if result.message:
                logger.info(f"  {result.message}")

        logger.info(f"全部完成，共抓取 {total} 条评论")
        return

    if args.command == "douyin-reply-comment":
        if args.headless:
            session_config = build_default_browser_session_config()
            session_config.headless = True
            adapter = DouyinAdapter(session=BrowserSession(session_config))
        else:
            adapter = DouyinAdapter()

        success = adapter.reply_to_comment(args.video_id, args.comment_id, args.content)
        if success:
            logger.info(f"回复成功！comment_id={args.comment_id}")
        else:
            logger.error("回复失败")
            sys.exit(1)
        return

    if args.command == "auto-reply":
        from src.platform_adapter.auto_reply_service import AutoReplyService
        from src.services.video_service import get_videos

        if args.headless:
            session_config = build_default_browser_session_config()
            session_config.headless = True
            session = BrowserSession(session_config)
        else:
            session = None

        reply_service = AutoReplyService(session=session)

        target_ids = []
        if args.video_id:
            target_ids = [args.video_id]
        elif args.all:
            videos = get_videos(status="published", limit=100)
            target_ids = [v["video_id"] for v in videos if v.get("video_id")]
        else:
            logger.error("请指定 --video-id 或 --all")
            sys.exit(1)

        total_replied = 0
        total_skipped = 0
        total_failed = 0
        for vid in target_ids:
            logger.info(f"处理视频评论: {vid}")
            result = reply_service.process_video(vid)
            total_replied += result.replied
            total_skipped += result.skipped
            total_failed += result.failed
            logger.info(f"  → 回复={result.replied}, 跳过={result.skipped}, 失败={result.failed}, 总评论={result.total_comments}")

        logger.info(f"全部完成: 回复={total_replied}, 跳过={total_skipped}, 失败={total_failed}")
        if total_failed > 0:
            sys.exit(1)
        return

    if args.command == "auto-publish":
        auto_service = AutoPublishService()
        request = AutoPublishRequest(
            keywords=args.keywords,
            title=args.title or _auto_generate_title(args.keywords),
            description=args.desc,
            hashtags=args.tags,
            template_video=args.template or "",
            bgm=args.bgm or "",
            bgm_volume=args.bgm_volume,
            output_dir=args.output_dir,
            interactive=args.interactive,
        )
        result = auto_service.publish(request)
        if result.success:
            logger.info(f"自动发布成功！")
            logger.info(f"  视频路径: {result.video_path}")
            logger.info(f"  抖音ID: {result.post_id}")
            logger.info(f"  链接: {result.publish_url}")
            print(result.publish_url or result.post_id or result.video_path)
        else:
            logger.error(f"自动发布失败: {result.message}")
            sys.exit(1)
        if args.wait_for_enter:
            logger.info("浏览器保持打开，按回车键关闭...")
            try:
                input()
            except (EOFError, OSError):
                pass
        return

    parser.print_help()


if __name__ == "__main__":
    main()
