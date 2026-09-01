from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlparse

from src.trend_intelligence.providers.base import TrendCollectionRequest
from src.trend_intelligence.providers.douyin_web import (
    DouyinWebTrendProvider,
    estimate_douyin_planned_pages,
)
from src.trend_intelligence.source_policy import (
    PolicyStatus,
    SourcePolicy,
    SourceProvider,
)
from src.trend_intelligence.models import TrendObservation
from src.trend_intelligence.tag_graph import (
    build_keyword_tag_relations,
    extract_hashtags,
)


NOW = datetime.now(timezone.utc)


class FakeLocator:
    def __init__(self, page, selector: str):
        self.page = page
        self.selector = selector

    def evaluate(self, script: str):
        if "const links = Array.from" in script:
            return [self.page.visible_row()]
        if "sort-selection-signature" in script:
            for label, sort_key in self.page.sort_keys_by_label.items():
                if f'const targetLabel = "{label}"' in script:
                    return self.page.menu_open and self.page.active_sort == sort_key
            return False
        if "window.scrollTo" in script:
            self.page.scrolled_to_top += 1
        return None

    def inner_text(self):
        return self.page.body_text

    def count(self):
        return self.page.video_link_count


class FakePage:
    sort_keys_by_label = {
        "综合排序": "comprehensive",
        "最多点赞": "most_liked",
        "最新发布": "latest",
    }
    rows_by_sort = {
        "comprehensive": {
            "url": "https://www.douyin.com/video/7531234567890123456",
            "title": "综合排序：没有借条如何证明借款 #法律科普",
            "author": "@律师",
            "metricText": "2.4万",
            "rawText": "综合测试样本",
        },
        "most_liked": {
            "url": "https://www.douyin.com/video/7541234567890123456",
            "title": "最多点赞：夫妻共同债务如何认定 #法律科普",
            "author": "@律师",
            "metricText": "8.8万",
            "rawText": "点赞测试样本",
        },
        "latest": {
            "url": "https://www.douyin.com/video/7551234567890123456",
            "title": "最新发布：劳动仲裁证据清单 #法律科普 #劳动法",
            "author": "@律师",
            "metricText": "128",
            "rawText": "最新测试样本",
        },
    }
    tag_rows_by_sort = {
        "comprehensive": {
            "url": "https://www.douyin.com/video/7561234567890123456",
            "title": "法律科普综合样本 #法律科普#借款证据",
            "author": "@普法律师",
            "metricText": "3.2万",
            "rawText": "标签综合测试样本 #法律科普#借款证据",
        },
        "most_liked": {
            "url": "https://www.douyin.com/video/7571234567890123456",
            "title": "法律科普点赞样本 #法律科普 #婚姻法",
            "author": "@普法律师",
            "metricText": "9.1万",
            "rawText": "标签点赞测试样本 #法律科普 #婚姻法",
        },
        "latest": {
            "url": "https://www.douyin.com/video/7581234567890123456",
            "title": "法律科普最新样本 #法律科普 #劳动法",
            "author": "@普法律师",
            "metricText": "256",
            "rawText": "标签最新测试样本 #法律科普 #劳动法",
        },
    }

    def __init__(
        self,
        *,
        blocked: bool = False,
        hover_opens: bool = True,
        no_op_labels: set[str] | None = None,
    ):
        self.body_text = "安全验证" if blocked else "搜索结果"
        self.video_link_count = 0 if blocked else 1
        self.waits = []
        self.hover_opens = hover_opens
        self.no_op_labels = no_op_labels or set()
        self.interactions: list[tuple[str, str, bool]] = []
        self.navigation_count = 0
        self.scrolled_to_top = 0
        self.reset_for_navigation("法律")

    def reset_for_navigation(self, query: str = "法律"):
        self.navigation_count += 1
        self.current_query = query
        self.active_sort = "comprehensive"
        self.menu_open = False

    def visible_row(self):
        if self.current_query.startswith("#"):
            return dict(self.tag_rows_by_sort[self.active_sort])
        return dict(self.rows_by_sort[self.active_sort])

    def locator(self, selector: str):
        return FakeLocator(self, selector)

    def wait_for_timeout(self, milliseconds: int):
        self.waits.append(milliseconds)

    def interact_visible_exact_text(
        self,
        text: str,
        *,
        operation: str = "inspect",
        prefer_parent: bool = False,
    ) -> bool:
        self.interactions.append((text, operation, prefer_parent))
        if text == "筛选":
            if operation == "hover" and self.hover_opens:
                self.menu_open = True
            elif operation == "click":
                self.menu_open = True
            return True
        if text not in self.sort_keys_by_label or not self.menu_open:
            return False
        if operation == "click" and text not in self.no_op_labels:
            self.active_sort = self.sort_keys_by_label[text]
        return True


