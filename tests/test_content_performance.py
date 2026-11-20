import pytest
from src.services import database
from src.services.content_performance import normalize_metrics, record_snapshot, latest_snapshots, analyze_snapshot, latest_metric_totals
from src.platform_adapter.models import VideoItem
from src.platform_adapter.sync_workflow import SyncWorkflow
from src.services.content_performance import parse_manage_card, attach_manage_cards


def test_dashboard_recovers_service_cached_before_upgrade(monkeypatch):
    import importlib
    from src.services import content_performance
    from src.web import content_performance_dashboard
    monkeypatch.delattr(content_performance, 'snapshot_history')
    monkeypatch.delattr(content_performance, 'WATCH_FIELDS')
    page = importlib.reload(content_performance_dashboard)
    assert callable(page.snapshot_history)
    assert 'avg_watch_seconds' in page.WATCH_FIELDS
    assert callable(content_performance.review_prompts)


def test_missing_invalid_and_real_zero_are_distinct():
    metrics = normalize_metrics({'play_count': 0, 'digg_count': '2', 'share_count': -1,
                                 'collect_count': 'NaN', 'comment_count': True})
    assert metrics == dict(play_count=0, like_count=2, comment_count=None, share_count=None, collect_count=None)
    assert all(v is None for v in normalize_metrics({}).values())


def test_parse_preserves_observed_metrics():
    video = SyncWorkflow(None)._parse_aweme({'aweme_id': '123', 'statistics': {'play_count': 20, 'digg_count': 3}})
    assert video.creator_metrics['like_count'] == 3
    assert video.creator_metrics['share_count'] is None


def test_history_and_account_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'metrics.db')
    for account, plays in [('a', 10), ('b', 999), ('a', 20)]:
        record_snapshot(VideoItem(account_uuid=account, video_id='v', creator_metrics={'play_count': plays}))
    assert latest_snapshots('a')[0]['play_count'] == 20
    assert latest_snapshots('b')[0]['play_count'] == 999
    assert latest_snapshots('*') == []
    totals = latest_metric_totals('a')
    assert totals['play_count'] == 20
    assert totals['play_count_coverage'] == 1
    assert totals['comment_count'] is None
    assert totals['comment_count_coverage'] == 0
    with database.get_db() as db:
        assert db.execute('SELECT COUNT(*) FROM creator_metric_snapshots').fetchone()[0] == 3
    with pytest.raises(ValueError):
        record_snapshot(VideoItem(video_id='v'))


def test_rates_do_not_invent_denominator():
    for plays in (None, 0):
        rates, note = analyze_snapshot({'play_count': plays, 'like_count': 0})
        assert rates['like_count'] is None
    rates, note = analyze_snapshot({'play_count': 20, 'like_count': 0})
    assert rates['like_count'] == 0
    assert rates['share_count'] is None
    assert '样本较少' in note


def test_dashboard_selected_account_without_binding(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from src.operations_accounts import AccountProfile, AccountProfileRepository, stable_account_uuid
    monkeypatch.setenv('ACCOUNT_PROFILE_DB_PATH', str(tmp_path / 'accounts.db'))
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'douyin.db')
    account_uuid = stable_account_uuid('test')
    AccountProfileRepository().save(AccountProfile(account_uuid=account_uuid, account_key='test',
        display_name='测试', domain_strategy_id='legal_services', seed_keywords=['法律']))
    record_snapshot(VideoItem(account_uuid=account_uuid, video_id='123', title='样例',
                              creator_metrics={'play_count': 20}))
    app = AppTest.from_string('''
import streamlit as st
from src.web.content_performance_dashboard import render_content_performance
render_content_performance()
''', default_timeout=30)
    app.session_state['active_account_uuid'] = account_uuid
    app.run()
    assert not app.exception
    assert next(b for b in app.button if b.label == '采集视频后台数据').disabled
    assert len(app.dataframe) >= 1
    assert {'后台播放量','后台点赞量','后台评论量','后台转发 / 分享','后台收藏量'} <= {m.label for m in app.metric}


def test_real_manage_card_units_and_unique_association():
    import json
    from pathlib import Path
    cards = json.loads(Path('data/qa/creator_metrics_20260914/observed_cards.json').read_text(encoding='utf-8'))['cards']
    first = parse_manage_card(cards[0])
    assert first['metrics']['completion_rate'] == 21.43
    assert first['metrics']['bounce_2s_rate'] == 37.5
    assert first['metrics']['follower_count'] == 0
    description = cards[0]['title'].split('？ ', 1)[1]
    video = VideoItem(video_id='one', title=description, publish_time=first['publish_time'])
    assert attach_manage_cards([video], cards) == 1
    assert video.creator_metrics['play_count'] == 20
    assert attach_manage_cards([video], [cards[0], cards[0]]) == 0
    other = VideoItem(video_id='two', title=description, publish_time=first['publish_time'])
    assert attach_manage_cards([video, other], cards) == 0
    video.publish_time = '2026年09月13日 19:19'
    assert attach_manage_cards([video], cards) == 0


def test_retention_missing_or_invalid_stays_unknown():
    card = parse_manage_card({'title': 'x', 'text': '完播率\n--\n2秒跳出率\n101%\n播放\n1.2万'})
    assert card['metrics']['completion_rate'] is None
    assert card['metrics']['bounce_2s_rate'] is None
    assert card['metrics']['play_count'] is None
