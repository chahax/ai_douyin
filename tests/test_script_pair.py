import copy
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from script_pair_fixture import FixtureClient, pair_payload, fixture_source_evidence, enrich_review_report
from test_pre_video_script import _Profiles, _Repository, _row, _expanded_rows, NOW
from src.trend_intelligence.pre_video_script import PreVideoScriptService, PreVideoScriptRequest
from src.trend_intelligence.script_pair import parse_pair


@pytest.fixture(autouse=True)
def script_pair_uses_isolated_output_root(monkeypatch):
    # This module tests story/review contracts. The output containment gate is
    # tested separately; allow each pytest tmp_path as its isolated artifact root.
    monkeypatch.setattr(PreVideoScriptService, '_resolve_output_dir',
                        staticmethod(lambda request: Path(request.output_dir).resolve()))


def parse(data):
    return parse_pair(json.dumps(data, ensure_ascii=False), profile=_Profiles().get('account01'),
                      created_at=NOW.isoformat(), short_seconds=60, long_seconds=180, generation={},
                      source_evidence=fixture_source_evidence())


def test_complete_pair_is_independent_and_has_visible_endings():
    short, long = parse(pair_payload())
    assert (short.target_duration_seconds, long.target_duration_seconds) == (60, 180)
    assert short.core_message == long.core_message
    assert short.script_id != long.script_id and len(long.shots) > len(short.shots)
    for script in (short, long):
        assert script.shots[-1].dialogue == script.closing_line
        assert script.story_beats[-1]['role'] == 'closure'
        assert script.generation['expression_plan']['presentation_mode'] == 'prop_demonstration'
        assert script.generation['reference_usage_validation']['references'][0]['source_evidence'][0]['id'] == 'visual-1'
    assert short.generation is not long.generation


def test_shared_premise_allows_a_long_version_with_different_dialogue_and_added_action():
    data = pair_payload()
    data['long']['premise'] = data['short']['premise']
    added = [
        ('这份付款记录上的编号和通知一致。', '把付款记录与第二张通知的编号并排对齐。'),
        ('金额也一样，再核对到账日期。', '按住已比对的编号，把付款记录移到日期栏旁。'),
        ('到账在前，通知在后，这一步也对上了。', '沿两份记录的日期栏逐项核对，确认先后次序。'),
    ]
    for shot, (dialogue, action) in zip(data['long']['shots'][6:9], added):
        shot.update(dialogue=dialogue, action=action)
    before = copy.deepcopy(data)
    short, long = parse(data)
    assert short.premise == long.premise
    assert len(long.shots) >= len(short.shots) + 3
    assert [s.dialogue for s in long.shots] != [s.dialogue for s in short.shots]
    assert [s.action for s in long.shots[6:9]] == [action for _, action in added]
    assert data == before


def test_shared_premise_does_not_bypass_independent_long_adds_value_review():
    from src.trend_intelligence.script_pair import review_pair, REVIEW_CHECKS
    data = pair_payload()
    data['long']['premise'] = data['short']['premise']
    class LongValueReviewer:
        def chat_completion_tracked(self, messages, **kwargs):
            payload = json.loads(messages[1]['content'])
            checks = {key: True for key in REVIEW_CHECKS}
            checks['long_adds_value'] = False
            shot = next(s for s in payload['scripts'] if s['format_kind'] == 'long')['shots'][6]
            return json.dumps(enrich_review_report({'checks': checks,
                'summary': '合成测试：不同对白仍不能证明长版有增量。',
                'issues': [{'problem': '长版动作仍重复已有核对。',
                    'rewrite_instruction': '补充真正改变下一步选择的中段行动。',
                    'evidence': [{'script': 'long', 'shot_id': shot['shot_id'],
                                  'field': 'action', 'quote': shot['action']}]}]}, payload))
    result = review_pair(LongValueReviewer(), parse(data), {'source_evidence': fixture_source_evidence()})
    assert result['checks']['long_adds_value'] is False
    assert result['passed'] is False


@pytest.mark.parametrize('defect', ['missing_plan', 'unknown_character', 'fake_source', 'fake_evidence',
                                   'fake_shot', 'fake_percentage', 'repeated_action', 'wrong_turn', 'wrong_ending'])
def test_expression_attribution_requires_real_evidence_and_story_locations(defect):
    data = pair_payload()
    short = data['short']
    if defect == 'missing_plan': del short['expression_plan']
    if defect == 'unknown_character': short['expression_plan']['protagonist'] = '编造角色'
    if defect == 'fake_source': short['reference_usage'][0]['source_id'] = 'not-in-cohort'
    if defect == 'fake_evidence': short['reference_usage'][0]['evidence_ids'] = ['invented-frame']
    if defect == 'fake_shot': short['reference_usage'][0]['shot_ids'] = ['S99']
    if defect == 'fake_percentage': short['reference_usage'][0]['contribution_percent'] = 99
    if defect == 'repeated_action':
        short['expression_plan']['action_chain'][1]['state_change'] = short['expression_plan']['action_chain'][0]['state_change']
    if defect == 'wrong_turn': short['expression_plan']['turn']['shot_ids'] = ['S01']
    if defect == 'wrong_ending': short['expression_plan']['ending']['shot_ids'] = ['S01']
    with pytest.raises(ValueError):
        parse(data)


def test_reference_validation_cannot_be_silently_skipped_without_source_input():
    with pytest.raises(ValueError, match='source_evidence'):
        parse_pair(json.dumps(pair_payload()), profile=_Profiles().get('account01'), created_at=NOW.isoformat(),
                   short_seconds=60, long_seconds=180, generation={})


@pytest.mark.parametrize('defect', ['nan', 'negative', 'reversed', 'outside_video', 'bad_channel', 'duplicate_id'])
def test_reference_timestamps_and_channels_are_validated_even_in_standalone_parser(defect):
    sources = fixture_source_evidence()
    sources[0]['media_evidence'] = {'duration_seconds': 3}
    item = sources[0]['expression_analysis']['evidence'][0]
    if defect == 'nan': item['start_seconds'] = float('nan')
    if defect == 'negative': item['start_seconds'] = -1
    if defect == 'reversed': item['start_seconds'] = 2.5
    if defect == 'outside_video': item['end_seconds'] = 20
    if defect == 'bad_channel': item['channel'] = 'invented_audio_emotion'
    if defect == 'duplicate_id': sources[0]['expression_analysis']['evidence'].append(copy.deepcopy(item))
    with pytest.raises(ValueError):
        parse_pair(json.dumps(pair_payload()), profile=_Profiles().get('account01'), created_at=NOW.isoformat(),
                   short_seconds=60, long_seconds=180, generation={}, source_evidence=sources)


def test_expression_and_reference_metadata_can_be_patched_without_rewriting_other_fields():
    from src.trend_intelligence.script_pair import _merge_model_revision
    original = pair_payload()
    new_plan = {**original['short']['expression_plan'], 'account_fit': '把目光放在观众避免重复支付的当下需求。'}
    merged = _merge_model_revision(original, json.dumps({'changes': [
        {'script': 'short', 'shot_id': '', 'field': 'expression_plan', 'value': new_plan}]}))
    assert merged['short']['shots'] == original['short']['shots']
    assert merged['long'] == original['long']
    assert parse(merged)[0].generation['expression_plan'] == new_plan


