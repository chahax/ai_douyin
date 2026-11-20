"""Synthetic fixtures only: never presented as a real novel or model acceptance."""
from copy import deepcopy
import hashlib
import json
import pytest
from src.content_factory import serial_story_contract_v1 as c
from src.content_factory import serial_story_production_v1 as p
from src.content_factory.corpus_screenplay_v1 import digest, read, freeze


def chapter(i):
    text = f'林岚和阿禾在厨房。第{i}天，林岚把钥匙交给阿禾。'
    return {'index': i, 'book_id': 'fixture', 'text': text,
            'sha256': hashlib.sha256(text.encode()).hexdigest(), 'title': str(i)}


def source(n=2):
    return {'manifest': {'book_id': 'fixture', 'full_book_confirmed': False},
            'chapters': [chapter(i) for i in range(1, n+1)]}


def claim(i):
    return {'id': f'F{i}', 'category': 'event', 'statement': '交钥匙',
            'evidence': [{'source_id': f'CH{i}-P001', 'quote': '林岚把钥匙交给阿禾'}]}


def material(i):
    return {'chapter_index': i, 'claims': [claim(i)],
            'coverage': [{'source_id': f'CH{i}-P001', 'claim_ids': [f'F{i}'], 'omission_reason': ''}]}


def bible(indices=(1, 2)):
    refs = [f'CH{i}-P001' for i in indices]
    return {'chapter_indices': list(indices), 'claims': [claim(i) for i in indices],
            'characters': [{'id': x, 'name': x, 'aliases': [], 'source_ids': refs} for x in ('林岚', '阿禾')],
            'places': [{'id': '厨房', 'name': '厨房', 'source_ids': refs}],
            'visual_style': '生活化', 'creative_additions': [], 'unresolved': []}


def episode(i, seconds=25):
    return {'id': f'E{i}', 'title': str(i), 'chapters': [i], 'context_chapters': [1] if i>1 else [],
            'information': '交接与承接', 'conflict': '确认归属', 'resolution': '收到钥匙',
            'hook': '下一步', 'continuation': '承接前集', 'target_seconds': seconds,
            'depends_on': [f'E{i-1}'] if i>1 else [], 'source_ids': [f'CH{i}-P001']}


def outline(n=2):
    return {'title': 'fixture', 'arc': 'fixture', 'scope_is_complete_book': False,
            'episodes': [episode(i, 25+i*5) for i in range(1, n+1)], 'omitted_chapters': []}


def script(ep, previous=None):
    i = int(ep['id'][1:]); refs = [f'CH{i}-P001']
    intro = [] if previous else [
        {'id': x, 'timeline': 'CURRENT', 'kind': 'location', 'subject': x, 'item': '位置',
         'value': '厨房', 'source_ids': refs} for x in ('林岚', '阿禾')]
    if not previous:
        intro.append({'id': 'KEY', 'timeline': 'CURRENT', 'kind': 'prop', 'subject': '阿禾',
                      'item': '钥匙', 'value': '林岚', 'source_ids': refs})
    return {'episode_id': ep['id'], 'title': 'fixture', 'creative_additions': [], 'scenes': [{
        'id': 'S1', 'timeline': 'CURRENT', 'story_time': f'第{i}天', 'place_id': '厨房',
        'cast': ['林岚', '阿禾'], 'seconds': ep['target_seconds'], 'information': '收到钥匙',
        'plot': '交接', 'performance': '自然', 'camera': '近景', 'source_ids': refs,
        'introductions': intro,
        'actions': [{'id': 'A1', 'people': ['林岚', '阿禾'], 'description': '交接',
                     'start': 0, 'end': 4, 'source_ids': refs}],
        'changes': [] if previous else [{'state_id': 'KEY', 'before': '林岚', 'after': '阿禾',
                                        'action_id': 'A1', 'source_ids': refs}],
        'audio': [{'id': 'D1', 'speaker': '阿禾', 'mode': 'onscreen', 'text': '我收好了', 'start': 0, 'end': 2}]}]}


def make_run(tmp_path, n=2):
    entries = []
    for i in range(1, n+1):
        ch = chapter(i); path = tmp_path/f'ch{i}.json'; freeze(path, ch)
        entries.append({'index': i, 'sha256': ch['sha256'], 'path': str(path)})
    manifest = tmp_path/'manifest.json'
    freeze(manifest, {**source(n)['manifest'], 'status': 'accessible_catalogue_complete', 'chapters': entries})
    run = tmp_path/'run'
    p.prepare(manifest, run, user_statement='offline fixture', episode_limit=2)
    return run


