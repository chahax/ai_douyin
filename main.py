import argparse
import sys

from src.platform_adapter import DouyinAdapter
from src.platform_adapter.browser_session import BrowserSession, build_default_browser_session_config
from src.platform_adapter.models import PublishRequest
from src.services import (
    AutoPublishRequest,
    AutoPublishService,
    GenerationRequest,
    GenerationService,
    KnowledgeImportRequest,
    QuickGenerationRequest,
)
from src.content_factory.presenter import DEFAULT_SONIC_FOX_CHARACTER, PresenterRequest
from src.content_factory.presenter_pipeline import PresenterPipeline
from src.shared.config import settings
from src.shared.logger import logger


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
    presenter_parser.add_argument("--max-segments", type=int, default=16, help="Maximum number of presenter segments")
    presenter_parser.add_argument("--no-comfy-background", action="store_true", help="Use local fallback anime backgrounds without ComfyUI")

    presenter_assets_parser = subparsers.add_parser("presenter-assets", help="Generate presenter script and background images only")
    presenter_assets_parser.add_argument("--keywords", type=str, default="", help="Keywords/topic for script generation")
    presenter_assets_parser.add_argument("--text", type=str, default="", help="Direct presenter script text")
    presenter_assets_parser.add_argument("--title", type=str, default="", help="On-screen title")
    presenter_assets_parser.add_argument("--character", type=str, default=DEFAULT_SONIC_FOX_CHARACTER, help="Character id or asset path. Default: Sonic fox video layer")
    presenter_assets_parser.add_argument("--background", type=str, default="", help="Background image/video path")
    presenter_assets_parser.add_argument("--background-style", type=str, default="anime", choices=["anime", "existing", "gradient"], help="Default background style when --background is omitted")
    presenter_assets_parser.add_argument("--tts-provider", type=str, default="edge", choices=["edge", "gpt_sovits"], help="TTS provider hint for script generation")
    presenter_assets_parser.add_argument("--voice", type=str, default="", help="Voice ID or reference audio path")
    presenter_assets_parser.add_argument("--max-segments", type=int, default=8, help="Maximum number of presenter segments")
    presenter_assets_parser.add_argument("--comfy-background", action="store_true", help="Use ComfyUI to generate preview backgrounds. Default uses fast local fallback images.")

    import_parser = subparsers.add_parser("import-knowledge", help="Import books into the vector knowledge base")
    import_parser.add_argument("--books-dir", type=str, default=service.default_books_dir, help="Books directory to import")

    login_parser = subparsers.add_parser("douyin-login", help="Open Douyin in a visible browser and keep it paused")
    login_parser.add_argument("--url", type=str, default=settings.DOUYIN_HOME_URL, help="Target URL to open")
    login_parser.add_argument("--pause-seconds", type=int, default=600, help="How long to keep the browser open")
    login_parser.add_argument("--wait-for-enter", action="store_true", help="Keep browser open until Enter is pressed")

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
        if not args.text and not args.keywords:
            logger.error("presenter command requires --text or --keywords.")
            sys.exit(1)

        presenter = PresenterPipeline()
        request = PresenterRequest(
            keywords=args.keywords or "",
            text=args.text or "",
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
        if not args.text and not args.keywords:
            logger.error("presenter-assets command requires --text or --keywords.")
            sys.exit(1)

        presenter = PresenterPipeline()
        request = PresenterRequest(
            keywords=args.keywords or "",
            text=args.text or "",
            title=args.title or args.keywords or "",
            voice=args.voice or "",
            tts_provider=args.tts_provider,
            character=args.character,
            background=args.background or "",
            background_style=args.background_style,
            max_segments=args.max_segments,
            use_comfy_background=args.comfy_background,
        )
        result = presenter.run_assets_preview(request)
        if not result.success:
            logger.error(f"数字人文字和背景图预览生成失败: {result.message}")
            sys.exit(1)
        logger.info(f"数字人文字和背景图预览生成成功: {result.work_dir}")
        print(result.work_dir)
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
            import json
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

        service = AutoReplyService(session=session)

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
            result = service.process_video(vid)
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
