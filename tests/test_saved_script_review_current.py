"""Saved/cached scripts stay readable without inheriting obsolete review badges."""
import copy
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from script_pair_fixture import FixtureClient
from test_pre_video_script import NOW, _Profiles, _Repository, _expanded_rows, _row
from source_media_fixture import complete_media_analysis
from src.trend_intelligence.pre_video_script import PreVideoScriptRequest, PreVideoScriptService
from src.trend_intelligence import saved_script_review as saved
from src.trend_intelligence import script_pair
from src.web.trend_dashboard import _load_saved_script_pair


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def isolated_service(client, root):
    # Other agents exercise the legacy fixture concurrently; this module never
    # rewrites that shared media directory while another test verifies its SHA.
    rows = _expanded_rows([_row('labor', '被辞退后核对通知', video_type='mixed', metric=50_000),
                           _row('marriage', '离婚后核对材料', video_type='mixed', metric=50_000)])
    for observation, _ in rows:
        observation.collected_at = NOW.isoformat()
    rows = [(observation, complete_media_analysis(analysis, root / 'media' / observation.item_id))
            for observation, analysis in rows]
    return PreVideoScriptService(repository=_Repository([r[0] for r in rows], [r[1] for r in rows]),
                                 profile_repository=_Profiles(), script_client=client)


@pytest.fixture
def case(tmp_path):
    client = FixtureClient()
    pair = isolated_service(client, tmp_path).generate(PreVideoScriptRequest(
        account_key='account01', short_seconds=60, recent_video_types=('mixed',),
        output_dir=str(tmp_path)), now=NOW)
    items = _load_saved_script_pair(pair.short.script.account_uuid, tmp_path)
    return {'root': tmp_path, 'client': client, 'pair': pair, 'items': items,
            'manifest': Path(pair.manifest_path),
            'trace': Path(pair.short.script.generation['trace_dir'])}


class ThirdFormatResponseClient(FixtureClient):
    """Real saved fake-client calls, not a manual upgrade of an old report."""
    def chat_completion_tracked(self, messages, **kwargs):
        response = super().chat_completion_tracked(messages, **kwargs)
        if kwargs.get('caller') == 'pre_video_script_review':
            attempt = sum(call[1].get('caller') == 'pre_video_script_review' for call in self.calls)
            if attempt < 3:
                return '{"checks":'  # Preserve each actual invalid response in its trace.
        return response


@pytest.fixture
def three_round_case(tmp_path):
    client = ThirdFormatResponseClient()
    pair = isolated_service(client, tmp_path).generate(PreVideoScriptRequest(
        account_key='account01', short_seconds=60, recent_video_types=('mixed',),
        output_dir=str(tmp_path)), now=NOW)
    return {'root': tmp_path, 'client': client, 'pair': pair,
            'items': _load_saved_script_pair(pair.short.script.account_uuid, tmp_path),
            'manifest': Path(pair.manifest_path),
            'trace': Path(pair.short.script.generation['trace_dir'])}


def status(case):
    before = len(case['client'].calls)
    result = saved.current_saved_script_review(case['items'], allowed_root=case['root'])
    assert len(case['client'].calls) == before  # Loading never calls the fake reviewer either.
    return result


def update_script(case, index, mutate):
    item = case['items'][index]
    path = Path(item['script_json_path'])
    script = read_json(path)
    mutate(script)
    write_json(path, script)
    item['json'] = path.read_text(encoding='utf-8')


def sync_report(case, mutate):
    path = case['trace'] / 'review_1.json'
    report = read_json(path)
    mutate(report)
    write_json(path, report)
    for index in (0, 1):
        update_script(case, index, lambda script: script['generation']['reviews'][0].update(report=copy.deepcopy(report)))


def test_current_pair_has_complete_proof_and_does_not_mutate_or_call_models(case):
    before = copy.deepcopy(case['items'])
    result = status(case)
    assert result['status'] == 'current_passed', result
    assert result['schema'] == script_pair.CURRENT_SCRIPT_REVIEW_SCHEMA
    assert result['legal_review_status'] == 'pending_human_review'
    assert result['scope'].endswith('no_media_review')
    assert len(result['full_source_evidence_sha256']) == 64
    assert case['items'] == before
    assert len(case['client'].calls) == 2


