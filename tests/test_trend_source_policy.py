from datetime import datetime, timedelta, timezone

import pytest

from src.trend_intelligence.source_policy import (
    PolicyStatus,
    SourcePolicy,
    SourcePolicyGate,
    SourceProvider,
    SourceRequest,
    approved_manual_import_policy,
)


NOW = datetime(2026, 8, 26, tzinfo=timezone.utc)


def _approved_web_policy(**overrides) -> SourcePolicy:
    values = {
        "policy_id": "douyin-authorized-v1",
        "provider": SourceProvider.AUTHORIZED_WEB,
        "status": PolicyStatus.APPROVED,
        "allowed_hosts": ("www.douyin.com",),
        "allowed_path_prefixes": ("/search",),
        "allowed_fields": frozenset({"title", "displayed_metrics"}),
        "allowed_purposes": frozenset({"trend_analysis", "generative_processing"}),
        "min_interval_seconds": 30,
        "max_pages_per_run": 20,
        "daily_page_cap": 50,
        "raw_retention_days": 0,
        "starts_at": NOW - timedelta(days=1),
        "expires_at": NOW + timedelta(days=1),
        "authorization_reference_hash": "sha256:example",
    }
    values.update(overrides)
    return SourcePolicy(**values)


def _web_request(**overrides) -> SourceRequest:
    values = {
        "provider": SourceProvider.AUTHORIZED_WEB,
        "purposes": frozenset({"trend_analysis"}),
        "requested_fields": frozenset({"title"}),
        "target_url": "https://www.douyin.com/search/%E6%B3%95%E5%BE%8B",
        "planned_pages": 2,
        "pages_used_today": 3,
        "requested_at": NOW,
    }
    values.update(overrides)
    return SourceRequest(**values)


def test_authorized_web_is_still_disabled_by_default() -> None:
    decision = SourcePolicyGate().evaluate(_approved_web_policy(), _web_request())
    assert decision.allowed is False
    assert decision.code == "web_crawler_disabled"


def test_authorized_web_allows_only_complete_approved_scope() -> None:
    decision = SourcePolicyGate().evaluate(
        _approved_web_policy(),
        _web_request(),
        web_crawler_enabled=True,
    )
    assert decision.allowed is True
    assert decision.min_interval_seconds == 30
    assert decision.max_pages_per_run == 20


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("https://www.douyin.com.evil.example/search/legal", "host_not_allowed"),
        ("https://www.douyin.com/searching/legal", "path_not_allowed"),
        ("javascript:alert(1)", "invalid_target_url"),
    ],
)
def test_authorized_web_rejects_scope_escape(url: str, code: str) -> None:
    decision = SourcePolicyGate().evaluate(
        _approved_web_policy(),
        _web_request(target_url=url),
        web_crawler_enabled=True,
    )
    assert decision.allowed is False
    assert decision.code == code


def test_expired_policy_is_denied() -> None:
    policy = _approved_web_policy(expires_at=NOW)
    decision = SourcePolicyGate().evaluate(
        policy,
        _web_request(),
        web_crawler_enabled=True,
    )
    assert decision.code == "policy_expired"


def test_request_cannot_exceed_daily_cap() -> None:
    request = _web_request(planned_pages=2, pages_used_today=49)
    decision = SourcePolicyGate().evaluate(
        _approved_web_policy(),
        request,
        web_crawler_enabled=True,
    )
    assert decision.code == "daily_page_cap_exceeded"


def test_manual_import_does_not_require_web_switch() -> None:
    policy = approved_manual_import_policy(allowed_fields={"title"})
    request = SourceRequest(
        provider=SourceProvider.MANUAL_IMPORT,
        purposes=frozenset({"trend_analysis"}),
        requested_fields=frozenset({"title"}),
        requested_at=NOW,
    )
    assert SourcePolicyGate().evaluate(policy, request).allowed is True


def test_naive_policy_dates_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _approved_web_policy(expires_at=datetime(2026, 8, 27))