class FakeSession:
    def __init__(self, **page_options):
        self.page = FakePage(**page_options)
        self.urls = []
        self.stopped = False

    def open_page(self, url: str):
        self.urls.append(url)
        encoded_query = urlparse(url).path.split("/search/", 1)[-1]
        self.page.reset_for_navigation(unquote(encoded_query))
        return self.page

    def stop(self):
        self.stopped = True


def _policy() -> SourcePolicy:
    return SourcePolicy(
        policy_id="test-authorized-web",
        provider=SourceProvider.AUTHORIZED_WEB,
        status=PolicyStatus.APPROVED,
        allowed_hosts=("www.douyin.com",),
        allowed_path_prefixes=("/search",),
        allowed_fields=frozenset(
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
                "tag_relationships",
                "tag_traffic_snapshots",
            }
        ),
        allowed_purposes=frozenset({"trend_analysis"}),
        max_pages_per_run=10,
        daily_page_cap=20,
        starts_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=1),
        authorization_reference_hash="sha256:test",
    )


def test_provider_is_blocked_before_browser_without_explicit_enable() -> None:
    called = []
    provider = DouyinWebTrendProvider(
        session_factory=lambda headless: called.append(headless)
    )
    result = provider.collect(
        TrendCollectionRequest(keywords=["法律"]),
        policy=_policy(),
    )

    assert result.policy_code == "web_crawler_disabled"
    assert result.observations == []
    assert called == []


def test_provider_collects_visible_rows_with_fake_browser() -> None:
    session = FakeSession()
    provider = DouyinWebTrendProvider(session_factory=lambda headless: session)
    result = provider.collect(
        TrendCollectionRequest(
            keywords=["法律"],
            limit_per_sort=1,
            web_crawler_enabled=True,
        ),
        policy=_policy(),
    )

    assert result.policy_code == "allowed"
    assert len(result.observations) == 3
    assert {row.sort_key for row in result.observations} == {
        "comprehensive",
        "most_liked",
        "latest",
    }
    assert {row.sort_key: row.video_id for row in result.observations} == {
        "comprehensive": "7531234567890123456",
        "most_liked": "7541234567890123456",
        "latest": "7551234567890123456",
    }
    assert {row.sort_key: row.metric_value for row in result.observations} == {
        "comprehensive": 24_000,
        "most_liked": 88_000,
        "latest": 128,
    }
    assert len(session.urls) == 3
    assert not any(
        text == "综合排序" for text, _, _ in session.page.interactions
    )
    assert session.stopped is True


def test_provider_clicks_filter_when_hover_does_not_open_menu() -> None:
    session = FakeSession(hover_opens=False)
    provider = DouyinWebTrendProvider(session_factory=lambda headless: session)
    result = provider.collect(
        TrendCollectionRequest(
            keywords=["法律"],
            sorts=("latest",),
            limit_per_sort=1,
            web_crawler_enabled=True,
        ),
        policy=_policy(),
    )

    assert [row.video_id for row in result.observations] == [
        "7551234567890123456"
    ]
    assert ("筛选", "hover", True) in session.page.interactions
    assert ("筛选", "click", True) in session.page.interactions
    assert ("最新发布", "click", False) in session.page.interactions


def test_provider_rejects_sort_when_click_does_not_change_selected_state() -> None:
    session = FakeSession(no_op_labels={"最新发布"})
    provider = DouyinWebTrendProvider(session_factory=lambda headless: session)
    result = provider.collect(
        TrendCollectionRequest(
            keywords=["法律"],
            sorts=("latest",),
            limit_per_sort=1,
            web_crawler_enabled=True,
        ),
        policy=_policy(),
    )

    assert result.observations == []
    assert result.warnings == ["法律：无法确认排序“最新发布”已生效"]


def test_each_sort_reloads_page_so_comprehensive_returns_to_default() -> None:
    session = FakeSession()
    provider = DouyinWebTrendProvider(session_factory=lambda headless: session)
    result = provider.collect(
        TrendCollectionRequest(
            keywords=["法律"],
            sorts=("most_liked", "comprehensive"),
            limit_per_sort=1,
            web_crawler_enabled=True,
        ),
        policy=_policy(),
    )

    assert [(row.sort_key, row.video_id) for row in result.observations] == [
        ("most_liked", "7541234567890123456"),
        ("comprehensive", "7531234567890123456"),
    ]
    assert len(session.urls) == 2


def test_provider_stops_for_human_verification() -> None:
    session = FakeSession(blocked=True)
    provider = DouyinWebTrendProvider(session_factory=lambda headless: session)
    result = provider.collect(
        TrendCollectionRequest(
            keywords=["法律"],
            web_crawler_enabled=True,
        ),
        policy=_policy(),
    )

    assert result.observations == []
    assert result.stopped_reason == "human_required"
    assert "安全验证" in result.warnings[0]
    assert session.stopped is True