def test_third_format_response_restores_only_its_actual_saved_report(three_round_case):
    case = three_round_case
    report = read_json(case['trace'] / 'review_1.json')
    assert report['format_attempts'] == 3 == script_pair.SCRIPT_REVIEW_MAX_FORMAT_ATTEMPTS
    for attempt in (1, 2, 3):
        assert (case['trace'] / f'review_1_request_{attempt}.json').is_file()
        assert (case['trace'] / f'review_1_response_{attempt}.txt').is_file()
    assert (case['trace'] / 'review_1_response_1.txt').read_text(encoding='utf-8') == '{"checks":'
    assert (case['trace'] / 'review_1_response_2.txt').read_text(encoding='utf-8') == '{"checks":'
    raw = read_json(case['trace'] / 'review_1_response_3.txt')
    assert raw['candidate_sha256'] == report['candidate_sha256']
    assert raw['evidence_sha256'] == report['evidence_sha256']
    assert status(case)['current_passed']
    assert len(case['client'].calls) == 4  # One author + three format attempts, no loader call.


@pytest.mark.parametrize('damage', ['missing', 'tampered'])
def test_third_format_response_must_exist_and_match(three_round_case, damage):
    path = three_round_case['trace'] / 'review_1_response_3.txt'
    if damage == 'missing':
        path.unlink()
    else:
        raw = read_json(path)
        raw['summary'] = '第三次真实响应被替换，不能沿用旧报告'
        write_json(path, raw)
    result = status(three_round_case)
    assert result['status'] == 'needs_review' and not result['current_passed']
    if damage == 'tampered':
        assert '真实模型响应不一致' in result['reason']
    assert len(three_round_case['client'].calls) == 4


@pytest.mark.parametrize('field', ['action', 'dialogue', 'audio', 'emotion_and_performance',
                                  'blocking', 'camera_angle', 'start_frame', 'end_frame'])
def test_cross_field_change_cannot_use_old_review_even_after_cache_reload(case, field):
    update_script(case, 0, lambda script: script['shots'][0].__setitem__(field, script['shots'][0][field] + ' 已修改'))
    result = status(case)
    assert not result['current_passed'] and '送审内容不一致' in result['reason']


@pytest.mark.parametrize('field', ['model_prompt_zh', 'subtitle', 'camera'])
def test_unprojected_display_fields_must_still_match_original_draft(case, field):
    update_script(case, 0, lambda script: script['shots'][0].__setitem__(field, '不属于原稿的新内容'))
    result = status(case)
    assert not result['current_passed'] and '原始审核草稿不一致' in result['reason']


def test_changed_markdown_is_readable_but_cannot_borrow_json_approval(case):
    item = case['items'][0]
    item['markdown'] += '\n新增未审核的签约结局。'
    Path(item['script_path']).write_text(item['markdown'], encoding='utf-8')
    assert 'Markdown' in status(case)['reason']
    loaded = _load_saved_script_pair(case['pair'].short.script.account_uuid, case['root'])
    assert len(loaded) == 2 and '未审核' in loaded[0]['markdown']
    assert loaded[0]['current_review']['status'] == 'needs_review'


def test_stale_cached_text_is_not_passed_and_is_not_silently_replaced(case):
    item = case['items'][0]
    item['markdown'] += '\n仅缓存中新增的动作'
    item['current_review'] = {'current_passed': True, 'status': 'current_passed'}
    assert '缓存已变化' in status(case)['reason']
    assert '仅缓存中' in item['markdown']


@pytest.mark.parametrize('withdrawal', ['needs_revision', 'failed', 'rejected', 'withdrawn'])
def test_live_withdrawal_invalidates_cache_but_loader_preserves_history(case, withdrawal):
    assert status(case)['current_passed']
    manifest = read_json(case['manifest'])
    manifest['agent_review'] = {'status': withdrawal}
    write_json(case['manifest'], manifest)
    assert '已被退回' in status(case)['reason']
    loaded = _load_saved_script_pair(case['pair'].short.script.account_uuid, case['root'])
    assert len(loaded) == 2 and loaded[0]['current_review']['status'] == 'needs_review'


