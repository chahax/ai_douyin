import json

from src.platform_adapter.fanqie_promotion import (
    FANQIE_ALIAS_STATUS_MAP,
    FANQIE_NOVEL_LIST_URL,
    LIST_PROMOTIONS_JS,
    FanqiePromotionService,
)


class _FakeLocator:
    def __init__(self, page):
        self.page = page

    def evaluate(self, _script):
        value = self.page.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class _FakePage:
    def __init__(self, responses):
        self.responses = list(responses)
        self.waits = []

    def locator(self, _selector):
        return _FakeLocator(self)

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)


class _FakeSession:
    def __init__(self, page):
        self.page = page
        self.opened_url = None
        self.stopped = False

    def open_page(self, url):
        self.opened_url = url
        return self.page

    def stop(self):
        self.stopped = True


def test_list_promotions_waits_until_rows_are_loaded(monkeypatch, tmp_path):
    complete = {
        "count": 1,
        "items": [{
            "alias": "alias-1", "book_name": "book-1",
            "book_id": "7376186979257420825", "publish_type": "AIGC",
            "alias_status": "生效中",
        }],
        "all_headers": ["关键词", "书本信息", "发文类型", "别名状态", "书籍状态", "发文详情"],
        "table_ready": True,
        "loading": False,
    }
    page = _FakePage([
        {"count": 0, "items": [], "parse_error": "no_table_header", "loading": True},
        {"count": 1, "items": [{"alias": "placeholder"}], "table_ready": True, "loading": False},
        complete, complete, complete, complete,
    ])
    session = _FakeSession(page)
    service = FanqiePromotionService(root_dir=tmp_path)
    monkeypatch.setattr(service, "_open_browser_cache_session", lambda **_kwargs: session)

    result = service.list_promotions(sync_to_tasks=False, wait_timeout_ms=5_000)

    assert result["count"] == 1
    assert result["schema_version"] == "fanqie_live_promotion_snapshot/v1"
    assert result["capture_method"] == "fanqie-promo-list/live-browser"
    assert result["source_url"] == FANQIE_NOVEL_LIST_URL
    assert result["complete_rows_verified"] is True
    assert result["stable_poll_count"] == 4
    assert result["items"][0]["alias_status_internal"] == "active"
    assert page.waits == [1000] * 5
    assert session.opened_url == FANQIE_NOVEL_LIST_URL
    assert session.stopped is True


def test_list_promotions_rejects_partial_rows_at_timeout(monkeypatch, tmp_path):
    partial = {
        "count": 1,
        "items": [{"alias": "placeholder"}],
        "all_headers": ["关键词", "书本信息", "发文类型", "别名状态", "书籍状态", "发文详情"],
        "table_ready": True,
        "loading": False,
    }
    page = _FakePage([partial])
    session = _FakeSession(page)
    service = FanqiePromotionService(root_dir=tmp_path)
    monkeypatch.setattr(service, "_open_browser_cache_session", lambda **_kwargs: session)
    times = iter([0.0, 0.5, 2.0])
    monkeypatch.setattr(
        "src.platform_adapter.fanqie_promotion.time.monotonic", lambda: next(times)
    )
    try:
        service.list_promotions(sync_to_tasks=False, wait_timeout_ms=1_000)
    except RuntimeError as exc:
        assert "incomplete_rows" in str(exc)
        assert "book_name" in str(exc)
    else:
        raise AssertionError("Expected partial-row timeout")
    assert session.stopped is True


def test_list_promotions_accepts_only_stable_verified_empty_table(monkeypatch, tmp_path):
    empty = {
        "count": 0,
        "items": [],
        "all_headers": [
            "关键词", "书本信息", "发文类型", "别名状态", "书籍状态", "发文详情"
        ],
        "table_ready": True,
        "loading": False,
        "empty_state": True,
    }
    page = _FakePage([empty, empty, empty, empty])
    session = _FakeSession(page)
    service = FanqiePromotionService(root_dir=tmp_path)
    monkeypatch.setattr(service, "_open_browser_cache_session", lambda **_kwargs: session)
    result = service.list_promotions(sync_to_tasks=False, wait_timeout_ms=5_000)
    assert result["schema_version"] == "fanqie_live_promotion_snapshot/v1"
    assert result["count"] == 0 and result["items"] == []
    assert result["empty_state"] is True
    assert result["complete_rows_verified"] is True
    assert result["stable_poll_count"] == 4
    assert page.waits == [1000] * 3
    assert session.stopped is True


