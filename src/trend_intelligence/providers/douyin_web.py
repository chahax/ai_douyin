"""Authorized, browser-visible Douyin keyword sample collector."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import quote

from src.platform_adapter.browser_session import BrowserSession, BrowserNavigationTimeout
from src.platform_adapter.douyin_challenge import confirmed_douyin_challenge, VERIFICATION_STOP_CODES
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

from .base import TrendCollectionRequest, TrendCollectionResult, related_tag_selection_options


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
BLOCK_TEXT = re.compile(
    r"扫码登录|验证码登录|安全验证|访问异常|账号异常|操作频繁|"
    r"点击两个形状相同的物体|拖动滑块|请完成验证"
)
LOGIN_PROMPT_TEXT = re.compile(r"扫码登录|验证码登录")
SECURITY_BLOCK_TEXT = re.compile(
    r"安全验证|访问异常|账号异常|操作频繁|点击两个形状相同的物体|拖动滑块|请完成验证"
)
BLOCKED_SEARCH_DETECTIONS = frozenset({"visible_challenge", "security_text_without_results",
    "login_prompt_without_results", "unclassified", "verification_ui_unconfirmed", "navigation_timeout"})


class _NavigationRecovered(str):
    def __new__(cls, evidence):
        value = super().__new__(cls, '')
        value.navigation_evidence = evidence
        return value


class _BlockedSearchIssue(str):
    """Keep the private two-value collection protocol while carrying detection evidence."""
    def __new__(cls, detection):
        value = super().__new__(cls, "human_required")
        value.detection = str(detection)
        value.evidence = getattr(detection, 'evidence', {})
        value.stop_code = 'verification_ui_unconfirmed' if detection in {'verification_ui_unconfirmed', 'security_text_without_results'} else 'human_required'
        return value


class _PageDetection(str):
    def __new__(cls, code, evidence):
        value = super().__new__(cls, code)
        value.evidence = evidence
        return value


class SearchResultsUnavailable(RuntimeError):
    code = 'search_results_unavailable'


def _verification_stop(detection):
    if detection == 'login_prompt_without_results':
        raise SearchResultsUnavailable('搜索结果未能读取；普通登录入口不足以证明需要验证码或登录过期。')
    return _BlockedSearchIssue(detection)


def _blocked_search_context(query, query_kind, sort_key, detection) -> dict:
    # Persist only query parameters supplied to this search, never page text,
    # a navigated URL, a browser request or credential-looking values.
    if (not isinstance(query, str) or not query.strip() or len(query) > 200
            or re.search(r"[\x00-\x1f]|https?://|file:|\\|[A-Za-z]:[/\\]|(?:cookie|authorization|password|token)\s*[:=]", query, re.I)
            or query_kind not in {"keyword", "hashtag"} or sort_key not in SORTS_BY_KEY):
        return {}
    return {"query": query, "query_kind": query_kind, "sort_key": sort_key,
        "detection": str(detection) if detection in BLOCKED_SEARCH_DETECTIONS else "unclassified"}
MAX_RELATED_TAGS_PER_KEYWORD = 3
MAX_TOTAL_RELATED_TAGS = 6


# Observed outline-heart geometry on the 2026-10-07 public search cards.
# Exact geometry + adjacent numeric count only; an arbitrary SVG is not a like marker.
VERIFIED_SEARCH_LIKE_PATHS = ('M9.224 4.667C6.326 4.667 4 7.151 4 10.043l.002.169a1.078 1.078 0 0 0-.002.094c.009.387.097.855.195 1.245.096.382.23.806.38 1.113.605 1.301 1.664 2.563 2.683 3.6a30.679 30.679 0 0 0 3.425 3.008l.02.017.015.012c.226.226.703.7 1.554.7h.025c.241 0 .816-.001 1.331-.502.009-.008.022-.02.042-.035l.182-.151.004-.004c.565-.465 1.886-1.554 3.188-2.867.834-.836 1.698-1.807 2.359-2.81.09-.136.176-.273.258-.41.033-.055.06-.112.082-.17.03-.077.044-.108.055-.13.013-.025.034-.063.088-.146.038-.06.07-.122.096-.188.037-.093.064-.156.085-.199l.004-.009c.087-.11.152-.238.19-.374.162-.576.273-1.082.284-1.705 0-.03 0-.058-.002-.087a7.123 7.123 0 0 0 .001-.206c-.019-2.876-2.338-5.341-5.224-5.341-1.094 0-2.159.339-2.999 1.021-.909-.658-1.957-1.021-3.097-1.021zm9.162 5.377v.134a2.388 2.388 0 0 0 0 .14c-.01.294-.057.559-.156.935-.043.07-.076.135-.1.186a4.313 4.313 0 0 0-.116.26c-.108.173-.178.31-.251.492-.05.082-.104.167-.16.252h-.001c-.55.834-1.304 1.69-2.087 2.476l-.003.002c-1.223 1.234-2.474 2.266-3.033 2.727l-.041.034c-.05.04-.105.086-.157.13l-.06-.061c-.065-.064-.154-.135-.197-.17l-.008-.006a28.517 28.517 0 0 1-3.214-2.817l-.003-.004c-.968-.985-1.824-2.042-2.27-3.009a4.077 4.077 0 0 1-.24-.719 4.491 4.491 0 0 1-.129-.715l.001-.036v-.098l-.001-.005-.002-.129c0-1.778 1.436-3.218 3.066-3.218.857 0 1.667.348 2.393 1.102a1.079 1.079 0 0 0 1.66-.129c.428-.61 1.155-.973 2.043-.973 1.63 0 3.066 1.441 3.066 3.218v.001z',)


SEARCH_RESULT_SELECTOR = (
    'a[href*="/video/"], '
    '#waterFallScrollContainer [id^="waterfall_item_"] .search-result-card'
)

EXTRACT_SCRIPT = r"""(() => {
  const links = Array.from(document.querySelectorAll('a[href*="/video/"]'));
  const candidates = links.map(link => ({link, url: link.href, card:
    link.closest('.search-result-card') || link.closest('li, article')
      || link.parentElement?.parentElement?.parentElement
      || link.parentElement}));
  // Public search UI observed 2026-10-20: video cards can be DIVs without links.
  // Related-search tiles also have waterfall IDs; require an actual video card.
  for (const card of document.querySelectorAll(
      '#waterFallScrollContainer [id^="waterfall_item_"] .search-result-card')) {
    const id = card.closest('[id^="waterfall_item_"]')?.id.match(/^waterfall_item_(\d{15,22})$/)?.[1];
    const lines = (card.innerText || '').split(/\n+/).map(s => s.trim()).filter(Boolean);
    if (!id || !lines.some(s => /^(?:\d{1,2}:)?\d{1,2}:\d{2}$/.test(s))
        || !lines.some(s => s.startsWith('@'))) continue;
    candidates.push({link: card, card, url: 'https://www.douyin.com/video/' + id});
  }
  const seen = new Set();
  return candidates.map(({link, card, url}) => {
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
    let metricText = lines.find(
      (value) => /^(?:\d+(?:\.\d+)?)(?:万|亿)?$/.test(value)
    ) || '';
    let metricKind = 'displayed_unknown';
    // A bare number remains unknown. Explicit UI semantics take precedence.
    const likeElements = card?.querySelectorAll(
      '[data-e2e="like-icon"], [data-e2e="video-like"], [aria-label*="点赞"], [aria-label*="喜欢"]'
    ) || [];
    for (const element of likeElements) {
      const candidates = [element.getAttribute('aria-label') || '', element.innerText || ''];
      if (element.getAttribute('data-e2e') === 'like-icon') {
        candidates.push(element.parentElement?.innerText || '');
      }
      const values = candidates.flatMap((text) => text.trim().split(/\n+/));
      const found = values.map((text) => text.trim().match(
        /^(?:点赞|喜欢)?\s*(\d+(?:\.\d+)?(?:万|亿)?)\s*(?:次?点赞|次?喜欢)?$/
      )).find(Boolean);
      if (found) { metricText = found[1]; metricKind = 'likes'; break; }
    }
    // Verified 2026-10-07 search-card UI: SVG heart and count are siblings.
    if (metricKind === 'displayed_unknown') {
      const knownHeartPaths = __VERIFIED_SEARCH_LIKE_PATHS__;
      const normalizePath = value => String(value || '').replace(/\s+/g, '');
      for (const svg of card?.querySelectorAll('svg[viewBox="0 0 24 24"]') || []) {
        const paths = Array.from(svg.querySelectorAll('path'));
        if (paths.length !== 1 || !knownHeartPaths.some(
          path => normalizePath(path) === normalizePath(paths[0].getAttribute('d')))) continue;
        const holder = svg.parentElement;
        const counts = Array.from(holder?.children || []).filter(
          element => element.tagName.toLowerCase() === 'span'
            && /^(\d+(?:\.\d+)?(?:万|亿)?)$/.test((element.textContent || '').trim()));
        if (counts.length !== 1 || !/^(\d+(?:\.\d+)?(?:万|亿)?)$/.test((holder.innerText || '').trim())) continue;
        metricText = counts[0].textContent.trim();
        metricKind = 'likes';
        break;
      }
    }
    const publishedAtText = lines.map(value => value.replace(/^[·•]\s*/, '')).find(
      (value) => /^(?:刚刚|昨天|前天|\d+(?:分钟|小时|天)前|\d{1,2}-\d{1,2}|\d{4}-\d{1,2}-\d{1,2}|(?:\d{4}年)?\d{1,2}月\d{1,2}日)$/.test(value)
    ) || '';
    const durationText = lines.find(
      (value) => /^(?:\d{1,2}:)?\d{1,2}:\d{2}$/.test(value)
    ) || '';
    const hashtags = Array.from(
      raw.matchAll(/[#＃]([0-9A-Za-z_\u3400-\u9fff]{1,40})/gu),
      (match) => match[1]
    );
    return {
      url,
      title,
      author,
      metricText,
      metricKind,
      publishedAtText,
      durationText,
      hashtags,
      rawText: raw.slice(0, 1000),
    };
  }).filter((item) => {
    const id = item.url.match(/\/video\/(\d+)/)?.[1];
    if (!id || seen.has(id)) return false;
    seen.add(id);
    return true;
  });
})()""".replace("__VERIFIED_SEARCH_LIKE_PATHS__", json.dumps(VERIFIED_SEARCH_LIKE_PATHS))

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


def build_account_douyin_trend_session(
    account_key: str, *, headless: bool = False
) -> BrowserSession:
    """Resolve the selected account through the unified runtime binding."""
    from src.operations_accounts import AccountRuntimeService

    context = AccountRuntimeService().resolve(account_key)
    return context.create_browser_session(headless=headless)


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

    @classmethod
    def for_account(cls, account_key: str) -> "DouyinWebTrendProvider":
        return cls(
            session_factory=lambda headless: build_account_douyin_trend_session(
                account_key,
                headless=headless,
            )
        )

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
                    "published_at",
                    "hashtags",
                    "duration_seconds",
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
        blocked_search = {}
        navigation_evidence = {}
        challenge_evidence = {}
        tag_relations = []
        tag_traffic_snapshots = []
        last_navigation_started = 0.0
        verification_deadline = time.monotonic() + (
            min(600, max(0, request.manual_verification_timeout_seconds)) if not request.headless else 0
        )

        def collect_sort(
            *,
            query: str,
            root_keywords: list[str],
            query_kind: str,
            query_depth: int,
            sort: DouyinSort,
        ) -> tuple[list[TrendObservation], str]:
            nonlocal last_navigation_started, blocked_search, challenge_evidence, navigation_evidence
            if last_navigation_started:
                remaining = (
                    decision.min_interval_seconds
                    - (time.monotonic() - last_navigation_started)
                )
                if remaining > 0:
                    time.sleep(remaining)
            last_navigation_started = time.monotonic()
            try:
                rows, issue = self._collect_sort(
                    session, query=query, root_keywords=root_keywords, query_kind=query_kind,
                    query_depth=query_depth, sort=sort, limit=safe_limit,
                    retain_raw=policy.raw_retention_days > 0,
                    manual_verification_seconds=max(0, verification_deadline - time.monotonic()))
            except BrowserNavigationTimeout as exc:
                blocked_search = _blocked_search_context(query, query_kind, sort.key, 'navigation_timeout')
                navigation_evidence = exc.navigation_evidence
                return [], 'browser_navigation_timeout'
            navigation_evidence = getattr(issue, 'navigation_evidence', {}) or navigation_evidence
            if issue == "human_required":
                blocked_search = _blocked_search_context(query, query_kind, sort.key,
                    getattr(issue, "detection", "unclassified"))
                challenge_evidence = dict(getattr(issue, 'evidence', {}) or {})
            return rows, issue

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
                    if issue == 'browser_navigation_timeout':
                        stopped_reason = issue
                        warnings.append('搜索页面跳转超时，未确认可用结果；未刷新重试或记为成功观看。')
                        human_required = True
                        break
                    if issue == "human_required":
                        warnings.append(f"{keyword}：" + ("验证界面未就绪或读取不明，未确认可操作验证码" if getattr(issue, "stop_code", "") == "verification_ui_unconfirmed" else "需要人工完成登录或安全验证"))
                        stopped_reason = getattr(issue, 'stop_code', 'human_required')
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
                **related_tag_selection_options(request),
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
                        if issue == 'browser_navigation_timeout':
                            stopped_reason = issue
                            warnings.append('关联话题页面跳转超时，未确认可用结果；本次采集已停止。')
                            human_required = True
                            break
                        if issue == "human_required":
                            warnings.append(
                                f"{query}：" + ("验证界面未就绪或读取不明，未确认可操作验证码" if getattr(issue, "stop_code", "") == "verification_ui_unconfirmed" else "需要人工完成登录或安全验证")
                            )
                            stopped_reason = getattr(issue, 'stop_code', 'human_required')
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
            blocked_search=blocked_search,
            challenge_evidence=challenge_evidence,
            navigation_evidence=navigation_evidence,
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
        manual_verification_seconds: float = 0,
    ) -> tuple[list[TrendObservation], str]:
        # Every sort starts from a fresh page so comprehensive is the real
        # default and filter/scroll state cannot leak into the next ranking.
        navigation_error = None
        try:
            page = session.open_page(build_douyin_search_url(query))
        except BrowserNavigationTimeout as exc:
            if exc.page is None or not exc.navigation_evidence['target_matched']:
                raise
            navigation_error, page = exc, exc.page
        detection = self._wait_until_ready(page) or self._blocked_detection(page)
        if detection == 'login_prompt_without_results':
            raise SearchResultsUnavailable('搜索结果未能读取；普通登录入口不足以证明需要验证码或登录过期。')
        if detection in {'verification_ui_unconfirmed', 'security_text_without_results'}:
            issue = _verification_stop(detection)
            issue.navigation_evidence = navigation_error.navigation_evidence if navigation_error else {}
            return [], issue
        if detection:
            if not self._await_manual_verification(page, manual_verification_seconds):
                issue = _verification_stop(detection)
                issue.navigation_evidence = navigation_error.navigation_evidence if navigation_error else {}
                return [], issue
            session.cmd('save_visible_state', path=session.config.storage_state_path)
        if navigation_error and not (
                navigation_error.navigation_evidence['navigation_committed']
                and navigation_error.navigation_evidence['ready_state'] in {'interactive', 'complete'}
                and page.locator(SEARCH_RESULT_SELECTOR).count() > 0):
            raise navigation_error
        if sort.key != "comprehensive" and not self._select_sort(page, sort.label):
            detection = self._blocked_detection(page)
            if detection:
                return [], _verification_stop(detection)
            return [], "sort_unconfirmed"

        found: dict[str, dict] = {}
        unchanged_rounds = 0
        for _ in range(12):
            detection = self._blocked_detection(page)
            if detection:
                return [], _verification_stop(detection)
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
            published_at_text = str(row.get("publishedAtText") or "").strip()
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
                    metric_kind="likes" if row.get("metricKind") == "likes" else "displayed_unknown",
                    collected_at=collected_at,
                    published_at=parse_visible_publish_time(
                        published_at_text, collected_at=collected_at
                    ),
                    published_at_text=published_at_text,
                    raw_text=raw_text if retain_raw else "",
                    query_kind=query_kind,
                    query_value=query,
                    query_depth=query_depth,
                    root_keywords=list(root_keywords),
                    hashtags=hashtags,
                    duration_seconds=_duration_to_seconds(
                        str(row.get("durationText") or "")
                    ),
                )
            )
        return output, _NavigationRecovered(navigation_error.navigation_evidence) if navigation_error else ""

    @staticmethod
    def _await_manual_verification(page, timeout_seconds):
        if timeout_seconds <= 0:
            return False
        print('等待人工验证：请在当前采集窗口完成验证码，保持窗口打开；验证通过后本次采集直接继续。', flush=True)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            page.wait_for_timeout(1000)
            if not DouyinWebTrendProvider._is_blocked(page) and page.locator(SEARCH_RESULT_SELECTOR).count() > 0:
                print('当前采集窗口已显示视频结果，继续本次采集。', flush=True)
                return True
        return False

    @staticmethod
    def _blocked_detection(page) -> str:
        evidence = confirmed_douyin_challenge(page)
        if evidence['blocking']:
            code = 'visible_challenge' if evidence['surface_state'] == 'challenge_ready' else 'verification_ui_unconfirmed'
            return _PageDetection(code, evidence)
        text = page.locator("body").inner_text()
        links = page.locator(SEARCH_RESULT_SELECTOR).count()
        if links != 0:
            return ""
        if len((text or '').strip()) <= 160 and SECURITY_BLOCK_TEXT.search(text or ""):
            page.wait_for_timeout(400)
            second = page.locator('body').inner_text() or ''
            if (page.locator(SEARCH_RESULT_SELECTOR).count() == 0 and len(second.strip()) <= 160
                    and SECURITY_BLOCK_TEXT.search(second)):
                evidence.update(security_text_confirmed=True,confirmations=0,observations=2,
                    blocking=True,surface_state='unconfirmed')
                return _PageDetection('security_text_without_results', evidence)
            return ''
        if LOGIN_PROMPT_TEXT.search(text or ""):
            return "login_prompt_without_results"
        return ""

    @staticmethod
    def _is_blocked(page) -> bool:
        return bool(DouyinWebTrendProvider._blocked_detection(page))

    @staticmethod
    def _wait_until_ready(page) -> str:
        for _ in range(20):
            detection = DouyinWebTrendProvider._blocked_detection(page)
            if detection and detection != "login_prompt_without_results":
                return detection
            if page.locator(SEARCH_RESULT_SELECTOR).count() > 0:
                return
            # A normal login entry can be present while results are rendering.
            # Give that case the existing bounded readiness window; if no rows
            # ever appear, _collect_sort still stops with its original evidence.
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


def _duration_to_seconds(value: str) -> float | None:
    parts = str(value or "").strip().split(":")
    if len(parts) not in {2, 3} or not all(part.isdigit() for part in parts):
        return None
    values = [int(part) for part in parts]
    if len(values) == 2:
        minutes, seconds = values
        hours = 0
    else:
        hours, minutes, seconds = values
    if minutes >= 60 or seconds >= 60:
        return None
    return float(hours * 3600 + minutes * 60 + seconds)


def parse_visible_publish_time(value: str, *, collected_at: str) -> str:
    """Normalize a visible relative/date label without pretending second precision."""
    text = str(value or "").strip()
    text = re.sub(r"^[·•]\s*", "", text)
    text = re.sub(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$", r"\1-\2-\3", text)
    text = re.sub(r"^(\d{1,2})月(\d{1,2})日$", r"\1-\2", text)
    if not text:
        return ""
    try:
        captured = datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    captured = captured.astimezone(timezone.utc)
    if text == "刚刚":
        published = captured
    elif text == "昨天":
        published = captured - timedelta(days=1)
    elif text == "前天":
        published = captured - timedelta(days=2)
    else:
        relative = re.fullmatch(r"(\d+)(分钟|小时|天)前", text)
        if relative:
            amount = int(relative.group(1))
            delta = {
                "分钟": timedelta(minutes=amount),
                "小时": timedelta(hours=amount),
                "天": timedelta(days=amount),
            }[relative.group(2)]
            published = captured - delta
        else:
            china_tz = timezone(timedelta(hours=8))
            local_captured = captured.astimezone(china_tz)
            try:
                if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", text):
                    local_date = datetime.strptime(text, "%Y-%m-%d").date()
                elif re.fullmatch(r"\d{1,2}-\d{1,2}", text):
                    local_date = datetime.strptime(
                        f"{local_captured.year}-{text}", "%Y-%m-%d"
                    ).date()
                    if local_date > local_captured.date() + timedelta(days=1):
                        local_date = local_date.replace(year=local_date.year - 1)
                else:
                    return ""
            except ValueError:
                return ""
            published = datetime.combine(
                local_date, datetime.min.time(), tzinfo=china_tz
            ).astimezone(timezone.utc)
    return published.isoformat()