def test_legacy_script_schema_remains_readable(case):
    update_script(case, 0, lambda script: script.update(schema='detailed_video_script/v3'))
    loaded = _load_saved_script_pair(case['pair'].short.script.account_uuid, case['root'])
    assert len(loaded) == 2 and loaded[0]['markdown']
    assert not loaded[0]['current_review']['current_passed']


def test_legacy_review_schema_requires_current_review(case):
    sync_report(case, lambda report: report.update(schema='script_editorial_evidence_review/v1'))
    assert not status(case)['current_passed']


def test_prompt_change_requires_review_even_if_schema_is_still_v2(case, tmp_path, monkeypatch):
    prompt_dir = tmp_path / 'new_policy'
    prompt_dir.mkdir()
    current = script_pair.PROMPT_PATH.with_name('script_pair_review.md').read_text(encoding='utf-8')
    (prompt_dir / 'script_pair_review.md').write_text(current + '\n新增实质审核规则。', encoding='utf-8')
    monkeypatch.setattr(script_pair, 'PROMPT_PATH', prompt_dir / 'script_pair.md')
    assert '审核规则已更新' in status(case)['reason']


@pytest.mark.parametrize('filename', ['review_1.json', 'review_1_request_1.json',
                                     'review_1_response_1.txt', 'source_evidence.full.json', 'draft_1.json'])
def test_missing_proof_never_hides_history_or_auto_reviews(case, filename):
    (case['trace'] / filename).unlink()
    assert not status(case)['current_passed']
    assert len(_load_saved_script_pair(case['pair'].short.script.account_uuid, case['root'])) == 2


def test_changed_original_source_snapshot_is_detected(case):
    path = case['trace'] / 'source_evidence.full.json'
    sources = read_json(path)
    sources[-1]['title'] += ' changed'
    write_json(path, sources)
    assert '完整来源证据已变化' in status(case)['reason']


def test_permanently_rejected_source_invalidates_old_script_review(case, monkeypatch):
    source = read_json(case['trace'] / 'source_evidence.full.json')[0]
    marker_dir = case['root'] / 'rejection_markers'
    marker_dir.mkdir()
    monkeypatch.setattr(saved, 'SEMANTIC_REJECTIONS_ROOT', marker_dir)
    (marker_dir / f"{source['media_evidence']['visual']['artifact_sha256']}.json").write_text('{}', encoding='utf-8')
    assert '永久拒绝' in status(case)['reason']


def test_report_passed_flag_cannot_override_failed_cross_field_check(case):
    def change(report):
        report['shot_audit'][0]['cross_checks']['dialogue_action'] = False
    sync_report(case, change)
    assert not status(case)['current_passed']


def test_raw_model_response_is_verified_too(case):
    path = case['trace'] / 'review_1_response_1.txt'
    report = read_json(path)
    report['summary'] = '保存报告没有这项真实响应文本'
    write_json(path, report)
    assert '真实模型响应不一致' in status(case)['reason']


def test_forged_cache_status_without_paths_is_only_history(case):
    for item in case['items']:
        item.pop('manifest_path')
        item['current_review'] = {'current_passed': True}
    assert '缓存没有绑定' in status(case)['reason']


def test_trace_cannot_escape_output_directory(case):
    for index in (0, 1):
        update_script(case, index, lambda script: script['generation'].update(trace_dir=str(case['root'].parent)))
    assert '超出本次输出目录' in status(case)['reason']


def test_manifest_cannot_escape_trusted_ui_root(case):
    result = saved.current_saved_script_review(case['items'], allowed_root=case['root'] / 'other')
    assert not result['current_passed'] and '超出本次输出目录' in result['reason']


def test_duplicate_json_is_rejected_without_losing_readable_markdown(case):
    item = case['items'][0]
    item['json'] = item['json'].replace('{', '{"schema":"forged",', 1)
    Path(item['script_json_path']).write_text(item['json'], encoding='utf-8')
    assert '重复 JSON' in status(case)['reason']
    assert item['markdown']