def test_reviewer_can_reject_decorative_actions_using_current_expression_plan_quote():
    from src.trend_intelligence.script_pair import review_pair, REVIEW_CHECKS
    scripts = parse(pair_payload())
    class ActionReviewer:
        def chat_completion_tracked(self, messages, **kwargs):
            payload = json.loads(messages[-1]['content'])
            assert payload['scripts'][0]['reference_usage'][0]['evidence_ids'] == ['visual-1']
            checks = {key: True for key in REVIEW_CHECKS}
            checks['action_drives_story'] = False
            return json.dumps(enrich_review_report({'checks': checks, 'summary': '测试拒绝动作与计划未对应。', 'issues': [{
                'problem': '动作应落实到镜头。', 'rewrite_instruction': '定点修改对应动作。',
                'evidence': [{'script': 'short', 'shot_id': '', 'field': 'expression_plan',
                              'quote': '避免为已经支付的账单再次付款。'}]}]}, payload))
    report = review_pair(ActionReviewer(), scripts, {'source_evidence': fixture_source_evidence()})
    assert not report['passed']


def _semantic_failure(source_id, evidence_id, quote):
    from src.trend_intelligence.script_pair import REVIEW_CHECKS
    checks = {key: True for key in REVIEW_CHECKS}
    checks['source_semantic_fidelity'] = False
    return {'checks': checks, 'summary': '测试来源语义待复核。', 'issues': [{
        'problem': '候选归纳改变了原句的担忧和条件，不能作为已发生的因果。',
        'rewrite_instruction': '先复核来源，不能基于错误归纳编剧。',
        'evidence': [{'source_id': source_id, 'evidence_id': evidence_id, 'quote': quote}]}]}


def test_semantic_review_receives_original_asr_and_can_reject_invented_causality():
    from src.trend_intelligence.script_pair import review_pair
    sources = fixture_source_evidence()
    expression = sources[0]['expression_analysis']
    expression['core_message'] = {'text': '页数篡改导致盖章不全而失效。', 'evidence_ids': ['A1', 'A2']}
    expression['evidence'].extend([
        {'id': 'A1', 'channel': 'asr', 'start_seconds': 0, 'end_seconds': 1.5, 'text': '我怕合同页数被动过'},
        {'id': 'A2', 'channel': 'asr', 'start_seconds': 1.5, 'end_seconds': 3, 'text': '没盖齐缝章会不会直接失效'}])
    class SemanticReviewer:
        def chat_completion_tracked(self, messages, **kwargs):
            payload = json.loads(messages[-1]['content'])
            original = payload['evidence']['source_evidence'][0]['expression_analysis']
            assert original['core_message']['text'] == '页数篡改导致盖章不全而失效。'
            assert original['evidence'][-2]['text'] == '我怕合同页数被动过'
            return json.dumps(enrich_review_report(
                _semantic_failure('labor-0', 'A1', '我怕合同页数被动过'), payload))
    report = review_pair(SemanticReviewer(), parse(pair_payload()), {'source_evidence': sources})
    assert not report['checks']['source_semantic_fidelity'] and not report['passed']


@pytest.mark.parametrize('defect', ['source', 'evidence', 'quote', 'missing_citation'])
def test_source_review_cannot_invent_evidence_when_rejecting_a_source(defect):
    from src.trend_intelligence.script_pair import review_pair
    sources = fixture_source_evidence()
    original = sources[0]['expression_analysis']['evidence'][0]['text']
    report = _semantic_failure('labor-0', 'visual-1', original)
    citation = report['issues'][0]['evidence'][0]
    if defect == 'source': citation['source_id'] = 'invented-source'
    if defect == 'evidence': citation['evidence_id'] = 'invented-frame'
    if defect == 'quote': citation['quote'] = '未曾出现的原句'
    if defect == 'missing_citation': report['issues'] = []
    class InvalidReviewer:
        def chat_completion_tracked(self, messages, **kwargs):
            return json.dumps(enrich_review_report(report, json.loads(messages[1]['content'])))
    with pytest.raises(RuntimeError, match='审稿结果格式无效'):
        review_pair(InvalidReviewer(), parse(pair_payload()), {'source_evidence': sources})


def test_source_semantic_failure_stops_delivery_and_does_not_trigger_author_rewrite(tmp_path):
    class RejectSourceClient(FixtureClient):
        def chat_completion_tracked(self, messages, **kwargs):
            result = super().chat_completion_tracked(messages, **kwargs)
            if kwargs.get('caller') == 'pre_video_script_review':
                source = json.loads(messages[-1]['content'])['evidence']['source_evidence'][0]
                item = source['expression_analysis']['evidence'][0]
                return json.dumps(enrich_review_report(
                    _semantic_failure(source['source_id'], item['id'], item['text']),
                    json.loads(messages[1]['content'])))
            return result
    client = RejectSourceClient()
    with pytest.raises(RuntimeError, match='来源语义复核未通过'):
        service_for(client).generate(PreVideoScriptRequest(short_seconds=60, account_key='account01',
            recent_video_types=('mixed',), output_dir=str(tmp_path)), now=NOW)
    assert [kwargs['caller'] for _, kwargs in client.calls] == ['pre_video_script_pair', 'pre_video_script_review']
    assert not list(tmp_path.glob('*.json'))
    assert len(list(tmp_path.glob('_runs/*/draft_*.json'))) == 1
    attempts = json.loads(next(tmp_path.glob('_runs/*/attempts.json')).read_text(encoding='utf-8'))
    assert 'source_review_error' in attempts[-1]


def test_author_can_request_source_review_without_retrying_or_fabricating_a_script(tmp_path):
    client = FixtureClient([json.dumps({'source_review_required': [{'source_id': 'labor-0',
        'evidence_ids': ['visual-1'], 'reason': '画面无法确定候选摘要所称动作，需先复核原片。'}]})])
    with pytest.raises(RuntimeError, match='来源含义尚待核实'):
        service_for(client).generate(PreVideoScriptRequest(short_seconds=60, account_key='account01',
            recent_video_types=('mixed',), output_dir=str(tmp_path)), now=NOW)
    assert len(client.calls) == 1
    assert not list(tmp_path.glob('*.json'))


