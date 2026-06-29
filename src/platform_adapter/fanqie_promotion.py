import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from string import Template
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
FANQIE_NOVEL_LIST_URL = "https://kol.fanqieopen.com/page/promotion-list?tab_type=2&top_tab_genre=-1"
FANQIE_AUDIO_LIST_URL = "https://kol.fanqieopen.com/page/promotion-list?tab_type=3&top_tab_genre=-1"
FANQIE_NOVEL_HOME = "https://fanqienovel.com"

# list 页别名状态文案 → 内部状态
FANQIE_ALIAS_STATUS_MAP = {
    "生效中": "active",
    "审核中": "under_review",
    "审核不通过": "rejected",
    "已失效": "expired",
}

# 弹窗发文类型下拉的实际选项（用户从 kol.fanqieopen.com 抓取）。
# 番茄推广偏好 AI 数字人 > AIGC > 真人出镜；其他作为兜底。
FANQIE_PUBLISH_TYPE_PREFERRED = [
    "AI数字人",
    "AIGC",
    "真人出镜",
    "图文",
    "解说混剪",
    "视频",
]

# 申请状态机说明：
#   started            任务初始化完成
#   submitted          提交按钮已点击，等待审核
#   pending_review     番茄弹"别名创建成功"，进入审核队列（实测秒过）
#   under_review       list 页查到"审核中"
#   active             list 页查到"生效中"（可开始推广）
#   rejected           list 页查到"审核不通过"
#   expired            list 页查到"已失效"
#   alias_taken        推荐别名/手填别名被他人占用
#   needs_manual_check 流程中断，需要人工介入
#   manual_or_skipped  跳过 apply 直接进入 fetch_book 阶段
#   failed             异常


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
    book_id: str = ""
    chapters: list[dict] = field(default_factory=list)


# ── 弹窗操作 JS 模板 ──────────────────────────────────────────────────────
# 用 string.Template ($var) 而非 f-string，避免 {} 转义陷阱。
# Python 端用 .substitute() 注入 json.dumps 后的字符串字面量。

CLICK_APPLY_JS = Template(r"""
() => {
  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const textOf = el => (el.innerText || el.textContent || '').trim();
  const wanted = $wanted;

  // 稳定 hook .c-promotions 找书卡
  let cards = Array.from(document.querySelectorAll('.c-promotions'))
    .map(box => box.closest('.book-hQ7GYr'))
    .filter(Boolean);
  if (!cards.length) {
    // 兜底：直接选所有书卡
    cards = Array.from(document.querySelectorAll('.book-hQ7GYr')).filter(visible);
  }
  if (!cards.length) return { clicked: false, message: '未找到书卡' };

  let picked = cards[0];
  if (wanted) {
    const exact = cards.find(c => {
      const tEl = c.querySelector('.book-title-txt-_CIhYa');
      const title = tEl ? textOf(tEl) : '';
      return title.includes(wanted) || textOf(c).includes(wanted);
    });
    if (exact) picked = exact;
  }

  // 优先用稳定 hook .c-promotions button
  const button = picked.querySelector('.c-promotions button')
    || Array.from(picked.querySelectorAll('button')).find(b => textOf(b).includes('别名推广'));
  if (!button) return { clicked: false, message: '书卡里未找到别名推广按钮' };

  button.scrollIntoView({ block: 'center', inline: 'center' });
  button.click();

  const titleEl = picked.querySelector('.book-title-txt-_CIhYa');
  return {
    clicked: true,
    book_name: titleEl ? textOf(titleEl) : '',
    button_text: textOf(button),
  };
}
""")


