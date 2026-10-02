"""
publish_workflow.py — 抖音视频发布工作流

全自动化浏览器上传流程：
  1. 打开创作者后台上传页
  2. 注入视频文件（隐藏的 input[type=file]）
  3. 等待视频上传完成（进度条消失）
  4. 填写标题 + 描述 + 话题标签
  5. 主动选择并读回“内容由AI生成”声明
  6. 点击发布（声明未确认时停止）
  7. 提取发布结果（post_id / 链接）
  8. 浏览器打开对应作品，核验声明、播放器与审核提示并保存证据
"""

import re
import time
import json
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

from playwright.sync_api import Page

from src.platform_adapter.browser_session import BrowserSession
from src.platform_adapter.models import PublishRequest, PublishResult
from src.platform_adapter.publish_verification import FICTION_NOTICE, EDITORS, declared_description, video_id
from src.shared.logger import logger


# 抖音创作者后台上传页 URL
UPLOAD_URL = "https://creator.douyin.com/creator-micro/content/upload"
MANAGE_URL = "https://creator.douyin.com/creator-micro/content/manage"


class PublishWorkflowError(RuntimeError):
    def __init__(self, result):
        super().__init__(result.message)
        self.status = result.status


class AIDeclarationUnverified(RuntimeError):
    pass


class FictionDeclarationUnverified(RuntimeError):
    pass


