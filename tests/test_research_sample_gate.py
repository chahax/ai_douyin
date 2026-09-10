from dataclasses import replace
from unittest.mock import Mock

import pytest

from src.trend_intelligence.models import TrendObservation
from src.trend_intelligence.repository import TrendRepository
from src.trend_intelligence.sample_gate import (
    SampleGateError, batch_observations, evaluate_sample,
)
from src.trend_intelligence.service import TrendOperationsService
from src.trend_intelligence.content_analysis import ContentAnalysisBatchService, ContentAnalysisRequest
from src.operations_accounts import AccountProfile


def sample(count=20, **overrides):
    return [TrendObservation(
        item_id=f"item:{i}", video_id=str(i), url=f"https://example.test/{i}",
        title="sample", author="author", keyword=f"tag{i % 2}", sort_key="latest",
        sort_label="latest", rank=i + 1, run_id="batch", metric_kind="views",
        metric_value=50_000,
    ) for i in range(count)] if not overrides else [replace(row, **overrides) for row in sample(count)]


def test_exact_boundaries_and_duplicate_hits():
    rows = sample()
    assert evaluate_sample(rows).passed
    assert not evaluate_sample(rows[:19]).passed
    rows[-1].metric_value -= 1
    gate = evaluate_sample(rows)
    assert not gate.passed and gate.total_views == 999_999
    assert evaluate_sample(rows + rows).total_views == 999_999
    assert evaluate_sample(rows + rows).unique_videos == 20


@pytest.mark.parametrize("changes", [
    {"metric_kind": "displayed_unknown"},
    {"metric_value": None}, {"metric_value": -1}, {"metric_value": True},
    {"keyword": "only"}, {"run_id": ""}, {"video_id": ""},
])
def test_missing_or_wrong_evidence_blocks(changes):
    assert not evaluate_sample(sample(**changes)).passed


def test_likes_are_accepted_without_relabeling_or_mixing_views():
    gate = evaluate_sample(sample(metric_kind='likes_user_confirmed'))
    assert gate.passed and gate.total_likes == 1_000_000 and gate.total_views == 0
    assert gate.metric_kind == 'likes' and gate.metric_label == '点赞数'
    assert not evaluate_sample(sample()[:10] + sample(metric_kind='likes')[10:]).passed
    rows = sample(metric_kind='likes')
    rows[-1].metric_value -= 1
    assert not evaluate_sample(rows + rows).passed


def test_mixed_batches_and_duplicate_tags_cannot_satisfy_policy():
    rows = sample()
    rows[-1].run_id = "other"
    assert not evaluate_sample(rows).passed
    rows = sample(keyword="a")
    assert not evaluate_sample(rows + [replace(rows[0], keyword="b")]).passed


def test_latest_account_batch_does_not_borrow_old_or_other_account_samples(tmp_path):
    repo = TrendRepository(tmp_path / "trend.db")
    repo.save_collection(sample(), provider="fixture", keywords=["a", "b"], account_uuid="a")
    new = sample(6, collected_at="2099-01-01T00:00:00+00:00")
    latest_run = repo.save_collection(new, provider="fixture", keywords=["a", "b"], account_uuid="a")
    repo.save_collection(sample(collected_at="2100-01-01T00:00:00+00:00"),
                         provider="fixture", keywords=["a", "b"], account_uuid="b")
    rows = batch_observations(repo, account_uuid="a")
    assert len(rows) == 6 and {row.run_id for row in rows} == {latest_run}
    analyzer = Mock()
    profile = Mock(account_uuid="a")
    with pytest.raises(SampleGateError):
        TrendOperationsService(repo, analyzer=analyzer).analyze(account_profile=profile)
    analyzer.analyze.assert_not_called()


def test_passing_service_only_analyzes_selected_batch(tmp_path):
    repo = TrendRepository(tmp_path / "trend.db")
    run_id = repo.save_collection(sample(), provider="fixture", keywords=["a", "b"])
    analyzer = Mock()
    analyzer.analyze.return_value = ([], [])
    TrendOperationsService(repo, analyzer=analyzer).analyze(collection_run_id=run_id)
    analyzed = analyzer.analyze.call_args.args[0]
    assert len(analyzed) == 20 and {row.run_id for row in analyzed} == {run_id}


def test_content_batch_blocks_before_provider_or_cache(tmp_path):
    repo = TrendRepository(tmp_path / "trend.db")
    rows = sample(19)
    repo.save_collection(rows, provider="fixture", keywords=["a", "b"], account_uuid="a")
    profile = AccountProfile(account_uuid="a", account_key="a", domain_strategy_id="legal_services")
    requests = [ContentAnalysisRequest(item_id=r.item_id, video_id=r.video_id,
                title=r.title, author=r.author, account_profile=profile) for r in rows]
    registry = Mock()
    with pytest.raises(SampleGateError):
        ContentAnalysisBatchService(repo, registry=registry).analyze(requests)
    registry.get.assert_not_called()
    assert repo.list_content_analyses() == []


def test_metric_confirmation_is_scoped_and_keeps_original_numbers_and_times(tmp_path):
    repo = TrendRepository(tmp_path / 'trend.db')
    run = repo.save_collection(sample(metric_kind='displayed_unknown'), provider='fixture',
                               keywords=['a', 'b'], account_uuid='a')
    other = repo.save_collection(sample(metric_kind='displayed_unknown'), provider='fixture',
                                 keywords=['a', 'b'], account_uuid='b')
    with pytest.raises(ValueError, match='不属于'):
        repo.confirm_batch_likes(run_id=run, account_uuid='b', statement='用户确认点赞')
    record = repo.confirm_batch_likes(run_id=run, account_uuid='a', statement='这个是喜欢（点赞）数这个也行')
    assert len(record['observations']) == 20
    assert {r['metric_kind'] for r in record['observations']} == {'displayed_unknown'}
    assert {r['metric_value'] for r in record['observations']} == {50_000}
    assert evaluate_sample(batch_observations(repo, run_id=run, account_uuid='a')).passed
    assert not evaluate_sample(batch_observations(repo, run_id=other, account_uuid='b')).passed
    assert repo.list_metric_confirmations(run_id=run, account_uuid='a')[0]['statement'] == record['statement']