class Fake:
    def __init__(self, fail=None): self.calls = []; self.fail = fail
    def call(self, role, messages, schema):
        payload = json.loads(messages[1]['content']); self.calls.append((role, payload))
        if self.fail == 'unknown': raise TimeoutError('fixture')
        if 'candidate' in payload:
            value = {'candidate_sha256': payload['candidate_sha256'], 'decision': 'pass', 'issues': [], 'rationale': 'fixture only'}
            if self.fail == 'semantic':
                value.update(decision='revise', issues=[{'owner': 'materials', 'path': '/', 'reason': 'fixture', 'source_ids': ['CH1-P001']}])
        elif 'chapter' in payload: value = material(payload['chapter']['index'])
        elif 'children' in payload: value = bible(payload['required_chapters'])
        elif 'available_chapters' in payload: value = outline(len(payload['available_chapters']))
        elif 'current_scene' in payload:
            value = script(payload['episode'], payload['previous_state'])['scenes'][0]
            value.update(payload['current_scene'])
        else:
            value = script(payload['episode'], payload['previous_state'])
            value['scenes'] = [{k: s[k] for k in c.BRIEF['properties']} for s in value['scenes']]
        native = {'id': f'fixture-{len(self.calls)}', 'model': p.routes()[role]['model'],
                  'usage': {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}}
        message = {'content': json.dumps(value, ensure_ascii=False)}
        if role == 'writer':
            message['tool_calls'] = [{'function': {'name': 'submit_result', 'arguments': message.pop('content')}}]
        native['choices'] = [{'finish_reason': 'tool_calls' if role=='writer' else 'stop', 'message': message}]
        return native


def test_end_to_end_two_variable_duration_episodes(tmp_path):
    run = make_run(tmp_path); fake = Fake(); result = p.execute(run, fixture_client=fake)
    assert result['error'] is None, result
    assert result['simulation'] and result['accepted_episodes']==2
    assert result['state']['status']=='simulation_passed'
    one = read(run/'EPISODE_000_ACCEPTED.json'); two = read(run/'EPISODE_001_ACCEPTED.json')
    assert one['bound']['script']['scenes'][0]['seconds']==30
    assert two['bound']['script']['scenes'][0]['seconds']==35
    assert two['binding']['previous_state_sha256']==digest(one['bound']['end_state'])
    assert len([r for r, _ in fake.calls if r=='director'])==4
    with pytest.raises(ValueError, match='no_replay'): p.execute(run, fixture_client=fake)


@pytest.mark.parametrize('failure', ['unknown', 'semantic'])
def test_failures_preserved_and_not_replayed(tmp_path, failure):
    run = make_run(tmp_path); fake = Fake(failure)
    result = p.execute(run, fixture_client=fake)
    assert result['error'] and not result['production_quality_accepted']
    assert (result['state']['pending'] is not None)==(failure=='unknown')
    with pytest.raises(ValueError, match='no_replay'): p.execute(run, fixture_client=fake)


def test_real_dispatch_requires_authorization_before_start(tmp_path):
    run = make_run(tmp_path)
    with pytest.raises(FileNotFoundError): p.execute(run)
    assert not (run/'START.json').exists()
    assert read(run/'STATE.json')['calls_started']==0


@pytest.mark.parametrize('failure', ['chapter', 'quote', 'coverage', 'claim'])
def test_bad_materials_rejected(failure):
    value = material(1)
    if failure=='chapter': value['chapter_index']=2
    elif failure=='quote': value['claims'][0]['evidence'][0]['quote']='偷了钥匙'
    elif failure=='coverage': value['coverage'][0]['source_id']='CH1-P003'
    else: value['coverage'][0]['claim_ids']=['missing']
    with pytest.raises(ValueError): c.material_valid(value, chapter(1))


@pytest.mark.parametrize('failure', ['missing', 'ending', 'future', 'unread', 'context_only'])
def test_outline_guard(failure):
    value = outline()
    if failure=='missing': value['episodes'].pop()
    elif failure=='ending': value['scope_is_complete_book']=True
    elif failure=='future': value['episodes'][0]['depends_on']=['E2']
    elif failure=='unread': value['episodes'][1]['chapters']=[3]
    else: value['episodes'][1]['source_ids']=['CH1-P001']
    with pytest.raises(ValueError): c.outline_valid(value, source())


def test_source_coverage_can_be_explicitly_omitted_not_silent():
    value = outline(); value['episodes'].pop()
    value['omitted_chapters']=[{'chapter_index': 2, 'reason': '本篇支线暂不改编'}]
    c.outline_valid(value, source())


@pytest.mark.parametrize('failure', ['wrong_before', 'wrong_timeline', 'overwritten', 'absent', 'audio', 'teleport', 'duration'])
def test_script_guard(failure):
    ep = episode(1); raw = script(ep); s = raw['scenes'][0]
    if failure=='wrong_before': s['changes'][0]['before']='柜子'
    elif failure=='wrong_timeline': s['introductions'][-1]['timeline']='MEMORY_1'
    elif failure=='overwritten': s['introductions'].append(deepcopy(s['introductions'][0]))
    elif failure=='absent': s['cast']=['阿禾']
    elif failure=='audio': s['audio'][0]['text']='长'*20
    elif failure=='teleport': s['introductions'][0]['value']='院外'
    else: s['seconds']=26
    with pytest.raises(ValueError): c.script_valid(raw, source(), bible(), ep)


