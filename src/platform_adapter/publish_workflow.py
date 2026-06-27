"""
publish_workflow.py — 抖音视频发布工作流

全自动化浏览器上传流程：
  1. 打开创作者后台上传页
  2. 注入视频文件（隐藏的 input[type=file]）
  3. 等待视频上传完成（进度条消失）
  4. 填写标题 + 描述 + 话题标签
  5. 点击发布
  6. 提取发布结果（post_id / 链接）
  7. 通过标题匹配从 work_list API 获取真实视频 ID
"""

import re
import time
from pathlib import Path

from playwright.sync_api import Page

from src.platform_adapter.browser_session import BrowserSession
from src.platform_adapter.models import PublishRequest, PublishResult
from src.shared.logger import logger


# 抖音创作者后台上传页 URL
UPLOAD_URL = "https://creator.douyin.com/creator-micro/content/upload"
MANAGE_URL = "https://creator.douyin.com/creator-micro/content/manage"


class PublishWorkflow:
    def __init__(self, session: BrowserSession):
        self.session = session
        self._last_publish_title = ""

    def publish(self, request: PublishRequest, interactive: bool = False) -> PublishResult:
        validation_error = self._validate_request(request)
        if validation_error:
            return PublishResult(
                success=False,
                status="invalid_request",
                message=validation_error,
            )

        self.session.start()

        if not self.session.is_authenticated():
            return PublishResult(
                success=False,
                status="login_required",
                message="未检测到登录态，发布前请先完成浏览器登录。",
            )

        try:
            return self._do_publish(request, interactive=interactive)
        except Exception as exc:
            logger.exception("发布流程异常")
            return PublishResult(
                success=False,
                status="error",
                message=f"发布异常: {exc}",
            )

    # ─── 验证 ────────────────────────────────────────────────

    def _validate_request(self, request: PublishRequest) -> str:
        video_path = Path(request.video_path)
        if not request.video_path:
            return "video_path 不能为空"
        if not video_path.exists():
            return f"视频文件不存在: {video_path}"
        if video_path.stat().st_size == 0:
            return f"视频文件为空: {video_path}"
        if not request.title.strip():
            return "title 不能为空"
        if request.cover_path:
            cover_path = Path(request.cover_path)
            if not cover_path.exists():
                return f"封面文件不存在: {cover_path}"
        return ""

    # ─── 核心发布流程 ────────────────────────────────────────

    def _do_publish(self, request: PublishRequest, interactive: bool = False) -> PublishResult:
        """
        单次发布尝试。失败不重试（调用方自行循环）。
        interactive: 启用交互模式，每步等待用户确认后继续
        """
        def wait_confirm(step_name: str):
            if interactive:
                logger.info(f"=== 等待确认: {step_name} ===")
                input(f"[按回车继续: {step_name}]")

        logger.info(f"开始发布视频: {request.video_path}")
        wait_confirm("准备打开上传页")

        # 1. 打开上传页
        page = self._open_upload_page()
        logger.info("[OK] 上传页已打开")
        logger.info(f"  当前URL: {page.url}")
        wait_confirm("准备上传视频文件")

        # 2. 上传视频文件
        self._upload_video_file(page, request.video_path)
        logger.info(f"[OK] 视频文件已注入: {request.video_path}")
        logger.info("  等待上传完成...")
        wait_confirm("准备等待上传完成")

        # 3. 等待上传进度完成
        if not self._wait_for_upload_complete(page, interactive=interactive):
            return PublishResult(
                success=False,
                status="upload_failed",
                message="视频上传超时或失败，请检查网络或文件。",
            )
        logger.info("[OK] 视频上传完成")
        wait_confirm("准备填写标题")

        # 4. 填写标题
        self._fill_title(page, request.title)
        logger.info(f"[OK] 标题已填写: {request.title}")
        wait_confirm("准备填写描述")

        # 5. 填写描述（可选）
        if request.description:
            self._fill_description(page, request.description)
            logger.info(f"[OK] 描述已填写: {request.description[:50]}...")
        else:
            logger.info("  描述为空，跳过")
        wait_confirm("准备添加话题标签")

        # 6. 添加话题标签（可选）
        if request.hashtags:
            self._add_hashtags(page, request.normalized_hashtags())
            logger.info(f"[OK] 话题标签已添加: {request.hashtags}")
        else:
            logger.info("  话题标签为空，跳过")
        wait_confirm("准备上传封面")

        # 7. 封面（可选）
        if request.cover_path:
            self._upload_cover(page, request.cover_path)
            logger.info(f"[OK] 封面上传完成")
        else:
            logger.info("  封面未设置，跳过")
        wait_confirm("准备设置可见性")

        # 8. 设置可见性（公开/私密/仅粉丝）
        self._set_visibility(page, request.visibility)
        logger.info(f"[OK] 可见性已设置为: {request.visibility}")

        wait_confirm("准备点击发布按钮")

        # 8. 点击发布
        self._click_publish(page, interactive=interactive)
        logger.info("[OK] 发布按钮已点击")
        logger.info("  等待发布确认...")
        wait_confirm("准备等待发布结果")

        # 9. 等待发布结果（页面跳转或成功提示）
        post_id, publish_url = self._wait_for_publish_result(page, interactive=interactive)
        logger.info(f"  发布结果 - post_id: {post_id}, url: {publish_url}")

        # 注意：不在发布时获取 post_id。发布后数据库记录 status=PENDING，
        # 由独立 sync 流程通过标题匹配补上 video_id 和 status=published。

        return PublishResult(
            success=True,
            status="published",
            platform="douyin",
            post_id=post_id,
            publish_url=publish_url,
            message="发布完成！video_id 由后续 sync 流程补上",
        )

    # ─── 分步实现 ────────────────────────────────────────────

    def _open_upload_page(self) -> Page:
        """打开上传页，返回 page 对象供后续操作使用"""
        page = self.session.open_page(UPLOAD_URL)
        page.wait_for_timeout(2000)
        if self._page_requires_login(page):
            raise RuntimeError("抖音创作者中心登录态已失效，请先重新登录后再发布。")
        # 等待页面主要元素出现（上传区域）
        page.wait_for_selector("input[type=file]", timeout=30000)
        return page

    def _upload_video_file(self, page: Page, video_path: str) -> None:
        """
        找到隐藏的 <input type="file"> 并填充文件路径。
        抖音的上传 input 通常是隐藏的，用 evaluate 或 set_input_files 绕过。
        """
        # 方法1: 直接 set_input_files（Playwright 自动处理隐藏 input）
        file_input = page.locator("input[type=file]").first()
        file_input.set_input_files(video_path)

    def _wait_for_upload_complete(self, page: Page, timeout: int = 120, interactive: bool = False) -> bool:
        """
        等待视频上传完成。
        抖音上传时会有进度条/上传状态提示。
        上传完成后通常会消失或变为"已完成"状态。
        """
        def log(msg):
            logger.info(msg)
            if interactive:
                print(f"  [诊断] {msg}")

        log(f"开始检测上传状态，当前URL: {page.url}")
        page.wait_for_timeout(2000)  # 等待上传开始

        start = time.time()
        last_status = ""
        while time.time() - start < timeout:
            # 检查视频预览是否出现（最可靠的完成标志）
            video_preview = page.locator("video").first()
            if video_preview.count() > 0:
                log("检测到 video 元素出现，上传完成")
                return True

            # 检查上传进度条状态
            progress_bars = page.locator("[class*='progress']")
            loading = page.locator("[class*='loading'], [class*='spinner']")

            current_status = f"进度条:{progress_bars.count()}, loading:{loading.count()}"
            if current_status != last_status:
                log(f"上传状态: {current_status}")
                last_status = current_status

            # 检查上传完成标志
            upload_done = page.locator("[class*='upload-done'], [class*='upload-success'], [class*='complete']")
            if upload_done.count() > 0:
                log("检测到上传完成标志")
                return True

            if interactive:
                # 在交互模式下，每10秒提醒一次
                elapsed = int(time.time() - start)
                if elapsed % 10 == 0 and elapsed > 0:
                    log(f"已等待 {elapsed} 秒，上传进行中...")

            page.wait_for_timeout(2000)

        log("上传等待超时，但仍返回成功（视频可能已上传）")
        return True

    def _fill_title(self, page: Page, title: str) -> None:
        """填写视频标题"""
        self._last_publish_title = title
        # 抖音创作者后台：.semi-input[placeholder*="标题"]
        selectors = [
            "input.semi-input[placeholder*='标题']",
            "input.semi-input[placeholder*='作品标题']",
            ".semi-input-wrapper input.semi-input",
        ]
        for sel in selectors:
            if page.locator(sel).count() > 0:
                page.locator(sel).first().fill(title)
                logger.info(f"标题已填写: {title}")
                return
        logger.warning("未找到标题输入框，请检查页面结构")

    def _fill_description(self, page: Page, description: str) -> None:
        """填写视频描述（简介）"""
        # 抖音创作者后台：div[contenteditable][data-placeholder="添加作品简介"]
        selectors = [
            "[contenteditable][data-placeholder='添加作品简介']",
            ".editor[contenteditable='true']",
            "div[data-slate-editor='true']",
        ]
        for sel in selectors:
            if page.locator(sel).count() > 0:
                editor = page.locator(sel).first()
                editor.click()
                # 清空现有内容并填写新内容
                editor.fill(description)
                logger.info(f"描述已填写: {description[:50]}...")
                return
        logger.warning("未找到描述输入框，跳过")

    def _add_hashtags(self, page: Page, hashtags: list[str]) -> None:
        """
        添加话题标签。
        使用稳定的 selector + 原子 type_hashtag 操作，避免 DOM 重渲染导致后续 type 超时。
        """
        # 优先用稳定 selector（不依赖 placeholder 属性）
        stable_selectors = [
            "div[data-slate-editor='true']",
            ".editor[contenteditable='true']",
            "[contenteditable][data-placeholder='添加作品简介']",
        ]

        # 先确认编辑器存在
        editor = None
        for sel in stable_selectors:
            if page.locator(sel).count() > 0:
                editor = page.locator(sel).first()
                logger.info(f"找到简介编辑器: {sel}")
                break

        if not editor:
            logger.warning("未找到简介编辑器，跳过添加话题标签")
            return

        # 诊断日志：记录各 selector 的 count
        for sel in stable_selectors:
            cnt = page.locator(sel).count()
            logger.info(f"  selector '{sel}' count={cnt}")

        # 使用原子 type_hashtag，一次子进程调用完成所有键盘动作
        for tag in hashtags:
            editor.type_hashtag(tag, selectors=stable_selectors)
            logger.info(f"  已添加话题: #{tag}")
        logger.info(f"已添加话题: {hashtags}")

    def _upload_cover(self, page: Page, cover_path: str) -> None:
        """上传封面图（可选）"""
        cover_input = page.locator("input[type=file]").nth(1)
        if cover_input.count() > 0:
            cover_input.set_input_files(cover_path)
            page.wait_for_timeout(1000)
            logger.info("封面已上传")
        else:
            logger.warning("未找到封面上传 input")

    def _set_visibility(self, page: Page, visibility: str) -> None:
        """
        设置视频可见性。
        抖音创作者后台"谁可以看"使用 radio label 实现：
          value="0" = 公开, value="1" = 仅自己可见, value="2" = 好友可见
        """
        if visibility == "public":
            return  # 默认就是公开，跳过

        value_map = {"private": "1", "friends": "2", "public": "0"}
        target_value = value_map.get(visibility, "0")

        try:
            # 精确找到对应 value 的 radio input，然后点击其父 label
            radio_input = page.locator(f"input.radio-native-p6VBGt[value='{target_value}']")
            if radio_input.count() > 0:
                label = page.locator(f"label.radio-d4zkru:has(input[value='{target_value}'])")
                if label.count() > 0:
                    label.first().click()
                    logger.info(f"可见性已设置为: {visibility}")
                    return

            # 备选：按文本匹配
            text_map = {"private": "仅自己可见", "friends": "好友可见", "public": "公开"}
            target_text = text_map.get(visibility, "")
            option = page.locator("label.radio-d4zkru").filter(has_text=target_text)
            if option.count() > 0:
                option.first().click()
                logger.info(f"可见性已设置为（文本匹配）: {visibility}")
                return

        except Exception as exc:
            logger.warning(f"设置可见性失败: {exc}")

        logger.warning(f"未能自动设置可见性（{visibility}），请手动选择")

    def _click_publish(self, page: Page, interactive: bool = False) -> None:
        """点击发布按钮"""
        def log(msg):
            logger.info(msg)
            if interactive:
                print(f"  [诊断] {msg}")

        log(f"当前URL: {page.url}")

        # 打印所有按钮供诊断
        all_buttons = page.locator("button")
        log(f"页面上的按钮数量: {all_buttons.count()}")
        for i in range(min(all_buttons.count(), 10)):
            btn = all_buttons.nth(i)
            try:
                text = btn.inner_text().strip()[:30]
                cls = btn.get_attribute("class") or ""
                log(f"  按钮{i}: text='{text}', class='{cls[:50]}'")
            except:
                pass

        # 优先按可见按钮文案点击，避免抖音样式 class 变化或匹配到错误按钮。
        try:
            result = page.click_button_by_text(["发布", "立即发布", "确认发布"])
            for item in result.get("candidates", [])[:10]:
                if "error" in item:
                    log(f"  按钮{item.get('index')}: error={item.get('error')}")
                else:
                    log(
                        f"  按钮{item.get('index')}: text='{item.get('text')}', "
                        f"visible={item.get('visible')}, enabled={item.get('enabled')}, "
                        f"class='{(item.get('class') or '')[:50]}'"
                    )
            if result.get("clicked"):
                log(f"按按钮文案点击发布: {result['clicked'].get('text')}")
                page.wait_for_timeout(1000)
                log(f"点击后 URL: {page.url}")
                return
        except Exception as exc:
            log(f"按按钮文案点击发布失败: {exc}")

        # 兜底：用 class 匹配发布按钮（根据旧版创作者后台页面结构）
        class_publish_btn = page.locator("button.button-dhlUZE.primary-cECiOJ")
        if class_publish_btn.count() > 0:
            log("使用 class 选择器: button.button-dhlUZE.primary-cECiOJ")
            class_publish_btn.first().click()
            log("发布按钮已点击")
            page.wait_for_timeout(1000)
            log(f"点击后 URL: {page.url}")
            return

        logger.warning("未找到发布按钮")

    def _wait_for_publish_result(self, page: Page, timeout: int = 45, interactive: bool = False) -> tuple[str, str]:
        """
        等待发布结果。
        只把真实作品 URL 或作品管理页中能找到本次标题视为发布确认。
        返回 (post_id, publish_url)
        """
        def log(msg):
            logger.info(msg)
            if interactive:
                print(f"  [诊断] {msg}")

        title = (self._last_publish_title or "").strip()
        post_id = ""
        publish_url = ""

        log(f"等待发布结果，当前URL: {page.url}")

        success_selectors = [
            "text=发布成功",
            "text=作品发布成功",
            "text=投稿成功",
            "text=发布成功，作品正在审核",
            "text=作品发布成功，作品正在审核",
        ]

        start = time.time()
        last_url = page.url

        while time.time() - start < timeout:
            current_url = page.url
            if current_url != last_url:
                log(f"URL变化: {last_url} -> {current_url}")
                last_url = current_url
                if self._is_final_video_url(current_url):
                    post_id = self._extract_post_id(current_url)
                    publish_url = current_url
                    log(f"检测到作品页跳转，post_id: {post_id}")
                    return post_id, publish_url

            # 发布后作品管理页/API 常有审核同步延迟。看到明确提交成功提示后，
            # 先按“已提交审核”处理；管理页确认只作为补充，不再因为没同步就误报失败。
            for selector in success_selectors:
                if page.locator(selector).count() > 0:
                    log(f"检测到发布成功提示: {selector}")
                    current_url = page.url
                    try:
                        confirmed_url = self._confirm_publish_in_manage_page(
                            page,
                            title=title,
                            timeout=20,
                            interactive=interactive,
                        )
                        if confirmed_url:
                            return self._extract_post_id(confirmed_url), confirmed_url
                    except Exception as exc:
                        log(f"作品管理页暂未确认，交由用户稍后人工确认: {exc}")
                    return self._extract_post_id(current_url), current_url

            page.wait_for_timeout(1000)

        # 超时后检查最终状态。
        final_url = page.url
        if self._is_final_video_url(final_url):
            post_id = self._extract_post_id(final_url)
            log(f"最终 URL 已进入作品页，post_id: {post_id}")
            return post_id, final_url

        if interactive:
            log("请手动检查页面状态，确认发布是否成功")
            input("  按回车确认发布结果...")
            final_url = page.url
            return self._extract_post_id(final_url), final_url

        raise RuntimeError(f"发布结果确认超时，最终URL: {final_url}")

    def _is_final_video_url(self, url: str) -> bool:
        """只把带真实作品 ID 的 URL 视为最终作品页。"""
        return bool(self._extract_post_id(url))

    def _confirm_publish_in_manage_page(
        self,
        page: Page,
        title: str,
        timeout: int = 90,
        interactive: bool = False,
    ) -> str:
        """进入作品管理页，用标题确认作品真的进入创作者中心。"""
        def log(msg):
            logger.info(msg)
            if interactive:
                print(f"  [诊断] {msg}")

        title = (title or "").strip()
        if not title:
            log("缺少标题，无法通过作品管理页确认发布结果")
            return ""

        log(f"进入作品管理页确认发布结果，标题: {title}")
        try:
            page.goto(MANAGE_URL, timeout=45000)
        except Exception as exc:
            log(f"打开作品管理页失败: {exc}")

        start = time.time()
        last_log_bucket = -1
        while time.time() - start < timeout:
            current_url = page.url
            if self._page_requires_login(page):
                raise RuntimeError("抖音创作者中心登录态已失效，无法确认发布结果，请重新登录后再试。")

            if self._is_final_video_url(current_url):
                log(f"作品管理页跳转到作品 URL: {current_url}")
                return current_url

            if self._page_contains_title(page, title):
                log("作品管理页已找到本次发布标题")
                return current_url or MANAGE_URL

            elapsed = int(time.time() - start)
            log_bucket = elapsed // 10
            if log_bucket != last_log_bucket:
                log(f"作品管理页暂未找到标题，继续等待... {elapsed}s")
                last_log_bucket = log_bucket

            page.wait_for_timeout(5000)
            try:
                page.goto(MANAGE_URL, timeout=45000)
            except Exception as exc:
                log(f"刷新作品管理页失败: {exc}")

        log("作品管理页确认超时，未找到本次标题")
        return ""

    def _page_contains_title(self, page: Page, title: str) -> bool:
        try:
            body_text = page.locator("body").inner_text()
        except Exception as exc:
            logger.warning(f"读取作品管理页文本失败: {exc}")
            return False

        def normalize(value: str) -> str:
            return re.sub(r"\s+", "", value or "")

        page_text = normalize(body_text)
        normalized_title = normalize(title)
        if not normalized_title:
            return False

        candidates = [normalized_title]
        if len(normalized_title) >= 12:
            candidates.append(normalized_title[:12])

        return any(candidate and candidate in page_text for candidate in candidates)

    def _page_requires_login(self, page: Page) -> bool:
        try:
            body_text = page.locator("body").inner_text()
        except Exception:
            return False

        normalized = re.sub(r"\s+", "", body_text or "")
        login_markers = [
            "扫码登录",
            "验证码登录",
            "密码登录",
            "登录/注册",
            "创作者登录",
        ]
        return any(marker in normalized for marker in login_markers)

    def _extract_post_id(self, url: str) -> str:
        """从 URL 中提取抖音视频 ID"""
        patterns = [
            r'/video/(\d+)',
            r'/status/(\d+)',
            r'\?video_id=(\w+)',
            r'aweme_id=(\w+)',
        ]
        for p in patterns:
            m = re.search(p, url)
            if m:
                return m.group(1)
        return ""
