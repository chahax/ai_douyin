"""
sync_workflow.py — 抖音视频同步工作流

通过 API 同步已发布视频列表：
  1. 打开创作者后台获取 cookies
  2. 调用 /janus/douyin/creator/pc/work_list API
  3. 解析 aweme_list，返回视频列表
"""

import urllib.parse
from datetime import datetime
from typing import List, Optional, Tuple

from playwright.sync_api import Page

from src.platform_adapter.browser_session import BrowserSession
from src.platform_adapter.models import VideoItem, VideoStats, VideoStatus
from src.shared.logger import logger


MANAGE_URL = "https://creator.douyin.com/creator-micro/content/manage"
WORK_LIST_API = "https://creator.douyin.com/janus/douyin/creator/pc/work_list"


class SyncWorkflow:
    def __init__(self, session: BrowserSession):
        self.session = session

    def sync_videos(self, page_limit: int = 5, interactive: bool = False) -> Tuple[List[VideoItem], bool]:
        """
        通过 API 同步所有已发布视频。

        Args:
            page_limit: 最多翻页次数（每页 20 条）
            interactive: 启用交互模式

        Returns:
            (视频列表, API是否成功) 元组。API成功但返回0个视频表示平台上已无视频。
        """
        self.session.start()

        if not self._ensure_browser_authenticated():
            logger.error("未检测到登录态，同步前请先完成浏览器登录。")
            return [], False

        try:
            return self._do_sync(page_limit=page_limit, interactive=interactive)
        except Exception as exc:
            logger.exception("同步流程异常")
            return [], False

    def _ensure_browser_authenticated(self) -> bool:
        """确保浏览器已认证（user_data_dir 存在即认为已登录）"""
        user_data = self.session.config.user_data_dir
        from pathlib import Path
        return Path(user_data).exists()

    # ─── 核心同步流程 ────────────────────────────────────────

    def _do_sync(self, page_limit: int = 5, interactive: bool = False) -> Tuple[List[VideoItem], bool]:
        """
        Returns:
            (视频列表, API调用是否成功)
        """
        def wait_confirm(step_name: str):
            if interactive:
                logger.info(f"=== 等待确认: {step_name} ===")
                input(f"[按回车继续: {step_name}]")

        logger.info("开始通过 API 同步视频列表")
        wait_confirm("准备打开浏览器获取认证")

        # 用无头模式打开页面获取 cookies
        page = self._open_auth_page()
        logger.info("[OK] 已打开创作者后台")
        wait_confirm("准备调用视频列表 API")

        all_videos: List[VideoItem] = []
        max_cursor = 0

        for page_num in range(1, page_limit + 1):
            logger.info(f"--- 第 {page_num} 页，max_cursor={max_cursor} ---")
            videos, has_more, new_cursor = self._fetch_video_page(page, max_cursor)
            logger.info(f"  本页获取到 {len(videos)} 个视频，has_more={has_more}, new_cursor={new_cursor}")
            all_videos.extend(videos)

            if not has_more or new_cursor == max_cursor:
                logger.info("已到达最后一页")
                break

            max_cursor = new_cursor

            if interactive:
                resp = input(f"  继续抓取下一页？[y/n]: ").strip().lower()
                if resp != 'y':
                    break

        logger.info(f"[OK] 共同步到 {len(all_videos)} 个视频")
        return all_videos, True

    def _open_auth_page(self) -> Page:
        """打开创作者后台获取认证（不显示窗口）"""
        return self.session.open_page(MANAGE_URL)

    def _fetch_video_page(
        self, page: Page, max_cursor: int = 0
    ) -> tuple[List[VideoItem], bool, int]:
        """
        调用视频列表 API，返回 (视频列表, 是否有更多, 新的 max_cursor)
        """
        params = {
            "status": 0,
            "count": 20,
            "max_cursor": max_cursor,
            "scene": "star_atlas",
            "device_platform": "android",
            "aid": 1128,
        }
        url = WORK_LIST_API + "?" + urllib.parse.urlencode(params)

        response = page.request.get(url)
        if response.status != 200:
            logger.warning(f"API 返回状态码 {response.status}")
            return [], False, max_cursor

        try:
            data = response.json()
        except Exception as exc:
            logger.warning(f"API 响应解析失败: {exc}")
            return [], False, max_cursor

        aweme_list = data.get("aweme_list") or []
        has_more = bool(data.get("has_more"))
        new_cursor = data.get("max_cursor") or max_cursor

        videos = []
        for raw in aweme_list:
            video = self._parse_aweme(raw)
            if video:
                videos.append(video)

        return videos, has_more, new_cursor

    def _parse_aweme(self, raw: dict) -> Optional[VideoItem]:
        """解析单个 aweme 记录为 VideoItem"""
        try:
            video_id = str(raw.get("aweme_id") or "")
            if not video_id:
                return None

            # 标题：优先 caption（抖音的描述字段），其次 item_title
            title = raw.get("caption") or raw.get("item_title") or ""

            # 状态
            status = self._map_status(raw)

            # 发布时间
            create_time = raw.get("create_time")
            publish_time = ""
            if create_time:
                try:
                    dt = datetime.fromtimestamp(int(create_time))
                    publish_time = dt.strftime("%Y年%m月%d日 %H:%M")
                except Exception:
                    publish_time = str(create_time)

            # 统计数据
            stats_raw = raw.get("statistics") or {}
            stats = VideoStats(
                play_count=stats_raw.get("play_count", 0) or 0,
                like_count=stats_raw.get("like_count", 0) or 0,
                comment_count=stats_raw.get("comment_count", 0) or 0,
                share_count=stats_raw.get("share_count", 0) or 0,
                collect_count=stats_raw.get("collect_count", 0) or 0,
            )

            # 封面 URL
            cover = raw.get("Cover") or {}
            cover_url = ""
            url_list = cover.get("url_list") or []
            if url_list:
                cover_url = url_list[0]

            logger.info(f"  视频: id={video_id}, title={title[:30] if title else 'N/A'}, status={status.value}")

            return VideoItem(
                video_id=video_id,
                title=title,
                description="",
                status=status,
                publish_time=publish_time or None,
                cover_url=cover_url or None,
                stats=stats,
            )
        except Exception as exc:
            logger.warning(f"解析 aweme 失败: {exc}")
            return None

    def _map_status(self, raw: dict) -> VideoStatus:
        """根据 aweme 记录中的 status 字段映射 VideoStatus"""
        status_dict = raw.get("status") or {}
        status_value = raw.get("status_value") or 0

        # 优先根据 in_reviewing 判断（最准确）
        if status_dict.get("in_reviewing"):
            return VideoStatus.PENDING

        # 已发布（审核通过，不在审核中）
        if not status_dict.get("in_reviewing") and not status_dict.get("is_delete"):
            if status_dict.get("is_prohibited"):
                return VideoStatus.FAILED
            return VideoStatus.PUBLISHED

        # 兜底：用 status_value 简单判断
        # 143 = 已发布（抖音内部状态码）
        if status_value == 143:
            return VideoStatus.PUBLISHED
        elif status_value in (0, 4):
            return VideoStatus.PENDING
        elif status_value in (2, 3, 5):
            return VideoStatus.FAILED

        return VideoStatus.UNKNOWN
