"""Authorized, browser-visible Douyin keyword sample collector."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import quote

from src.platform_adapter.browser_session import BrowserSession
from src.platform_adapter.models import BrowserSessionConfig
from src.shared.config import settings
from src.trend_intelligence.analysis import metric_to_number, stable_item_id
from src.trend_intelligence.models import TrendObservation
from src.trend_intelligence.source_policy import (
    SourcePolicy,
    SourcePolicyGate,
    SourceProvider,
    SourceRequest,
)
from src.trend_intelligence.tag_graph import (
    build_keyword_tag_relations,
    build_tag_cooccurrence_relations,
    build_tag_traffic_snapshots,
    extract_hashtags,
    normalize_hashtag,
)

from .base import TrendCollectionRequest, TrendCollectionResult


@dataclass(frozen=True, slots=True)
class DouyinSort:
    key: str
    label: str


DOUYIN_SORTS = (
    DouyinSort("comprehensive", "综合排序"),
    DouyinSort("most_liked", "最多点赞"),
    DouyinSort("latest", "最新发布"),
)
SORTS_BY_KEY = {sort.key: sort for sort in DOUYIN_SORTS}
BLOCK_TEXT = re.compile(r"扫码登录|验证码登录|安全验证|访问异常|账号异常|操作频繁")
MAX_RELATED_TAGS_PER_KEYWORD = 3
MAX_TOTAL_RELATED_TAGS = 6


EXTRACT_SCRIPT = r"""(() => {
  const links = Array.from(document.querySelectorAll('a[href*="/video/"]'));
  return links.map((link) => {
    const card = link.closest('li, article')
      || link.parentElement?.parentElement?.parentElement
      || link.parentElement;
    const raw = (card?.innerText || link.innerText || '').trim();
    const lines = raw.split(/\n+/).map((value) => value.trim()).filter(Boolean);
    const image = link.querySelector('img[alt]') || card?.querySelector('img[alt]');
    const title = (
      image?.getAttribute('alt')
      || link.getAttribute('title')
      || lines.find((value) => value.length > 8)
      || ''
    ).slice(0, 500);
    const author = lines.find((value) => value.startsWith('@')) || '';
    const metricText = lines.find(
      (value) => /^(?:\d+(?:\.\d+)?)(?:万|亿)?$/.test(value)
    ) || '';
    const hashtags = Array.from(
      raw.matchAll(/[#＃]([0-9A-Za-z_\u3400-\u9fff]{1,40})/gu),
      (match) => match[1]
    );
    return {
      url: link.href,
      title,
      author,
      metricText,
      hashtags,
      rawText: raw.slice(0, 1000),
    };
  }).filter((item) => /\/video\/\d+/.test(item.url));
})()"""

SORT_SELECTION_SCRIPT = r"""(() => {
  // sort-selection-signature: verify the active option instead of trusting a click.
  const targetLabel = __TARGET_LABEL__;
  const visible = (element) => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0
      && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const indexed = Array.from(document.querySelectorAll('[data-index1="0"]'))
    .filter(visible);
  const target = indexed.find(
    (element) => (element.textContent || '').trim() === targetLabel
  );
  if (!target) return false;
  const directState = [
    target.getAttribute('aria-selected'),
    target.getAttribute('aria-checked'),
    target.getAttribute('data-state'),
  ].filter(Boolean).map((value) => value.toLowerCase());
  if (directState.some((value) => ['true', 'active', 'selected', 'checked'].includes(value))) {
    return true;
  }
  const siblings = indexed.filter(
    (element) => element !== target && element.parentElement === target.parentElement
  );
  if (siblings.length < 2) return false;
  const signature = (element) => {
    const style = getComputedStyle(element);
    return JSON.stringify([
      style.color,
      style.backgroundColor,
      style.fontWeight,
      element.classList.length,
    ]);
  };
  const targetSignature = signature(target);
  const siblingSignatures = siblings.map(signature);
  return new Set(siblingSignatures).size === 1
    && targetSignature !== siblingSignatures[0];
})()"""


def build_douyin_search_url(keyword: str) -> str:
    return f"https://www.douyin.com/search/{quote(keyword.strip())}?type=video"


def estimate_douyin_planned_pages(request: TrendCollectionRequest) -> int:
    keywords = _normalize_keywords(request.keywords)
    sort_count = len({key for key in request.sorts if key in SORTS_BY_KEY})
    base_pages = len(keywords) * sort_count
    if not request.expand_related_tags:
        return max(1, base_pages)
    per_keyword = max(
        0,
        min(MAX_RELATED_TAGS_PER_KEYWORD, int(request.max_related_tags_per_keyword)),
    )
    total_limit = max(
        0,
        min(MAX_TOTAL_RELATED_TAGS, int(request.max_total_related_tags)),
    )
    related_count = min(total_limit, len(keywords) * per_keyword)
    return max(1, base_pages + related_count * sort_count)


def build_douyin_trend_session(*, headless: bool = False) -> BrowserSession:
    return BrowserSession(
        BrowserSessionConfig(
            base_url="https://www.douyin.com",
            home_url="https://www.douyin.com/",
            storage_state_path=getattr(
                settings,
                "TREND_BROWSER_STORAGE_STATE_PATH",
                "./data/browser/douyin_trend/storage_state.json",
            ),
            user_data_dir=getattr(
                settings,
                "TREND_BROWSER_USER_DATA_DIR",
                "./data/browser/douyin_trend/user_data",
            ),
            browser_channel=settings.BROWSER_CHANNEL,
            headless=headless,
            slow_mo_ms=settings.BROWSER_SLOW_MO_MS,
            timeout_ms=settings.BROWSER_TIMEOUT_MS,
        )
    )


class DouyinWebTrendProvider:
    provider_id = "douyin_authorized_web"

    def __init__(
        self,
        *,
        session_factory: Callable[[bool], BrowserSession] | None = None,
        policy_gate: SourcePolicyGate | None = None,
    ):
        self.session_factory = session_factory or (
            lambda headless: build_douyin_trend_session(headless=headless)
        )
        self.policy_gate = policy_gate or SourcePolicyGate()

    def collect(
        self,
        request: TrendCollectionRequest,
        *,
        policy: SourcePolicy,
    ) -> TrendCollectionResult:
        keywords = _normalize_keywords(request.keywords)
        if not keywords:
            raise ValueError("请至少输入一个关键词")
        safe_limit = max(1, min(20, int(request.limit_per_sort)))
        sorts = [SORTS_BY_KEY[key] for key in request.sorts if key in SORTS_BY_KEY]
        if not sorts:
            raise ValueError("请至少选择一种有效排序")
        max_tags_per_keyword = max(
            0,
            min(
                MAX_RELATED_TAGS_PER_KEYWORD,
                int(request.max_related_tags_per_keyword),
            ),
        )
        max_total_tags = max(
            0,
            min(MAX_TOTAL_RELATED_TAGS, int(request.max_total_related_tags)),
        )

        target_url = build_douyin_search_url(keywords[0])
        source_request = SourceRequest(
            provider=SourceProvider.AUTHORIZED_WEB,
            purposes=frozenset({"trend_analysis"}),
            requested_fields=frozenset(
                {
                    "video_id",
                    "url",
                    "title",
                    "author",
                    "keyword",
                    "sort",
                    "rank",
                    "displayed_metrics",
                    "hashtags",
                    "tag_relationships",
                    "tag_traffic_snapshots",
                }
            ),
            target_url=target_url,
            planned_pages=estimate_douyin_planned_pages(request),
            requested_at=datetime.now(timezone.utc),
        )
        decision = self.policy_gate.evaluate(
            policy,
            source_request,
            web_crawler_enabled=request.web_crawler_enabled,
        )
        if not decision.allowed:
            return TrendCollectionResult(
                observations=[],
                warnings=[decision.reason],
                policy_code=decision.code,
                stopped_reason="policy_blocked",
            )

        session = self.session_factory(request.headless)
        observations: list[TrendObservation] = []
        primary_observations: list[TrendObservation] = []
        warnings: list[str] = []
        stopped_reason = ""
        tag_relations = []
        tag_traffic_snapshots = []
        last_navigation_started = 0.0

        def collect_sort(
            *,
            query: str,
            root_keywords: list[str],
            query_kind: str,
            query_depth: int,
            sort: DouyinSort,
        ) -> tuple[list[TrendObservation], str]:
            nonlocal last_navigation_started
            if last_navigation_started:
                remaining = (
                    decision.min_interval_seconds
                    - (time.monotonic() - last_navigation_started)
                )
                if remaining > 0:
                    time.sleep(remaining)
            last_navigation_started = time.monotonic()
            return self._collect_sort(
                session,
                query=query,
                root_keywords=root_keywords,
                query_kind=query_kind,
                query_depth=query_depth,
                sort=sort,
                limit=safe_limit,
                retain_raw=policy.raw_retention_days > 0,
            )

        try:
            human_required = False
            for keyword in keywords:
                for sort in sorts:
                    rows, issue = collect_sort(
                        query=keyword,
                        root_keywords=[keyword],
                        query_kind="keyword",
                        query_depth=0,
                        sort=sort,
                    )
                    if issue == "human_required":
                        warnings.append(f"{keyword}：需要人工完成登录或安全验证")
                        stopped_reason = "human_required"
                        human_required = True
                        break
                    if issue == "sort_unconfirmed":
                        warnings.append(f"{keyword}：无法确认排序“{sort.label}”已生效")
                        continue
                    observations.extend(rows)
                    primary_observations.extend(rows)
                if human_required:
                    break

            tag_relations, roots_by_tag = build_keyword_tag_relations(
                primary_observations,
                max_tags_per_keyword=(
                    max_tags_per_keyword if request.expand_related_tags else 0
                ),
                max_total_tags=(max_total_tags if request.expand_related_tags else 0),
            )
            observations_by_tag: dict[str, list[TrendObservation]] = {}
            if request.expand_related_tags and not human_required:
                for tag, root_keywords in roots_by_tag.items():
                    tag_rows: list[TrendObservation] = []
                    query = f"#{tag}"
                    for sort in sorts:
                        rows, issue = collect_sort(
                            query=query,
                            root_keywords=root_keywords,
                            query_kind="hashtag",
                            query_depth=1,
                            sort=sort,
                        )
                        if issue == "human_required":
                            warnings.append(
                                f"{query}：需要人工完成登录或安全验证"
                            )
                            stopped_reason = "human_required"
                            human_required = True
                            break
                        if issue == "sort_unconfirmed":
                            warnings.append(
                                f"{query}：无法确认排序“{sort.label}”已生效"
                            )
                            continue
                        tag_rows.extend(rows)
                        observations.extend(rows)
                    observations_by_tag[tag] = tag_rows
                    if human_required:
                        break

                tag_relations.extend(
                    build_tag_cooccurrence_relations(
                        observations_by_tag,
                        roots_by_tag,
                    )
                )
                tag_traffic_snapshots = build_tag_traffic_snapshots(
                    observations_by_tag,
                    roots_by_tag,
                    limit_per_sort=safe_limit,
                )
        finally:
            session.stop()

        return TrendCollectionResult(
            observations=observations,
            warnings=warnings,
            policy_code="allowed",
            stopped_reason=stopped_reason,
            tag_relations=tag_relations,
            tag_traffic_snapshots=tag_traffic_snapshots,
        )

    def _collect_sort(
        self,
        session: BrowserSession,
        *,
        query: str,
        root_keywords: list[str],
        query_kind: str,
        query_depth: int,
        sort: DouyinSort,
        limit: int,
        retain_raw: bool,
    ) -> tuple[list[TrendObservation], str]:
        # Every sort starts from a fresh page so comprehensive is the real
        # default and filter/scroll state cannot leak into the next ranking.
        page = session.open_page(build_douyin_search_url(query))
        self._wait_until_ready(page)
        if self._is_blocked(page):
            return [], "human_required"
        if sort.key != "comprehensive" and not self._select_sort(page, sort.label):
            return [], "sort_unconfirmed"

        found: dict[str, dict] = {}
        unchanged_rounds = 0
        for _ in range(12):
            rows = page.locator("body").evaluate(EXTRACT_SCRIPT) or []
            before = len(found)
            for row in rows:
                video_id = _video_id_from_url(str(row.get("url") or ""))
                if video_id and video_id not in found:
                    found[video_id] = row
            unchanged_rounds = unchanged_rounds + 1 if len(found) == before else 0
            if len(found) >= limit or unchanged_rounds >= 3:
                break
            page.locator("body").evaluate(
                "window.scrollBy({top: Math.max(window.innerHeight * 0.9, 720), behavior: 'smooth'})"
            )
            page.wait_for_timeout(900)

        output: list[TrendObservation] = []
        collected_at = datetime.now(timezone.utc).isoformat()
        for rank, (video_id, row) in enumerate(
            list(found.items())[:limit],
            start=1,
        ):
            metric_text = str(row.get("metricText") or "")
            raw_text = str(row.get("rawText") or "")[:1000]
            hashtags = _row_hashtags(row, raw_text=raw_text)
            output.append(
                TrendObservation(
                    item_id=stable_item_id(video_id=video_id),
                    video_id=video_id,
                    url=str(row.get("url") or ""),
                    title=str(row.get("title") or "").strip(),
                    author=str(row.get("author") or "").strip(),
                    keyword=query,
                    sort_key=sort.key,
                    sort_label=sort.label,
                    rank=rank,
                    metric_text=metric_text,
                    metric_value=metric_to_number(metric_text),
                    collected_at=collected_at,
                    raw_text=raw_text if retain_raw else "",
                    query_kind=query_kind,
                    query_value=query,
                    query_depth=query_depth,
                    root_keywords=list(root_keywords),
                    hashtags=hashtags,
                )
            )
        return output, ""

    @staticmethod
    def _is_blocked(page) -> bool:
        text = page.locator("body").inner_text()
        links = page.locator('a[href*="/video/"]').count()
        return links == 0 and bool(BLOCK_TEXT.search(text or ""))

    @staticmethod
    def _wait_until_ready(page) -> None:
        for _ in range(20):
            if page.locator('a[href*="/video/"]').count() > 0:
                return
            body_text = page.locator("body").inner_text()
            if BLOCK_TEXT.search(body_text or ""):
                return
            page.wait_for_timeout(500)

    @staticmethod
    def _sort_option_visible(page, label: str) -> bool:
        return page.interact_visible_exact_text(label, operation="inspect")

    @classmethod
    def _open_sort_menu(cls, page, label: str) -> bool:
        if cls._sort_option_visible(page, label):
            return True
        if page.interact_visible_exact_text(
            "筛选", operation="hover", prefer_parent=True
        ):
            for _ in range(4):
                page.wait_for_timeout(250)
                if cls._sort_option_visible(page, label):
                    return True
        if page.interact_visible_exact_text(
            "筛选", operation="click", prefer_parent=True
        ):
            for _ in range(4):
                page.wait_for_timeout(250)
                if cls._sort_option_visible(page, label):
                    return True
        return False

    @staticmethod
    def _is_sort_selected(page, label: str) -> bool:
        script = SORT_SELECTION_SCRIPT.replace(
            "__TARGET_LABEL__", json.dumps(label, ensure_ascii=False)
        )
        return bool(page.locator("body").evaluate(script))

    @classmethod
    def _select_sort(cls, page, label: str) -> bool:
        page.locator("body").evaluate(
            "window.scrollTo({top: 0, behavior: 'instant'})"
        )
        page.wait_for_timeout(400)
        if not cls._open_sort_menu(page, label):
            return False
        if cls._is_sort_selected(page, label):
            return True
        if not page.interact_visible_exact_text(label, operation="click"):
            return False
        for attempt in range(8):
            page.wait_for_timeout(350)
            if cls._is_sort_selected(page, label):
                page.wait_for_timeout(1000)
                return True
            if attempt == 2:
                cls._open_sort_menu(page, label)
        return False


def _normalize_keywords(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            output.append(normalized)
    return output[:10]


def _video_id_from_url(url: str) -> str:
    match = re.search(r"/video/(\d+)", url)
    return match.group(1) if match else ""


def _row_hashtags(row: dict, *, raw_text: str) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    values = list(row.get("hashtags") or [])
    values.extend(extract_hashtags(str(row.get("title") or ""), raw_text))
    for value in values:
        tag = normalize_hashtag(str(value))
        if tag and tag not in seen:
            seen.add(tag)
            output.append(tag)
    return output