class PublishWorkflow:
    def __init__(self, session: BrowserSession):
        self.session = session
        self._last_publish_title = ""
        self._submission_started = False
        self._journal_path = None
        self._ai_declaration_required = True
        self._fiction_declaration_required = False

    def _record(self, stage: str, **details) -> None:
        if self._journal_path is not None:
            with self._journal_path.open('a', encoding='utf8') as handle:
                handle.write(json.dumps({'at_bjt': datetime.now(timezone(timedelta(hours=8))).isoformat(),
                    'stage': stage, **details}, ensure_ascii=False)+'\n')
            state = {'stage': stage, 'at_bjt': datetime.now(timezone(timedelta(hours=8))).isoformat(), **details}
            target = self._journal_path.with_suffix('.status.json')
            temporary = target.with_suffix('.tmp')
            temporary.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
            temporary.replace(target)

    def _start_journal(self, request: PublishRequest) -> None:
        root = Path(__file__).resolve().parents[2] / 'data' / 'publish_runs'
        root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with Path(request.video_path).open('rb') as handle:
            for block in iter(lambda: handle.read(1024*1024), b''):
                digest.update(block)
        identity = {'account': request.extra_metadata.get('account_key', ''),
                    'video_sha256': digest.hexdigest()}
        if not identity['account']:
            raise ValueError('发布前必须绑定运营账号')
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        legacy_lock = root / (key+'.submitted.json')
        if legacy_lock.exists():
            raise ValueError('该账号与视频已有历史提交记录；先核对平台结果，禁止重复提交')
        platform_identity = request.extra_metadata.get('platform_identity_key')
        if not platform_identity:
            raise ValueError('发布缺少已验证的平台身份快照')
        identity.update(account_uuid=request.extra_metadata.get('account_uuid'),
                        platform_identity_key=platform_identity,
                        binding_verified_at=request.extra_metadata.get('binding_verified_at'))
        key = hashlib.sha256(json.dumps({'platform_identity_key': platform_identity,
                                         'video_sha256': identity['video_sha256']}, sort_keys=True).encode()).hexdigest()
        self._submission_lock = root / (key+'.submitted.json')
        if self._submission_lock.exists():
            raise ValueError('该账号与视频已有提交记录；先核对平台结果，禁止重复提交')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        self._journal_path = root / (key+'.'+stamp+'.jsonl')
        self._record('prepared', **identity, video_path=str(Path(request.video_path).resolve()),
                     title=request.title, description=request.description,
                     hashtags=request.normalized_hashtags(), visibility=request.visibility,
                     ai_declaration_required=request.ai_generated,
                     fiction_declaration_required=request.fictional_story,
                     effective_description=declared_description(request.description, request.fictional_story))

    def _reserve_submission(self):
        # Exclusive creation survives an uncertain click/timeout and blocks blind retries.
        with self._submission_lock.open('x', encoding='utf8') as handle:
            json.dump({'journal': str(self._journal_path), 'status': 'submission_started'}, handle)
        self._submission_started = True
        self._record('submission_started')

    def publish(self, request: PublishRequest, interactive: bool = False) -> PublishResult:
        validation_error = self._validate_request(request)
        if validation_error:
            return PublishResult(
                success=False,
                status="invalid_request",
                message=validation_error,
            )

        try:
            self._journal_path = None
            self._submission_started = False
            self._ai_declaration_required = request.ai_generated
            self._fiction_declaration_required = request.fictional_story
            self._start_journal(request)
            self._record('checking_login')
            self.session.start()
            if not self.session.is_authenticated():
                result = PublishResult(success=False, status='login_required', message='未检测到登录态，请先登录所选账号的创作者中心。')
            else:
                result = self._do_publish(request, interactive=interactive)
            self._record(result.status, message=result.message, post_id=result.post_id, publish_url=result.publish_url)
            return result
        except (AIDeclarationUnverified, FictionDeclarationUnverified) as exc:
            status = 'submission_unknown' if self._submission_started else ('ai_declaration_unverified' if isinstance(exc, AIDeclarationUnverified) else 'fiction_declaration_unverified')
            self._record(status, message=str(exc))
            return PublishResult(success=False, status=status, message=str(exc))
        except Exception as exc:
            self._record('submission_unknown' if self._submission_started else 'failed', error_type=type(exc).__name__)
            logger.exception("发布流程异常")
            return PublishResult(
                success=False,
                status="submission_unknown" if self._submission_started else "error",
                message=f"发布异常: {exc}",
            )

    # ─── 验证 ────────────────────────────────────────────────

    def _validate_request(self, request: PublishRequest) -> str:
        if type(request.fictional_story) is not bool:
            return 'fictional_story 必须为布尔值'
        if type(request.ai_generated) is not bool:
            return "ai_generated 必须为布尔值，不能用字符串跳过声明"
        video_path = Path(request.video_path)
        if not request.video_path:
            return "video_path 不能为空"
        if not video_path.is_file():
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
        self._record('file_selected')
        self._record('uploading')
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
        self._record('upload_complete')
        wait_confirm("准备填写标题")

        # 4. 填写标题
        self._fill_title(page, request.title)
        logger.info(f"[OK] 标题已填写: {request.title}")
        wait_confirm("准备填写描述")

        # 5. 填写描述（可选）
        description = declared_description(request.description, request.fictional_story)
        if description:
            self._fill_description(page, description)
            logger.info(f"[OK] 描述已填写: {description[:50]}...")
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

        # AI declaration is a platform setting, not a caption or hashtag.
        if request.ai_generated:
            self._record('setting_ai_declaration')
            self._require_ai_declaration(page, set_selected=True)

        wait_confirm("准备点击发布按钮")

        if request.ai_generated:
            self._require_ai_declaration(page)  # Re-read after any interactive pause.
        if request.fictional_story:
            self._require_fiction_declaration(page)
        self._record('form_prepared', title=request.title, hashtags=request.normalized_hashtags(),
                     ai_declaration_verified=request.ai_generated)
        self._reserve_submission()

        # 8. 点击发布
        self._click_publish(page, interactive=interactive)
        logger.info("[OK] 发布按钮已点击")
        logger.info("  等待发布确认...")
        wait_confirm("准备等待发布结果")

        # 9. 等待发布结果（页面跳转或成功提示）
        post_id, publish_url = self._wait_for_publish_result(page, interactive=interactive)
        logger.info(f"  发布结果 - post_id: {post_id}, url: {publish_url}")
        evidence = self._verify_published_work(page, post_id, publish_url, request)
        status = 'published' if evidence.get('verified') is True else 'post_publish_verification_pending'
        self._record(status, post_id=post_id, publish_url=publish_url, evidence=evidence)

        # 注意：不在发布时获取 post_id。发布后数据库记录 status=PENDING，
        # 由独立 sync 流程通过标题匹配补上 video_id 和 status=published。

        return PublishResult(
            success=True,
            status=status,
            platform="douyin",
            post_id=post_id,
            publish_url=publish_url,
            message="作品展示及声明已核验" if status == 'published' else "平台已接受提交，发布后检查待核验；禁止重复上传",
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
            # A local video preview can appear before upload completes.
            body = page.locator('body').inner_text()
            if any(marker in body for marker in ('上传失败', '上传出错', '重新上传失败')):
                return False

            # 检查上传进度条状态
            progress_bars = page.locator("[class*='progress']")
            loading = page.locator("[class*='loading'], [class*='spinner']")

            current_status = f"进度条:{progress_bars.count()}, loading:{loading.count()}"
            if current_status != last_status:
                log(f"上传状态: {current_status}")
                last_status = current_status

            # 检查上传完成标志
            if any(marker in body for marker in ('上传成功', '上传完成')):
                log("检测到上传完成标志")
                return True

            if interactive:
                # 在交互模式下，每10秒提醒一次
                elapsed = int(time.time() - start)
                if elapsed % 10 == 0 and elapsed > 0:
                    log(f"已等待 {elapsed} 秒，上传进行中...")

            page.wait_for_timeout(2000)

        log("上传等待超时，未确认成功，停止后续发布")
        return False

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
        raise RuntimeError("未找到标题输入框，停止发布")

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
        raise RuntimeError("未找到描述输入框，停止发布")

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
            raise RuntimeError("未找到简介编辑器，停止发布")

        # 诊断日志：记录各 selector 的 count
        for sel in stable_selectors:
            cnt = page.locator(sel).count()
            logger.info(f"  selector '{sel}' count={cnt}")

        # 使用原子 type_hashtag，一次子进程调用完成所有键盘动作
        for tag in hashtags:
            editor.type_hashtag(tag, selectors=stable_selectors)
            logger.info(f"  已添加话题: #{tag}")
        content = editor.inner_text()
        missing = [tag for tag in hashtags if '#' + tag not in content]
        if missing:
            raise RuntimeError('话题未完整写入，停止发布：' + '、'.join(missing))
        logger.info(f"已添加话题: {hashtags}")

    def _upload_cover(self, page: Page, cover_path: str) -> None:
        """上传封面图（可选）"""
        cover_input = page.locator("input[type=file]").nth(1)
        if cover_input.count() > 0:
            cover_input.set_input_files(cover_path)
            page.wait_for_timeout(1000)
            logger.info("封面已上传")
        else:
            raise RuntimeError('未找到指定封面的上传入口，停止发布')

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

        raise RuntimeError(f'未能设置可见性（{visibility}），停止发布')

    def _require_fiction_declaration(self, page):
        for selector in EDITORS:
            editors = page.locator(selector)
            if editors.count() == 1:
                if FICTION_NOTICE in editors.first().inner_text():
                    self._record('fiction_declaration_verified', notice=FICTION_NOTICE)
                    return
                break
        raise FictionDeclarationUnverified('简介中的剧情虚构声明未读回确认，已停止发布')

    def _verify_published_work(self, page, post_id, publish_url, request):
        evidence = {'verified': False, 'reason': '尚未取得准确作品链接'}
        try:
            if post_id and video_id(publish_url) == post_id:
                page.goto(publish_url, timeout=30000)
                page.wait_for_timeout(2000)
                path = str(self._journal_path.with_suffix('.published-work.png')) if self._journal_path else None
                evidence = page.inspect_published_video(post_id, ai_required=request.ai_generated,
                            fiction_required=request.fictional_story, evidence_path=path)
        except Exception as exc:
            evidence = {'verified': False, 'reason': str(exc), 'post_id': post_id, 'url': publish_url}
        self._record('post_publish_checked', evidence=evidence)
        return evidence

    def _require_ai_declaration(self, page: Page, *, set_selected=False) -> dict:
        evidence_path = None
        if self._journal_path is not None:
            suffix = '.ai-declaration-selected.png' if set_selected else '.ai-declaration-verified.png'
            evidence_path = str(self._journal_path.with_suffix(suffix))
        try:
            evidence = page.ai_content_declaration(set_selected=set_selected, evidence_path=evidence_path)
        except Exception as exc:
            raise AIDeclarationUnverified('未能设置或核验“内容由AI生成”自主声明，已停止发布：' + str(exc)) from exc
        if evidence.get('verified') is not True:
            self._record('ai_declaration_unverified', evidence=evidence)
            raise AIDeclarationUnverified('未确认“内容由AI生成”自主声明，已停止发布。' + evidence.get('reason', ''))
        self._record('ai_declaration_verified', evidence=evidence, set_selected=bool(set_selected))
        return evidence

    def _click_publish(self, page: Page, interactive: bool = False) -> None:
        """点击发布按钮"""
        if self._ai_declaration_required:
            self._require_ai_declaration(page)
        if self._fiction_declaration_required:
            self._require_fiction_declaration(page)
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

        raise RuntimeError("未找到发布按钮")

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
            if self._is_final_video_url(final_url):
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
                links = page.locator('a[href]')
                matches = set()
                for index in range(links.count()):
                    link = links.nth(index)
                    href = link.get_attribute('href') or ''
                    if href.startswith('/video/'):
                        href = 'https://www.douyin.com' + href
                    if video_id(href) and link.inner_text().strip() == title:
                        matches.add(href)
                if len(matches) == 1:
                    return matches.pop()
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

        return normalized_title in page_text

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