def test_new_evidence_can_patch_saved_pair_without_pretending_same_input_resume(tmp_path):
    service_for(FixtureClient()).generate(PreVideoScriptRequest(short_seconds=60,
        account_key='account01', recent_video_types=('mixed',), output_dir=str(tmp_path)), now=NOW)
    source = next(tmp_path.glob('_runs/*/draft_1.json'))
    original = source.read_bytes()
    patch = {'changes':[{'script':'short', 'shot_id':'S01', 'field':'audio',
                         'value':'当事人以清晰中音现场对白；纸张轻响，无旁白。'}]}
    client = FixtureClient([json.dumps(patch, ensure_ascii=False)])
    result = service_for(client).generate(PreVideoScriptRequest(short_seconds=60,
        account_key='account01', recent_video_types=('mixed',), output_dir=str(tmp_path),
        editor_feedback='本轮补充固定声音设定。', baseline_draft_path=str(source),
        revision_feedback='只修改短版 S01 audio，明确角色声音。'), now=NOW)
    assert source.read_bytes() == original
    generation_calls = [c for c in client.calls if c[1]['caller'] == 'pre_video_script_pair']
    assert len(generation_calls) == 1
    assert 'current_pair' in json.loads(generation_calls[0][0][-1]['content'])
    assert len(json.loads(generation_calls[0][0][-1]['content'])['source_evidence']) >= 20
    audit = json.loads(Path(result.short.audit_path).read_text(encoding='utf-8'))
    assert audit['generation']['baseline_provenance']['mode'] == 'new_evidence_targeted_revision_not_same_input_resume'


@pytest.mark.parametrize('defect', ['participant', 'camera', 'lighting', 'state', 'duration'])
def test_continuous_short_catches_production_defects_before_model_review(defect):
    from src.trend_intelligence.script_pair import validate_continuous_short
    data = pair_payload()
    short = data['short']
    short['characters'].append(dict(short['characters'][0], name='律师'))
    first = short['shots'][0]
    for shot in short['shots']:
        shot['participants'] = ['当事人', '律师']
        shot['start_frame'] = shot['end_frame'] = '两人隔桌坐定；合同在当事人右手下，手机在桌面右侧。'
        for field in ('shot_size', 'camera_angle', 'lighting'):
            shot[field] = first[field]
    validate_continuous_short(data)
    second = short['shots'][1]
    if defect == 'participant': second['participants'] = ['当事人']
    if defect == 'camera': second['camera_angle'] = '正反打'
    if defect == 'lighting': second['lighting'] += '不同光源'
    if defect == 'state': second['start_frame'] = '手机已在口袋，合同已收起。'
    if defect == 'duration': second['end_seconds'] = second['start_seconds']+16
    with pytest.raises(ValueError, match='连续拍摄结构未通过'):
        validate_continuous_short(data)


def test_continuity_binding_preserves_model_source_and_does_not_rewrite_actions():
    from src.trend_intelligence.script_pair import bind_continuous_starts
    source = pair_payload()
    original = copy.deepcopy(source)
    bound, changes = bind_continuous_starts(source)
    assert source == original and changes
    assert bound['long'] == source['long']
    for previous, shot in zip(bound['short']['shots'], bound['short']['shots'][1:]):
        assert shot['start_frame'] == previous['end_frame']
        old = next(s for s in source['short']['shots'] if s['shot_id'] == shot['shot_id'])
        assert {k:v for k,v in shot.items() if k != 'start_frame'} == {k:v for k,v in old.items() if k != 'start_frame'}


def continuous_production_payload():
    data = pair_payload()
    short = data['short']
    short['characters'].append(dict(short['characters'][0], name='律师'))
    for shot in short['shots']:
        shot['participants'] = ['当事人', '律师']
    short['shots'][1].update(camera_angle='桌子另一侧平视，沿用开场机位',
                             lighting='柔和窗光从当事人左侧照入，白墙补光', shot_size='中近景')
    short['shots'][2].update(camera_angle='同S01', lighting='同S01', shot_size='同S01')
    return data


def test_shared_production_inherits_s01_preserves_all_nonfixed_fields_and_is_idempotent():
    from src.trend_intelligence.script_pair import bind_continuous_production
    data = continuous_production_payload()
    del data['short']['shots'][3]['lighting']  # A derived setting can be omitted.
    before = copy.deepcopy(data)
    bound, record = bind_continuous_production(data)
    assert data == before
    assert bound['long'] == before['long']
    assert bound['short']['shots'][0] == before['short']['shots'][0]
    assert record['schema'] == 'continuous_short_shared_production/v1'
    assert record['source_shot_id'] == 'S01' and record['settings']['camera_movement'] == '固定'
    fields = {'shot_size', 'camera_angle', 'lighting'}
    for old, shot in zip(before['short']['shots'], bound['short']['shots']):
        assert all(shot[field] == before['short']['shots'][0][field] for field in fields)
        assert {k:v for k,v in shot.items() if k not in fields} == {k:v for k,v in old.items() if k not in fields}
    changes = {(change['shot_id'], change['field']): change for change in record['changes']}
    assert changes['S02', 'lighting']['model_proposed'] == before['short']['shots'][1]['lighting']
    assert changes['S04', 'lighting']['model_proposed'] is None
    assert all(change['source'] == 'short.S01.' + change['field'] for change in record['changes'])
    assert bind_continuous_production(bound)[0] == bound
    assert bind_continuous_production(bound)[1]['changes'] == []


@pytest.mark.parametrize('defect', ['empty_light', 'self_reference', 'bad_size', 'cut_angle', 'moving_camera'])
def test_shared_production_rejects_invalid_anchor_or_real_camera_movement(defect):
    from src.trend_intelligence.script_pair import bind_continuous_production
    data = continuous_production_payload()
    first = data['short']['shots'][0]
    if defect == 'empty_light': first['lighting'] = ''
    if defect == 'self_reference': first['lighting'] = '同S01'
    if defect == 'bad_size': first['shot_size'] = '中景转特写'
    if defect == 'cut_angle': first['camera_angle'] = '桌前正反打'
    if defect == 'moving_camera': data['short']['shots'][1]['camera_movement'] = '跟拍'
    before = copy.deepcopy(data)
    with pytest.raises(ValueError):
        bind_continuous_production(data)
    assert data == before


@pytest.mark.parametrize('defect', ['narration', 'fake_reference'])
def test_shared_production_does_not_relax_voice_or_reference_validation(defect):
    from src.trend_intelligence.script_pair import bind_continuous_production, bind_continuous_starts
    data = continuous_production_payload()
    if defect == 'narration': data['short']['shots'][1]['audio'] = '旁白解释法律条文。'
    if defect == 'fake_reference': data['short']['reference_usage'][0]['evidence_ids'] = ['fake-frame']
    bound, _ = bind_continuous_production(data)
    bound, _ = bind_continuous_starts(bound)
    with pytest.raises(ValueError):
        parse(bound)


