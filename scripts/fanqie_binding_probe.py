#!/usr/bin/env python3
"""
P0-A 番茄回填可行性探测脚本

验证内容：
  1. 推广列表是否存在"回填发文"入口
  2. 哪些状态的任务允许回填
  3. 接受的是抖音作品URL还是作品ID
  4. 是否限制发布账号
  5. 是否要求作品已经公开或审核通过
  6. 是否允许修改已回填URL
  7. 页面成功、失败和重复回填的提示
  8. 是否存在验证码或安全确认

安全约束：
  - 无可用推广任务和抖音URL时：只检查页面入口和字段，不点击最终提交
  - 报告结论写成 partially_verified
  - 不伪造成功记录

产物目录：data/fanqie_promotion/audit/feasibility/
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

# ── 添加到项目路径 ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.platform_adapter.browser_session import BrowserSession
from src.platform_adapter.models import BrowserSessionConfig
from src.shared.config import settings
from src.shared.logger import logger

# ── 配置 ──────────────────────────────────────────────────────
FANQIE_NOVEL_LIST_URL = "https://kol.fanqieopen.com/page/content?tab_type=2&top_tab_genre=-1"
FANQIE_AUDIO_LIST_URL = "https://kol.fanqieopen.com/page/content?tab_type=3&top_tab_genre=-1"
AUDIT_DIR = PROJECT_ROOT / "data" / "fanqie_promotion" / "audit" / "feasibility"

# ── 页面 JS 探针 ────────────────────────────────────────────────

# 1) 扫推广列表行，收集所有包含"回填发文"或"未填写"的行
SCAN_BACKFILL_ROWS_JS = r"""
() => {
  const textOf = el => (el.innerText || el.textContent || '').trim();
  const rows = Array.from(document.querySelectorAll('.arco-table-tr'));
  const dataRows = rows.filter(r => r.closest('thead') === null);

  const backfillRows = [];
  dataRows.forEach((row, i) => {
    const cells = Array.from(row.querySelectorAll('.arco-table-td'));
    const cellText = idx => cells[idx] ? textOf(cells[idx]).replace(/\s+/g, ' ').trim() : '';

    // 回填状态在第 7 列（index 6）
    const fillText = cellText(6);
    const hasLink = !!row.querySelector('.arco-table-cell .link, a[class*="link"]');
    const linkEl = row.querySelector('.arco-table-cell .link, a[class*="link"]');
    const linkHref = linkEl ? (linkEl.getAttribute('href') || '') : '';
    const linkText = linkEl ? textOf(linkEl) : '';

    // 别名状态
    const statusEl = row.querySelector('.alias-status-ButiOZ');
    const aliasStatus = statusEl ? textOf(statusEl) : '';

    backfillRows.push({
      index: i,
      alias: cellText(0),
      book_name: (row.querySelector('.book-name-iHil3A') ? textOf(row.querySelector('.book-name-iHil3A')) : ''),
      publish_type: cellText(3),
      alias_status: aliasStatus,
      fill_status: fillText,
      has_fill_link: hasLink,
      link_text: linkText,
      link_href: linkHref,
      created_at: cellText(7),
      valid_range: cellText(8),
    });
  });

  // 统计
  const withLink = backfillRows.filter(r => r.has_fill_link);
  const unfilled = backfillRows.filter(r => r.fill_status.includes('未填写'));
  const alreadyFilled = backfillRows.filter(r => !r.fill_status.includes('未填写') && r.fill_status);

  return {
    total_rows: backfillRows.length,
    has_fill_link_count: withLink.length,
    unfilled_count: unfilled.length,
    already_filled_count: alreadyFilled.length,
    items: backfillRows,
  };
}
"""

# 2) 点击指定行的"回填发文"链接
CLICK_BACKFILL_LINK_JS = r"""
() => {
  const rowIndex = __ROW_INDEX__;
  const rows = Array.from(document.querySelectorAll('.arco-table-tr'));
  const dataRows = rows.filter(r => r.closest('thead') === null);
  if (rowIndex < 0 || rowIndex >= dataRows.length) return { clicked: false, error: 'row index out of range', rowIndex: rowIndex };
  const row = dataRows[rowIndex];
  const link = row.querySelector('.arco-table-cell .link, a[class*="link"]');
  if (!link) return { clicked: false, error: 'no fill link found on row', rowIndex: rowIndex };
  link.scrollIntoView({ block: 'center' });
  link.click();
  return { clicked: true, link_text: (link.innerText || '').trim() };
}
"""

def _click_backfill_js(row_index: int) -> str:
    return CLICK_BACKFILL_LINK_JS.replace("__ROW_INDEX__", str(row_index))

# 3) 等待并检查弹窗/模态框
INSPECT_MODAL_JS = r"""
() => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const visible = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const textOf = el => el ? (el.innerText || el.textContent || '').trim() : '';

  // 找可见 modal（支持多种 class 模式）
  let modal = null;
  const selectors = [
    '.arco-modal-content',
    '.arco-modal',
    '[class*="modal"]:not([class*="mask"])',
    '[class*="dialog"]',
    '[role="dialog"]',
  ];
  for (const sel of selectors) {
    const els = Array.from(document.querySelectorAll(sel));
    modal = els.find(visible);
    if (modal) break;
  }

  // 也可能是页面内嵌表单（非弹窗）
  if (!modal) {
    // 检查是否有新出现的表单区域
    const forms = Array.from(document.querySelectorAll('form, [class*="form"]')).filter(visible);
    if (forms.length > 0) {
      modal = forms[0];
    }
  }

  if (!modal) return { found: false, message: 'no visible modal or form found' };

  // 收集所有输入
  const inputs = Array.from(modal.querySelectorAll('input, textarea, select')).map(el => ({
    tag: el.tagName.toLowerCase(),
    type: el.getAttribute('type') || 'text',
    name: el.getAttribute('name') || '',
    id: el.getAttribute('id') || '',
    placeholder: el.getAttribute('placeholder') || '',
    value: el.value || '',
    required: el.hasAttribute('required'),
    maxlength: el.getAttribute('maxlength') || '',
    readonly: el.hasAttribute('readonly'),
    disabled: el.hasAttribute('disabled'),
    class: (el.className || '').toString().slice(0, 150),
    aria_label: el.getAttribute('aria-label') || '',
  }));

  // 收集所有 label 文本
  const labels = Array.from(modal.querySelectorAll('label, [class*="label"], .arco-form-item-label')).map(el => ({
    text: textOf(el),
    for: el.getAttribute('for') || '',
  }));

  // 收集所有按钮
  const buttons = Array.from(modal.querySelectorAll('button, [role="button"]')).filter(visible).map(el => ({
    text: textOf(el),
    disabled: el.disabled || el.classList.contains('disabled') || el.classList.contains('arco-btn-disabled'),
    type: el.getAttribute('type') || '',
    class: (el.className || '').toString().slice(0, 150),
  }));

  // 验证码/安全确认检测
  const captchaEls = modal.querySelectorAll(
    '[class*="captcha"], [class*="verify"], [class*="security"], ' +
    'img[src*="captcha"], img[src*="verify"], [class*="slide"], [class*="puzzle"]'
  );
  const hasCaptcha = captchaEls.length > 0;

  // 错误提示区域
  const errorEls = modal.querySelectorAll('[class*="error"], [class*="err"], [class*="warning"], [class*="tip"]');
  const errorTexts = Array.from(errorEls).map(el => textOf(el)).filter(Boolean);

  // 表单验证提示
  const formTips = Array.from(modal.querySelectorAll('[class*="form-item"], .arco-form-item')).map(el => {
    const msgEl = el.querySelector('[class*="message"], [class*="error"], [class*="tip"]');
    return msgEl ? textOf(msgEl) : '';
  }).filter(Boolean);

  // 可见文本
  const allText = textOf(modal);

  return {
    found: true,
    modal_tag: modal.tagName.toLowerCase(),
    modal_class: (modal.className || '').toString().slice(0, 300),
    inputs,
    labels,
    buttons,
    has_captcha: hasCaptcha,
    error_texts: errorTexts,
    form_tips: formTips,
    all_text: allText.slice(0, 3000),
  };
}
"""

# 4) 在输入框填入测试 URL，观察校验反馈（不提交！）
FILL_AND_OBSERVE_JS = r"""
() => {
  const testUrl = __TEST_URL__;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const visible = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const textOf = el => el ? (el.innerText || el.textContent || '').trim() : '';

  // 找可见 modal
  let modal = null;
  for (const sel of ['.arco-modal-content', '.arco-modal', '[class*="modal"]:not([class*="mask"])', '[role="dialog"]']) {
    const els = Array.from(document.querySelectorAll(sel));
    modal = els.find(visible);
    if (modal) break;
  }
  if (!modal) return { filled: false, error: 'no modal found' };

  // 找 URL 输入框（按 placeholder/id/type 优先级）
  const inputCandidates = Array.from(modal.querySelectorAll('input[type="text"], input:not([type]), textarea'));
  const urlInput = inputCandidates.find(el => {
    const ph = (el.getAttribute('placeholder') || '').toLowerCase();
    const name = (el.getAttribute('name') || '').toLowerCase();
    const id = (el.getAttribute('id') || '').toLowerCase();
    return ph.includes('url') || ph.includes('链接') || ph.includes('地址') ||
           name.includes('url') || name.includes('link') ||
           id.includes('url') || id.includes('link');
  }) || inputCandidates.find(el => visible(el)) || inputCandidates[0];

  if (!urlInput) return { filled: false, error: 'no input field found in modal' };

  // 记录输入前的状态
  const before = {
    placeholder: urlInput.getAttribute('placeholder') || '',
    value: urlInput.value || '',
    name: urlInput.getAttribute('name') || '',
    id: urlInput.getAttribute('id') || '',
    type: urlInput.getAttribute('type') || 'text',
  };

  // 清空并填入测试 URL
  urlInput.value = '';
  urlInput.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(100);

  // 模拟逐字输入（触发 React 状态）
  const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value'
  ).set;
  nativeInputValueSetter.call(urlInput, testUrl);
  urlInput.dispatchEvent(new Event('input', { bubbles: true }));
  urlInput.dispatchEvent(new Event('change', { bubbles: true }));
  urlInput.dispatchEvent(new Event('blur', { bubbles: true }));

  await sleep(800);

  // 观察输入后状态
  const afterValue = urlInput.value;

  // 检查提交按钮状态变化
  const buttons = Array.from(modal.querySelectorAll('button')).filter(visible);
  const submitBtn = buttons.find(b => {
    const t = textOf(b);
    return /提交|确认|确定|保存|回填/.test(t);
  });
  const submitEnabled = submitBtn ? !(submitBtn.disabled || submitBtn.classList.contains('disabled') || submitBtn.classList.contains('arco-btn-disabled')) : null;

  // 检查是否有校验错误出现
  const errors = Array.from(modal.querySelectorAll('[class*="error"], [class*="err"], [class*="warning"]')).map(el => textOf(el)).filter(Boolean);

  // 检查是否有成功提示（URL 被识别）
  const successIndicators = Array.from(modal.querySelectorAll('[class*="success"], [class*="ok"], [class*="preview"]')).map(el => textOf(el)).filter(Boolean);

  return {
    filled: true,
    input_before: before,
    input_after_value: afterValue,
    test_url_used: testUrl,
    submit_button: submitBtn ? {
      text: textOf(submitBtn),
      enabled: submitEnabled,
      class: (submitBtn.className || '').toString().slice(0, 100),
    } : null,
    errors_after_fill: errors,
    success_indicators: successIndicators,
    all_buttons: buttons.map(b => ({
      text: textOf(b),
      disabled: b.disabled || b.classList.contains('disabled'),
      visible: visible(b),
    })),
  };
}
"""


def _fill_observe_js(test_url: str) -> str:
    return FILL_AND_OBSERVE_JS.replace("__TEST_URL__", json.dumps(test_url, ensure_ascii=False))


# ── 主探针逻辑 ─────────────────────────────────────────────────

def run_probe(headless: bool = False, keep_open: bool = False) -> dict:
    """执行回填可行性探测，返回结构化报告。"""

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    probe_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    report = {
        "probe_id": probe_id,
        "probe_type": "fanqie_binding_feasibility",
        "schema_version": "1.0.0",
        "started_at": now,
        "conclusion": "partially_verified",  # 默认，除非完成完整回填
        "steps": [],
        "findings": {},
        "warnings": [],
    }

    config = BrowserSessionConfig(
        base_url="https://kol.fanqieopen.com",
        home_url=FANQIE_NOVEL_LIST_URL,
        storage_state_path="./data/browser/fanqie/storage_state.json",
        user_data_dir="./data/browser/fanqie/user_data",
        browser_channel=settings.BROWSER_CHANNEL,
        headless=headless,
        slow_mo_ms=settings.BROWSER_SLOW_MO_MS,
        timeout_ms=settings.BROWSER_TIMEOUT_MS,
    )

    session = BrowserSession(config)

    try:
        # ── Step 1: 打开推广列表 + 手动导航 ──────────────────
        logger.info("[probe] Step 1: 打开推广列表页")
        page = session.open_page(FANQIE_NOVEL_LIST_URL)
        page.wait_for_timeout(3000)

        if not headless:
            input(
                "\n📌 浏览器已打开，当前是选书浏览页。\n"
                "   请手动找到【已申请的推广任务列表】页面\n"
                "   （能看到表格列：别名、书名、状态、回填状态等）\n"
                "   找到后回到终端按回车继续...\n"
            )
            page.wait_for_timeout(2000)

        # 记录当前 URL
        current_url_js = "() => location.href"
        current_url = page.locator("").evaluate(current_url_js) or ""
        logger.info(f"[probe] 当前页面 URL: {current_url}")

        # ── Step 1.5: 深度页面诊断 ─────────────────────────
        page_diag_js = r"""
        () => {
          const textOf = el => el ? (el.innerText || el.textContent || '').trim() : '';
          const title = document.title || '';
          const url = location.href;

          // 检查所有可能的表格选择器
          const selectors = ['.arco-table-tr', '.arco-table tbody tr', 'table tbody tr', '[class*="table"] tr', '[class*="Table"] tr', '.arco-table', 'table'];
          const tableInfo = {};
          for (const sel of selectors) {
            const cnt = document.querySelectorAll(sel).length;
            if (cnt > 0) tableInfo[sel] = cnt;
          }

          // 检查列表页特有的结构
          const hasBookCards = !!document.querySelector('.book-hQ7GYr');
          const promotionsEl = document.querySelector('.c-promotions');
          const hasPromotions = !!promotionsEl;

          // 检查是否是推广列表页（非登录页、非搜索页）
          const bodyText = textOf(document.body).slice(0, 3000);

          // 检查 tab 结构
          const tabs = Array.from(document.querySelectorAll('.task-menu-second-item, [class*="tab"], [class*="Tab"]')).map(el => ({
            text: textOf(el).slice(0, 60),
            active: el.classList.contains('active') || el.classList.contains('selected'),
            class: (el.className || '').toString().slice(0, 100),
          }));

          // 检查是否自动跳转到了其他页面
          const redirectInfo = {
            isLoginPage: bodyText.includes('登录') || bodyText.includes('验证码'),
            isSearchPage: !!document.querySelector('input[placeholder*="搜索"]'),
            hasTable: Object.values(tableInfo).some(v => v > 0),
            visibleText: bodyText.slice(0, 800),
          };

          // 抓 DOM 关键元素快照
          const keyElements = [];
          for (const tag of ['h1','h2','h3','.arco-table','table','.c-promotions','.book-hQ7GYr','[class*="promotion"]']) {
            const els = document.querySelectorAll(tag);
            for (const el of Array.from(els).slice(0, 5)) {
              const t = textOf(el).slice(0, 200);
              if (t) keyElements.push({ selector: tag, text: t });
            }
          }

          return { title, url, tableSelectors: tableInfo, redirectInfo, tabs: tabs.slice(0, 10), keyElements: keyElements.slice(0, 15) };
        }
        """
        diag = page.locator("").evaluate(page_diag_js) or {}
        logger.info(f"[probe] 页面诊断: title={diag.get('title')}, tableSelectors={diag.get('tableSelectors')}")
        logger.info(f"[probe] redirectInfo: {diag.get('redirectInfo', {})}")
        logger.info(f"[probe] tabs: {diag.get('tabs', [])}")

        # 保存诊断到文件
        diag_path = AUDIT_DIR / f"00_page_diag_{probe_id}.json"
        diag_path.write_text(json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8")

        # ── Step 1.6: 原始行结构 dump ─────────────────────
        row_dump_js = r"""
        () => {
          const rows = Array.from(document.querySelectorAll('.arco-table-tr'));
          const dataRows = rows.filter(r => r.closest('thead') === null);
          if (!dataRows.length) {
            // 尝试其他选择器
            const allRows = document.querySelectorAll('tr');
            return {
              total_arco_tr: rows.length,
              total_tr: allRows.length,
              dataRowCount: 0,
              sample: 'no data rows found. all <tr>: ' + allRows.length,
            };
          }
          const first = dataRows[0];
          // dump this row's HTML structure
          const children = Array.from(first.children).map(el => ({
            tag: el.tagName,
            class: (el.className || '').toString().slice(0, 120),
            text: (el.innerText || el.textContent || '').trim().slice(0, 100),
            childCount: el.children.length,
          }));
          return {
            dataRowCount: dataRows.length,
            firstRowTag: first.tagName,
            firstRowClass: (first.className || '').toString().slice(0, 200),
            firstRowCellCount: first.children.length,
            children: children,
          };
        }
        """
        row_dump = page.locator("").evaluate(row_dump_js) or {}
        logger.info(f"[probe] 行结构 dump: {json.dumps(row_dump, ensure_ascii=False, default=str)[:2000]}")
        diag["row_structure_dump"] = row_dump
        diag_path.write_text(json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8")

        report["steps"].append({
            "step": "page_diagnostic",
            "status": "ok",
            "diag_summary": {
                "title": diag.get("title"),
                "tableSelectors": diag.get("tableSelectors"),
                "isLoginPage": diag.get("redirectInfo", {}).get("isLoginPage"),
                "hasTable": diag.get("redirectInfo", {}).get("hasTable"),
            },
            "diag_file": str(diag_path),
        })

        # 截图列表页
        list_screenshot = str(AUDIT_DIR / f"01_list_page_{probe_id}.png")
        session.cmd("screenshot", path=list_screenshot, full_page=False)
        report["steps"].append({
            "step": "open_list_page",
            "status": "ok",
            "url": FANQIE_NOVEL_LIST_URL,
            "screenshot": list_screenshot,
        })
        logger.info(f"[probe] 列表页截图: {list_screenshot}")

        has_table = diag.get("redirectInfo", {}).get("hasTable", False)
        if not has_table:
            report["steps"].append({
                "step": "scan_backfill_rows",
                "status": "blocked",
                "message": f"页面未显示推广表格（title={diag.get('title')}, body={diag.get('bodyPreview', '')[:200]}）。请确认已登录番茄达人中心。",
            })
            report["conclusion"] = "blocked_not_logged_in"
            report["conclusion_detail"] = "页面未显示推广列表表格，可能是未登录或无推广任务。"
            return report

        # ── Step 2: 扫描回填入口 ──────────────────────────
        logger.info("[probe] Step 2: 扫描回填入口")
        scan_result = page.locator("").evaluate(SCAN_BACKFILL_ROWS_JS)

        if not scan_result:
            report["steps"].append({
                "step": "scan_backfill_rows",
                "status": "error",
                "message": "JS 扫描返回空",
            })
            report["conclusion"] = "failed"
            return report

        report["steps"].append({
            "step": "scan_backfill_rows",
            "status": "ok",
            "total_rows": scan_result.get("total_rows", 0),
            "has_fill_link_count": scan_result.get("has_fill_link_count", 0),
            "unfilled_count": scan_result.get("unfilled_count", 0),
            "already_filled_count": scan_result.get("already_filled_count", 0),
        })

        # 保存原始扫描数据
        page_fields_path = AUDIT_DIR / "page_fields.json"
        page_fields_path.write_text(
            json.dumps(scan_result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        report["findings"]["scan_result_summary"] = {
            "total_rows": scan_result.get("total_rows", 0),
            "with_link": scan_result.get("has_fill_link_count", 0),
            "unfilled": scan_result.get("unfilled_count", 0),
            "already_filled": scan_result.get("already_filled_count", 0),
        }
        logger.info(
            f"[probe] 扫描结果: {scan_result.get('total_rows', 0)} 行, "
            f"{scan_result.get('has_fill_link_count', 0)} 有回填链接, "
            f"{scan_result.get('already_filled_count', 0)} 已回填"
        )

        items = scan_result.get("items", [])

        # 按任务状态分类
        status_groups = {}
        for item in items:
            s = item.get("alias_status", "unknown")
            status_groups.setdefault(s, []).append(item)
        report["findings"]["status_groups"] = {
            k: len(v) for k, v in status_groups.items()
        }

        # 分析：哪些状态有回填入口
        backfill_by_status = {}
        for item in items:
            s = item.get("alias_status", "unknown")
            if item.get("has_fill_link"):
                backfill_by_status.setdefault(s, 0)
                backfill_by_status[s] += 1
        report["findings"]["backfill_available_by_status"] = backfill_by_status

        if backfill_by_status:
            logger.info(f"[probe] 回填入口按状态分布: {backfill_by_status}")
        else:
            logger.warning("[probe] 没有找到任何回填链接！")
            report["warnings"].append("no_backfill_link_found")

        # ── Step 3: 点击回填链接并分析弹窗 ───────────────────
        # 找一个有回填链接的行
        target_item = None
        for item in items:
            if item.get("has_fill_link"):
                # 优先选"生效中"的任务
                if item.get("alias_status") == "生效中":
                    target_item = item
                    break
        if not target_item:
            for item in items:
                if item.get("has_fill_link"):
                    target_item = item
                    break

        if target_item:
            logger.info(
                f"[probe] Step 3: 点击回填链接 (alias={target_item.get('alias')}, "
                f"status={target_item.get('alias_status')})"
            )

            # 截图点击前
            pre_click_ss = str(AUDIT_DIR / f"02_pre_click_{probe_id}.png")
            session.cmd("screenshot", path=pre_click_ss, full_page=False)

            # 点击回填链接
            row_idx = target_item["index"]
            click_result = page.locator("").evaluate(_click_backfill_js(row_idx))
            page.wait_for_timeout(2500)

            report["steps"].append({
                "step": "click_backfill_link",
                "status": "ok" if click_result.get("clicked") else "error",
                "target_alias": target_item.get("alias"),
                "target_status": target_item.get("alias_status"),
                "click_result": click_result,
            })

            if click_result.get("clicked"):
                # ── Step 4: 分析弹窗内容 ──────────────────
                logger.info("[probe] Step 4: 分析弹窗内容")
                page.wait_for_timeout(1500)

                modal_info = page.locator("").evaluate(INSPECT_MODAL_JS)

                # 截弹窗图
                modal_ss = str(AUDIT_DIR / f"03_modal_{probe_id}.png")
                session.cmd("screenshot", path=modal_ss, full_page=False)

                if modal_info.get("found"):
                    report["steps"].append({
                        "step": "inspect_modal",
                        "status": "ok",
                        "input_count": len(modal_info.get("inputs", [])),
                        "button_count": len(modal_info.get("buttons", [])),
                        "has_captcha": modal_info.get("has_captcha", False),
                    })

                    # 提取关键发现
                    inputs = modal_info.get("inputs", [])
                    findings = report["findings"]

                    # URL vs ID 判断
                    for inp in inputs:
                        ph = (inp.get("placeholder") or "").lower()
                        name = (inp.get("name") or "").lower()
                        label = (inp.get("aria_label") or "").lower()
                        combined = f"{ph} {name} {label}"
                        if "url" in combined or "链接" in combined:
                            findings["accepts_url"] = True
                        if "id" in combined and "url" not in combined:
                            findings["accepts_id"] = True

                    # 必填字段分析
                    required_fields = [inp for inp in inputs if inp.get("required")]
                    findings["required_fields"] = [
                        {"name": i.get("name", ""), "placeholder": i.get("placeholder", ""), "type": i.get("type", "")}
                        for i in required_fields
                    ]

                    # 按钮分析
                    buttons = modal_info.get("buttons", [])
                    findings["buttons"] = buttons
                    submit_btns = [b for b in buttons if any(
                        kw in b.get("text", "") for kw in ["提交", "确认", "确定", "保存", "回填"]
                    )]
                    findings["has_submit_button"] = len(submit_btns) > 0

                    # 验证码检测
                    findings["has_captcha"] = modal_info.get("has_captcha", False)

                    # 错误提示
                    findings["error_elements"] = modal_info.get("error_texts", [])

                    # 保存完整弹窗信息
                    modal_fields_path = AUDIT_DIR / f"modal_fields_{probe_id}.json"
                    modal_fields_path.write_text(
                        json.dumps(modal_info, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

                    # ── Step 5: 填入测试 URL（不提交！）──────
                    logger.info("[probe] Step 5: 填入测试 URL，观察校验行为")
                    test_url = "https://www.douyin.com/video/0000000000000000000"

                    fill_result = page.locator("").evaluate(_fill_observe_js(test_url))
                    page.wait_for_timeout(1000)

                    # 截图填URL后
                    filled_ss = str(AUDIT_DIR / f"04_filled_{probe_id}.png")
                    session.cmd("screenshot", path=filled_ss, full_page=False)

                    report["steps"].append({
                        "step": "fill_test_url",
                        "status": "ok" if fill_result.get("filled") else "error",
                        "test_url": test_url,
                        "submit_enabled_after_fill": (
                            fill_result.get("submit_button", {}).get("enabled")
                            if fill_result.get("submit_button") else None
                        ),
                        "errors_after_fill": fill_result.get("errors_after_fill", []),
                    })

                    findings["fill_test"] = {
                        "url_used": test_url,
                        "input_accepted": fill_result.get("filled", False),
                        "submit_enabled_after_fill": (
                            fill_result.get("submit_button", {}).get("enabled")
                            if fill_result.get("submit_button") else None
                        ),
                        "validation_errors": fill_result.get("errors_after_fill", []),
                        "success_indicators": fill_result.get("success_indicators", []),
                    }

                    # 判断是否要求作品已公开
                    if any("不存在" in e or "未找到" in e or "无效" in e for e in fill_result.get("errors_after_fill", [])):
                        findings["validates_url_existence"] = True

                    logger.info(
                        f"[probe] 填URL结果: submit_enabled={findings['fill_test']['submit_enabled_after_fill']}, "
                        f"errors={findings['fill_test']['validation_errors']}"
                    )

                    report["conclusion"] = "partially_verified"
                    report["conclusion_detail"] = (
                        "回填入口已确认存在，弹窗字段已分析，测试URL已填入但未提交。"
                        "未完成真实回填操作。"
                    )
                else:
                    report["steps"].append({
                        "step": "inspect_modal",
                        "status": "error",
                        "message": modal_info.get("message", "弹窗未出现"),
                    })
                    report["warnings"].append("modal_not_found_after_click")
            else:
                report["steps"].append({
                    "step": "click_backfill_link",
                    "status": "error",
                    "message": click_result.get("error", "点击失败"),
                })
        else:
            logger.warning("[probe] 没有任何行包含回填链接，无法测试弹窗")
            report["steps"].append({
                "step": "click_backfill_link",
                "status": "skipped",
                "message": "no rows with backfill link available",
            })
            report["warnings"].append("no_backfill_link_available")
            report["conclusion"] = "partially_verified"
            report["conclusion_detail"] = (
                "推广列表已打开并扫描，但当前没有可用的回填入口。"
                "可能原因：无生效中的推广任务，或所有任务已完成回填。"
                "已记录页面字段结构，等有可回填任务时可继续验证。"
            )

        # ── Step 6: 保存 response_snapshot ───────────────────
        response_snapshot = {
            "probe_id": probe_id,
            "collected_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "list_page_url": page.url if hasattr(page, 'url') else FANQIE_NOVEL_LIST_URL,
            "page_fields_summary": report.get("findings", {}).get("scan_result_summary", {}),
            "modal_analysis": {
                "has_captcha": report.get("findings", {}).get("has_captcha"),
                "accepts_url": report.get("findings", {}).get("accepts_url"),
                "accepts_id": report.get("findings", {}).get("accepts_id"),
                "required_fields": report.get("findings", {}).get("required_fields", []),
                "has_submit_button": report.get("findings", {}).get("has_submit_button"),
                "buttons": report.get("findings", {}).get("buttons", []),
            },
            "fill_test": report.get("findings", {}).get("fill_test", {}),
            "warnings": report.get("warnings", []),
        }
        response_path = AUDIT_DIR / "response_snapshot.json"
        response_path.write_text(
            json.dumps(response_snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # ── 最终截图 ──────────────────────────────────────
        final_ss = str(AUDIT_DIR / "screenshot_redacted.png")
        session.cmd("screenshot", path=final_ss, full_page=True)
        report["final_screenshot"] = final_ss

        report["completed_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"

        # 写探针报告
        probe_report_path = AUDIT_DIR / "probe_report.json"
        probe_report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"[probe] 报告已保存: {probe_report_path}")

        if keep_open:
            input("\n探针完成。浏览器保持打开，按回车关闭...")

        return report

    except Exception as exc:
        logger.error(f"[probe] 异常: {exc}")
        report["steps"].append({
            "step": "exception",
            "status": "error",
            "message": str(exc),
        })
        report["conclusion"] = "failed"
        report["completed_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"

        probe_report_path = AUDIT_DIR / "probe_report.json"
        probe_report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return report
    finally:
        session.stop()


# ── CLI ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="P0-A 番茄回填可行性探测")
    parser.add_argument("--headless", action="store_true", help="无头模式（默认有头）")
    parser.add_argument("--keep-open", action="store_true", help="探测完成后保持浏览器打开")
    args = parser.parse_args()

    print("=" * 60)
    print("P0-A 番茄回填可行性探测")
    print(f"产物目录: {AUDIT_DIR}")
    print(f"模式: {'无头' if args.headless else '有头（需人工监督）'}")
    print("=" * 60)
    print()
    print("⚠️  安全约束：")
    print("  - 只检查页面入口和字段")
    print("  - 填入测试 URL 但不点击最终提交")
    print("  - 报告结论为 partially_verified")
    print("  - 不伪造成功记录")
    print()

    if not args.headless:
        print("📌 浏览器将打开，请保持窗口可见。")
        print("   探针会自动操作（点击、扫描、填表），但不会提交。")
        print()

    result = run_probe(headless=args.headless, keep_open=args.keep_open)

    print()
    print("=" * 60)
    print(f"结论: {result.get('conclusion', 'unknown')}")
    print(f"完成时间: {result.get('completed_at', '')}")
    print(f"步骤数: {len(result.get('steps', []))}")
    if result.get("warnings"):
        print(f"⚠️  警告: {result['warnings']}")
    print()
    print(f"📁 报告: {AUDIT_DIR / 'probe_report.json'}")
    print(f"📁 页面字段: {AUDIT_DIR / 'page_fields.json'}")
    print(f"📁 响应快照: {AUDIT_DIR / 'response_snapshot.json'}")
    print(f"📁 截图: {AUDIT_DIR / 'screenshot_redacted.png'}")
    print("=" * 60)
