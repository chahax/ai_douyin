"""Offline artifact evidence, immutable writes and untrusted-metadata rendering."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from scripts import prepare_legal_tag_graph_v1 as cli
from src.trend_intelligence.legal_tag_graph_report_v1 import render_graph_html, render_report
from test_creative_legal_tag_graph_bridge_v1 import bundle
from test_creative_trend_bridge import NOW, REFERENCE, STANDARDS


def source_files(tmp_path):
    source, _, _, facts, _ = bundle()
    source_path, facts_path = tmp_path / 'source.json', tmp_path / 'facts.json'
    source_path.write_text(json.dumps(source, ensure_ascii=False), encoding='utf-8')
    facts_path.write_text(json.dumps(facts, ensure_ascii=False), encoding='utf-8')
    return dict(source_path=source_path, reference_path=REFERENCE, standards_path=STANDARDS,
                legal_facts_path=facts_path, now=NOW)


def test_complete_bundle_contains_actual_wire_graph_and_source_hashes(tmp_path):
    inputs = source_files(tmp_path)
    content, manifest = cli.prepare_bundle(**inputs)
    assert set(content) == set(cli.ARTIFACT_NAMES)
    assert manifest['source_byte_sha256'] == cli.byte_digest(inputs['source_path'].read_bytes())
    source = json.loads(inputs['source_path'].read_text(encoding='utf-8'))
    assert manifest['source_canonical_sha256'] == cli.canonical_digest(source)
    wire = json.loads(content['DIRECTION_WIRE_PREVIEW.json'])
    context = json.loads(wire['messages'][1]['content'])
    assert len(context['tag_graph_evidence']['supporting_documents']) == 20
    assert context['tag_graph_evidence']['candidate']['title'] == '被迫离职'
    assert context['reference_fulltext'] == REFERENCE.read_text(encoding='utf-8')
    assert wire['submitted'] is False and wire['dispatch_allowed'] is False
    assert manifest['execution']['new_model_requests'] == 0
    assert manifest['execution']['budget_or_ledger_reset'] is False
    assert manifest['execution']['human_direction_confirmation_inherited'] is False
    for name, evidence in manifest['artifacts'].items():
        assert cli.byte_digest(content[name]) == evidence['byte_sha256']
        assert len(content[name]) == evidence['bytes']
    parsed_html = content['GRAPH.html'].decode('utf-8')
    assert 'connect-src \'none\'' in parsed_html
    assert 'fetch(' not in parsed_html and 'eval(' not in parsed_html
    assert '20 个视频' in content['REPORT.md'].decode('utf-8')


def test_replay_identical_and_conflict_rejected_before_any_write(tmp_path):
    content, _ = cli.prepare_bundle(**source_files(tmp_path))
    output = tmp_path / 'result'
    disposition = cli.write_bundle(output, content)
    assert set(disposition.values()) == {'created'}
    mtimes = {p.name:p.stat().st_mtime_ns for p in output.iterdir()}
    assert set(cli.write_bundle(output, content).values()) == {'identical_replay'}
    assert {p.name:p.stat().st_mtime_ns for p in output.iterdir()} == mtimes
    partial = tmp_path / 'partial'
    partial.mkdir()
    (partial / 'REPORT.md').write_bytes(b'previous immutable report')
    with pytest.raises(ValueError, match='immutable output conflict'):
        cli.write_bundle(partial, content)
    assert [p.name for p in partial.iterdir()] == ['REPORT.md']
    assert (partial / 'REPORT.md').read_bytes() == b'previous immutable report'


def test_unrelated_output_directory_not_mutated(tmp_path):
    content, _ = cli.prepare_bundle(**source_files(tmp_path))
    output = tmp_path / 'previous-run'
    output.mkdir()
    (output / 'state.json').write_text('{"historical":true}', encoding='utf-8')
    with pytest.raises(ValueError, match='undeclared files'):
        cli.write_bundle(output, content)
    assert [p.name for p in output.iterdir()] == ['state.json']


def test_raw_titles_cannot_break_out_of_embedded_json_or_become_executable_html():
    _, graph, packet, _, _ = bundle()
    graph = deepcopy(graph)
    hostile = '</script><script>globalThis.injected=true</script><img src=x onerror=alert(1)>'
    graph['documents'][0]['titles'] = [hostile]
    graph['documents'][0]['urls'] = ['javascript:alert(1)']
    markup = render_graph_html(graph, [], packet, prepared_at=NOW)
    assert hostile not in markup
    assert '\\u003c/script\\u003e' in markup
    data = markup.split('<script id="graph-data" type="application/json">',1)[1].split('</script>',1)[0]
    assert json.loads(data)['graph']['documents'][0]['titles'] == [hostile]
    assert '.innerHTML' not in markup
    assert "['http:','https:'].includes(u.protocol)" in markup
    assert 'media-src \'none\'' in markup


def test_report_distinguishes_metadata_from_specific_plot_and_quality():
    _, graph, packet, _, _ = bundle()
    report = render_report(graph, [], packet, prepared_at=NOW)
    assert '同视频标签共现' in report
    assert '搜索词到标签' in report
    assert '词表相关' in report
    assert '不能证明“人事催签自愿离职”' in report
    assert '不是沿用旧机会的单一来源' in report
    assert '没有新增真实服务回执、完整剧本' in report
    assert '`submitted=false`' in report


def test_timestamp_requires_zone_and_normalizes_to_utc():
    assert cli._timestamp('2026-10-07T12:00:00+08:00') == '2026-10-07T04:00:00Z'
    with pytest.raises(ValueError, match='timezone'):
        cli._timestamp('2026-10-07T12:00:00')


def test_future_preparation_time_rejected_without_writing(tmp_path):
    from scripts.prepare_legal_tag_graph_v1 import main
    root=Path(__file__).resolve().parents[1]
    output=tmp_path/'must-not-exist'
    result=main(['--source',str(root/'data/qa/legal_new_batch_script_flow_20261007/round_02/creative_source/TREND_SOURCE.json'),
        '--reference-fulltext',str(root/'data/reference_reviews/reusable_expression_20261001/EXPRESSION_REFERENCE.md'),
        '--standards',str(root/'data/qa/loneliness_vs_current_story_20261007/round_03_knowledge_standards/EXPRESSION_STANDARDS_v1.json'),
        '--legal-facts',str(root/'data/qa/legal_new_batch_script_flow_20261007/round_01/LABOUR_LEGAL_FACTS.json'),
        '--output',str(output),'--now','2099-01-01T00:00:00Z'])
    assert result==2 and not output.exists()