def test_continuous_generation_shares_production_once_preserves_raw_and_still_calls_reviewer(tmp_path):
    import hashlib
    class PrettyClient(FixtureClient):
        def chat_completion_tracked(self, messages, **kwargs):
            response = super().chat_completion_tracked(messages, **kwargs)
            return json.dumps(json.loads(response), ensure_ascii=False, indent=2)

    data = continuous_production_payload()
    client = PrettyClient([json.dumps(data, ensure_ascii=False)])
    result = service_for(client).generate(PreVideoScriptRequest(short_seconds=60,
        account_key='account01', recent_video_types=('mixed',), output_dir=str(tmp_path),
        continuous_short=True), now=NOW)
    generation = result.short.script.generation
    assert generation['generation_api_calls'] == 1 and generation['accepted_attempt'] == 1
    assert generation['prompt_version'] == '2026-09-10-cross-field-v9'
    trace = Path(generation['trace_dir'])
    raw = json.loads((trace/'model_draft_1.json').read_text(encoding='utf-8'))
    assert raw == data
    assert (trace/'model_draft_1.json').read_bytes() == json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
    record = json.loads((trace/'shared_production_1.json').read_text(encoding='utf-8'))
    assert record['input_sha256'] == hashlib.sha256((trace/'model_before_shared_production_1.json').read_bytes()).hexdigest()
    assert record['output_sha256'] == hashlib.sha256((trace/'shared_production_draft_1.json').read_bytes()).hexdigest()
    assert record['settings'] == generation['continuous_production']['settings']
    assert len(generation['production_normalizations']) == 1
    normalized = json.loads((trace/'draft_1.json').read_text(encoding='utf-8'))
    for index, shot in enumerate(normalized['short']['shots']):
        for field in ('shot_size', 'camera_angle', 'lighting'):
            assert shot[field] == data['short']['shots'][0][field]
        for field in ('action', 'blocking', 'composition', 'audio', 'dialogue', 'end_frame'):
            assert shot[field] == data['short']['shots'][index][field]
    assert normalized['long'] == data['long']
    reviews = [call for call in client.calls if call[1]['caller'] == 'pre_video_script_review']
    assert len(reviews) == 1
    reviewed = json.loads(reviews[0][0][1]['content'])
    assert reviewed['continuous_production']['settings'] == record['settings']
    assert reviewed['continuous_production']['review_requirement']
    assert reviewed['scripts'][0]['shots'][1]['lighting'] == data['short']['shots'][0]['lighting']


def test_noncontinuous_generation_keeps_per_shot_production_and_has_no_shared_binding(tmp_path):
    data = pair_payload()
    data['short']['shots'][1].update(lighting='右侧柔光灯为主光，左侧白墙补光',
                                    camera_angle='桌侧平视', shot_size='中近景')
    client = FixtureClient([json.dumps(data, ensure_ascii=False)])
    result = service_for(client).generate(PreVideoScriptRequest(short_seconds=60,
        account_key='account01', recent_video_types=('mixed',), output_dir=str(tmp_path)), now=NOW)
    generation = result.short.script.generation
    assert 'continuous_production' not in generation and 'production_normalizations' not in generation
    assert result.short.script.shots[1].lighting == data['short']['shots'][1]['lighting']
    assert result.short.script.shots[1].camera_angle == data['short']['shots'][1]['camera_angle']
    trace = Path(generation['trace_dir'])
    assert not list(trace.glob('*shared_production*')) and not list(trace.glob('model_draft_*.json'))
    request = json.loads((trace/'request.json').read_text(encoding='utf-8'))
    assert 'production_constraints' not in json.loads(request[1]['content'])
    reviews = [call for call in client.calls if call[1]['caller'] == 'pre_video_script_review']
    assert 'continuous_production' not in json.loads(reviews[0][0][1]['content'])


@pytest.mark.parametrize('defect', ['missing_long', 'open_ending', 'gap', 'overlap', 'no_core',
                                   'no_resolution', 'offscreen_ending', 'missing_beat', 'duplicate_shot',
                                   'undefined_role', 'wrong_duration', 'copied_long'])
def test_rejects_broken_story_contract(defect):
    data = copy.deepcopy(pair_payload())
    short = data['short']
    if defect == 'missing_long': del data['long']
    if defect == 'open_ending': short['closing_line'] = '答案留到下集揭晓。'
    if defect == 'gap': short['shots'][1]['start_seconds'] += 1
    if defect == 'overlap': short['shots'][1]['start_seconds'] -= 1
    if defect == 'no_core': data['core_message'] = ''
    if defect == 'no_resolution': short['resolution'] = ''
    if defect == 'offscreen_ending': short['shots'][-1]['dialogue'] = '这是一句没有对应的台词。'
    if defect == 'missing_beat': short['story_beats'].pop()
    if defect == 'duplicate_shot': short['story_beats'][1]['shot_ids'] = ['S01']
    if defect == 'undefined_role': short['shots'][0]['participants'] = ['未定义角色']
    if defect == 'wrong_duration': short['shots'][-1]['end_seconds'] -= 1
    if defect == 'copied_long':
        # Different setup text must not disguise copying the entire short dialogue.
        for target, original in zip(data['long']['shots'], short['shots']):
            target['dialogue'] = original['dialogue']
    with pytest.raises(ValueError): parse(data)


def service_for(client):
    from source_media_fixture import complete_media_analysis

    seeds = [_row('labor', '被辞退后核对通知', video_type='mixed', metric=50_000),
             _row('marriage', '离婚后核对材料', video_type='mixed', metric=50_000)]
    rows = _expanded_rows(seeds)
    media_folder = Path(__file__).resolve().parents[1] / 'data/qa/script_pair_media_fixture'
    for observation, _ in rows:
        observation.collected_at = NOW.isoformat()
    rows = [(observation, complete_media_analysis(analysis, media_folder / observation.item_id))
            for observation, analysis in rows]
    repo = _Repository([r[0] for r in rows], [r[1] for r in rows])
    return PreVideoScriptService(repository=repo, profile_repository=_Profiles(), script_client=client)


def test_invalid_long_never_delivers_only_short(tmp_path):
    data = pair_payload()
    del data['long']['resolution']
    client = FixtureClient([json.dumps(data)])
    with pytest.raises(ValueError, match='未交付'):
        service_for(client).generate(PreVideoScriptRequest(short_seconds=60, account_key='account01',
            recent_video_types=('mixed',), output_dir=str(tmp_path)), now=NOW)
    assert len(client.calls) == 3
    assert not list(tmp_path.glob('*.json'))
    assert not list(tmp_path.glob('*.md'))
    assert len(list(tmp_path.glob('_runs/*/draft_*.json'))) == 3


def test_sample_gate_runs_before_any_model_call(tmp_path):
    client = FixtureClient()
    service = service_for(client)
    service.repository.observations = service.repository.observations[:19]
    with pytest.raises(ValueError, match='19/20'):
        service.generate(PreVideoScriptRequest(short_seconds=60, account_key='account01', recent_video_types=('mixed',),
                                               output_dir=str(tmp_path)), now=NOW)
    assert not client.calls