FILL_AND_SUBMIT_JS = Template(r"""
async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const textOf = el => (el.innerText || el.textContent || '').trim();

  const wantAlias = $alias;
  const publishType = $publish_type;
  const maxAttempts = $max_attempts;

  // 等弹窗出现（最长 6 秒）
  let modal = null;
  for (let i = 0; i < 30; i++) {
    modal = Array.from(document.querySelectorAll('.arco-modal-content')).find(visible);
    if (modal && modal.querySelector('.alias-input-EBp1Sw')) break;
    modal = null;
    await sleep(200);
  }
  if (!modal) return { submitted: false, step: 'wait_modal', message: '弹窗未出现' };

  const input = modal.querySelector('.alias-input-EBp1Sw');
  if (!input) return { submitted: false, step: 'find_input', message: '未找到别名 input' };

  const recommends = Array.from(modal.querySelectorAll('.recommend-alias-name-ISh2a3'));
  const candidates = [];
  if (wantAlias) candidates.push({ alias: wantAlias, source: 'manual' });
  recommends.forEach((el, i) => candidates.push({ alias: textOf(el), source: 'recommend', index: i }));
  if (!candidates.length) {
    return { submitted: false, step: 'no_alias', message: '未指定 alias 且无推荐别名' };
  }

  input.scrollIntoView({ block: 'center' });
  input.focus();

  let publishTypeSelected = false;
  let publishTypeText = '';
  const triedLog = [];
  const lastIdx = Math.min(maxAttempts, candidates.length) - 1;

  // 循环尝试每个候选 alias
  for (let ci = 0; ci <= lastIdx; ci++) {
    const cand = candidates[ci];
    triedLog.push(cand.alias);

    // 1) 填 input
    input.value = cand.alias;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));

    // 2) 等客户端实时校验（最多 1.5 秒）
    let clientErr = '';
    for (let i = 0; i < 8; i++) {
      const errBox = input.parentElement.querySelector('.err-list-h4mOz7');
      clientErr = errBox ? textOf(errBox) : '';
      if (clientErr) break;
      await sleep(200);
    }
    if (clientErr) {
      // 客户端撞名；继续下一个
      continue;
    }

    // 3) 选发文类型（第一次设置）
    if (!publishTypeSelected) {
      const select = Array.from(modal.querySelectorAll('.arco-select')).find(visible);
      if (select && textOf(select).includes('请选择')) {
        select.scrollIntoView({ block: 'center' });
        select.click();
        await sleep(600);
        const options = Array.from(document.querySelectorAll('.arco-select-option, [role="option"]')).filter(visible);
        const picked = options.find(o => textOf(o) === publishType) || options[0];
        if (picked) {
          picked.click();
          publishTypeSelected = true;
          publishTypeText = textOf(picked);
          await sleep(400);
        }
      }
    }

    // 4) 等提交按钮可点
    let submit = null;
    let waitedMs = 0;
    for (let i = 0; i < 20; i++) {
      const buttons = Array.from(modal.querySelectorAll('button')).filter(visible);
      submit = buttons.find(b => {
        const t = textOf(b);
        return /提交|确认申请|提交申请/.test(t) && !b.disabled && !b.className.includes('disabled');
      });
      if (submit) break;
      waitedMs += 300;
      await sleep(300);
    }
    if (!submit) {
      return {
        submitted: false,
        step: 'submit_disabled',
        message: '提交按钮未启用或未找到',
        alias: cand.alias,
        tried: triedLog,
        tried_count: ci + 1,
      };
    }

    // 5) 点击提交
    submit.scrollIntoView({ block: 'center' });
    submit.click();

    // 6) 等服务端响应（最多 6 秒）
    let serverResult = null;
    for (let i = 0; i < 12; i++) {
      // 服务端撞名：err-list 重新出现
      const errBox = input.parentElement.querySelector('.err-list-h4mOz7');
      if (errBox && textOf(errBox).trim()) {
        serverResult = { status: 'alias_taken', message: textOf(errBox).trim() };
        break;
      }
      // 成功弹窗
      const successTitle = Array.from(document.querySelectorAll('.title-azi_qL')).find(visible);
      if (successTitle) {
        const desc = Array.from(document.querySelectorAll('.desc-RDMKS1')).find(visible);
        serverResult = {
          status: 'pending_review',
          title: textOf(successTitle),
          message: desc ? textOf(desc).slice(0, 800) : '',
        };
        break;
      }
      await sleep(500);
    }

    if (!serverResult) serverResult = { status: 'timeout', message: '等待服务端响应超时' };

    if (serverResult.status === 'alias_taken') {
      // 服务端撞名：换下一个候选
      continue;
    }

    // 成功（pending_review）或超时：结束
    return {
      submitted: true,
      alias: cand.alias,
      recommend_index: cand.source === 'recommend' ? cand.index : -1,
      tried: triedLog,
      tried_count: ci + 1,
      publish_type: publishTypeText,
      publish_type_selected: publishTypeSelected,
      waited_ms: waitedMs,
      wait: serverResult,
      step: 'submitted',
    };
  }

  return {
    submitted: false,
    step: 'all_aliases_taken',
    message: '所有候选别名都被占用',
    tried: triedLog,
    tried_count: triedLog.length,
  };
}
""")


