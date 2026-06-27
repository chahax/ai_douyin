"""
comment_workflow.py — 抖音评论抓取工作流

通过浏览器自动化抓取视频下的评论列表：
  1. 打开视频页
  2. 点击评论图标展开评论区
  3. 滚动加载评论
  4. 解析每条评论内容
"""

import time
import re
from typing import Optional

from playwright.sync_api import Page

from src.platform_adapter.browser_session import BrowserSession
from src.platform_adapter.models import CommentQuery, CommentRecord, CommentSyncResult
from src.shared.logger import logger


# 视频页 URL 模板
VIDEO_URL_TEMPLATE = "https://www.douyin.com/video/{video_id}"


class CommentWorkflow:
    def __init__(self, session: BrowserSession):
        self.session = session

    def fetch_comments(self, query: CommentQuery) -> CommentSyncResult:
        validation_error = self._validate_query(query)
        if validation_error:
            return CommentSyncResult(
                success=False,
                status="invalid_request",
                message=validation_error,
            )

        self.session.start()

        if not self.session.is_authenticated():
            return CommentSyncResult(
                success=False,
                status="login_required",
                message="未检测到登录态，拉取评论前请先完成浏览器登录。",
            )

        try:
            return self._do_fetch(query)
        except Exception as exc:
            logger.exception("评论抓取流程异常")
            return CommentSyncResult(
                success=False,
                status="error",
                message=f"异常: {exc}",
            )

    # ─── 验证 ────────────────────────────────────────────────

    def _validate_query(self, query: CommentQuery) -> str:
        if not query.post_id.strip() and not query.post_url.strip():
            return "post_id 和 post_url 至少需要提供一个"
        if query.page < 1:
            return "page 必须大于等于 1"
        if query.page_size < 1:
            return "page_size 必须大于等于 1"
        return ""

    # ─── 核心抓取流程 ───────────────────────────────────────

    def _do_fetch(self, query: CommentQuery) -> CommentSyncResult:
        """
        打开视频页 → 点击评论图标 → 滚动加载 → 解析评论
        """
        # 确定视频 URL
        if query.post_url:
            video_url = query.post_url
        else:
            video_url = VIDEO_URL_TEMPLATE.format(video_id=query.post_id)

        logger.info(f"打开视频页: {video_url}")

        # 1. 打开视频页
        page = self._open_video_page(video_url)

        # 2. 点击评论图标（包 try/except 防止失败导致浏览器退出）
        try:
            self._click_comment_icon(page)
            logger.info("[OK] 评论图标已点击")
        except Exception as exc:
            logger.warning(f"评论图标点击异常: {exc}")

        # 3. 等待评论列表出现
        self._wait_for_comment_list(page)
        logger.info("[OK] 评论列表已加载")

        # 4. 滚动加载更多评论
        self._scroll_to_load_comments(page, target=query.page_size)
        logger.info("[OK] 评论已滚动加载")

        # 5. 解析所有评论
        comments = self._parse_comments(page, video_url)

        logger.info(f"[OK] 共抓取到 {len(comments)} 条评论")

        return CommentSyncResult(
            success=True,
            status="fetched",
            comments=comments,
            message=f"抓取完成，共 {len(comments)} 条评论",
        )

    # ─── 分步实现 ────────────────────────────────────────────

    def _open_video_page(self, video_url: str) -> Page:
        """打开视频页"""
        page = self.session.open_page(video_url)
        # 等待 DOM 加载完成即继续，不等 networkidle（抖音是重前端 SPA，永远不会完全静止）
        page.wait_for_load_state("domcontentloaded", timeout=30000)
        # 额外等待让视频和评论区渲染（Douyin 是重 JS 应用，需要更长等待）
        page.wait_for_timeout(5000)
        return page

    def _click_comment_icon(self, page: Page) -> None:
        """
        点击评论图标展开评论区。
        抖音视频页的评论图标在播放器controls里，播放时controls自动隐藏。
        策略：hover 唤出controls，再点击评论按钮。
        """
        # 正确的视频元素（右侧播放器里的视频）
        video_sel = "#douyin-right-container video"
        if page.locator(video_sel).count() > 0:
            try:
                page.locator(video_sel).hover(force=True)
            except Exception:
                pass
            page.wait_for_timeout(800)

        selectors = [
            "[data-e2e='feed-comment-icon']",
            ".tvnVKTp7",
        ]
        for sel in selectors:
            count = page.locator(sel).count()
            if count > 0:
                locator = page.locator(sel).first
                # hover 到元素本身，唤出controls
                try:
                    locator.hover(force=True, timeout=5000)
                except Exception:
                    pass
                page.wait_for_timeout(500)
                # force=True 直接点击，绕过 visibility/stable 检查
                try:
                    locator.click(force=True, timeout=5000)
                except Exception:
                    pass
                page.wait_for_timeout(1500)
                return
        # 备选：滚动到页面中部评论区域
        page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.5)")
        page.wait_for_timeout(1000)

    def _wait_for_comment_list(self, page: Page, timeout: int = 15000) -> None:
        """等待评论区容器出现"""
        start = time.time()
        while time.time() - start < timeout:
            if page.locator("[data-e2e='comment-list']").count() > 0:
                return
            page.wait_for_timeout(500)
        raise RuntimeError("评论区加载超时")

    def _scroll_to_load_comments(self, page: Page, target: int = 20) -> None:
        """
        滚动评论区以加载更多评论，直到达到 target 数量或无法再加载。
        """
        last_count = 0
        no_new_count = 0

        while no_new_count < 3:
            # 滚动到评论区底部
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(800)

            current = page.locator("[data-e2e='comment-item']").count()
            logger.info(f"  当前评论数: {current}")

            if current >= target:
                logger.info(f"  已达到目标数量 {target}，停止滚动")
                break

            if current == last_count:
                no_new_count += 1
            else:
                no_new_count = 0
                last_count = current

    def _parse_comments(self, page: Page, video_url: str) -> list[CommentRecord]:
        """
        解析页面上的所有评论。
        返回 CommentRecord 列表。
        """
        items = page.locator("[data-e2e='comment-item']").all()
        comments = []

        for item in items:
            try:
                record = self._parse_single_comment(item, video_url)
                if record:
                    comments.append(record)
            except Exception as exc:
                logger.warning(f"  解析单条评论异常: {exc}")
                continue

        return comments

    def _parse_single_comment(self, item, video_url: str) -> Optional[CommentRecord]:
        """
        解析单条评论，返回 CommentRecord。
        """
        # 评论 ID：从 tooltip ID 中提取数字
        comment_id = ""
        tooltip_el = item.locator("[id^='tooltip_']")
        if tooltip_el.count() > 0:
            tooltip_id = tooltip_el.first.get_attribute("id") or ""
            m = re.search(r'tooltip_(\d+)', tooltip_id)
            if m:
                comment_id = m.group(1)

        # 作者昵称
        author_name = ""
        author_el = item.locator(".mQdPVwNH")
        if author_el.count() > 0:
            # 取第一个 span 的文本
            author_name = self._get_text_from_composed(author_el.first) or ""

        # 是否作者
        is_author = item.locator(".comment-item-tag").count() > 0

        # 评论内容
        content = ""
        content_el = item.locator(".WFJiGxr7")
        if content_el.count() > 0:
            content = self._get_text_from_composed(content_el.first) or ""

        if not content:
            return None

        # 发布时间
        time_el = item.locator(".fJhvAqos")
        created_at = ""
        if time_el.count() > 0:
            created_at = time_el.first.inner_text().strip()

        # 点赞数
        like_count = 0
        like_el = item.locator(".xZhLomAs")
        if like_el.count() > 0:
            text = like_el.first.inner_text().strip()
            m = re.search(r'(\d+)', text)
            if m:
                like_count = int(m.group(1))

        # 回复数
        reply_count = 0
        reply_el = item.locator(".noSPpzeu")
        if reply_el.count() > 0:
            text = reply_el.first.inner_text().strip()
            m = re.search(r'(\d+)', text)
            if m:
                reply_count = int(m.group(1))

        logger.info(f"  评论: id={comment_id}, author={author_name}, content={content[:30]}, is_author={is_author}")

        return CommentRecord(
            comment_id=comment_id,
            author_name=author_name,
            content=content,
            created_at=created_at,
        )

    def _get_text_from_composed(self, locator) -> str:
        """
        获取元素的合成文本（兼容 shadow DOM / 嵌套 iframe）。
        Playwright inner_text() 不够时用 evaluate JavaScript 获取。
        """
        try:
            return locator.inner_text().strip()
        except Exception:
            pass
        try:
            return locator.evaluate("el => el.innerText").strip()
        except Exception:
            return ""

    # ─── 回复评论 ───────────────────────────────────────────

    def reply_to_comment(
        self,
        post_id: str,
        comment_id: str,
        content: str,
    ) -> bool:
        """
        对指定评论发送回复。

        Args:
            post_id: 视频 ID
            comment_id: 要回复的评论 ID
            content: 回复内容

        Returns:
            True 表示回复成功
        """
        video_url = VIDEO_URL_TEMPLATE.format(video_id=post_id)
        logger.info(f"打开视频页: {video_url}")

        # 1. 打开视频页
        page = self._open_video_page(video_url)

        # 2. 点击评论图标展开评论区
        self._click_comment_icon(page)
        logger.info("[OK] 评论区已展开")

        # 3. 等待评论列表出现
        self._wait_for_comment_list(page)

        # 4. 滚动加载确保目标评论可见
        self._scroll_to_load_comments(page, target=50)

        # 5. 定位到目标评论并点击回复按钮
        if not self._click_reply_button(page, comment_id):
            logger.warning(f"未找到评论 {comment_id} 的回复按钮")
            return False
        logger.info("[OK] 回复输入框已打开")

        # 6. 填写回复内容
        self._fill_reply_content(page, content)
        logger.info(f"[OK] 回复内容已填写: {content[:30]}")

        # 7. 点击发送
        self._submit_reply(page)
        logger.info("[OK] 回复已发送")

        return True

    def _click_reply_button(self, page: Page, comment_id: str) -> bool:
        """
        找到目标评论的回复按钮并点击。
        回复按钮文字为"回复"。
        """
        # 遍历所有评论项，找目标 comment_id 的回复按钮
        items = page.locator("[data-e2e='comment-item']").all()
        for item in items:
            # 检查这个评论的 tooltip ID 是否匹配
            tooltip_el = item.locator("[id^='tooltip_']")
            if tooltip_el.count() == 0:
                continue
            tooltip_id = tooltip_el.first.get_attribute("id") or ""
            if comment_id not in tooltip_id:
                continue

            # 找到了目标评论，点击它的回复按钮
            reply_btn = item.locator(".ANYunOWC")
            if reply_btn.count() > 0:
                reply_btn.first.scroll_into_view_if_needed()
                page.wait_for_timeout(300)
                try:
                    reply_btn.first.click(force=True, timeout=5000)
                except Exception:
                    page.evaluate("arguments[0].click()", reply_btn.first)
                return True

        # 备选：直接用文本"回复"定位
        all_reply_btns = page.locator("text=回复").all()
        for btn in all_reply_btns:
            try:
                btn.scroll_into_view_if_needed()
                btn.click(force=True, timeout=3000)
                page.wait_for_timeout(500)
                return True
            except Exception:
                continue

        return False

    def _fill_reply_content(self, page: Page, content: str) -> None:
        """
        在回复输入框中填写内容。
        回复输入框是一个 contenteditable 的 div。
        """
        # 等待输入框出现
        page.wait_for_timeout(500)

        selectors = [
            "[data-e2e='comment-list'] [contenteditable='true']",
            ".comment-input-container [contenteditable='true']",
            ".DraftEditor-editorContainer [contenteditable='true']",
            "div[aria-label='评论']",
        ]
        for sel in selectors:
            if page.locator(sel).count() > 0:
                editor = page.locator(sel).first
                editor.scroll_into_view_if_needed()
                page.wait_for_timeout(200)
                try:
                    editor.click(force=True, timeout=3000)
                except Exception:
                    pass
                page.wait_for_timeout(200)
                # 填入内容
                try:
                    editor.fill(content)
                except Exception:
                    # contenteditable 不支持 fill，用 type
                    editor.type(content)
                page.wait_for_timeout(200)
                return

        logger.warning("未找到回复输入框")

    def _submit_reply(self, page: Page) -> None:
        """
        点击发送按钮提交回复。
        发送按钮在输入框右侧，包含发送图标。
        """
        # 发送按钮：查找包含"发送"文字或发送图标的按钮
        submit_selectors = [
            "button:has-text('发送')",
            "[data-e2e='comment-submit']",
            ".comment-input-right-ct button",
            ".commentInput-right-ct button",
        ]
        for sel in submit_selectors:
            if page.locator(sel).count() > 0:
                btn = page.locator(sel).first
                btn.scroll_into_view_if_needed()
                page.wait_for_timeout(200)
                try:
                    btn.click(force=True, timeout=5000)
                except Exception:
                    page.evaluate("arguments[0].click()", btn)
                page.wait_for_timeout(1000)
                return

        logger.warning("未找到发送按钮，尝试直接按回车提交")
        page.keyboard.press("Enter")
        page.wait_for_timeout(1000)