def test_pair_artifacts_and_prompt_are_auditable(tmp_path):
    client = FixtureClient()
    pair = service_for(client).generate(PreVideoScriptRequest(short_seconds=60, account_key='account01',
        recent_video_types=('mixed',), output_dir=str(tmp_path)), now=NOW)
    manifest = json.loads(Path(pair.manifest_path).read_text(encoding='utf-8'))
    assert manifest['paused_at'] == 'before_video_generation'
    assert manifest['video_generation_submitted'] is False
    assert len(client.calls) == 2
    for item in (pair.short, pair.long):
        audit = json.loads(Path(item.audit_path).read_text(encoding='utf-8'))
        assert audit['selection']['sample_gate']['passed']
        assert audit['generation']['prompt_sha256']
        assert '本片结局' in Path(item.script_path).read_text(encoding='utf-8')
    assert client.calls[0][1]['caller'] == 'pre_video_script_pair'
    assert '未完待续' in client.calls[0][0][0]['content']
    payload = json.loads(client.calls[0][0][1]['content'])
    source = payload['source_evidence'][0]
    assert source['source_id'] and source['analysis_id']
    assert source['expression_analysis']['core_message']['evidence_ids']
    assert source['expression_analysis']['evidence'][0]['start_seconds'] == 0
    assert source['media_evidence']['visual']['status'] == 'completed'
    assert len(source['media_evidence']['source_video_sha256']) == 64
    assert len(source['media_evidence']['visual']['artifact_sha256']) == 64
    assert source['media_evidence']['audio']['coverage_start_seconds'] == 0
    assert '_path"' not in json.dumps(source['media_evidence'])
    assert source['metric_kind'] == 'views' and source['metric_value'] > 0
    assert payload['account_positioning']['domain_config']['practice_areas']
    assert payload['expression_patterns']['patterns'][0]['mode'] == 'prop_demonstration'
    assert payload['expression_patterns']['creative_contribution_percent'] is None
    for script in (pair.short.script, pair.long.script):
        assert script.generation['reference_usage_validation']['status'] == 'identifiers_verified_editorially_reviewed'
        assert script.generation['reference_usage'][0]['source_id'] == 'labor-0'
        assert script.generation['expression_plan']['ending']['shot_ids'] == [script.shots[-1].shot_id]


def test_public_media_metadata_strips_paths_recursively_and_preserves_hashes():
    from src.trend_intelligence.script_pair import _public_media_evidence
    media = {'schema': 'local_media_evidence/v1', 'source_video_path': 'D:/private/original.mp4',
             'source_video_sha256': 'a'*64, 'visual': {'status': 'completed',
                 'frames': [{'image_path': 'D:/private/frame.png', 'sha256': 'b'*64, 'time_seconds': 1.5}]},
             'audio': {'status': 'transcribed', 'artifact_path': 'D:/private/audio.json'},
             'unknown_items': ['voice_identity']}
    result = _public_media_evidence(media)
    assert 'source_video_path' in media
    assert result['source_video_sha256'] == 'a'*64
    assert result['visual']['frames'] == [{'sha256': 'b'*64, 'time_seconds': 1.5}]
    assert result['audio'] == {'status': 'transcribed'}
    assert result['unknown_items'] == ['voice_identity']
    assert 'D:/private' not in json.dumps(result)


def test_independent_reviewer_is_read_only_and_has_separate_model_provenance(tmp_path):
    author, reviewer = FixtureClient(), FixtureClient()
    reviewer.model_name = 'independent_review_fixture'
    service = service_for(author)
    service.review_client = reviewer
    result = service.generate(PreVideoScriptRequest(short_seconds=60, account_key='account01',
        recent_video_types=('mixed',), output_dir=str(tmp_path)), now=NOW)
    assert [c[1]['caller'] for c in author.calls] == ['pre_video_script_pair']
    assert [c[1]['caller'] for c in reviewer.calls] == ['pre_video_script_review']
    generation = json.loads(Path(result.short.audit_path).read_text(encoding='utf-8'))['generation']
    assert generation['model'] == author.model_name
    assert generation['review_model'] == reviewer.model_name


def test_readonly_rejection_preserves_saved_draft_and_never_calls_author(tmp_path):
    service_for(FixtureClient()).generate(PreVideoScriptRequest(short_seconds=60, account_key='account01',
        recent_video_types=('mixed',), output_dir=str(tmp_path)), now=NOW)
    source = next(tmp_path.glob('_runs/*/draft_1.json'))
    original = source.read_bytes()
    class RejectingReviewer(FixtureClient):
        def chat_completion_tracked(self, messages, **kwargs):
            report = json.loads(super().chat_completion_tracked(messages, **kwargs))
            report['checks']['ending_complete'] = False
            report['issues'] = [{'problem':'fixture rejection', 'rewrite_instruction':'do not execute',
                'evidence':[{'script':'short', 'shot_id':'S06', 'field':'dialogue',
                             'quote':pair_payload()['short']['shots'][-1]['dialogue']}]}]
            return json.dumps(report)
    author, reviewer = FixtureClient(), RejectingReviewer()
    service = service_for(author)
    service.review_client = reviewer
    with pytest.raises(ValueError, match='只读复核未通过'):
        service.generate(PreVideoScriptRequest(short_seconds=60, account_key='account01',
            recent_video_types=('mixed',), output_dir=str(tmp_path), initial_draft_path=str(source), review_only=True), now=NOW)
    assert not author.calls and len(reviewer.calls) == 1
    assert source.read_bytes() == original


def test_pair_page_has_two_tabs_and_four_downloads():
    app = AppTest.from_string('''
from src.web.trend_dashboard import _render_script_pair_result
_render_script_pair_result([
    {'kind':'short', 'duration':60, 'markdown':'短版：问题已经回答。', 'json':'{}'},
    {'kind':'long', 'duration':180, 'markdown':'长版：冲突得到解决。', 'json':'{}'}])
''').run(timeout=30)
    assert not app.exception
    assert [tab.label for tab in app.tabs] == ['短视频 · 60 秒', '长视频 · 180 秒']
    assert len(app.get('download_button')) == 4


def test_editorial_failure_triggers_rewrite_before_delivery(tmp_path):
    from src.trend_intelligence.script_pair import REVIEW_CHECKS
    class ReviewClient(FixtureClient):
        failed_once = False
        def chat_completion_tracked(self, messages, **kwargs):
            result = super().chat_completion_tracked(messages, **kwargs)
            if kwargs.get('caller') == 'pre_video_script_review' and not self.failed_once:
                self.failed_once = True
                report = {'checks': {key: True for key in REVIEW_CHECKS},
                          'issues': [{'problem': '收尾未回答核心', 'rewrite_instruction': '重写最后镜头',
                                      'evidence': [{'script': 'short', 'shot_id': 'S06', 'field': 'dialogue',
                                                    'quote': pair_payload()['short']['closing_line']}]}],
                          'summary': '需要修改'}
                report['checks']['ending_complete'] = False
                return json.dumps(enrich_review_report(report, json.loads(messages[1]['content'])))
            return result
    client = ReviewClient()
    pair = service_for(client).generate(PreVideoScriptRequest(short_seconds=60,
        account_key='account01', recent_video_types=('mixed',), output_dir=str(tmp_path)), now=NOW)
    generation = pair.short.script.generation
    assert generation['accepted_attempt'] == 2
    assert not generation['reviews'][0]['report']['passed']
    assert generation['reviews'][1]['report']['passed']
    drafts = [call for call in client.calls if call[1]['caller'] == 'pre_video_script_pair']
    assert len(drafts) == 2
    assert '重写最后镜头' in drafts[1][0][-1]['content']


