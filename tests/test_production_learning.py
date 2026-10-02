import json
import sqlite3
import pytest

from src.services import database
from src.services.content_performance import record_snapshot, latest_snapshots, snapshot_history
from src.services.production_learning import (save_reference,list_references,save_experiment,
    list_experiments,experiment_packet,record_outcome)
from src.platform_adapter.models import VideoItem


@pytest.fixture
def db(tmp_path,monkeypatch):
    path = tmp_path / 'douyin.db'
    monkeypatch.setattr(database,'DB_PATH',path)
    return path


def observation(account='a',**values):
    return VideoItem(account_uuid=account,video_id='v',title='视频',creator_metrics=values)


def test_new_fields_raw_data_and_periods_do_not_overwrite(db):
    first = record_snapshot(observation(play_count=100,avg_watch_seconds=6.7,
        _raw_metrics={'new_metric':{'value':8,'unit':'s'}},
        _details={'traffic_sources':[{'label':'推荐','percent':65}], 'retention':[{'second':2,'percent':70}]}))
    record_snapshot(observation(play_count=5,_period='daily',_period_start='2026-09-15',_period_end='2026-09-15'))
    assert latest_snapshots('a')[0]['id'] == first
    rows = snapshot_history('a','v')
    assert len(rows) == 2
    assert rows[0]['avg_watch_seconds'] == 6.7
    assert json.loads(rows[0]['raw_metrics_json'])['new_metric']['unit'] == 's'
    assert json.loads(rows[0]['metric_details_json'])['traffic_sources'][0]['percent'] == 65
    assert rows[1]['avg_watch_seconds'] is None
    assert snapshot_history('b','v') == []
    with pytest.raises(ValueError):
        record_snapshot(observation(_period='daily',_period_start='2026-09-15',_period_end='2026-09-16'))
    assert len(snapshot_history('a')) == 2


def test_reference_deduplication_validation_and_account_scope(db):
    ref = save_reference('a','https://www.douyin.com/video/123','参考','开头清晰')
    assert save_reference('a','https://www.douyin.com/video/123#x','参考更新',notes='00:02 冲突出现',status='已学习') == ref
    save_reference('b','https://www.douyin.com/video/123','另一个账号')
    assert len(list_references('a')) == 1
    assert list_references('a')[0]['notes'] == '00:02 冲突出现'
    for url in ('javascript:alert(1)','file:///tmp/v','https://user:pass@example.com'):
        with pytest.raises(ValueError):
            save_reference('a',url,'bad')


def test_experiment_evidence_scope_and_export(db):
    snapshot_id = record_snapshot(observation(play_count=200))
    ref = save_reference('a','https://example.com/watch/1','参考')
    kwargs = dict(title='开头实验',hypothesis='前2秒信息可能不清楚',proposed_change='提前展示争议金额',
                  evaluation='同发布时长对比2秒跳出率',snapshot_ids=[snapshot_id],reference_ids=[ref],
                  baseline_version='v1',candidate_version='v2')
    experiment_id = save_experiment('a',**kwargs)
    record_outcome('a',experiment_id,'试验中','候选尚未发布')
    packet = experiment_packet('a',experiment_id)
    assert packet['metric_evidence'][0]['play_count'] == 200
    assert packet['references'][0]['id'] == ref
    assert packet['experiment']['candidate_version'] == 'v2'
    assert len(packet['outcome_history']) == 1
    record_outcome('a',experiment_id,'不采用','对比后没有改善，保留原生产版本')
    assert len(experiment_packet('a',experiment_id)['outcome_history']) == 2
    assert list_experiments('b') == []
    with pytest.raises(ValueError):
        save_experiment('b',**kwargs)
    with pytest.raises(ValueError):
        record_outcome('b',experiment_id,'保留改动','bad')


def test_legacy_schema_migrates_without_erasing_snapshot(db):
    conn = sqlite3.connect(db)
    conn.execute('''CREATE TABLE creator_metric_snapshots(id INTEGER PRIMARY KEY, account_uuid TEXT,
        video_id TEXT,title TEXT,publish_time TEXT,collected_at TEXT,source TEXT,play_count INTEGER,
        like_count INTEGER,comment_count INTEGER,share_count INTEGER,collect_count INTEGER)''')
    conn.execute("INSERT INTO creator_metric_snapshots(id,account_uuid,video_id,play_count) VALUES(1,'a','v',20)")
    conn.commit()
    conn.close()
    row = latest_snapshots('a')[0]
    assert row['id'] == 1 and row['play_count'] == 20
    assert row['avg_watch_seconds'] is None
    assert row['period'] == 'lifetime'


def test_reference_form_persists_in_empty_dashboard(db):
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string("from src.web.production_learning_dashboard import render_learning\nrender_learning('a', [], True)", default_timeout=30).run()
    assert not app.exception
    next(i for i in app.text_input if i.label == '视频链接').set_value('https://www.douyin.com/video/123')
    next(i for i in app.text_input if i.label == '参考视频标题').set_value('镜头节奏参考')
    next(i for i in app.text_area if i.label == '推荐理由 / 值得学习的地方').set_value('00:02 展示争议点')
    next(i for i in app.button if i.label == '保存参考视频').click()
    app.run()
    assert not app.exception
    assert list_references('a')[0]['title'] == '镜头节奏参考'


def test_review_prompts_are_grounded_and_small_sample_is_qualified():
    from src.services.content_performance import review_prompts
    assert '不足' in review_prompts({'play_count':20,'bounce_2s_rate':37.5})[0]
    prompts = review_prompts({'play_count':214,'bounce_2s_rate':30.5,'completion_rate':19.29})
    assert '30.5%' in prompts[0]
    assert '19.29%' in prompts[1]