# 旧的 FILL_MODAL_JS / WAIT_RESULT_JS 已被 FILL_AND_SUBMIT_JS 取代
FILL_MODAL_JS = FILL_AND_SUBMIT_JS  # alias for backwards-compat
WAIT_RESULT_JS = r"""
async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const textOf = el => (el.innerText || el.textContent || '').trim();

  for (let i = 0; i < 60; i++) {
    const successTitle = Array.from(document.querySelectorAll('.title-azi_qL')).find(visible);
    if (successTitle) {
      const desc = Array.from(document.querySelectorAll('.desc-RDMKS1')).find(visible);
      return { status: 'pending_review', title: textOf(successTitle), message: desc ? textOf(desc).slice(0, 800) : '' };
    }
    const errBox = document.querySelector('.err-list-h4mOz7');
    if (errBox && textOf(errBox).trim()) {
      return { status: 'alias_taken', message: textOf(errBox).trim() };
    }
    const modalVisible = Array.from(document.querySelectorAll('.arco-modal-content')).some(visible);
    if (!modalVisible && i > 5) return { status: 'closed', message: '弹窗关闭，未识别到结果' };
    await sleep(500);
  }
  return { status: 'timeout', message: '等待结果超时（30s）' };
}
"""


# 扫推广列表页：每行 { alias, book_name, book_id, content_type, publish_type, alias_status, book_status, fill_status, created_at, valid_range }
LIST_PROMOTIONS_JS = r"""
() => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const textOf = el => (el.innerText || el.textContent || '').trim();
  const rows = Array.from(document.querySelectorAll('.arco-table-tr'));

  // 过滤：跳过 thead
  const dataRows = rows.filter(r => r.closest('thead') === null);
  const out = dataRows.map(row => {
    const cells = Array.from(row.querySelectorAll('.arco-table-td'));
    // 用 first-child textContent 提取列（部分 cell 内含嵌套 div）
    const cellText = i => cells[i] ? textOf(cells[i]).replace(/\s+/g, ' ').trim() : '';

    // 别名状态：.alias-status-ButiOZ 文本（去除 svg 等）
    const statusEl = row.querySelector('.alias-status-ButiOZ');
    const aliasStatusText = statusEl ? textOf(statusEl) : '';

    // 书本信息：.book-name-iHil3A + .extra-info-hpGb2J
    const bookNameEl = row.querySelector('.book-name-iHil3A');
    const extraEl = row.querySelector('.extra-info-hpGb2J');
    const bookName = bookNameEl ? textOf(bookNameEl) : '';
    const extraText = extraEl ? textOf(extraEl) : '';
    const bookIdMatch = extraText.match(/id:\s*(\d+)/);
    const bookId = bookIdMatch ? bookIdMatch[1] : '';

    // 回填状态：第 7 列（"未填写" 或带"回填发文" link）
    const fillText = cellText(6);
    const hasFillLink = !!row.querySelector('.arco-table-cell .link');

    return {
      alias: cellText(0),
      book_name: bookName,
      book_id: bookId,
      content_type: cellText(2),
      publish_type: cellText(3),
      alias_status: aliasStatusText,
      book_status: cellText(5),
      fill_status: fillText,
      has_fill_link: hasFillLink,
      created_at: cellText(7),
      valid_range: cellText(8),
    };
  }).filter(r => r.alias);

  return { count: out.length, items: out };
}
"""


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
        auto_submit: bool = True,
        publish_type: str = "AI数字人",
        max_alias_attempts: int = 5,
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

            # 1) 点击书卡
            click_js = CLICK_APPLY_JS.substitute(
                wanted=json.dumps(book_name.strip(), ensure_ascii=False),
            )
            click_result = page.locator("").evaluate(click_js)
            if click_result.get("clicked"):
                page.wait_for_timeout(3000)  # 等弹窗 + 推荐别名异步加载
            if not click_result.get("clicked"):
                raise RuntimeError(click_result.get("message", "未找到书卡"))
            if click_result.get("book_name"):
                task.book_name = click_result["book_name"]

            # 2) 填表 + 提交 + 等结果（含 alias 重试循环）
            if auto_submit:
                fill_js = FILL_AND_SUBMIT_JS.substitute(
                    alias=json.dumps(task.promotion_alias, ensure_ascii=False),
                    publish_type=json.dumps(publish_type, ensure_ascii=False),
                    max_attempts=str(max(1, max_alias_attempts)),
                )
                fill_result = page.locator("").evaluate(fill_js)
                wait_result = fill_result.get("wait") or {"status": "submitted", "message": "已提交"}
            else:
                # 不自动提交：只填表，停在提交按钮前
                fill_js = FILL_AND_SUBMIT_JS.substitute(
                    alias=json.dumps(task.promotion_alias, ensure_ascii=False),
                    publish_type=json.dumps(publish_type, ensure_ascii=False),
                    max_attempts="1",
                )
                # 截断：不在 JS 里点击 submit，靠不点 submit 实现 dry-run
                fill_result = page.locator("").evaluate(fill_js)
                wait_result = {"status": "manual_confirm", "message": "未自动提交，等待用户确认"}

            if fill_result.get("alias"):
                task.promotion_alias = fill_result["alias"]
            elif not task.promotion_alias:
                task.promotion_alias = self._default_alias(task.book_name)

            task.extra = {"click": click_result, "fill": fill_result}

            if not fill_result.get("submitted"):
                task.apply_status = "needs_manual_check"
                task.apply_message = fill_result.get("message", "提交未完成")
                task.updated_at = self._now()
                self._write_json(task_path, asdict(task))
                if keep_open:
                    input("弹窗填写未完成，检查后按回车关闭...")
                return task

            status_map = {
                "pending_review": "pending_review",
                "alias_taken": "alias_taken",
                "closed": "submitted",
                "timeout": "needs_manual_check",
                "submitted": "submitted",
                "manual_confirm": "submitted_pending_confirm",
            }
            task.apply_status = status_map.get(wait_result.get("status"), "needs_manual_check")
            task.apply_message = wait_result.get("message", fill_result.get("message", ""))
            task.updated_at = self._now()
            self._write_json(task_path, asdict(task))

            if keep_open:
                input(
                    f"申请结果：{task.apply_status}。"
                    f"按回车关闭浏览器..."
                )
            return task
        except Exception as exc:
            task.apply_status = "failed"
            task.apply_message = str(exc)
            task.updated_at = self._now()
            self._write_json(task_path, asdict(task))
            raise
        finally:
            session.stop()

    def list_books(self) -> list[dict]:
        """扫 data/fanqie_promotion/books/ 下所有 meta.json，返回已抓书籍列表。

        返回 [{ book_id, book_name, author, tags, categories, abstract, total_chapters_seen, chapters_fetched, paywall_hit, scraped_at }]
        """
        books_dir = self.root_dir / "books"
        if not books_dir.exists():
            return []
        out = []
        for entry in sorted(books_dir.iterdir()):
            if not entry.is_dir():
                continue
            meta_path = entry / "meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            out.append({
                "book_id": meta.get("book_id", ""),
                "book_name": meta.get("book_name", ""),
                "dir": entry.name,
                "author": meta.get("author", ""),
                "tags": meta.get("tags", []),
                "categories": meta.get("categories", []),
                "abstract_preview": (meta.get("abstract") or "")[:80],
                "total_chapters_seen": meta.get("total_chapters_seen", 0),
                "chapters_fetched": meta.get("chapters_fetched", 0),
                "paywall_hit": meta.get("paywall_hit", False),
                "scraped_at": meta.get("scraped_at", ""),
            })
        return out

    def list_promotions(
        self,
        content_type: str = "novel",
        headless: bool = False,
        sync_to_tasks: bool = True,
    ) -> dict:
        """扫推广列表页，返回所有别名状态；可选同步到 tasks/<id>/task.json。

        Returns:
            dict: { content_type, count, items: [...], synced: [task_id, ...] }
        """
        url = FANQIE_AUDIO_LIST_URL if content_type == "audio" else FANQIE_NOVEL_LIST_URL
        session = self._open_browser_cache_session(headless=headless)
        try:
            page = session.open_page(url)
            page.wait_for_timeout(3000)  # 等表格异步加载
            result = page.locator("").evaluate(LIST_PROMOTIONS_JS)
            items = result.get("items") or []
            # 文案 → 内部状态
            for it in items:
                raw = it.get("alias_status") or ""
                it["alias_status_internal"] = FANQIE_ALIAS_STATUS_MAP.get(raw, "unknown")

            synced_task_ids: list[str] = []
            if sync_to_tasks and items:
                synced_task_ids = self._sync_promotion_status(content_type, items)
            return {
                "content_type": content_type,
                "url": url,
                "count": len(items),
                "items": items,
                "synced_task_ids": synced_task_ids,
            }
        finally:
            session.stop()

    def _sync_promotion_status(self, content_type: str, items: list[dict]) -> list[str]:
        """把 list 页扫到的别名状态同步到 tasks/<id>/task.json。

        匹配规则：task.promotion_alias == item.alias
        - 成功匹配的 task.apply_status 从 pending_review 推进到 active/under_review/rejected/expired
        - 同步 item.book_id / item.publish_type / item.valid_range 到 task（如果之前没填）
        """
        tasks_dir = self.root_dir / "tasks"
        if not tasks_dir.exists():
            return []
        by_alias = {it["alias"]: it for it in items if it.get("alias")}
        synced: list[str] = []
        for task_dir in tasks_dir.iterdir():
            if not task_dir.is_dir():
                continue
            task_path = task_dir / "task.json"
            if not task_path.exists():
                continue
            try:
                data = json.loads(task_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("content_type") != content_type:
                continue
            alias = data.get("promotion_alias")
            if not alias or alias not in by_alias:
                continue
            item = by_alias[alias]
            changed = False
            # 1) 推进状态
            internal = item.get("alias_status_internal") or "unknown"
            if data.get("apply_status") in ("pending_review", "submitted", "started"):
                if internal in ("active", "under_review", "rejected", "expired"):
                    data["apply_status"] = internal
                    data["apply_message"] = (
                        f"list 页同步：{item.get('alias_status')}"
                        f"（创建 {item.get('created_at')}，"
                        f"有效期 {item.get('valid_range')}）"
                    )
                    changed = True
            # 2) 补充 book_id / publish_type / valid_range
            if item.get("book_id") and not data.get("book_url"):
                # 记录 book_id（之前用 book_url 字段存；这里新加 fanqie_book_id 更准）
                data["fanqie_book_id"] = item["book_id"]
                changed = True
            if item.get("publish_type") and not data.get("publish_type"):
                data["publish_type"] = item["publish_type"]
                changed = True
            if item.get("valid_range") and not data.get("valid_range"):
                data["valid_range"] = item["valid_range"]
                changed = True
            if item.get("has_fill_link") is not None:
                data["has_fill_link"] = item["has_fill_link"]
                data["fill_status"] = item.get("fill_status", "")
                changed = True
            if changed:
                data["updated_at"] = self._now()
                self._write_json(task_path, data)
                synced.append(data.get("task_id", task_dir.name))
        return synced

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
        """抓小说正文。流程：
        1. 跳达人中心 /page/content，用搜索框过滤（前端 in-memory）
        2. 找匹配书名 → click → pushState → 跳详情页拿 book_id
        3. 抓 meta 元数据 + 抓所有目录项
        4. 逐章点击目录项 → 抓 #content → 付费墙检测
        5. 保存 meta.json + chapters/NN.txt + material.txt
        """
        if not book_name.strip():
            raise RuntimeError("缺少小说名称。")
        session = self._open_browser_cache_session(headless=headless)
        try:
            # 1) 跳达人中心 + 搜索 + 找书卡 + click
            list_url = "https://kol.fanqieopen.com/page/content?tab_type=2&top_tab_genre=-1"
            page = session.open_page(list_url)
            page.wait_for_timeout(3000)

            # 在搜索框输入书名（前端过滤）
            search_input_js = """
            () => {
              const wanted = %s;
              const inputs = Array.from(document.querySelectorAll('input[placeholder]'));
              const target = inputs.find(i => i.offsetParent !== null) || inputs[0];
              if (!target) return { error: 'no search input' };
              const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
              setter.call(target, wanted);
              target.dispatchEvent(new Event('input', { bubbles: true }));
              target.dispatchEvent(new Event('change', { bubbles: true }));
              return { ok: true };
            }
            """ % json.dumps(book_name.strip(), ensure_ascii=False)
            page.locator("").evaluate(search_input_js)
            page.wait_for_timeout(2000)  # 等前端过滤

            # 找匹配书卡
            click_js = """
            () => {
              const wanted = %s;
              const cards = Array.from(document.querySelectorAll('.book-hQ7GYr'));
              for (const c of cards) {
                const t = c.querySelector('.book-title-txt-_CIhYa');
                const title = t ? t.innerText.trim() : '';
                if (title === wanted || title.includes(wanted) || wanted.includes(title)) {
                  c.click();
                  return { clicked: true, title };
                }
              }
              return { clicked: false, message: '搜索后未找到匹配书名' };
            }
            """ % json.dumps(book_name.strip(), ensure_ascii=False)
            click_result = page.locator("").evaluate(click_js)
            if not click_result or not click_result.get("clicked"):
                raise RuntimeError(f"达人中心搜索未匹配: {book_name}")
            book_title = click_result.get("title") or book_name
            page.wait_for_timeout(3500)
            book_id = self._get_book_id_from_url(page)
            if not book_id:
                raise RuntimeError(f"详情页 URL 未含 book_id: {page.url}")
            detail_url = page.url
            logger.info(f"详情页: {detail_url}, book_id={book_id}")

            # 2) 抓所有可见目录项（拿全，让 meta.total_chapters_seen 准确）
            catalogue = self._collect_catalogue_items(page, max_count=10000)
            if not catalogue:
                raise RuntimeError(f"详情页未找到章节目录: {detail_url}")

            # 3) 抓取小说元数据
            meta = self._extract_book_meta(page)
            meta["book_id"] = book_id
            meta["book_name"] = book_title
            meta["source_url"] = detail_url
            meta["scraped_at"] = self._now()
            meta["total_chapters_seen"] = len(catalogue)

            # 4) 逐章点击 + 抓正文（带付费墙检测）
            book_dir = self.root_dir / "books" / f"{book_id}_{self._safe_name(book_title)}"
            chapters_dir = book_dir / "chapters"
            chapters_dir.mkdir(parents=True, exist_ok=True)
            fetched = []
            paywall_hit = False
            for idx, item in enumerate(catalogue[:chapters], start=1):
                chapter_title = item.get("title") or f"第{idx}章"
                # 点击该目录项触发 pushState
                click_item_js = """
                () => {
                  const wanted = %s;
                  const items = Array.from(document.querySelectorAll('.catalogue__item-ImEeJx, [class*="catalogue__item"]:not([class*="text"]):not([class*="header"]):not([class*="list"])'));
                  const target = items.find(it => {
                    const t = it.querySelector('.catalogue__item-text-Dcm6hj, [class*="catalogue__item-text"]');
                    return t && t.innerText.trim() === wanted;
                  });
                  if (target) { target.click(); return true; }
                  return false;
                }
                """ % json.dumps(chapter_title.strip(), ensure_ascii=False)
                clicked = page.locator("").evaluate(click_item_js)
                if not clicked:
                    logger.warning(f"未找到/未点击目录项: {chapter_title}")
                    continue
                page.wait_for_timeout(1200)
                item_id = self._get_item_id_from_url(page)
                # 抓 #content 段落
                content_js = """
                () => {
                  const el = document.querySelector('#content, [class*="chapter-content"]');
                  if (!el) return '';
                  return Array.from(el.querySelectorAll('p')).map(p => p.innerText.trim()).filter(Boolean).join('\\n\\n');
                }
                """
                text = page.locator("").evaluate(content_js) or ""
                text = self._clean_chapter_text(text)

                # 付费墙检测
                is_paywall, paywall_reason = self._detect_paywall(text)
                if is_paywall:
                    logger.info(f"[{idx}] 付费墙: {chapter_title} ({paywall_reason})")
                    paywall_hit = True
                    meta["paywall_at_chapter"] = idx
                    meta["paywall_reason"] = paywall_reason
                    break

                if not text:
                    logger.warning(f"章节内容为空: {chapter_title}")

                chapter_path = chapters_dir / f"{idx:03d}.txt"
                self._write_text(chapter_path, f"{chapter_title}\n\n{text}\n")
                fetched.append({
                    "index": idx,
                    "title": chapter_title,
                    "item_id": item_id,
                    "char_count": len(text),
                    "file": str(chapter_path),
                })
                logger.info(f"[{idx}/{chapters}] {chapter_title} ({len(text)} chars)")

            # 5) 写 meta.json
            meta["chapters_fetched"] = len(fetched)
            meta["paywall_hit"] = paywall_hit
            meta["fetch_log"] = fetched
            meta_path = book_dir / "meta.json"
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

            # 6) 合并 material.txt（兼容旧 promo-video）
            material_path = book_dir / "material.txt"
            material = [
                f"小说名称：{book_title}",
                f"书籍 ID：{book_id}",
                f"作者：{meta.get('author', '')}",
                f"分类标签：{' / '.join(meta.get('tags', []))}",
                f"作品简介：{meta.get('abstract', '')}",
                f"详情页：{detail_url}",
                "",
            ]
            for item in fetched:
                material.append(Path(item["file"]).read_text(encoding="utf-8"))
                material.append("\n")
            self._write_text(material_path, "\n".join(material).strip() + "\n")

            return FanqieBookFetchResult(
                book_name=book_title,
                book_id=book_id,
                book_url=detail_url,
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

    def _search_kol_book(self, page, book_name: str) -> dict:
        """在达人中心列表遍历 .book-hQ7GYr 找匹配书名；返回 {title, book_id}。

        达人列表只展示推荐 Top 20-30 本，所以 book_name 必须已经"进入推荐池"才能命中。
        """
        js = r"""
        () => {
          const cards = Array.from(document.querySelectorAll('.book-hQ7GYr'));
          const items = cards.map(c => {
            const titleEl = c.querySelector('.book-title-txt-_CIhYa');
            const title = titleEl ? titleEl.innerText.trim() : '';
            return { title };
          }).filter(i => i.title);
          return items;
        }
        """
        result = page.locator("").evaluate(js) or []
        for item in result:
            if book_name in item.get("title", "") or item.get("title", "") in book_name:
                # 找到匹配 → 点击进详情页拿 book_id
                # 这里 book_id 不在 list 页 DOM，需要从点击后 URL 拿
                # 简单方案：返回 title，让调用方 click 后从 URL 拿
                return {"title": item["title"], "book_id": ""}
        return {}

    def _get_book_id_from_url(self, page) -> str:
        """从当前 URL 拿 book_id"""
        js = "() => new URL(location.href).searchParams.get('book_id') || ''"
        result = page.locator("").evaluate(js) or ""
        return str(result).strip()

    def _collect_catalogue_items(self, page, max_count: int = 10000) -> list[dict]:
        """抓详情页所有可见目录项 + 触发第一次点击拿 item_id。

        返回 [{title, item_id}]，item_id 来自点击后 URL 的 search param。
        max_count 是软上限（避免内存爆炸），默认 10000 几乎能拿全。
        """
        # 抓所有目录项文本
        js = r"""
        () => {
          const items = Array.from(document.querySelectorAll('.catalogue__item-ImEeJx, [class*="catalogue__item"]:not([class*="text"]):not([class*="header"]):not([class*="list"])'));
          return items.map(it => {
            const t = it.querySelector('.catalogue__item-text-Dcm6hj, [class*="catalogue__item-text"]');
            return t ? t.innerText.trim() : '';
          }).filter(Boolean);
        }
        """
        titles = page.locator("").evaluate(js) or []
        if not titles:
            return []
        out = []
        # 点第 1 个拿 item_id（默认显示章节的 item_id）
        first_js = """
        () => {
          const it = document.querySelector('.catalogue__item-ImEeJx, [class*="catalogue__item"]:not([class*="text"]):not([class*="header"]):not([class*="list"])');
          if (it) it.click();
        }
        """
        page.locator("").evaluate(first_js)
        page.wait_for_timeout(800)
        first_item_id = self._get_item_id_from_url(page)
        if titles:
            out.append({"title": titles[0], "item_id": first_item_id})
        # 剩下的标题（fetch_book 会在主循环里逐一点击拿 item_id）
        for t in titles[1:max_count]:
            out.append({"title": t, "item_id": ""})
        return out[:max_count]

    def _get_item_id_from_url(self, page) -> str:
        js = "() => new URL(location.href).searchParams.get('item_id') || ''"
        result = page.locator("").evaluate(js) or ""
        return str(result).strip()

    def _clean_chapter_text(self, text: str) -> str:
        """清理章节文本：去空段、保留段落。"""
        if not text:
            return ""
        # 多余空行
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text

    def _extract_book_meta(self, page) -> dict:
        """从详情页抓小说元数据：作者/简介/标签/评分/字数/状态。"""
        js = r"""
        () => {
          const textOf = el => el ? (el.innerText || '').trim() : '';
          const nameEl = document.querySelector('.book-name-WEvqxi, [class*="book-name"]:not([class*="copy"])');
          const authorEl = document.querySelector('.book-author-Ygu_Z1, [class*="book-author"]');
          const abstractEl = document.querySelector('.book-abstract-content-p6QvfA, [class*="book-abstract-content"]');
          const idEl = document.querySelector('.book-id-cyFb30, [class*="book-id"]:not([class*="copy"])');
          // 标签（年代/101.9万字/8.1分 等）—— 用 split + 去重，因为某些 class 是 wrapper
          const tagEls = Array.from(document.querySelectorAll('.book-tag-yYbHV7, [class*="book-tag"]:not([class*="copy"])'));
          const rawTags = tagEls.map(t => textOf(t)).filter(Boolean);
          const tags = [...new Set(rawTags.flatMap(t => t.split(/\s+/).filter(Boolean)))];
          // 分类（年代/现代言情/萌宝 等）
          const catEls = Array.from(document.querySelectorAll('.book-category-w1IX9j, [class*="book-category"]'));
          const rawCats = catEls.map(t => textOf(t)).filter(Boolean);
          const categories = [...new Set(rawCats.flatMap(t => t.split(/\s+/).filter(Boolean)))];
          return {
            author: textOf(authorEl),
            abstract: textOf(abstractEl),
            tags,
            categories,
            raw_id_text: textOf(idEl),
          };
        }
        """
        return page.locator("").evaluate(js) or {}

    def _detect_paywall(self, text: str) -> tuple[bool, str]:
        """检测付费墙/试读结束。返回 (is_paywall, reason)。"""
        if not text:
            return True, "empty_content"
        keywords = [
            ("试读结束", "preview_ended"),
            ("试读已结束", "preview_ended"),
            ("试读章节", "preview_only"),
            ("开通会员", "vip_required"),
            ("开通SVIP", "svip_required"),
            ("付费章节", "paid_chapter"),
            ("本章为VIP", "vip_chapter"),
            ("本章为付费", "paid_chapter"),
            ("请先登录", "login_required"),
            ("登录后", "login_required"),
        ]
        for kw, code in keywords:
            if kw in text:
                return True, code
        return False, ""

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
        response = llm_client.chat_completion_tracked(
            messages, caller="fanqie_promo", temperature=0.55, json_mode=True,
        )
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