def test_saved_pair_can_be_opened_after_cli_generation(tmp_path):
    from src.web.trend_dashboard import _load_saved_script_pair
    pair = service_for(FixtureClient()).generate(PreVideoScriptRequest(short_seconds=60,
        account_key='account01', recent_video_types=('mixed',), output_dir=str(tmp_path)), now=NOW)
    saved = _load_saved_script_pair(pair.short.script.account_uuid, tmp_path)
    assert [s['kind'] for s in saved] == ['short', 'long']
    assert [s['duration'] for s in saved] == [60, 180]
    assert _load_saved_script_pair('other-account', tmp_path) == []
    path = Path(pair.manifest_path)
    manifest = json.loads(path.read_text(encoding='utf-8'))
    manifest['agent_review'] = {'status': 'needs_revision'}
    path.write_text(json.dumps(manifest), encoding='utf-8')
    historical = _load_saved_script_pair(pair.short.script.account_uuid, tmp_path)
    assert [s['kind'] for s in historical] == ['short', 'long']
    assert all(s['current_review']['status'] == 'needs_review' for s in historical)
    assert all(s['current_review']['current_passed'] is False for s in historical)


def test_voice_annotations_and_defined_offscreen_speakers_are_preserved():
    data = pair_payload()
    voice = {**data['short']['characters'][0], 'name': '来电者'}
    data['short']['characters'].append(voice)
    shot = data['short']['shots'][0]
    shot['dialogue_speaker'] = '来电者（语音外放）'
    shot['dialogue_mode'] = 'device'
    shot['audio'] = '桌面手机免提传来来电者对白，纸张轻响'
    short, _ = parse(data)
    assert short.shots[0].participants == ('当事人',)
    assert short.shots[0].dialogue_speaker == '来电者'
    assert '语音外放' in short.shots[0].audio
    assert short.shots[0].dialogue == shot['dialogue']
    assert '入画人物不代说、不对口型' in short.shots[0].model_prompt_zh


def test_delivery_errors_are_reported_together():
    data = pair_payload()
    for s in data['short']['shots'][:2]:
        s['dialogue'] = '超' * 60
    with pytest.raises(ValueError) as exc:
        parse(data)
    assert 'S01 台词过长' in str(exc.value) and 'S02 台词过长' in str(exc.value)


def test_missing_fields_do_not_hide_other_shot_defects():
    data = pair_payload()
    del data['short']['shots'][0]['narrative_purpose']
    data['short']['shots'][1]['dialogue_speaker'] = '旁白'
    data['long']['shots'][0]['shot_id'] = 'S07'
    with pytest.raises(ValueError) as exc:
        parse(data)
    errors = str(exc.value)
    assert 'narrative_purpose' in errors and '禁止旁白' in errors and '独立从 S01' in errors


def test_model_field_revision_keeps_unaffected_storyboard_intact(tmp_path):
    data = pair_payload()
    data['short']['shots'][0]['dialogue'] = '超' * 110
    patch = {'changes': [{'script': 'short', 'shot_id': 'S01', 'field': 'dialogue', 'value': '这笔账我已经付过了。'}]}
    client = FixtureClient([json.dumps(data), json.dumps(patch)])
    pair = service_for(client).generate(PreVideoScriptRequest(short_seconds=60,
        account_key='account01', recent_video_types=('mixed',), output_dir=str(tmp_path)), now=NOW)
    trace = Path(pair.short.script.generation['trace_dir'])
    merged = json.loads((trace / 'draft_2.json').read_text(encoding='utf-8'))
    assert merged['long'] == data['long']
    assert merged['short']['shots'][1:] == data['short']['shots'][1:]
    assert merged['short']['shots'][0]['dialogue'] == patch['changes'][0]['value']
    assert json.loads((trace / 'revision_2.json').read_text(encoding='utf-8')) == patch
    assert (trace / 'call_2.json').is_file()
    request = json.loads((trace / 'call_2.json').read_text(encoding='utf-8'))
    assert '定点修订编辑' in request[0]['content']
    assert '严格返回 JSON 对象，键为 core_message、short、long' not in request[0]['content']


def test_model_revision_cannot_sneak_in_extra_shots():
    from src.trend_intelligence.script_pair import _merge_model_revision
    with pytest.raises(ValueError, match='不得增加'):
        _merge_model_revision(pair_payload(), json.dumps({'short': {'shots': [{'shot_id':'S07', 'dialogue':''}]}}))


def test_new_reading_feedback_forces_model_revision_of_saved_draft(tmp_path):
    first = service_for(FixtureClient()).generate(PreVideoScriptRequest(short_seconds=60,
        account_key='account01', recent_video_types=('mixed',), output_dir=str(tmp_path)), now=NOW)
    draft = str(Path(first.short.script.generation['trace_dir']) / 'draft_1.json')
    patch = {'changes': [{'script':'short', 'shot_id':'S01', 'field':'dialogue', 'value':'这笔账我已经付过了。'}]}
    client = FixtureClient([json.dumps(patch)])
    second = service_for(client).generate(PreVideoScriptRequest(short_seconds=60,
        account_key='account01', recent_video_types=('mixed',), output_dir=str(tmp_path),
        initial_draft_path=draft, revision_feedback='客户需要提出具体困惑'), now=NOW)
    assert [call[1]['caller'] for call in client.calls] == ['pre_video_script_pair', 'pre_video_script_review']
    assert second.short.script.shots[0].dialogue == patch['changes'][0]['value']
    assert '客户需要提出具体困惑' in client.calls[0][0][-1]['content']
    assert '客户需要提出具体困惑' in client.calls[1][0][-1]['content']
    trace = Path(second.short.script.generation['trace_dir'])
    assert (trace / 'revision_feedback.md').read_text(encoding='utf-8') == '客户需要提出具体困惑'


def test_timing_can_use_spare_seconds_without_rewriting_dialogue():
    from src.trend_intelligence.script_pair import _fit_spoken_timing
    data = pair_payload()
    data['short']['shots'][0]['dialogue'] = '字' * 60
    fitted, adjustments = _fit_spoken_timing(data, short_seconds=60, long_seconds=180)
    short, _ = parse(fitted)
    assert short.shots[0].end_seconds == 12
    assert short.shots[-1].end_seconds == 60
    assert fitted['long'] == data['long']
    assert [s['dialogue'] for s in fitted['short']['shots']] == [s['dialogue'] for s in data['short']['shots']]
    assert adjustments
    data['short']['shots'][1]['start_seconds'] += 1
    unchanged, adjustments = _fit_spoken_timing(data, short_seconds=60, long_seconds=180)
    assert unchanged == data and not adjustments