def test_cross_episode_reset_rejected():
    ep = episode(1); one = c.script_valid(script(ep), source(), bible(), ep)
    ep2 = episode(2)
    with pytest.raises(ValueError, match='reintroduced'):
        c.script_valid(script(ep2), source(), bible(), ep2, one['end_state'])


def test_shots_preserve_audio_and_state():
    ep = episode(1, 37); bound = c.script_valid(script(ep), source(), bible(), ep)
    shots = c.split_shots(bound, 15)
    assert sum(s['end']-s['start'] for s in shots)==37
    assert all(s['end']-s['start']<=15 for s in shots)
    assert [x for s in shots for x in s['audio_ids']]==['D1']
    assert shots[-1]['state_after']==bound['end_state']
    assert shots[1]['state_before']==shots[0]['state_after']
    bound['script']['scenes'][0]['actions'][0]['end']=20
    with pytest.raises(ValueError, match='exceeds_model'): c.split_shots(bound, 15)


def test_final_source_restriction_and_dependency_invalidation():
    selected = c.select_source(source(), episode(1))
    b = c.episode_bible(bible(), selected)
    assert b['chapter_indices']==[1]
    assert all(e['source_id']=='CH1-P001' for x in b['claims'] for e in x['evidence'])
    assert c.descendants(outline(4), 'E2')==['E2', 'E3', 'E4']


def test_review_must_bind_real_candidate_path_and_sha():
    candidate = material(1)
    review = {'candidate_sha256': digest(candidate), 'decision': 'revise', 'rationale': 'fixture',
              'issues': [{'owner': 'materials', 'path': '/claims/0/statement', 'reason': 'fixture', 'source_ids': ['CH1-P001']}]}
    c.review_valid(review, candidate, source())
    review['issues'][0]['path']='/claims/9/statement'
    with pytest.raises(ValueError, match='pointer_missing'): c.review_valid(review, candidate, source())
    review.update(candidate_sha256='wrong')
    with pytest.raises(ValueError, match='candidate_changed'): c.review_valid(review, candidate, source())


def test_all_69_chapters_scheduled_in_simulation(tmp_path):
    run = make_run(tmp_path, 69); fake = Fake(); result = p.execute(run, fixture_client=fake)
    assert result['error'] is None, result
    indices = [payload['chapter']['index'] for _, payload in fake.calls if 'chapter' in payload]
    assert indices==list(range(1, 70))
    assert len(read(run/'MATERIALS_BOUND.json')['materials'])==69
    assert read(run/'SERIAL_SCREENPLAY.json')['planned']==69
    assert not read(run/'SERIAL_SCREENPLAY.json')['all_planned_generated']


def test_long_episode_not_limited_to_old_120_seconds():
    ep = episode(1, 240)
    raw = script(ep)
    bound = c.script_valid(raw, source(), bible(), ep)
    shots = c.split_shots(bound, 15)
    assert len(shots)==16
    assert shots[-1]['end']==240


def test_staging_cannot_rewrite_fixed_dialogue():
    ep = episode(1); raw = script(ep)['scenes'][0]
    brief = {k: deepcopy(raw[k]) for k in c.BRIEF['properties']}
    raw['audio'][0]['text']='这是偷来的'
    with pytest.raises(ValueError, match='fixed_story'):
        c.scene_valid(raw, brief, source(), bible(), ep, [])


def test_historical_state_does_not_mutate_current_person():
    ep = episode(1); first = c.script_valid(script(ep), source(), bible(), ep)
    raw = script(episode(2)); scene = raw['scenes'][0]
    scene['timeline']='MEMORY_1'
    for slot in scene['introductions']:
        slot['timeline']='MEMORY_1'; slot['id']='past_'+slot['id']
    scene['changes'][0]['state_id']='past_KEY'
    bound = c.script_valid(raw, source(), bible(), episode(2), first['end_state'])
    assert [s for s in bound['end_state'] if s['timeline']=='CURRENT']==first['end_state']


@pytest.mark.parametrize('field,value', [('chapter_indices', [1]), ('max_calls', 999), ('media', True)])
def test_authorization_must_match_frozen_scope(tmp_path, field, value):
    run = make_run(tmp_path); plan = read(run/'PLAN.json')
    scope = {'plan_sha256': digest(plan), 'source_sha256': plan['source_sha256'],
             'chapter_indices': plan['chapter_indices'], 'destinations': plan['routes'],
             'max_calls': plan['max_calls'], 'media': False, 'publication': False,
             'user_statement': 'fixture approval', 'origin': 'explicit_user_approval'}
    scope[field]=value
    with pytest.raises(ValueError, match='scope_required'): p.authorize(run, scope)
    assert not (run/'AUTHORIZATION.json').exists()


def test_source_tamper_stops_before_any_fixture_call(tmp_path):
    run = make_run(tmp_path); data = read(run/'SOURCE.json')
    data['chapters'][0]['text']='changed'
    (run/'SOURCE.json').write_text(json.dumps(data), encoding='utf-8')
    fake = Fake()
    with pytest.raises(ValueError, match='source_changed'): p.execute(run, fixture_client=fake)
    assert not fake.calls