def test_list_promotions_rejects_empty_table_missing_publish_gate_headers(
    monkeypatch, tmp_path,
):
    incomplete_empty = {
        "count": 0,
        "items": [],
        "all_headers": ["关键词", "书本信息", "别名状态"],
        "table_ready": True,
        "loading": False,
        "empty_state": True,
    }
    page = _FakePage([incomplete_empty])
    session = _FakeSession(page)
    service = FanqiePromotionService(root_dir=tmp_path)
    monkeypatch.setattr(service, "_open_browser_cache_session", lambda **_kwargs: session)
    times = iter([0.0, 0.5, 2.0])
    monkeypatch.setattr(
        "src.platform_adapter.fanqie_promotion.time.monotonic", lambda: next(times)
    )
    try:
        service.list_promotions(sync_to_tasks=False, wait_timeout_ms=1_000)
    except RuntimeError as exc:
        assert "missing_publish_gate_headers" in str(exc)
        assert "发文详情" in str(exc)
    else:
        raise AssertionError("Expected missing-header timeout")
    assert session.stopped is True


def test_list_promotions_stops_session_when_browser_evaluation_fails(monkeypatch, tmp_path):
    page = _FakePage([RuntimeError("evaluate failed")])
    session = _FakeSession(page)
    service = FanqiePromotionService(root_dir=tmp_path)
    monkeypatch.setattr(service, "_open_browser_cache_session", lambda **_kwargs: session)

    try:
        service.list_promotions(sync_to_tasks=False, wait_timeout_ms=5_000)
    except RuntimeError as exc:
        assert "evaluate failed" in str(exc)
    else:
        raise AssertionError("Expected browser evaluation failure")

    assert session.stopped is True


def test_promotion_list_contract_is_header_driven():
    assert "/page/promotion-list" in FANQIE_NOVEL_LIST_URL
    assert "headerMap" in LIST_PROMOTIONS_JS
    assert "missing_required_headers" in LIST_PROMOTIONS_JS
    assert "发文详情" in LIST_PROMOTIONS_JS
    for required in ("关键词", "书本信息", "发文类型", "别名状态", "书籍状态", "发文详情"):
        assert required in LIST_PROMOTIONS_JS
    assert "'.arco-spin-loading, .arco-spin," not in LIST_PROMOTIONS_JS
    assert '[aria-busy="true"]' in LIST_PROMOTIONS_JS


def test_force_invalid_maps_active_task_to_expired_and_is_idempotent(tmp_path):
    task_dir = tmp_path / "tasks" / "task-1"
    task_dir.mkdir(parents=True)
    task_path = task_dir / "task.json"
    task_path.write_text(json.dumps({
        "task_id": "task-1",
        "content_type": "novel",
        "promotion_alias": "alias-1",
        "apply_status": "active",
        "apply_message": "old active status",
        "fanqie_book_id": "7376186979257420825",
        "publish_type": "AI数字人",
        "valid_range": "old range",
        "has_fill_link": True,
        "fill_status": "old value",
        "updated_at": "old timestamp",
    }, ensure_ascii=False), encoding="utf-8")

    assert FANQIE_ALIAS_STATUS_MAP["强制失效"] == "expired"
    item = {
        "alias": "alias-1",
        "alias_status": "强制失效",
        "alias_status_internal": "expired",
        "book_id": "7376186979257420825",
        "publish_type": "AI数字人",
        "created_at": "2026-06-29 15:26:28",
        "valid_range": "2026-01-08～ 2026-07-07",
        "has_fill_link": False,
        "fill_status": "未填写",
    }
    service = FanqiePromotionService(root_dir=tmp_path)

    first = service._sync_promotion_status("novel", [item])
    updated = json.loads(task_path.read_text(encoding="utf-8"))
    first_updated_at = updated["updated_at"]

    assert first == ["task-1"]
    assert updated["apply_status"] == "expired"
    assert updated["valid_range"] == "2026-01-08～ 2026-07-07"
    assert updated["has_fill_link"] is False
    assert updated["fill_status"] == "未填写"

    second = service._sync_promotion_status("novel", [item])
    unchanged = json.loads(task_path.read_text(encoding="utf-8"))
    assert second == []
    assert unchanged["updated_at"] == first_updated_at