@pytest.mark.parametrize('damage', ['missing', 'invalid_json'])
def test_damaged_json_keeps_remaining_markdown_visible_as_unreviewed(case, damage):
    path = Path(case['items'][0]['script_json_path'])
    if damage == 'missing':
        path.unlink()
    else:
        path.write_text('{damaged JSON', encoding='utf-8')
    items = _load_saved_script_pair(case['pair'].short.script.account_uuid, case['root'])
    assert len(items) == 2 and items[0]['markdown'] == case['items'][0]['markdown']
    assert items[0]['duration'] is None
    assert items[0]['current_review']['status'] == 'needs_review'
    app = AppTest.from_function(render_items, args=(items,)).run(timeout=20)
    assert not app.exception and not app.success
    assert '时长待核对' in app.tabs[0].label


def render_items(items):
    from src.web.trend_dashboard import _render_script_pair_result
    _render_script_pair_result(items)


def test_render_rechecks_live_manifest_instead_of_cached_badge(case, monkeypatch):
    monkeypatch.setattr(saved, 'PROJECT_ROOT', case['root'])
    assert case['items'][0]['current_review']['current_passed']
    manifest = read_json(case['manifest'])
    manifest['agent_review'] = {'status': 'needs_revision'}
    write_json(case['manifest'], manifest)
    app = AppTest.from_function(render_items, args=(case['items'],)).run(timeout=20)
    assert not app.exception
    assert not app.success
    assert any('需复核' in element.value for element in app.warning)
    assert len(app.tabs) == 2 and len(app.get('download_button')) == 4
    assert any('完整分镜' in element.value for element in app.markdown)


def test_unbound_malformed_history_still_renders_without_passed_badge():
    items = [{'kind': 'short', 'duration': 45, 'markdown': '历史稿原文', 'json': '{invalid'}]
    app = AppTest.from_function(render_items, args=(items,)).run(timeout=20)
    assert not app.exception and not app.success
    assert len(app.get('download_button')) == 2
    assert any('历史稿原文' in element.value for element in app.markdown)


def test_focused_review_retains_twenty_source_binding(tmp_path):
    client = FixtureClient()
    pair = isolated_service(client, tmp_path).generate(PreVideoScriptRequest(
        account_key='account01', short_seconds=60, recent_video_types=('mixed',),
        script_reference_source_ids=('labor-0',), output_dir=str(tmp_path)), now=NOW)
    items = _load_saved_script_pair(pair.short.script.account_uuid, tmp_path)
    result = saved.current_saved_script_review(items, allowed_root=tmp_path)
    assert result['current_passed'], result
    assert len(read_json(Path(pair.short.script.generation['trace_dir']) / 'source_evidence.full.json')) == 20
    assert len(client.calls) == 2


def test_path_wrapper_resolves_exact_original_pair_without_any_model_call(case):
    path = case['pair'].short.script_json_path
    result = saved.require_current_saved_script_review(path, allowed_root=case['root'])
    assert result['current_passed'] and result['manifest_path'] == str(case['manifest'])
    assert result['script_json_path'] == str(Path(path).resolve())
    assert len(result['script_json_sha256']) == 64
    assert len(case['client'].calls) == 2


def test_path_wrapper_cannot_infer_approval_for_a_locked_copy(case):
    path = case['root'] / 'locked.json'
    path.write_bytes(Path(case['pair'].short.script_json_path).read_bytes())
    with pytest.raises(ValueError, match='唯一绑定'):
        saved.require_current_saved_script_review(path, allowed_root=case['root'])


def test_path_wrapper_rejects_ambiguous_pair_manifests(case):
    (case['root'] / 'duplicate.pair.json').write_bytes(case['manifest'].read_bytes())
    with pytest.raises(ValueError, match='唯一绑定'):
        saved.require_current_saved_script_review(case['pair'].short.script_json_path, allowed_root=case['root'])


def test_path_wrapper_rechecks_long_even_when_only_short_will_be_used(case):
    update_script(case, 1, lambda script: script['shots'][0].update(action='未送审的新动作'))
    with pytest.raises(ValueError, match='项目双稿需要复核'):
        saved.require_current_saved_script_review(case['pair'].short.script_json_path, allowed_root=case['root'])


def test_path_wrapper_rejects_live_withdrawal(case):
    manifest = read_json(case['manifest'])
    manifest['agent_review'] = {'status': 'needs_revision'}
    write_json(case['manifest'], manifest)
    with pytest.raises(ValueError, match='已被退回'):
        saved.require_current_saved_script_review(case['pair'].long.script_json_path, allowed_root=case['root'])
