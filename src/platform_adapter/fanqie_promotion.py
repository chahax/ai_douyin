import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from src.content_factory.presenter import DEFAULT_SONIC_FOX_CHARACTER, PresenterRequest
from src.content_factory.presenter_pipeline import PresenterPipeline
from src.platform_adapter.browser_session import BrowserSession
from src.platform_adapter.models import BrowserSessionConfig
from src.shared.config import settings
from src.shared.llm_client import llm_client
from src.shared.logger import logger


FANQIE_ROOT = Path("data/fanqie_promotion")
FANQIE_NOVEL_CONTENT_URL = "https://kol.fanqieopen.com/page/content?tab_type=2&top_tab_genre=-1"
FANQIE_AUDIO_CONTENT_URL = "https://kol.fanqieopen.com/page/content?tab_type=3&top_tab_genre=-1"
FANQIE_NOVEL_HOME = "https://fanqienovel.com"


@dataclass
class FanqiePromotionTask:
    task_id: str
    account_id: str = "browser_cache"
    content_type: str = "novel"
    book_name: str = ""
    promotion_alias: str = ""
    apply_status: str = "unknown"
    apply_message: str = ""
    kol_content_url: str = ""
    book_url: str = ""
    chapters_dir: str = ""
    material_path: str = ""
    script_path: str = ""
    video_path: str = ""
    work_dir: str = ""
    created_at: str = ""
    updated_at: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class FanqieBookFetchResult:
    book_name: str
    book_url: str
    chapters_dir: str
    material_path: str
    chapters: list[dict] = field(default_factory=list)