def test_common_core_scope_can_be_normalized_but_conflicts_are_rejected():
    from src.trend_intelligence.script_pair import _merge_model_revision
    change = {'script':'short', 'shot_id':'', 'field':'core_message', 'value':'核对后说明一个共同核心。'}
    result = _merge_model_revision(pair_payload(), json.dumps({'changes':[change]}))
    assert result['core_message'] == change['value']
    assert 'core_message' not in result['short']
    metadata = _merge_model_revision(pair_payload(), json.dumps({'changes':[
        {'script':'short', 'field':'resolution', 'value':'已完成的核对结果。'}]}))
    assert metadata['short']['resolution'] == '已完成的核对结果。'
    with pytest.raises(ValueError, match='互相冲突'):
        _merge_model_revision(pair_payload(), json.dumps({'changes':[change, {**change, 'script':'long', 'value':'不同核心'}]}))


def test_saved_model_revision_is_reused_only_with_its_exact_draft(tmp_path):
    data = pair_payload()
    data['short']['shots'][0]['dialogue'] = '超'*110
    patch = {'changes':[{'script':'short', 'shot_id':'S01', 'field':'dialogue', 'value':'这笔账我付过了。'}]}
    first = service_for(FixtureClient([json.dumps(data), json.dumps(patch)])).generate(PreVideoScriptRequest(
        short_seconds=60, account_key='account01', recent_video_types=('mixed',), output_dir=str(tmp_path)), now=NOW)
    trace = Path(first.short.script.generation['trace_dir'])
    client = FixtureClient()
    second = service_for(client).generate(PreVideoScriptRequest(short_seconds=60, account_key='account01',
        recent_video_types=('mixed',), output_dir=str(tmp_path), initial_draft_path=str(trace/'draft_1.json'),
        initial_revision_path=str(trace/'revision_2.json')), now=NOW)
    assert [c[1]['caller'] for c in client.calls] == ['pre_video_script_review']
    assert second.short.script.generation['generation_api_calls'] == 0
    assert second.short.script.shots[0].dialogue == patch['changes'][0]['value']
    with pytest.raises(ValueError, match='不匹配'):
        service_for(FixtureClient()).generate(PreVideoScriptRequest(short_seconds=60, account_key='account01',
            recent_video_types=('mixed',), output_dir=str(tmp_path), initial_draft_path=str(trace/'draft_2.json'),
            initial_revision_path=str(trace/'revision_2.json')), now=NOW)


def test_single_known_participant_shape_is_normalized_without_inventing_roles(tmp_path):
    data = pair_payload()
    data['short']['shots'][0]['participants'] = '当事人'
    pair = service_for(FixtureClient([json.dumps(data)])).generate(PreVideoScriptRequest(short_seconds=60,
        account_key='account01', recent_video_types=('mixed',), output_dir=str(tmp_path)), now=NOW)
    assert pair.short.script.shots[0].participants == ('当事人',)
    assert pair.short.script.generation['shape_normalizations'][0]['changes'][0]['before'] == '当事人'
    from src.trend_intelligence.script_pair import _normalize_single_participants
    data['short']['shots'][0]['participants'] = '陌生人'
    unchanged, changes = _normalize_single_participants(data)
    assert unchanged == data and not changes


@pytest.mark.parametrize('always_invalid', [False, True])
@pytest.mark.parametrize('bad_evidence', [False, True])
def test_bad_review_format_never_triggers_script_rewrite(tmp_path, always_invalid, bad_evidence):
    class ReviewFormatClient(FixtureClient):
        review_calls = 0
        def chat_completion_tracked(self, messages, **kwargs):
            result = super().chat_completion_tracked(messages, **kwargs)
            if kwargs.get('caller') == 'pre_video_script_review':
                self.review_calls += 1
                if always_invalid or self.review_calls == 1:
                    if bad_evidence:
                        report = json.loads(result)
                        report['checks']['shot_continuity'] = False
                        report['issues'] = [{'problem': '手机跳变', 'rewrite_instruction': '移动手机',
                                             'evidence': [{'script': 'short', 'shot_id': 'S05',
                                                           'field': 'composition', 'quote': '桌面右侧手机'}]}]
                        return json.dumps(report)
                    return '这不是有效审稿JSON'
            return result
    client = ReviewFormatClient()
    request = PreVideoScriptRequest(short_seconds=60, account_key='account01',
        recent_video_types=('mixed',), output_dir=str(tmp_path))
    if always_invalid:
        with pytest.raises(RuntimeError, match='审稿结果格式无效'):
            service_for(client).generate(request, now=NOW)
        assert not list(tmp_path.glob('*.pair.json'))
    else:
        pair = service_for(client).generate(request, now=NOW)
        assert pair.short.script.generation['reviews'][0]['report']['format_attempts'] == 2
    from src.trend_intelligence.script_pair import SCRIPT_REVIEW_MAX_FORMAT_ATTEMPTS
    assert client.review_calls == (SCRIPT_REVIEW_MAX_FORMAT_ATTEMPTS if always_invalid else 2)
    assert sum(call[1]['caller'] == 'pre_video_script_pair' for call in client.calls) == 1
    assert not list(tmp_path.glob('_runs/*/revision_*.json'))


def test_saved_draft_resume_skips_generation_but_still_reviews(tmp_path):
    first = service_for(FixtureClient()).generate(PreVideoScriptRequest(short_seconds=60,
        account_key='account01', recent_video_types=('mixed',), output_dir=str(tmp_path)), now=NOW)
    draft = str(Path(first.short.script.generation['trace_dir']) / 'draft_1.json')
    client = FixtureClient()
    second = service_for(client).generate(PreVideoScriptRequest(short_seconds=60,
        account_key='account01', recent_video_types=('mixed',), output_dir=str(tmp_path), initial_draft_path=draft), now=NOW)
    assert [c[1]['caller'] for c in client.calls] == ['pre_video_script_review']
    assert second.short.script.generation['generation_api_calls'] == 0
    with pytest.raises(ValueError, match='输入不一致'):
        service_for(FixtureClient()).generate(PreVideoScriptRequest(short_seconds=60,
            account_key='account01', recent_video_types=('mixed',), output_dir=str(tmp_path),
            initial_draft_path=draft, editor_feedback='new instructions'), now=NOW)


@pytest.mark.parametrize('defect', ['narrator', 'renamed_narrator', 'hidden_audio', 'monologue',
                                   'unseen_speaker', 'device_without_source', 'missing_lighting',
                                   'missing_composition', 'multiple_sizes', 'internal_cut'])
def test_rejects_narration_and_unshootable_storyboards(defect):
    data = pair_payload()
    s = data['short']['shots'][0]
    if defect == 'narrator': s['dialogue_speaker'] = '旁白'
    if defect == 'renamed_narrator': data['short']['characters'][0]['identity'] = '画外解说员'
    if defect == 'hidden_audio': s['audio'] = '旁白总结核对结果'
    if defect == 'monologue': s['emotion_and_performance'] = '内心独白解释疑虑'
    if defect == 'unseen_speaker':
        data['short']['characters'].append({**data['short']['characters'][0], 'name': '另一人'})
        s['dialogue_speaker'] = '另一人'
    if defect == 'device_without_source': s['dialogue_mode'] = 'device'
    if defect == 'missing_lighting': s['lighting'] = ''
    if defect == 'missing_composition': del s['composition']
    if defect == 'multiple_sizes': s['shot_size'] = '中景切特写'
    if defect == 'internal_cut': s['camera_angle'] = '正反打'
    with pytest.raises(ValueError, match='长版不能直接复制短版扩时' if defect == 'copied_long' else None):
        parse(data)