def test_provider_expands_one_hashtag_level_across_all_sorts() -> None:
    session = FakeSession()
    provider = DouyinWebTrendProvider(session_factory=lambda headless: session)
    request = TrendCollectionRequest(
        keywords=["法律"],
        limit_per_sort=1,
        web_crawler_enabled=True,
        expand_related_tags=True,
        max_related_tags_per_keyword=1,
    )

    result = provider.collect(request, policy=_policy())

    assert len(result.observations) == 6
    tag_rows = [
        row for row in result.observations if row.query_kind == "hashtag"
    ]
    assert {row.keyword for row in tag_rows} == {"#法律科普"}
    assert {row.sort_key for row in tag_rows} == {
        "comprehensive",
        "most_liked",
        "latest",
    }
    assert all(row.query_depth == 1 for row in tag_rows)
    assert all(row.root_keywords == ["法律"] for row in tag_rows)
    assert len(session.urls) == 6
    assert not any("%23%E5%80%9F%E6%AC%BE%E8%AF%81%E6%8D%AE" in url for url in session.urls)
    assert any(
        relation.source_kind == "keyword"
        and relation.target_tag == "法律科普"
        and relation.expanded
        for relation in result.tag_relations
    )
    assert any(
        relation.source_kind == "tag"
        and relation.source_value == "法律科普"
        and relation.target_tag == "借款证据"
        for relation in result.tag_relations
    )
    assert len(result.tag_traffic_snapshots) == 3
    assert {item.sort_key for item in result.tag_traffic_snapshots} == {
        "comprehensive",
        "most_liked",
        "latest",
    }


def test_expanded_page_budget_is_fail_closed_before_browser() -> None:
    called = []
    provider = DouyinWebTrendProvider(
        session_factory=lambda headless: called.append(headless)
    )
    request = TrendCollectionRequest(
        keywords=["法律", "小说"],
        web_crawler_enabled=True,
        expand_related_tags=True,
        max_related_tags_per_keyword=2,
    )

    result = provider.collect(request, policy=_policy())

    assert estimate_douyin_planned_pages(request) == 18
    assert result.policy_code == "run_page_cap_exceeded"
    assert called == []


def test_hashtag_extraction_handles_adjacent_fullwidth_and_long_text() -> None:
    long_text = "正文" * 600 + " ＃LateTag"
    assert extract_hashtags(
        "#法律科普#未成年人保护法 ＃劳动法 #LEGAL #legal",
        long_text,
    ) == ["法律科普", "未成年人保护法", "劳动法", "legal", "latetag"]


def test_planned_pages_preserves_legacy_and_caps_related_queries() -> None:
    assert estimate_douyin_planned_pages(
        TrendCollectionRequest(keywords=["法律"])
    ) == 3
    assert estimate_douyin_planned_pages(
        TrendCollectionRequest(
            keywords=["法律"],
            expand_related_tags=True,
            max_related_tags_per_keyword=2,
        )
    ) == 9
    assert estimate_douyin_planned_pages(
        TrendCollectionRequest(
            keywords=[str(index) for index in range(10)],
            expand_related_tags=True,
            max_related_tags_per_keyword=3,
        )
    ) == 48


def test_related_tag_selection_prefers_root_topic_over_incidental_slogan() -> None:
    rows = [
        TrendObservation(
            item_id="douyin:topic",
            video_id="topic",
            url="https://www.douyin.com/video/topic",
            title="法律科普样本",
            author="@律师",
            keyword="法律",
            sort_key="comprehensive",
            sort_label="综合排序",
            rank=1,
            metric_value=100_000,
            root_keywords=["法律"],
            hashtags=["法律科普"],
        )
    ]
    for sort_key in ("comprehensive", "most_liked", "latest"):
        rows.append(
            TrendObservation(
                item_id="douyin:slogan",
                video_id="slogan",
                url="https://www.douyin.com/video/slogan",
                title="事件评论",
                author="@评论员",
                keyword="法律",
                sort_key=sort_key,
                sort_label=sort_key,
                rank=1,
                metric_value=50_000,
                root_keywords=["法律"],
                hashtags=["超哥金句"],
            )
        )

    relations, selected = build_keyword_tag_relations(
        rows,
        max_tags_per_keyword=1,
        max_total_tags=1,
    )

    assert selected == {"法律科普": ["法律"]}
    assert next(
        item for item in relations if item.target_tag == "法律科普"
    ).expanded is True
    assert next(
        item for item in relations if item.target_tag == "超哥金句"
    ).expanded is False