class FanqiePromotionService:
    def __init__(self, root_dir: str | Path = FANQIE_ROOT):
        self.root_dir = Path(root_dir)

    def apply_promotion(
        self,
        content_type: str = "novel",
        book_name: str = "",
        alias: str = "",
        wait_for_login: bool = True,
        headless: bool = False,
        keep_open: bool = False,
    ) -> FanqiePromotionTask:
        task = FanqiePromotionTask(
            task_id=self._new_task_id(),
            account_id="browser_cache",
            content_type=content_type,
            book_name=book_name.strip(),
            promotion_alias=alias.strip(),
            apply_status="started",
            kol_content_url=self._content_url(content_type),
            created_at=self._now(),
            updated_at=self._now(),
        )
        task_path = self._task_path(task.task_id)

        session = self._open_browser_cache_session(headless=headless)
        try:
            page = session.open_page(task.kol_content_url)
            page.wait_for_timeout(2500)
            if wait_for_login:
                logger.info("番茄达人中心已打开。请在浏览器中完成登录/验证码后，回到终端按回车继续。")
                input()
                page.wait_for_timeout(1500)

            selected = self._click_apply_button(page, task.book_name)
            if selected.get("book_name"):
                task.book_name = selected["book_name"]
            if not task.book_name:
                task.book_name = self._extract_book_name(selected.get("card_text", ""))

            if not task.promotion_alias:
                task.promotion_alias = self._default_alias(task.book_name)

            page.wait_for_timeout(1200)
            submit = self._fill_alias_and_submit(page, task.promotion_alias)
            page.wait_for_timeout(1500)

            task.apply_status = "submitted" if submit.get("submitted") else "needs_manual_check"
            task.apply_message = submit.get("message", "")
            task.extra = {"selected": selected, "submit": submit}
            task.updated_at = self._now()
            self._write_json(task_path, asdict(task))

            if keep_open:
                input("番茄申请页面保持打开，检查完成后按回车关闭...")
            return task
        except Exception as exc:
            task.apply_status = "failed"
            task.apply_message = str(exc)
            task.updated_at = self._now()
            self._write_json(task_path, asdict(task))
            raise
        finally:
            session.stop()

    def open_login_window(
        self,
        url: str = FANQIE_NOVEL_CONTENT_URL,
        pause_seconds: int = 900,
        wait_for_enter: bool = True,
    ) -> dict:
        session = self._open_browser_cache_session(headless=False)
        state = session.open_for_manual_login(
            url=url or FANQIE_NOVEL_CONTENT_URL,
            pause_seconds=pause_seconds,
            wait_for_enter=wait_for_enter,
        )
        return {
            "login_state": "browser_session",
            "storage_state_path": state.storage_state_path,
            "user_data_dir": state.user_data_dir,
            "authenticated": state.authenticated,
        }

    def fetch_book(
        self,
        book_name: str,
        chapters: int = 10,
        headless: bool = True,
    ) -> FanqieBookFetchResult:
        if not book_name.strip():
            raise RuntimeError("缺少小说名称。")
        session = self._open_browser_cache_session(headless=headless)
        try:
            page = session.open_page(f"{FANQIE_NOVEL_HOME}/search/{quote(book_name.strip())}")
            page.wait_for_timeout(3500)
            book = self._extract_search_result(page, book_name.strip())
            if not book.get("url"):
                book = self._search_book_api(page, book_name.strip())
            if not book.get("url"):
                raise RuntimeError(f"未找到小说搜索结果: {book_name}")

            page.goto(book["url"])
            page.wait_for_timeout(2500)
            chapter_links = self._extract_chapter_links(page, max_count=chapters)
            if not chapter_links:
                raise RuntimeError(f"未找到章节目录: {book['url']}")

            book_dir = self.root_dir / "books" / self._safe_name(book.get("title") or book_name)
            chapters_dir = book_dir / "chapters"
            chapters_dir.mkdir(parents=True, exist_ok=True)
            fetched = []
            for idx, chapter in enumerate(chapter_links[:chapters], start=1):
                page.goto(chapter["url"])
                page.wait_for_timeout(1500)
                text = self._extract_reader_text(page)
                chapter_title = chapter.get("title") or f"第{idx}章"
                chapter_path = chapters_dir / f"{idx:03d}.txt"
                self._write_text(chapter_path, f"{chapter_title}\n\n{text}\n")
                fetched.append({"index": idx, "title": chapter_title, "url": chapter["url"], "path": str(chapter_path)})

            material_path = book_dir / "material.txt"
            material = [f"小说名称：{book.get('title') or book_name}", f"小说页面：{book['url']}", ""]
            for item in fetched:
                material.append(Path(item["path"]).read_text(encoding="utf-8"))
                material.append("\n")
            self._write_text(material_path, "\n".join(material).strip() + "\n")
            return FanqieBookFetchResult(
                book_name=book.get("title") or book_name,
                book_url=book["url"],
                chapters_dir=str(chapters_dir),
                material_path=str(material_path),
                chapters=fetched,
            )
        finally:
            session.stop()

    def generate_promo_video(
        self,
        task_file: str = "",
        book_name: str = "",
        chapters: int = 10,
        alias: str = "",
        output_dir: str = "data/videos",
        max_segments: int = 0,
        no_comfy_background: bool = False,
        assets_only: bool = False,
    ) -> FanqiePromotionTask:
        task = self._load_or_create_task(task_file=task_file, book_name=book_name, alias=alias)
        if not task.material_path:
            fetched = self.fetch_book(task.book_name, chapters=chapters, headless=True)
            task.book_name = fetched.book_name
            task.book_url = fetched.book_url
            task.chapters_dir = fetched.chapters_dir
            task.material_path = fetched.material_path

        script = self._generate_script(task)
        task_dir = self.root_dir / "tasks" / task.task_id
        script_path = task_dir / "promo_script.txt"
        self._write_text(script_path, script)
        task.script_path = str(script_path)

        presenter = PresenterPipeline()
        request = PresenterRequest(
            keywords=f"{task.book_name}, 小说推广, 番茄小说",
            text=script,
            input_mode="article_direct",
            title=task.book_name or "小说推广",
            character=DEFAULT_SONIC_FOX_CHARACTER,
            output_dir=output_dir,
            max_segments=max_segments,
            use_comfy_background=not no_comfy_background,
        )
        result = presenter.run_assets_preview(request) if assets_only else presenter.run(request)
        if not result.success:
            raise RuntimeError(result.message)

        task.work_dir = result.work_dir
        task.video_path = result.video_path
        task.updated_at = self._now()
        self._write_json(self._task_path(task.task_id), asdict(task))
        return task

    def _click_apply_button(self, page, book_name: str) -> dict:
        js = f"""
        () => {{
          const wanted = {json.dumps(book_name, ensure_ascii=False)};
          const visible = el => {{
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
          }};
          const textOf = el => (el.innerText || el.textContent || '').trim();
          const cards = Array.from(document.querySelectorAll('.book-hQ7GYr')).filter(visible);
          const candidates = cards.map(card => {{
            const titleEl = card.querySelector('.book-title-txt-_CIhYa');
            const title = textOf(titleEl || card.querySelector('[class*=book-title]') || card).split('\n')[0].trim();
            const button = Array.from(card.querySelectorAll('button')).find(btn => textOf(btn).includes('别名推广'));
            return {{card, button, title, cardText: textOf(card).replace(/\n{{3,}}/g, '\n').slice(0, 1200)}};
          }}).filter(item => item.button && item.title);

          if (!candidates.length) {{
            const fallbackButtons = Array.from(document.querySelectorAll('button')).filter(btn => visible(btn) && textOf(btn).includes('别名推广'));
            for (const button of fallbackButtons) {{
              const card = button.closest('.book-hQ7GYr') || button.parentElement;
              const titleEl = card && card.querySelector('.book-title-txt-_CIhYa');
              candidates.push({{card, button, title: textOf(titleEl || card || button).split('\n')[0].trim(), cardText: textOf(card || button)}});
            }}
          }}

          if (!candidates.length) return {{clicked:false, message:'未找到别名推广按钮'}};
          let picked = candidates[0];
          if (wanted) {{
            const exact = candidates.find(c => c.title.includes(wanted) || c.cardText.includes(wanted));
            if (exact) picked = exact;
          }}
          picked.button.scrollIntoView({{block:'center', inline:'center'}});
          picked.button.click();
          return {{clicked:true, button_text:textOf(picked.button), book_name:picked.title, card_text:picked.cardText}};
        }}
        """
        result = page.locator("").evaluate(js)
        if not result.get("clicked"):
            raise RuntimeError(result.get("message") or "未找到申请按钮")
        return result

    def _fill_alias_and_submit(self, page, alias: str) -> dict:
        js = f"""
        async () => {{
          const alias = {json.dumps(alias, ensure_ascii=False)};
          const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
          const visible = el => {{
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
          }};
          const textOf = el => (el.innerText || el.textContent || '').trim();
          const modal = Array.from(document.querySelectorAll('.arco-modal-content')).find(visible) || document.body;
          const bookInfo = textOf(modal.querySelector('.book-info-ytEh1A') || Array.from(modal.querySelectorAll('.task-info-row-I9KS_b')).find(row => textOf(row).includes('书籍信息')) || modal);
          const target = modal.querySelector('.alias-input-EBp1Sw') || Array.from(modal.querySelectorAll('input,textarea,[contenteditable="true"]')).find(el => /别名|昵称|名称|推广/.test([el.placeholder, el.name, el.id, el.getAttribute('aria-label'), el.parentElement?.innerText].join(' ')));
          if (!target) return {{submitted:false, message:'未找到别名输入框', book_info: bookInfo}};
          target.scrollIntoView({{block:'center', inline:'center'}});
          target.focus();
          if (target.isContentEditable) {{
            target.textContent = alias;
          }} else {{
            target.value = alias;
          }}
          target.dispatchEvent(new Event('input', {{bubbles:true}}));
          target.dispatchEvent(new Event('change', {{bubbles:true}}));

          const select = Array.from(modal.querySelectorAll('.arco-select')).find(visible);
          let publishTypeSelected = false;
          if (select && textOf(select).includes('请选择')) {{
            select.scrollIntoView({{block:'center', inline:'center'}});
            select.click();
            await sleep(500);
            const options = Array.from(document.querySelectorAll('.arco-select-option, [role="option"')).filter(visible);
            const preferred = ['视频', '短视频', '图文', '解说', '推文'];
            const picked = options.find(opt => preferred.some(word => textOf(opt).includes(word))) || options[0];
            if (picked) {{
              picked.click();
              publishTypeSelected = true;
              await sleep(500);
            }}
          }}

          const submitTexts = ['提交', '确认申请', '提交申请', '申请推广', '确认', '确定'];
          let submit = null;
          for (let i = 0; i < 20; i++) {{
            const buttons = Array.from(modal.querySelectorAll('button')).filter(visible);
            submit = buttons.find(btn => submitTexts.some(t => textOf(btn).includes(t)) && !btn.disabled && !btn.className.includes('disabled'));
            if (submit) break;
            await sleep(300);
          }}
          if (!submit) return {{submitted:false, message:'已填写别名，但提交按钮未启用或未找到', alias, book_info: bookInfo, publish_type_selected: publishTypeSelected}};
          submit.scrollIntoView({{block:'center', inline:'center'}});
          submit.click();
          return {{submitted:true, message:'已填写别名、选择发文类型并点击提交', alias, book_info: bookInfo, publish_type_selected: publishTypeSelected}};
        }}
        """
        return page.locator("").evaluate(js)

    def _extract_search_result(self, page, book_name: str) -> dict:
        js = f"""
        () => {{
          const wanted = {json.dumps(book_name, ensure_ascii=False)};
          const links = Array.from(document.querySelectorAll('a[href*="/page/"]')).map(a => {{
            const text = (a.innerText || a.textContent || '').trim().replace(/\\s+/g, '\\n');
            return {{title: text.split('\\n').find(x => x.length >= 2 && x.length <= 60) || text.slice(0, 60), text, url: new URL(a.getAttribute('href'), location.href).href}};
          }}).filter(x => x.url && x.title);
          return links.find(x => x.text.includes(wanted) || x.title.includes(wanted)) || links[0] || {{}};
        }}
        """
        return page.locator("").evaluate(js)

    def _search_book_api(self, page, book_name: str) -> dict:
        api_url = (
            f"{FANQIE_NOVEL_HOME}/api/author/search/search_book/v1"
            f"?filter=127,127,127,127&page_count=10&page_index=0&query_type=0&query_word={quote(book_name)}"
        )
        try:
            js = f"""
            async () => {{
              const resp = await fetch({json.dumps(api_url)}, {{
                method: 'GET',
                credentials: 'include',
                headers: {{
                  'Accept': 'application/json, text/javascript',
                  'Content-Type': 'application/x-www-form-urlencoded'
                }}
              }});
              const text = await resp.text();
              return {{status: resp.status, text}};
            }}
            """
            api_result = page.locator("").evaluate(js)
            if int(api_result.get("status") or 0) >= 400:
                logger.warning(f"番茄搜索接口状态异常: {api_result.get('status')}")
                return {}
            data = json.loads(api_result.get("text") or "{}")
        except Exception as exc:
            logger.warning(f"番茄搜索接口请求失败: {exc}")
            return {}

        books = self._collect_book_like_items(data)
        for item in books:
            title = str(item.get("book_name") or item.get("bookName") or item.get("title") or item.get("name") or "")
            book_id = str(item.get("book_id") or item.get("bookId") or item.get("bookID") or item.get("id") or "")
            if book_id and (not book_name or book_name in title or title in book_name):
                return {"title": title or book_name, "url": f"{FANQIE_NOVEL_HOME}/page/{book_id}", "raw": item}
        for item in books:
            book_id = str(item.get("book_id") or item.get("bookId") or item.get("bookID") or item.get("id") or "")
            if book_id:
                title = str(item.get("book_name") or item.get("bookName") or item.get("title") or item.get("name") or book_name)
                return {"title": title, "url": f"{FANQIE_NOVEL_HOME}/page/{book_id}", "raw": item}
        return {}

    def _collect_book_like_items(self, value) -> list[dict]:
        found: list[dict] = []
        if isinstance(value, dict):
            keys = set(value.keys())
            if keys & {"book_id", "bookId", "bookID"} and keys & {"book_name", "bookName", "title", "name"}:
                found.append(value)
            for child in value.values():
                found.extend(self._collect_book_like_items(child))
        elif isinstance(value, list):
            for child in value:
                found.extend(self._collect_book_like_items(child))
        return found

    def _extract_chapter_links(self, page, max_count: int) -> list[dict]:
        js = f"""
        () => {{
          const seen = new Set();
          return Array.from(document.querySelectorAll('a[href*="/reader/"]')).map(a => {{
            const title = (a.innerText || a.textContent || '').trim();
            const match = title.match(/第\\s*(\\d+)\\s*章/);
            return {{title, number: match ? Number(match[1]) : 0, url: new URL(a.getAttribute('href'), location.href).href}};
          }}).filter(x => x.title && x.number > 0 && !seen.has(x.url) && seen.add(x.url))
            .sort((a, b) => a.number - b.number)
            .slice(0, {int(max_count)});
        }}
        """
        return page.locator("").evaluate(js) or []

    def _extract_reader_text(self, page) -> str:
        js = """
        () => {
          const candidates = Array.from(document.querySelectorAll('article,main,[class*=reader],[class*=content],body'));
          const best = candidates.map(el => (el.innerText || el.textContent || '').trim()).sort((a,b) => b.length - a.length)[0] || document.body.innerText || '';
          return best;
        }
        """
        text = page.locator("").evaluate(js) or ""
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"(下一章|加书架|目录|夜间|字号|下载|领红包)[\s\S]*$", "", text).strip()
        return text

    def _generate_script(self, task: FanqiePromotionTask) -> str:
        material = Path(task.material_path).read_text(encoding="utf-8")
        material = material[:12000]
        prompt = f"""请根据下面小说前文素材，生成一条60-90秒中文短视频推广口播稿。
要求：
1. 开头3秒必须有剧情钩子，不要说“大家好”。
2. 不剧透大结局，只提炼人物冲突、爽点、悬念和情绪张力。
3. 结尾给评论区搜索引导：想看原文，在评论区搜“{task.book_name}”。
4. 不要输出Markdown，只输出JSON：{{"title":"","script_content":"","comment_keyword":""}}。

小说名：{task.book_name}
推广别名：{task.promotion_alias}
素材：
{material}
"""
        messages = [
            {"role": "system", "content": "你是小说推文短视频编导，只输出JSON。"},
            {"role": "user", "content": prompt},
        ]
        response = llm_client.chat_completion(messages, temperature=0.55, json_mode=True)
        if response:
            cleaned = response.replace("```json", "").replace("```", "").strip()
            try:
                data = json.loads(cleaned)
                script = data.get("script_content") or data.get("script") or ""
                if script:
                    return str(script).strip()
            except json.JSONDecodeError:
                logger.warning("小说推广脚本 JSON 解析失败，使用兜底脚本。")
        return self._fallback_script(task)

    def _fallback_script(self, task: FanqiePromotionTask) -> str:
        return (
            f"如果一个人明明被所有人看轻，却偏偏藏着最不服输的底牌，你会不会继续看下去？\n"
            f"这本《{task.book_name}》开局就把人物冲突拉满，主角被传成绝世天才，可真正的麻烦也跟着来了。\n"
            "有人等着看他露馅，有人想借他的名声布局，还有人一步步把他推到风口浪尖。\n"
            "前几章最抓人的地方，不是单纯变强，而是主角怎么在误会、质疑和机会之间，把局面一点点翻回来。\n"
            f"想看原文，在评论区搜“{task.book_name}”。"
        )

    def _load_or_create_task(self, task_file: str, book_name: str, alias: str) -> FanqiePromotionTask:
        if task_file:
            data = json.loads(Path(task_file).read_text(encoding="utf-8"))
            return FanqiePromotionTask(**data)
        if not book_name.strip():
            raise RuntimeError("缺少 --task-file 或 --book-name。")
        now = self._now()
        return FanqiePromotionTask(
            task_id=self._new_task_id(),
            account_id="browser_cache",
            book_name=book_name.strip(),
            promotion_alias=alias.strip() or self._default_alias(book_name),
            apply_status="manual_or_skipped",
            created_at=now,
            updated_at=now,
        )

    def _open_browser_cache_session(self, headless: bool) -> BrowserSession:
        config = BrowserSessionConfig(
            base_url="https://kol.fanqieopen.com",
            home_url=FANQIE_NOVEL_CONTENT_URL,
            storage_state_path="./data/browser/fanqie/storage_state.json",
            user_data_dir="./data/browser/fanqie/user_data",
            browser_channel=settings.BROWSER_CHANNEL,
            headless=headless,
            slow_mo_ms=settings.BROWSER_SLOW_MO_MS,
            timeout_ms=settings.BROWSER_TIMEOUT_MS,
        )
        return BrowserSession(config)

    def _content_url(self, content_type: str) -> str:
        return FANQIE_AUDIO_CONTENT_URL if content_type == "audio" else FANQIE_NOVEL_CONTENT_URL

    def _task_path(self, task_id: str) -> Path:
        return self.root_dir / "tasks" / task_id / "task.json"

    def _write_json(self, path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _new_task_id(self) -> str:
        return time.strftime("%Y%m%d_%H%M%S")

    def _now(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _default_alias(self, book_name: str) -> str:
        date = time.strftime("%m%d")
        base = re.sub(r"\s+", "", book_name or "小说推广")
        return f"{base[:12]}-{date}"

    def _safe_name(self, value: str) -> str:
        value = re.sub(r"[\\/:*?\"<>|\s]+", "_", value.strip())
        return value[:80] or self._new_task_id()

    def _extract_book_name(self, text: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines:
            if 2 <= len(line) <= 40 and not re.search(r"申请|推广|佣金|达人|收益|状态|任务", line):
                return line
        return ""