def test_preflight_reports_long_inherited_size_as_enum_error_not_a_fabricated_cut():
    from src.trend_intelligence.script_pair import _preflight_shots, SHOT_SIZES
    data = pair_payload()
    data['long']['shots'][1]['shot_size'] = '同 S01'
    before = copy.deepcopy(data)
    with pytest.raises(ValueError) as caught:
        _preflight_shots(data, short_seconds=60, long_seconds=180)
    message = str(caught.value)
    assert "long S02 shot_size='同 S01' 无效" in message
    assert '、'.join(SHOT_SIZES) in message and '长版每镜须完整填写实际景别' in message
    assert '正反打' not in message and '切镜' not in message and '变焦' not in message
    assert data == before  # Long settings are not expanded or otherwise repaired.


def test_preflight_aggregates_independent_visual_defects_and_timeline_problems():
    from src.trend_intelligence.script_pair import _preflight_shots
    data = pair_payload()
    second = data['long']['shots'][1]
    second.update(shot_size='同 S01', camera_movement='同上', lighting='')
    data['long']['shots'][2]['camera_angle'] = '桌前平视后切到门口'
    data['long']['shots'][-1]['start_seconds'] = 152
    data['long']['shots'][-1]['end_seconds'] = 185
    before = copy.deepcopy(data)
    with pytest.raises(ValueError) as caught:
        _preflight_shots(data, short_seconds=60, long_seconds=180)
    message = str(caught.value)
    assert 'long S02 缺失摄影/画面字段' in message and 'lighting' in message
    assert "long S02 shot_size='同 S01' 无效" in message
    assert "long S02 camera_movement='同上' 无效" in message and '固定、横移、跟拍、摇镜' in message
    assert "long S03 camera_angle='桌前平视后切到门口' 含切镜" in message
    assert 'long S12 时间线不连续：上一镜结束于 165 秒，本镜开始于 152 秒' in message
    assert 'long S12 单镜时长 33 秒超出3—20秒范围；当前 152—185 秒' in message
    assert 'long 总时长须为 180 秒' in message
    assert data == before


def test_missing_visual_field_does_not_claim_camera_motion_or_cutting():
    from src.trend_intelligence.script_pair import _validate_shot_production
    shot = pair_payload()['short']['shots'][0]
    del shot['composition']
    with pytest.raises(ValueError) as caught:
        _validate_shot_production(shot, names={'当事人'}, kind='short')
    assert 'composition' in str(caught.value)
    assert '缺失摄影/画面字段' in str(caught.value)
    assert '切镜' not in str(caught.value) and '运镜' not in str(caught.value)


def test_preflight_overlong_shot_does_not_falsely_report_noncontinuous_timeline():
    from src.trend_intelligence.script_pair import _preflight_shots
    data = pair_payload()
    data['long']['shots'][-1]['end_seconds'] = 193
    with pytest.raises(ValueError) as caught:
        _preflight_shots(data, short_seconds=60, long_seconds=180)
    message = str(caught.value)
    assert 'long S12 单镜时长 28 秒超出3—20秒范围' in message
    assert 'long 总时长须为 180 秒' in message
    assert '时间线不连续' not in message


def test_silent_action_has_no_invented_speech_or_lip_sync():
    data = pair_payload()
    s = data['short']['shots'][0]
    s.update(dialogue_mode='none', dialogue_speaker='', dialogue='', audio='纸张轻响，无旁白')
    short, _ = parse(data)
    shot = short.shots[0]
    assert shot.dialogue == shot.subtitle == ''
    assert '不生成字幕' in shot.model_prompt_zh
    assert '说出' not in shot.model_prompt_zh


@pytest.mark.parametrize('stage', ['pre_video_script_pair', 'pre_video_script_review'])
def test_request_failure_does_not_spend_creative_rewrite_attempts(tmp_path, stage):
    class UnavailableClient(FixtureClient):
        def chat_completion_tracked(self, messages, **kwargs):
            response = super().chat_completion_tracked(messages, **kwargs)
            return None if kwargs.get('caller') == stage else response
    client = UnavailableClient()
    with pytest.raises(RuntimeError, match='模型请求失败'):
        service_for(client).generate(PreVideoScriptRequest(short_seconds=60,
            account_key='account01', recent_video_types=('mixed',), output_dir=str(tmp_path)), now=NOW)
    assert sum(c[1]['caller'] == 'pre_video_script_pair' for c in client.calls) == 1
    assert not list(tmp_path.glob('*.pair.json'))
    attempts = json.loads(next(tmp_path.glob('_runs/*/attempts.json')).read_text(encoding='utf-8'))
    assert 'request_error' in attempts[-1]


def test_full_visuals_reach_model_prompt_reviewer_export_and_browser(tmp_path):
    client = FixtureClient()
    pair = service_for(client).generate(PreVideoScriptRequest(short_seconds=60,
        account_key='account01', recent_video_types=('mixed',), output_dir=str(tmp_path)), now=NOW)
    from src.trend_intelligence.script_pair import VISUAL_FIELDS
    reviewed = json.loads(client.calls[1][0][1]['content'])
    expected = pair_payload()['short']['shots'][0]
    assert reviewed['scripts'][0]['core_message'] == pair.short.script.core_message
    assert reviewed['scripts'][0]['shots'][0]['narrative_purpose'] == expected['narrative_purpose']
    assert 'purpose' not in reviewed['scripts'][0]['shots'][0]
    for field in VISUAL_FIELDS:
        assert reviewed['scripts'][0]['shots'][0][field] == expected[field]
    shot = pair.short.script.shots[0]
    for field in ('composition', 'lighting', 'start_frame', 'end_frame', 'transition'):
        assert getattr(shot, field) in shot.model_prompt_zh
    manifest = json.loads(Path(pair.manifest_path).read_text(encoding='utf-8'))
    packet = Path(manifest['review_path']).read_text(encoding='utf-8')
    assert '光线：' in packet and '画面结构／构图：' in packet and '剪辑衔接：' in packet
    assert '本镜视频提示词' not in packet
    markdown = Path(pair.short.script_path).read_text(encoding='utf-8')
    raw = Path(pair.short.script_json_path).read_text(encoding='utf-8')
    app = AppTest.from_string('''
import streamlit as st
from src.web.trend_dashboard import _render_script_pair_result
_render_script_pair_result(st.session_state['scripts'])
''')
    app.session_state['scripts'] = [{'kind':'short', 'duration':60, 'markdown':markdown, 'json':raw}]
    app.run(timeout=30)
    assert not app.exception
    visible = '\n'.join(item.value for item in app.markdown)
    assert expected['lighting'] in visible and expected['composition'] in visible
