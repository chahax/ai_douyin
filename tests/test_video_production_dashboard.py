import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.web.video_production_dashboard import ROOT, load_run, local_file, workflow_steps
from src.web.production_insights import direction_counts, compare_styles, display_time, source_history


def test_real_run_and_render(monkeypatch):
    manifest = ROOT / 'data/video_generation/jimeng_continuity_20260906/production.json'
    run = load_run(manifest)
    assert len(run['shots']) == 3
    assert all(s['downloaded'] for s in run['shots'])
    assert sum(s['cost'] for s in run['shots']) == 180
    assert workflow_steps(run)[-1] == ('审核', '未通过')
    app = AppTest.from_string('from src.web.video_production_dashboard import page_video_production\npage_video_production()')
    from src.services.production_registry import list_projects
    chosen = next(p for p in list_projects(ROOT) if manifest in p['attempts'])
    app.session_state['production_project'] = chosen['key']
    app.session_state['production_batch'] = manifest
    app.run(timeout=30)
    assert not app.exception
    assert any('未通过' in e.value for e in app.error)
    assert app.session_state['production_section'] == '分析依据'
    assert any('还缺 14 个' in e.value for e in app.warning)
    from src.trend_intelligence.sample_gate import evaluate_sample
    assert all(any(reason in e.value for e in app.warning) for reason in evaluate_sample(run['provenance']['source_videos']).reasons)
    assert len(run['provenance']['source_videos']) == 6
    assert workflow_steps(run)[0] == ('灵感来源', '6 条记录')
    for node in ['灵感来源', '剧本内容', '分镜与采集', '合并成片', '一致性审核', '本地文件', '页面风格', '分析依据']:
        # Simulate the validated selection emitted by the browser graph; the
        # graph's actual click / keyboard path is also checked in browser QA.
        monkeypatch.setattr('src.web.components.flow_graph._graph',
                            lambda node=node, **kwargs: {'kind': 'node', 'id': node})
        app.run()
        assert not app.exception
        assert app.session_state['production_section'] == node
        if node == '灵感来源':
            assert any('媒体级分析覆盖 0/6' in e.value for e in app.warning)
    app.button(key='direction_婚姻家事').click().run()
    assert app.session_state['production_direction'] == '婚姻家事'
    app.button(key='production_refresh').click().run()
    assert not app.exception


def test_missing_and_corrupt_artifacts(tmp_path):
    folder = tmp_path / 'data/run'
    folder.mkdir(parents=True)
    (folder / 'production.json').write_text(json.dumps({'shots': ['S01', '../escape'], 'review_result': 'passed'}))
    (folder / 'S01.json').write_text('{broken')
    run = load_run(folder / 'production.json', tmp_path)
    assert len(run['errors']) == 2
    assert not run['shots'][0]['downloaded']
    assert workflow_steps(run)[-1] == ('审核', '报告缺失')
    assert workflow_steps(run)[0] == ('灵感来源', '未记录')


def test_path_isolation(tmp_path):
    outside = tmp_path / 'private.txt'
    outside.write_text('secret')
    assert local_file(tmp_path, str(outside)) is None
    assert local_file(tmp_path, 'data/../private.txt') is None
    assert local_file(tmp_path, '') is None


def test_distribution_time_and_comparison():
    run = load_run(ROOT / 'data/video_generation/jimeng_continuity_20260906/production.json')
    counts = direction_counts(run['provenance']['source_videos'])
    assert sum(i['条数'] for i in counts) == 6
    assert abs(sum(i['占比'] for i in counts) - 1) < 0.00001
    assert next(i['条数'] for i in counts if i['方向'] == '婚姻家事') == 2
    assert direction_counts([]) == []
    assert display_time(None) == '未记录'
    assert display_time('2026-09-03T13:48:39+00:00') == '2026-09-03 21:48:39'
    diff = compare_styles({'dimensions': {'颜色': '紫', '字体': 'sans'}}, {'dimensions': {'颜色': '蓝'}})
    assert all(d['差异'] == '不同／缺失' for d in diff)


def test_source_times_do_not_invent_missing_data(tmp_path):
    run = {'provenance': {'source_videos': [{'item_id': 'x', 'published_at': '2026-01-01'}]}}
    source = source_history(run, tmp_path)[0]
    assert source.get('collected_at') is None
    assert source.get('analyzed_at') is None
    assert source['time_basis'] == '未记录'


def test_history_matches_only_before_selection_and_same_account(tmp_path):
    import sqlite3
    (tmp_path / 'data').mkdir()
    with sqlite3.connect(tmp_path / 'data/trend_intelligence.db') as db:
        db.execute('CREATE TABLE trend_observations(item_id,metric_value,collected_at)')
        db.execute('CREATE TABLE trend_content_analyses(item_id,account_uuid,provider_id,created_at)')
        db.executemany('INSERT INTO trend_observations VALUES(?,?,?)', [('x', 5, '2026-01-01T00:00:00Z'), ('x', 5, '2026-01-03T00:00:00Z')])
        db.executemany('INSERT INTO trend_content_analyses VALUES(?,?,?,?)', [('x', 'a', 'metadata', '2026-01-01T01:00:00Z'), ('x', 'other', 'metadata', '2026-01-01T02:00:00Z')])
    run = {'provenance': {'account_uuid': 'a', 'opportunity': {'created_at': '2026-01-02T00:00:00Z'},
                          'source_videos': [{'item_id': 'x', 'visible_metric': 5, 'analysis_provider': 'metadata'}]}}
    source = source_history(run, tmp_path)[0]
    assert source['collected_at'] == '2026-01-01T00:00:00Z'
    assert source['analyzed_at'] == '2026-01-01T01:00:00Z'
    assert '回溯匹配' in source['time_basis']
