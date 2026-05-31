import json
import random
import re
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from src.platform_adapter.browser_session import BrowserSession
from src.platform_adapter.models import BrowserSessionConfig
from src.shared.config import settings
from src.shared.logger import logger


WARMUP_ROOT = Path("data/douyin_warmup")
DEFAULT_RECOMMEND_URL = "https://www.douyin.com/jingxuan"
DEFAULT_KEYWORDS = ["小说推荐", "短剧反转", "番茄小说", "书荒推荐", "剧情解说"]


@dataclass
class WarmupAccount:
    account_id: str
    display_name: str = ""
    douyin_uid: str = ""
    login_name: str = ""
    phone_hint: str = ""
    purpose: str = "novel_promotion"
    status: str = "active"
    notes: str = ""
    keywords: list[str] = field(default_factory=list)
    browser_profile_dir: str = ""
    browser_channel: str = ""
    login_status: str = "unknown"
    last_login_at: str = ""
    last_warmup_at: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class WarmupResult:
    account_id: str
    session_id: str
    mode: str
    keyword: str
    videos_seen: int = 0
    status: str = "completed"
    message: str = ""
    log_path: str = ""
    items: list[dict] = field(default_factory=list)


class DouyinWarmupService:
    def __init__(self, root_dir: str | Path = WARMUP_ROOT):
        self.root_dir = Path(root_dir)

    def get_account(self, account_id: str) -> WarmupAccount:
        return self._load_account(account_id)

    def list_accounts(self) -> list[WarmupAccount]:
        accounts_root = self.root_dir / "accounts"
        if not accounts_root.exists():
            return []

        accounts: list[WarmupAccount] = []
        for account_path in sorted(accounts_root.glob("*/account.json")):
            try:
                data = json.loads(account_path.read_text(encoding="utf-8"))
                accounts.append(self._account_from_dict(data))
            except Exception as exc:
                logger.warning(f"读取养号账号失败: {account_path}, {exc}")
        return accounts

    def update_account(
        self,
        account_id: str,
        display_name: str = "",
        douyin_uid: str = "",
        login_name: str = "",
        phone_hint: str = "",
        purpose: str = "",
        status: str = "",
        notes: str = "",
        keywords: list[str] | None = None,
    ) -> WarmupAccount:
        account = self._load_or_create_account(account_id, display_name=display_name)
        if display_name:
            account.display_name = display_name
        if douyin_uid:
            account.douyin_uid = douyin_uid
        if login_name:
            account.login_name = login_name
        if phone_hint:
            account.phone_hint = phone_hint
        if purpose:
            account.purpose = purpose
        if status:
            account.status = status
        if notes:
            account.notes = notes
        if keywords is not None:
            account.keywords = keywords
        self._save_account(account)
        return account

    def open_login_window(
        self,
        account_id: str,
        display_name: str = "",
        url: str = "",
        pause_seconds: int = 900,
        wait_for_enter: bool = False,
    ) -> WarmupAccount:
        account = self._load_or_create_account(account_id, display_name=display_name)
        session = BrowserSession(self._build_session_config(account))
        try:
            session.open_for_manual_login(
                url=url or settings.DOUYIN_HOME_URL,
                pause_seconds=pause_seconds,
                wait_for_enter=wait_for_enter,
            )
            account.login_status = "logged_in" if session.is_authenticated() else "unknown"
            account.last_login_at = self._now()
            if display_name:
                account.display_name = display_name
            self._save_account(account)
            return account
        except Exception:
            account.login_status = "blocked"
            self._save_account(account)
            raise

    def run_warmup(
        self,
        account_id: str,
        mode: str = "daily",
        keyword: str = "",
        min_watch: int = 8,
        max_watch: int = 45,
        max_videos: int = 12,
        duration_minutes: int = 0,
        comment_probability: float = 0.0,
        headless: bool = False,
        keep_open_on_blocked: bool = True,
        start_url: str = "",
        use_search: bool = False,
        keep_open_after_run: bool = False,
        no_comment_max_watch: int = 10,
        duration_ratio_min: float = 0.1,
        duration_ratio_max: float = 2.0,
        like_probability: float = 0.0,
        max_likes: int = 0,
        min_comment_opens: int = 1,
        comment_scrolls: int = 3,
        comment_like_probability: float = 0.0,
        max_comment_likes: int = 0,
    ) -> WarmupResult:
        if min_watch < 1 or (max_watch > 0 and max_watch < min_watch):
            raise ValueError("观看时长参数无效，需满足 min_watch >= 1，且 max_watch 为 0 或 >= min_watch。")
        if max_videos < 1:
            raise ValueError("max_videos 必须大于 0。")
        if comment_probability < 0 or comment_probability > 1:
            raise ValueError("comment_probability 必须在 0 到 1 之间。")
        if like_probability < 0 or like_probability > 1:
            raise ValueError("like_probability 必须在 0 到 1 之间。")
        if max_likes < 0:
            raise ValueError("max_likes 不能小于 0。")
        if comment_like_probability < 0 or comment_like_probability > 1:
            raise ValueError("comment_like_probability 必须在 0 到 1 之间。")
        if max_comment_likes < 0:
            raise ValueError("max_comment_likes 不能小于 0。")
        if min_comment_opens < 0:
            raise ValueError("min_comment_opens 不能小于 0。")
        if comment_scrolls < 0:
            raise ValueError("comment_scrolls 不能小于 0。")

        account = self._load_account(account_id)
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        keyword_pool = account.keywords or DEFAULT_KEYWORDS
        selected_keyword = keyword.strip() or random.choice(keyword_pool)
        result = WarmupResult(
            account_id=account.account_id,
            session_id=session_id,
            mode=mode,
            keyword=selected_keyword,
        )

        config = self._build_session_config(account)
        config.headless = headless
        session = BrowserSession(config)
        started_at = time.time()
        max_seconds = duration_minutes * 60 if duration_minutes > 0 else None
        likes_done = 0
        comment_likes_done = 0
        comment_opens_done = 0

        try:
            target_url = self._build_start_url(selected_keyword, mode, start_url=start_url, use_search=use_search)
            page = session.open_page(target_url)
            page.wait_for_timeout(random.randint(2500, 5000))
            self._prepare_recommend_page(page)

            if self._looks_blocked(page):
                account.login_status = "expired"
                result.status = "blocked"
                result.message = "检测到登录页、验证码或异常提示，已停止。"
            else:
                for index in range(max_videos):
                    if max_seconds is not None and time.time() - started_at >= max_seconds:
                        result.message = "达到本次任务时长上限。"
                        break

                    has_comment_button = self._has_comment_entry(page)
                    video_timing = self._get_video_timing(page)
                    watch_plan = self._resolve_watch_plan(
                        min_watch=min_watch,
                        max_watch=max_watch,
                        has_comment_button=has_comment_button,
                        no_comment_max_watch=no_comment_max_watch,
                        video_timing=video_timing,
                        duration_ratio_min=duration_ratio_min,
                        duration_ratio_max=duration_ratio_max,
                    )
                    watch_seconds = watch_plan["watch_seconds"]
                    title = self._safe_eval(page, "document.title || ''")
                    current_url = page.url
                    logger.info(
                        f"养号浏览 {index + 1}/{max_videos}: watch={watch_seconds}s, "
                        f"has_comment={has_comment_button}, duration={video_timing.get('duration_text', '')}, "
                        f"ratio={watch_plan.get('duration_ratio', '')}, reason={watch_plan.get('reason', '')}, "
                        f"live={video_timing.get('is_live', False)}, url={current_url}"
                    )

                    self._safe_eval(page, "const v=document.querySelector('video'); if(v){v.muted=true; v.play().catch(()=>{});} true;")
                    page.wait_for_timeout(watch_seconds * 1000)

                    opened_comments = False
                    comment_likes = 0
                    should_open_comments = comment_opens_done < min_comment_opens or (
                        comment_probability > 0 and random.random() < comment_probability
                    )
                    if should_open_comments:
                        opened_comments = self._open_comment_area(page)
                        if opened_comments:
                            comment_opens_done += 1
                            self._scroll_comment_area(page, comment_scrolls)
                            if max_comment_likes > 0 and comment_likes_done < max_comment_likes and comment_like_probability > 0:
                                remaining = max_comment_likes - comment_likes_done
                                comment_likes = self._like_random_comments(
                                    page,
                                    probability=comment_like_probability,
                                    max_count=remaining,
                                )
                                comment_likes_done += comment_likes
                            page.wait_for_timeout(random.randint(5000, 20000))

                    liked = False
                    if max_likes > 0 and likes_done < max_likes and like_probability > 0 and random.random() < like_probability:
                        liked = self._click_like_button(page)
                        if liked:
                            likes_done += 1
                            page.wait_for_timeout(random.randint(800, 1800))

                    result.items.append(
                        {
                            "index": index + 1,
                            "title": title,
                        "url": current_url,
                        "watch_seconds": watch_seconds,
                        "has_comment_button": has_comment_button,
                        "video_timing": video_timing,
                        "watch_plan": watch_plan,
                        "opened_comments": opened_comments,
                        "comment_scrolls": comment_scrolls if opened_comments else 0,
                        "comment_likes": comment_likes,
                        "liked": liked,
                    }
                )
                    result.videos_seen += 1

                    if self._looks_blocked(page):
                        account.login_status = "expired"
                        result.status = "blocked"
                        result.message = "浏览过程中检测到登录页、验证码或异常提示，已停止。"
                        break

                    if index < max_videos - 1:
                        page.wait_for_timeout(random.randint(1000, 8000))
                        self._scroll_to_next(page)
                        page.wait_for_timeout(random.randint(1200, 3500))

            if result.status == "blocked" and keep_open_on_blocked and not headless:
                self._wait_for_manual_resolution(session)
                account.login_status = "logged_in"
                result.message = f"{result.message} 已等待用户人工处理并保存浏览器会话。"

            if result.status == "completed" and not result.message:
                result.message = "养号浏览完成。"
            if result.status == "completed":
                account.login_status = "logged_in"
                account.last_warmup_at = self._now()

            if keep_open_after_run and not headless:
                self._wait_for_manual_close(session)
        except Exception as exc:
            result.status = "failed"
            result.message = str(exc)
            raise
        finally:
            result.log_path = self._save_session_log(result)
            self._save_account(account)
            session.stop()

        return result

    def report(self, account_id: str, days: int = 7) -> list[dict]:
        account = self._load_account(account_id)
        logs_dir = self._account_dir(account.account_id) / "logs"
        if not logs_dir.exists():
            return []

        cutoff = time.time() - max(days, 1) * 86400
        rows: list[dict] = []
        for path in sorted(logs_dir.glob("*.json"), reverse=True):
            if path.stat().st_mtime < cutoff:
                continue
            try:
                rows.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception as exc:
                rows.append({"path": str(path), "status": "read_failed", "message": str(exc)})
        return rows

    def _build_start_url(self, keyword: str, mode: str, start_url: str = "", use_search: bool = False) -> str:
        if start_url.strip():
            return start_url.strip()
        if use_search and keyword:
            return f"https://www.douyin.com/search/{quote(keyword)}?type=video"
        return DEFAULT_RECOMMEND_URL

    def _open_comment_area(self, page) -> bool:
        if self._is_comment_area_open(page):
            return True

        js = r"""
        (() => {
          const clickAtCenter = (el) => {
            const rect = el.getBoundingClientRect();
            const x = rect.left + rect.width / 2;
            const y = rect.top + rect.height / 2;
            const target = document.elementFromPoint(x, y) || el;
            target.dispatchEvent(new MouseEvent('mousemove', {clientX: x, clientY: y, bubbles: true}));
            target.dispatchEvent(new MouseEvent('mousedown', {clientX: x, clientY: y, bubbles: true}));
            target.dispatchEvent(new MouseEvent('mouseup', {clientX: x, clientY: y, bubbles: true}));
            target.dispatchEvent(new MouseEvent('click', {clientX: x, clientY: y, bubbles: true}));
            return true;
          };

          const commentSvg = Array.from(document.querySelectorAll('svg[viewBox="0 0 99 99"]')).find(svg => {
            if (svg.offsetParent === null) return false;
            const pathText = Array.from(svg.querySelectorAll('path')).map(path => path.getAttribute('d') || '').join(' ');
            return /C-3\.56,3\.75|-2\.25,-1\.29|C-7\.29,-11\.25/.test(pathText);
          });
          if (commentSvg) return clickAtCenter(commentSvg);

          const actionRows = Array.from(document.querySelectorAll('.FzsqcKBH p'));
          if (actionRows.length >= 2) {
            return clickAtCenter(actionRows[1]);
          }

          const candidates = Array.from(document.querySelectorAll('button, div, span, p'));
          const target = candidates.find(el => /评论/.test((el.innerText || '').trim()) && el.offsetParent !== null);
          if (target) return clickAtCenter(target);
          return false;
        })()
        """
        clicked = bool(self._safe_eval(page, js, default=False))
        if clicked:
            page.wait_for_timeout(random.randint(1000, 2200))
            opened = self._is_comment_area_open(page)
            if opened:
                logger.info("已打开评论区。")
            else:
                logger.warning("已尝试点击评论入口，但未确认评论区打开。")
            return opened
        return False

    def _is_comment_area_open(self, page) -> bool:
        js = r"""
        (() => {
          const card = document.querySelector('#videoSideCard, #relatedVideoCard');
          if (!card) return false;
          const style = window.getComputedStyle(card);
          const rect = card.getBoundingClientRect();
          const text = (card.innerText || '').trim();
          return style.display !== 'none'
            && style.visibility !== 'hidden'
            && card.offsetParent !== null
            && rect.width > 80
            && rect.height > 80
            && text.length > 5;
        })()
        """
        return bool(self._safe_eval(page, js, default=False))

    def _scroll_comment_area(self, page, count: int) -> None:
        if count <= 0:
            return
        for _ in range(count):
            js = r"""
            (() => {
              const card = document.querySelector('#videoSideCard, #relatedVideoCard');
              if (!card) return false;
              const scrollTarget = Array.from(card.querySelectorAll('div')).find(el => el.scrollHeight > el.clientHeight + 80) || card;
              scrollTarget.scrollBy({top: Math.max(180, scrollTarget.clientHeight * 0.65), left: 0, behavior: 'smooth'});
              return true;
            })()
            """
            self._safe_eval(page, js, default=False)
            page.wait_for_timeout(random.randint(900, 1800))

    def _like_random_comments(self, page, probability: float, max_count: int) -> int:
        if max_count <= 0 or probability <= 0:
            return 0
        js = r"""
        ({ probability, maxCount }) => {
          const card = document.querySelector('#videoSideCard, #relatedVideoCard');
          if (!card) return 0;

          const clickAtCenter = (el) => {
            const rect = el.getBoundingClientRect();
            if (!rect.width || !rect.height) return false;
            const x = rect.left + rect.width / 2;
            const y = rect.top + rect.height / 2;
            const target = document.elementFromPoint(x, y) || el;
            target.dispatchEvent(new MouseEvent('mousemove', {clientX: x, clientY: y, bubbles: true}));
            target.dispatchEvent(new MouseEvent('mouseover', {clientX: x, clientY: y, bubbles: true}));
            target.dispatchEvent(new PointerEvent('pointerdown', {clientX: x, clientY: y, bubbles: true, pointerType: 'mouse'}));
            target.dispatchEvent(new MouseEvent('mousedown', {clientX: x, clientY: y, bubbles: true}));
            target.dispatchEvent(new PointerEvent('pointerup', {clientX: x, clientY: y, bubbles: true, pointerType: 'mouse'}));
            target.dispatchEvent(new MouseEvent('mouseup', {clientX: x, clientY: y, bubbles: true}));
            target.dispatchEvent(new MouseEvent('click', {clientX: x, clientY: y, bubbles: true}));
            return true;
          };

          const candidates = Array.from(card.querySelectorAll('[data-e2e="comment-item"] .comment-item-stats-container .FzsqcKBH p.NPOpw1Yj')).filter(el => {
            if (el.offsetParent === null) return false;
            const hasIcon = !!el.querySelector('svg');
            return hasIcon;
          });

          const shuffled = candidates.sort(() => Math.random() - 0.5);
          let clicked = 0;
          for (const el of shuffled) {
            if (clicked >= maxCount) break;
            if (Math.random() > probability) continue;
            if (clickAtCenter(el)) clicked += 1;
          }
          return clicked;
        }
        """
        try:
            result = page.locator("").evaluate(f"({js})({{probability:{probability},maxCount:{max_count}}})")
            count = int(result or 0)
            if count:
                logger.info(f"已随机点赞评论 {count} 条。")
            return count
        except Exception:
            return 0

    def _has_comment_entry(self, page) -> bool:
        js = r"""
        (() => {
          if (document.querySelector('#videoSideCard, #relatedVideoCard')) return true;
          const commentSvg = Array.from(document.querySelectorAll('svg[viewBox="0 0 99 99"]')).find(svg => {
            const pathText = Array.from(svg.querySelectorAll('path')).map(path => path.getAttribute('d') || '').join(' ');
            return /C-3\.56,3\.75|-2\.25,-1\.29|C-7\.29,-11\.25/.test(pathText);
          });
          if (commentSvg) return true;
          if (document.querySelectorAll('.FzsqcKBH p').length >= 2) return true;
          const candidates = Array.from(document.querySelectorAll('button, div, span, svg'));
          return candidates.some(el => {
            const text = (el.innerText || el.getAttribute('aria-label') || '').trim();
            const cls = el.getAttribute('class') || '';
            return /评论/.test(text) || /comment/i.test(cls);
          });
        })()
        """
        return bool(self._safe_eval(page, js, default=False))

    def _click_like_button(self, page) -> bool:
        js = r"""
        (() => {
          const actionRows = Array.from(document.querySelectorAll('.FzsqcKBH p'));
          if (actionRows.length > 0) {
            actionRows[0].click();
            return true;
          }

          const candidates = Array.from(document.querySelectorAll('button, div, p'));
          const target = candidates.find(el => {
            const text = (el.innerText || el.getAttribute('aria-label') || '').trim();
            const cls = el.getAttribute('class') || '';
            return /赞|喜欢/.test(text) || /like|digg/i.test(cls);
          });
          if (target) { target.click(); return true; }
          return false;
        })()
        """
        clicked = bool(self._safe_eval(page, js, default=False))
        if clicked:
            logger.info("已随机执行点赞动作。")
        return clicked

    def _resolve_watch_plan(
        self,
        min_watch: int,
        max_watch: int,
        has_comment_button: bool,
        no_comment_max_watch: int,
        video_timing: dict | None = None,
        duration_ratio_min: float = 0.1,
        duration_ratio_max: float = 2.0,
    ) -> dict:
        timing = video_timing or {}
        duration_seconds = int(timing.get("duration_seconds") or 0)
        is_live = bool(timing.get("is_live"))

        if duration_seconds > 0 and not is_live:
            ratio_low = min(duration_ratio_min, duration_ratio_max)
            ratio_high = max(duration_ratio_min, duration_ratio_max)
            ratio = round(random.uniform(ratio_low, ratio_high), 3)
            watch_seconds = max(min_watch, int(duration_seconds * ratio))
            if max_watch > 0:
                watch_seconds = min(watch_seconds, max_watch)
            return {
                "watch_seconds": watch_seconds,
                "duration_ratio": ratio,
                "reason": "duration_ratio",
            }

        if has_comment_button and not is_live:
            upper = max(min_watch, max_watch) if max_watch > 0 else max(min_watch, 45)
            return {
                "watch_seconds": random.randint(min_watch, upper),
                "duration_ratio": None,
                "reason": "comment_no_duration",
            }

        upper_limit = max(1, no_comment_max_watch)
        if max_watch > 0:
            upper_limit = min(upper_limit, max_watch)
        capped_max = max(min_watch, upper_limit)
        return {
            "watch_seconds": random.randint(min_watch, capped_max),
            "duration_ratio": None,
            "reason": "short_no_comment_or_live",
        }

    def _get_video_timing(self, page) -> dict:
        js = r"""
        (() => {
          const current = document.querySelector('.time-current');
          const duration = document.querySelector('.time-duration');
          const live = document.querySelector('.time-live-tag');
          const isVisible = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
          };
          return {
            current_text: current ? (current.innerText || '').trim() : '',
            duration_text: duration ? (duration.innerText || '').trim() : '',
            is_live: live ? isVisible(live) && /直播/.test(live.innerText || '') : false
          };
        })()
        """
        data = self._safe_eval(page, js, default={}) or {}
        data["current_seconds"] = self._parse_time_text(data.get("current_text", ""))
        data["duration_seconds"] = self._parse_time_text(data.get("duration_text", ""))
        return data

    def _parse_time_text(self, text: str) -> int:
        value = (text or "").strip()
        if not value or not re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", value):
            return 0
        parts = [int(item) for item in value.split(":")]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        return parts[0] * 3600 + parts[1] * 60 + parts[2]

    def _prepare_recommend_page(self, page) -> None:
        self._click_recommend_nav(page)
        page.wait_for_timeout(random.randint(800, 1800))
        self._dismiss_recommend_hint(page)
        page.wait_for_timeout(random.randint(800, 1800))

    def _click_recommend_nav(self, page) -> bool:
        js = r"""
        (() => {
          const links = Array.from(document.querySelectorAll('a'));
          const target = links.find(el => {
            const href = el.getAttribute('href') || '';
            const text = (el.innerText || '').trim();
            return href.includes('recommend=1') || text === '推荐';
          });
          if (target) { target.click(); return true; }
          return false;
        })()
        """
        clicked = bool(self._safe_eval(page, js, default=False))
        if clicked:
            logger.info("已点击抖音精选页的推荐入口。")
        return clicked

    def _dismiss_recommend_hint(self, page) -> bool:
        js = r"""
        (() => {
          const buttons = Array.from(document.querySelectorAll('button'));
          const target = buttons.find(el => (el.innerText || '').trim() === '我知道了');
          if (target) { target.click(); return true; }
          return false;
        })()
        """
        clicked = bool(self._safe_eval(page, js, default=False))
        if clicked:
            logger.info("已关闭抖音精选页滚动引导弹窗。")
        return clicked

    def _scroll_to_next(self, page) -> None:
        js = r"""
        (() => {
          const keyDown = new KeyboardEvent('keydown', {key: 'ArrowDown', code: 'ArrowDown', keyCode: 40, which: 40, bubbles: true});
          const keyUp = new KeyboardEvent('keyup', {key: 'ArrowDown', code: 'ArrowDown', keyCode: 40, which: 40, bubbles: true});
          document.dispatchEvent(keyDown);
          document.body && document.body.dispatchEvent(keyDown);
          window.dispatchEvent(new WheelEvent('wheel', {deltaY: window.innerHeight, bubbles: true}));
          window.scrollBy({top: window.innerHeight * 0.95, left: 0, behavior: 'smooth'});
          document.dispatchEvent(keyUp);
          document.body && document.body.dispatchEvent(keyUp);
          return true;
        })()
        """
        self._safe_eval(page, js)

    def _looks_blocked(self, page) -> bool:
        js = r"""
        (() => {
          const text = document.body ? document.body.innerText : '';
          const url = location.href || '';
          return /login/.test(url) || /扫码登录|验证码|安全验证|账号异常|访问异常|风控/.test(text);
        })()
        """
        return bool(self._safe_eval(page, js, default=False))

    def _safe_eval(self, page, js: str, default=None):
        try:
            return page.locator("").evaluate(js)
        except Exception:
            return default

    def _wait_for_manual_resolution(self, session: BrowserSession) -> None:
        logger.warning("检测到登录/验证码/安全验证，浏览器将保持打开。请在浏览器中处理完成后回到终端按回车。")
        try:
            input("处理完成后按回车保存会话并关闭浏览器...")
        except (EOFError, OSError):
            logger.warning("当前环境无法等待回车，改为等待 10 分钟后保存会话。")
            time.sleep(600)
        try:
            session.save_storage_state()
        except Exception as exc:
            logger.warning(f"保存登录态失败，浏览器 profile 仍会保留本地会话: {exc}")

    def _wait_for_manual_close(self, session: BrowserSession) -> None:
        logger.info("浏览器将保持打开，查看页面后回到终端按回车关闭。")
        try:
            input("查看完成后按回车保存会话并关闭浏览器...")
        except (EOFError, OSError):
            logger.warning("当前环境无法等待回车，改为等待 10 分钟后保存会话。")
            time.sleep(600)
        try:
            session.save_storage_state()
        except Exception as exc:
            logger.warning(f"保存登录态失败，浏览器 profile 仍会保留本地会话: {exc}")

    def _load_or_create_account(self, account_id: str, display_name: str = "") -> WarmupAccount:
        try:
            account = self._load_account(account_id)
            if display_name and account.display_name != display_name:
                account.display_name = display_name
                self._save_account(account)
            return account
        except FileNotFoundError:
            safe_id = self._normalize_account_id(account_id)
            account_dir = self._account_dir(safe_id)
            account = WarmupAccount(
                account_id=safe_id,
                display_name=display_name or safe_id,
                browser_profile_dir=str(account_dir / "profile"),
                browser_channel=settings.BROWSER_CHANNEL,
                keywords=DEFAULT_KEYWORDS.copy(),
                created_at=self._now(),
            )
            self._save_account(account)
            return account

    def _load_account(self, account_id: str) -> WarmupAccount:
        safe_id = self._normalize_account_id(account_id)
        account_path = self._account_dir(safe_id) / "account.json"
        if not account_path.exists():
            raise FileNotFoundError(f"账号不存在，请先运行 douyin-warmup-login --account-id {safe_id}")
        data = json.loads(account_path.read_text(encoding="utf-8"))
        return self._account_from_dict(data)

    def _save_account(self, account: WarmupAccount) -> None:
        account_dir = self._account_dir(account.account_id)
        account_dir.mkdir(parents=True, exist_ok=True)
        Path(account.browser_profile_dir).mkdir(parents=True, exist_ok=True)
        (account_dir / "logs").mkdir(parents=True, exist_ok=True)
        account.updated_at = self._now()
        if not account.created_at:
            account.created_at = account.updated_at
        (account_dir / "account.json").write_text(
            json.dumps(asdict(account), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _account_from_dict(self, data: dict) -> WarmupAccount:
        allowed = {item.name for item in fields(WarmupAccount)}
        filtered = {key: value for key, value in data.items() if key in allowed}
        account = WarmupAccount(**filtered)
        if not account.keywords:
            account.keywords = DEFAULT_KEYWORDS.copy()
        if not account.browser_profile_dir:
            account.browser_profile_dir = str(self._account_dir(account.account_id) / "profile")
        return account

    def _save_session_log(self, result: WarmupResult) -> str:
        log_dir = self._account_dir(result.account_id) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / f"{result.session_id}.json"
        result.log_path = str(path)
        path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def _build_session_config(self, account: WarmupAccount) -> BrowserSessionConfig:
        account_dir = self._account_dir(account.account_id)
        return BrowserSessionConfig(
            base_url=settings.DOUYIN_CREATOR_BASE_URL,
            home_url=settings.DOUYIN_HOME_URL,
            storage_state_path=str(account_dir / "storage_state.json"),
            user_data_dir=account.browser_profile_dir or str(account_dir / "profile"),
            browser_channel=account.browser_channel or settings.BROWSER_CHANNEL,
            headless=False,
            slow_mo_ms=0,
            timeout_ms=30000,
        )

    def _account_dir(self, account_id: str) -> Path:
        return self.root_dir / "accounts" / self._normalize_account_id(account_id)

    def _normalize_account_id(self, account_id: str) -> str:
        value = (account_id or "").strip()
        if not value:
            raise ValueError("缺少 account_id。")
        return re.sub(r"[^a-zA-Z0-9_-]+", "_", value)

    def _now(self) -> str:
        return datetime.now().isoformat(timespec="seconds")
