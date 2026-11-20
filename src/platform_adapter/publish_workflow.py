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
import unicodedata
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from playwright.sync_api import Page

from src.platform_adapter.browser_session import BrowserSession
from src.platform_adapter.upload_surface_diagnostic import capture_upload_surface
from src.platform_adapter.models import PublishRequest, PublishResult
from src.platform_adapter.publish_verification import FICTION_NOTICE, EDITORS, declared_description, video_id, wait_for_published_video
from src.shared.logger import logger
from src.shared.published_work_discovery import is_manage_url, canonical_video


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


class HashtagReadbackError(RuntimeError):
    pass


class PublishWorkflow:
    def __init__(self, session: BrowserSession):
        self.session = session
        self._last_publish_title = ""
        self._submission_started = False
        self._journal_path = None
        self._ai_declaration_required = True
        self._fiction_declaration_required = False
        self._upload_diagnostic_count = 0
        self._upload_selection = None
        self._upload_fast_selection = None

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
        self._upload_diagnostic_count = 0
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
        self._upload_selection = None
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
                message="未确认视频上传完成，已停止后续发布；请核对本次上传状态与诊断证据。",
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
            self._add_hashtags(page, request.normalized_hashtags(), expected_description=description)
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
        if request.hashtags:
            self._confirm_hashtag_form(page, request.normalized_hashtags(), description)
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
        self._upload_fast_selection = None
        file_input = page.locator("input[type=file]").first()
        file_input.set_input_files(video_path)
        # Only a successful selection on this exact Page can start the compound proof.
        self._upload_selection = (page, self._journal_path)
        begin = getattr(page, 'upload_check_proof', None)
        if callable(begin) and self._journal_path is not None:
            nonce = uuid.uuid4().hex
            try:
                armed = begin('begin', nonce)
                if (not isinstance(armed, dict) or armed.get('schema') != 'upload_check_transition/v2'
                        or armed.get('selection_nonce') != nonce
                        or armed.get('verified') is not False):
                    raise ValueError('upload_check_begin_unknown')
                self._record('upload_check_transition_initial', selection_nonce=nonce, proof=armed)
                if armed.get('state') not in ('armed_upload', 'armed_editor'):
                    self._record('upload_check_transition_rejected', selection_nonce=nonce,
                        reason=armed.get('reason'), proof=armed)
                    return
                self._upload_fast_selection = (page, self._journal_path, nonce)
                self._record('upload_check_transition_armed', selection_nonce=nonce, proof=armed)
            except Exception as exc:
                # No transport retry or file reselection. The independent old
                # bytes/cancel branch may still establish its own known proof.
                self._record('upload_check_transition_unavailable', error_type=type(exc).__name__)

    @staticmethod
    def _probe_upload_completion(page):
        """Bounded rendered UI only; no file values, media, storage or network reads."""
        result = page.evaluate(r"""() => {
            // publish-upload-completion-probe/v1
            const visible = el => {
                if (!el || el.closest('script,style,noscript,template,video,audio,canvas')) return false;
                let p=el, depth=0;
                for (; p && depth<40; p=p.parentElement, depth++) {
                    const s=getComputedStyle(p);
                    if (s.display==='none' || s.visibility==='hidden' || s.visibility==='collapse' || Number(s.opacity)===0 || p.hidden || p.getAttribute('aria-hidden')==='true') return false;
                }
                return !p && el.getClientRects().length>0;
            };
            const hit = el => {
                if (!visible(el)) return false;
                const r=el.getBoundingClientRect();
                const x=(Math.max(0,r.left)+Math.min(innerWidth,r.right))/2;
                const y=(Math.max(0,r.top)+Math.min(innerHeight,r.bottom))/2;
                if (r.right<=0 || r.bottom<=0 || r.left>=innerWidth || r.top>=innerHeight) return false;
                const top=document.elementFromPoint(x,y);
                return !!top && (top===el || el.contains(top));
            };
            const usable = el => {
                for (let p=el, d=0; p && d<40; p=p.parentElement,d++) {
                    if (p.disabled || p.getAttribute('aria-disabled')==='true' || p.hasAttribute('inert') || getComputedStyle(p).pointerEvents==='none') return false;
                }
                return hit(el);
            };
            const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
            let node, scanned=0, text='', exactClean=false, reupload=false, candidates=0, truncated=false, transferStatus=false;
            while ((node=walker.nextNode())) {
                if (++scanned>5000) {truncated=true;break;}
                const el=node.parentElement;
                if (!visible(el)) continue;
                const part=(node.textContent||'').trim();
                if (!part) continue;
                if (text.length+part.length+1>16000) {truncated=true;break;}
                text+='\n'+part;
                // Conditional footer instructions are not current transfer state.
                if (/^(?:正在上传|上传中|上传处理中)(?:\s*\d+(?:\.\d+)?\s*%)?[.…。]*$/.test(part)) transferStatus=true;
                if (part==='作品未见异常' && hit(el)) exactClean=true;
                if (part==='重新上传' && candidates<12) {
                    candidates++;
                    for (let p=el,d=0; p && d<5 && p!==document.body; p=p.parentElement,d++) {
                        const tag=p.tagName.toLowerCase(), role=p.getAttribute('role');
                        if (tag==='button' || tag==='a' && p.hasAttribute('href') || role==='button' || p.hasAttribute('tabindex') && p.tabIndex>=0 || getComputedStyle(p).cursor==='pointer') {
                            if ((p.innerText||'').trim()==='重新上传' && usable(p)) reupload=true;
                            break;
                        }
                    }
                }
            }
            const cancel=/取消\s*上传/.test(text);
            const bytes=/已上传\s*[:：]?\s*\d+(?:\.\d+)?\s*(?:[KMGT]?B)?\s*\/\s*\d+(?:\.\d+)?\s*[KMGT]?B/i.test(text);
            return {schema:'upload_completion_probe/v1', truncated,
                transfer_bytes:bytes, cancel_upload:cancel,
                transferring:bytes||cancel||transferStatus,
                checking:/检测中|正在检测|检测\s*\d+(?:\.\d+)?\s*%/.test(text),
                failed:/上传失败|上传出错|重新上传失败/.test(text),
                clean:exactClean, reupload_usable:reupload, reupload_candidates:candidates};
        }""")
        fields = ('truncated', 'transfer_bytes', 'cancel_upload', 'transferring', 'checking',
                  'failed', 'clean', 'reupload_usable')
        if not isinstance(result, dict) or result.get('schema') != 'upload_completion_probe/v1' or any(
                type(result.get(key)) is not bool for key in fields):
            raise ValueError('upload_completion_probe_unknown')
        return {key: result[key] for key in fields}

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
        start = time.time()
        last_status = ""
        selected = self._upload_selection == (page, self._journal_path) and self._journal_path is not None
        transfer_proof = None
        stable_proofs = []
        fast = self._upload_fast_selection
        fast_bound = (selected and fast is not None and fast[:2] == (page, self._journal_path))
        fast_check_recorded = False
        while time.time() - start < timeout:
            # A local video preview can appear before upload completes.
            body = page.locator('body').inner_text()
            if any(marker in body for marker in ('上传失败', '上传出错', '重新上传失败')):
                self._capture_upload_diagnostic(page, event='failure_marker', status=last_status, terminal=True)
                return False

            # 检查上传进度条状态
            progress_bars = page.locator("[class*='progress']")
            loading = page.locator("[class*='loading'], [class*='spinner']")

            current_status = f"进度条:{progress_bars.count()}, loading:{loading.count()}"
            if current_status != last_status:
                log(f"上传状态: {current_status}")
                last_status = current_status
                if not self._capture_upload_diagnostic(page, event='state_changed', status=current_status):
                    return False

            # 检查上传完成标志
            if any(marker in body for marker in ('上传成功', '上传完成')):
                log("检测到上传完成标志")
                return self._capture_upload_diagnostic(page, event='success_marker', status=current_status, terminal=True)

            try:
                proof = self._probe_upload_completion(page) if selected else None
            except Exception as exc:
                self._record('upload_completion_probe_failed', error_type=type(exc).__name__)
                self._capture_upload_diagnostic(page, event='probe_failed', status=current_status, terminal=True)
                return False
            if proof is None:
                page.wait_for_timeout(2000)
                continue
            if proof['failed']:
                self._capture_upload_diagnostic(page, event='failure_marker', status=current_status, terminal=True)
                return False
            if fast_bound:
                try:
                    fast_proof = page.upload_check_proof('observe', fast[2])
                    if (not isinstance(fast_proof, dict) or fast_proof.get('schema') != 'upload_check_transition/v2'
                            or fast_proof.get('selection_nonce') != fast[2]
                            or type(fast_proof.get('verified')) is not bool):
                        raise ValueError('upload_check_observation_unknown')
                    self._record('upload_check_transition_observed', selection_nonce=fast[2], proof=fast_proof)
                    if fast_proof.get('state') == 'invalid':
                        fast_bound = False
                        self._record('upload_check_transition_rejected', selection_nonce=fast[2],
                            reason=fast_proof.get('reason'), proof=fast_proof)
                        if fast_proof.get('reason') in ('reupload_scroll_document_changed',
                                'reupload_scroll_candidate_changed','reupload_scroll_identity_unknown'):
                            self._capture_upload_diagnostic(page, event='scroll_identity_failed',
                                status=current_status, terminal=True)
                            return False  # Earlier bytes cannot override this native-action uncertainty.
                    elif fast_proof.get('checking_observed') is True and not fast_check_recorded:
                        fast_check_recorded = True
                        self._record('upload_checking_nodes_bound', selection_nonce=fast[2], proof=fast_proof)
                    if (fast_proof.get('verified') is True and fast_proof.get('state') == 'verified'
                            and fast_check_recorded and len(fast_proof.get('stable_observations', [])) == 2
                            and not proof['truncated'] and proof['clean'] and proof['reupload_usable']
                            and not proof['transferring'] and not proof['checking']):
                        if not self._capture_upload_diagnostic(page, event='check_transition_success', status=current_status, terminal=True):
                            return False
                        self._record('upload_completion_verified', method='original_check_nodes_then_stable_clean',
                            file_selection_stage='file_selected', selection_journal=str(self._journal_path),
                            selection_nonce=fast[2], proof=fast_proof)
                        return True
                except Exception as exc:
                    fast_bound = False
                    self._record('upload_check_transition_unavailable', error_type=type(exc).__name__)
            if transfer_proof is None and not proof['truncated'] and proof['transfer_bytes'] and proof['cancel_upload']:
                transfer_proof = dict(proof, elapsed_seconds=round(time.time()-start, 3))
                self._record('upload_transfer_observed', file_selection_stage='file_selected',
                    selection_journal=str(self._journal_path), proof=transfer_proof)
            complete = (selected and transfer_proof is not None and not proof['truncated']
                and proof['clean'] and proof['reupload_usable'] and not proof['transferring']
                and not proof['checking'])
            if complete:
                stable_proofs.append(dict(proof, elapsed_seconds=round(time.time()-start, 3)))
                if len(stable_proofs) == 2:
                    if not self._capture_upload_diagnostic(page, event='compound_success', status=current_status, terminal=True):
                        return False
                    self._record('upload_completion_verified', method='visible_transfer_then_stable_check',
                        file_selection_stage='file_selected', selection_journal=str(self._journal_path),
                        transfer=transfer_proof, stable_observations=stable_proofs)
                    return True
            else:
                stable_proofs = []

            if interactive:
                # 在交互模式下，每10秒提醒一次
                elapsed = int(time.time() - start)
                if elapsed % 10 == 0 and elapsed > 0:
                    log(f"已等待 {elapsed} 秒，上传进行中...")

            page.wait_for_timeout(2000)

        log("上传等待超时，未确认成功，停止后续发布")
        self._capture_upload_diagnostic(page, event='timeout', status=last_status, terminal=True)
        return False

    def _capture_upload_diagnostic(self, page: Page, *, event: str, status: str, terminal: bool = False) -> bool:
        """At most five changes plus one terminal snapshot; failure never allows publication."""
        maximum = 6 if terminal else 5
        if self._upload_diagnostic_count >= maximum:
            return True  # Budget exhaustion does not replace the original completion gate.
        self._upload_diagnostic_count += 1
        index = self._upload_diagnostic_count
        try:
            if self._journal_path is None:
                raise RuntimeError('upload_diagnostic_journal_missing')
            journal = Path(self._journal_path)
            captured = capture_upload_surface(page, journal.parent,
                artifact_name=journal.stem + f'.upload-{index:02d}-{event}')
            self._record('upload_ui_diagnostic', event=event, index=index, status=status,
                evidence_path=captured['evidence']['path'],
                evidence_sha256=captured['evidence']['sha256'],
                screenshot=captured['screenshot']['path'],
                screenshot_sha256=captured['screenshot']['sha256'])
            return True
        except Exception as exc:
            self._record('upload_ui_diagnostic_failed', event=event, index=index,
                error_type=type(exc).__name__)
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

    @staticmethod
    def _hashtag_tokens(snapshot):
        """Read whole words after a hash, or exact rendered semantic chips."""
        # Formatting characters must not turn 劳动法律 into a false 劳动法 hit.
        clean = lambda text: ''.join(c for c in text if unicodedata.category(c) != 'Cf')
        sources = {}
        for match in re.finditer(r'(?<![#＃])[#＃]\s*(\w+)', clean(snapshot['text'])):
            sources.setdefault(match.group(1), []).append('visible_text')
        for chip in snapshot['chips']:
            label = re.sub(r'\s+', '', clean(chip['text']))
            pattern = r'[#＃](\w+)' if not chip['explicit_topic'] else r'[#＃]?(\w+)'
            match = re.fullmatch(pattern, label)
            if match:
                sources.setdefault(match.group(1), []).append('topic_chip' if chip['explicit_topic'] else 'slate_chip')
        return sources

    def _hashtag_snapshot(self, page):
        """Reacquire the current visible Slate root; do not cache a replaced node."""
        for selector in ("div[data-slate-editor='true']", ".editor[contenteditable='true']",
                "[contenteditable][data-placeholder='添加作品简介']"):
            candidates = page.locator(selector)
            for index in range(min(candidates.count(), 3)):
                editor = candidates.nth(index)
                observed = editor.evaluate("""editor => {
                    const visible = element => {
                        const rect = element.getBoundingClientRect();
                        if (!(rect.width > 0 && rect.height > 0)) return false;
                        for (let parent = element; parent; parent = parent.parentElement) {
                            const style = getComputedStyle(parent);
                            if (style.display === 'none' || style.visibility === 'hidden'
                                || style.visibility === 'collapse' || Number(style.opacity) === 0) return false;
                        }
                        return true;
                    };
                    if (!visible(editor)) return {visible: false};
                    const topicSelector = '[class*="topic"],[class*="hashtag"],[data-type="topic"],[data-type="hashtag"]';
                    const raw = editor.innerText || '';
                    return {visible: true, text: raw.slice(0, 12000), truncated: raw.length > 12000,
                        chips: Array.from(editor.querySelectorAll(topicSelector + ',[data-slate-inline="true"],[data-slate-void="true"],[contenteditable="false"]'))
                            .filter(visible).slice(0, 40).map(chip => ({
                                text: (chip.innerText || '').slice(0, 256), explicit_topic: chip.matches(topicSelector)
                            }))};
                }""")
                if not isinstance(observed, dict) or observed.get('visible') is not True:
                    continue
                if (not isinstance(observed.get('text'), str) or not isinstance(observed.get('chips'), list)
                        or observed.get('truncated') is True):
                    raise RuntimeError('简介读回不完整，停止发布')
                chips = []
                for chip in observed['chips'][:40]:
                    if not isinstance(chip, dict) or not isinstance(chip.get('text'), str):
                        raise RuntimeError('话题节点读回无效，停止发布')
                    chips.append({'text': chip['text'][:256], 'explicit_topic': chip.get('explicit_topic') is True})
                snapshot = {'text': observed['text'], 'chips': chips, 'editor': editor,
                    'selector': f':nth-match({selector}, {index+1})'}
                snapshot['tokens'] = self._hashtag_tokens(snapshot)
                return snapshot
        raise RuntimeError('未找到可见简介编辑器，停止发布')

    @staticmethod
    def _description_preserved(snapshot, description):
        # Slate can insert presentation line breaks; wording and punctuation
        # must remain unchanged at the start of the editor.
        # The observed Slate editor also inserts U+200B around visible blocks.
        # Only that confirmed formatting character is ignored beyond whitespace.
        normalize = lambda text: re.sub(r'\s+', '', text.replace('\u200b', ''))
        return snapshot is not None and normalize(snapshot['text']).startswith(normalize(description))

    def _wait_hashtag_readback(self, page, description, required, *, final=False):
        previous, stable, latest = None, 0, None
        for attempt in range(24 if final else 12):
            try:
                snapshot = self._hashtag_snapshot(page)
                latest = snapshot
                signature = (snapshot['text'], tuple((c['text'], c['explicit_topic']) for c in snapshot['chips']))
                valid = self._description_preserved(snapshot, description) and all(tag in snapshot['tokens'] for tag in required)
                stable = stable+1 if valid and signature == previous else (1 if valid else 0)
                previous = signature
                if stable >= (7 if final else 3):
                    return snapshot, True
            except Exception:
                previous, stable = None, 0
            if attempt < (23 if final else 11):
                page.wait_for_timeout(250)
        return latest, False

    def _record_hashtag_readback(self, phase, expected, snapshot, description, **details):
        actual = snapshot['text'] if snapshot else ''
        tokens = snapshot['tokens'] if snapshot else {}
        self._record('hashtags_readback', phase=phase, expected=expected,
            actual_text=actual[:4096], actual_text_truncated=len(actual)>4096,
            actual_text_sha256=hashlib.sha256(actual.encode('utf-8')).hexdigest(),
            observed={tag: tokens.get(tag, []) for tag in expected if tag in tokens},
            missing=[tag for tag in expected if tag not in tokens],
            description_preserved=self._description_preserved(snapshot, description), **details)

    def _hashtag_failure(self, page, tags, snapshot, description, message):
        self._record_hashtag_readback('failed', tags, snapshot, description)
        try:
            if self._journal_path is not None:
                journal = Path(self._journal_path)
                captured = capture_upload_surface(page, journal.parent,
                    artifact_name=journal.stem+'.hashtags-failed')
                self._record('hashtags_failure_ui', evidence=captured['evidence'], screenshot=captured['screenshot'])
        except Exception as exc:
            self._record('hashtags_failure_ui_failed', error_type=type(exc).__name__)
        raise HashtagReadbackError(message)

    def _add_hashtags(self, page: Page, hashtags: list[str], *, expected_description=None) -> None:
        self._hashtag_reference_description = expected_description or ''
        try:
            self._write_hashtags_bounded(page, hashtags, expected_description=expected_description)
        except HashtagReadbackError:
            raise
        except Exception as exc:
            try:
                snapshot = self._hashtag_snapshot(page)
            except Exception:
                snapshot = None
            self._hashtag_failure(page, hashtags, snapshot, self._hashtag_reference_description,
                f'话题表单操作未完成，停止发布（{type(exc).__name__}）')

    def _write_hashtags_bounded(self, page: Page, hashtags: list[str], *, expected_description=None) -> None:
        """Read every topic back, then allow at most one missing-only repair."""
        tags = list(dict.fromkeys(tag.strip().lstrip('#').strip() for tag in hashtags))
        if any(not re.fullmatch(r'\w+', tag) for tag in tags):
            raise ValueError('话题必须是完整名称，不含空白或分隔符')
        try:
            initial = self._hashtag_snapshot(page)
        except Exception:
            self._hashtag_failure(page, tags, None, expected_description or '', '简介暂无法读回，停止发布')
        description = initial['text'] if expected_description is None else expected_description
        self._hashtag_reference_description = description
        snapshot, settled = self._wait_hashtag_readback(page, description, [])
        if not settled:
            self._hashtag_failure(page, tags, snapshot, description, '原简介未稳定确认，停止发布')
        self._record_hashtag_readback('before', tags, snapshot, description)
        for index, tag in enumerate(tags):
            snapshot = self._hashtag_snapshot(page)
            if not self._description_preserved(snapshot, description):
                self._hashtag_failure(page, tags, snapshot, description, '原简介发生变化，停止发布')
            if tag not in snapshot['tokens']:
                required = list(dict.fromkeys(list(snapshot['tokens']) + tags[:index+1]))
                snapshot['editor'].type_hashtag(tag, selectors=[snapshot['selector']])
                snapshot, settled = self._wait_hashtag_readback(page, description, required)
                if not self._description_preserved(snapshot, description):
                    self._hashtag_failure(page, tags, snapshot, description, '原简介未保留，停止发布')
                if not settled:
                    self._hashtag_failure(page, tags, snapshot, description,
                        '话题未稳定写入或原话题未保留，停止发布：'+tag)
            self._record_hashtag_readback('after_initial_tag', tags, snapshot, description, attempted_tag=tag)
            if not self._description_preserved(snapshot, description):
                self._hashtag_failure(page, tags, snapshot, description, '原简介未保留，停止发布')
        snapshot, complete = self._wait_hashtag_readback(page, description, tags, final=True)
        if not self._description_preserved(snapshot, description):
            self._hashtag_failure(page, tags, snapshot, description, '原简介未保留，停止发布')
        if not complete:
            missing = [tag for tag in tags if tag not in snapshot['tokens']]
            self._record_hashtag_readback('repair_once', tags, snapshot, description, repair_targets=missing)
            for tag in missing:
                current = self._hashtag_snapshot(page)
                if not self._description_preserved(current, description):
                    self._hashtag_failure(page, tags, current, description, '原简介发生变化，停止发布')
                if tag not in current['tokens']:
                    required = list(dict.fromkeys(list(current['tokens']) + [tag]))
                    current['editor'].type_hashtag(tag, selectors=[current['selector']])
                    snapshot, settled = self._wait_hashtag_readback(page, description, required)
                    if not self._description_preserved(snapshot, description):
                        self._hashtag_failure(page, tags, snapshot, description, '原简介未保留，停止发布')
                    if not settled:
                        self._hashtag_failure(page, tags, snapshot, description,
                            '修补话题未稳定写入或原话题未保留，停止发布：'+tag)
            snapshot, complete = self._wait_hashtag_readback(page, description, tags, final=True)
        if not complete:
            missing = [tag for tag in tags if tag not in (snapshot['tokens'] if snapshot else {})]
            self._hashtag_failure(page, tags, snapshot, description,
                '话题未完整稳定写入，停止发布：'+('、'.join(missing) or '表单仍在变化'))
        self._record_hashtag_readback('complete', tags, snapshot, description)

    def _confirm_hashtag_form(self, page, tags, description):
        """Final read-only check; never restart the one-shot repair or upload."""
        snapshot, complete = self._wait_hashtag_readback(page, description, tags, final=True)
        self._record_hashtag_readback('before_submission', tags, snapshot, description)
        if not complete:
            self._hashtag_failure(page, tags, snapshot, description, '发布前话题或完整简介未稳定确认，停止发布')

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
                path = str(self._journal_path.with_suffix('.published-work.png')) if self._journal_path else None
                evidence = wait_for_published_video(page,post_id, ai_required=request.ai_generated,
                            fiction_required=request.fictional_story, evidence_path=path,
                            required_hashtags=request.normalized_hashtags(),expected_title=request.title,
                            dispatch_guard=getattr(self.session,'_guard',None))
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
        """Locate one exact usable button, dispatch one click, never retry it."""
        if self._ai_declaration_required:
            self._require_ai_declaration(page)
        if self._fiction_declaration_required:
            self._require_fiction_declaration(page)
        def log(msg):
            logger.info(msg)
            if interactive:
                print(f"  [诊断] {msg}")

        # Exact full button text includes labels nested in spans. Visibility and
        # native enabled state are inspected before any submission is attempted.
        # Old-class buttons with these labels already belong to this same set.
        selector = ('button:visible:enabled:not([aria-disabled="true"]) >> '
            'xpath=self::*[normalize-space(.)="发布" or normalize-space(.)="立即发布" '
            'or normalize-space(.)="确认发布"]')
        button = page.locator(selector)
        count = button.count()
        self._record('publish_button_located', eligible_count=count)
        if count != 1:
            raise RuntimeError('发布按钮不是唯一可见可用的精确文案按钮，未执行点击。')
        text = ' '.join(button.inner_text().split())
        if text not in {'发布', '立即发布', '确认发布'} or button.count() != 1:
            raise RuntimeError('发布按钮复核发生变化，未执行点击。')
        self._record('publish_click_dispatching', button_text=text, attempt=1)
        try:
            button.click(timeout=15000)
        except Exception as exc:
            self._record('publish_click_outcome_unknown', error_type=type(exc).__name__, attempt=1)
            raise
        self._record('publish_click_returned', attempt=1)
        log('已向唯一发布按钮派发一次点击；后续仅核验原提交结果。')
        # A timeout here also propagates; there is deliberately no second path.
        page.wait_for_timeout(1000)

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
            exact_url=canonical_video(current_url)
            if exact_url:
                return video_id(exact_url),exact_url
            if current_url != last_url:
                log(f"URL变化: {last_url} -> {current_url}")
                last_url = current_url
                if self._is_final_video_url(current_url):
                    post_id = self._extract_post_id(current_url)
                    publish_url = current_url
                    log(f"检测到作品页跳转，post_id: {post_id}")
                    return post_id, publish_url

            # A normal redirect may consume the success toast before polling.
            # Manage navigation starts exact card/ID discovery, never success
            # merely from the route or a matching title elsewhere on the page.
            if is_manage_url(current_url) and title:
                confirmed = self._confirm_publish_in_manage_page(page,title,
                    timeout=min(8,max(1,timeout-(time.time()-start))),interactive=interactive)
                if confirmed:
                    return self._extract_post_id(confirmed),confirmed

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
                    if canonical_video(current_url):
                        return self._extract_post_id(current_url),current_url
                    break

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
        return bool(canonical_video(url))

    def _confirm_publish_in_manage_page(
        self,
        page: Page,
        title: str,
        timeout: int = 90,
        interactive: bool = False,
    ) -> str:
        """Discover only one original-title card carrying an exact canonical ID."""
        if not title:
            return ""
        if not is_manage_url(page.url):
            page.goto(MANAGE_URL,timeout=45000)
        deadline=time.time()+timeout
        while time.time()<deadline:
            if not is_manage_url(page.url):
                return canonical_video(page.url)
            if self._page_requires_login(page):
                raise RuntimeError("原管理会话需要人工登录核验")
            discovery=getattr(page,'discover_published_work',None)
            if callable(discovery):
                evidence=discovery(title)
            else:
                from src.shared.published_work_discovery import discover_published_work
                evidence=discover_published_work(page,title)
            self._record('published_work_discovery',evidence=evidence)
            count=getattr(self,'_publish_discovery_count',0)+1
            self._publish_discovery_count=count
            if self._journal_path is not None and count<=3:
                path=str(self._journal_path.with_suffix(f'.work-discovery-{count}.png'))
                try:
                    if callable(getattr(page,'screenshot',None)):
                        page.screenshot(path=path,full_page=False)
                    else:
                        page._cmd('screenshot',path=path,full_page=False)
                    self._record('published_work_discovery_ui',path=path)
                except Exception as exc:
                    self._record('published_work_discovery_ui_failed',error_type=type(exc).__name__)
            url=canonical_video(evidence.get('publish_url',''))
            if evidence.get('verified') is True and url and video_id(url)==evidence.get('post_id'):
                return url
            if evidence.get('reason') not in ('title_not_unique','canonical_id_missing','independent_card_unbound','manage_loading','title_candidate_missing'):
                return ""
            page.wait_for_timeout(1000)
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
