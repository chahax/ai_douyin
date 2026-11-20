import json
from copy import deepcopy
import pytest
from src.content_factory import serial_story_contract_v6 as c
from src.content_factory import serial_story_production_v6 as p
from src.content_factory.corpus_screenplay_v1 import read, digest
from test_serial_story_v1 import make_run, source, bible, episode, script, outline, Fake
from test_serial_story_v2 import native_value, set_value


class ScopedFake(Fake):
    required_question = False
    answer_question = False
    def call(self, role, messages, schema):
        payload = json.loads(messages[1]['content'])
        if 'questions_to_resolve' in payload:
            from test_serial_story_v1 import claim
            fact = claim(payload['complete_chapters'][0]['index']); fact['id'] = 'Q_RESOLVED'
            value = {'answers': [{'question_id': 'Q', 'status': 'answered' if self.answer_question else 'unknown',
                                 'claim': fact if self.answer_question else None, 'reason': 'fixture only'}]}
        elif 'stable_identities' in payload:
            ids = [x['index'] for x in payload['complete_chapters']]
            value = {'bible': bible(ids), 'questions': [{'id': 'Q', 'description': '母亲去向不明', 'source_ids': [f'CH{ids[0]}-P001']}]}
        elif 'complete_chapters' in payload and 'episode' not in payload and 'candidate' not in payload:
            value = {'chapter_indices': [x['index'] for x in payload['complete_chapters']], 'analysis': '关系与交接，非验收事实', 'open_questions': ['母亲去向不明']}
        else:
            result = super().call(role, messages, schema)
            value = native_value(result)
            if 'scenes' in value and 'current_scene' not in payload:
                for scene in value['scenes']:
                    scene['required_claim_ids'] = [f"F{payload['episode']['chapters'][0]}"]
                    scene['required_question_ids'] = ['Q'] if self.required_question else []
            return set_value(result, value)
        self.calls.append((role, payload))
        return {'id': f'fixture-{len(self.calls)}', 'model': p.routes()[role]['model'],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20},
                'choices': [{'finish_reason': 'tool_calls', 'message': {'tool_calls': [{'function': {
                    'name': 'submit_result', 'arguments': json.dumps(value, ensure_ascii=False)}}]}}]}


def setup(tmp_path, fake):
    make_run(tmp_path)
    run = tmp_path/'v6'
    p.prepare(tmp_path/'manifest.json', run, user_statement='offline fixture')
    return run, p.execute(run, fixture_client=fake)


def test_unrelated_question_does_not_stop_two_episodes(tmp_path):
    fake = ScopedFake()
    run, result = setup(tmp_path, fake)
    assert result['error'] is None, result
    assert result['accepted_episodes'] == 2
    assert not result['production_quality_accepted']
    assert all('chapter' not in payload for _, payload in fake.calls)
    for _, payload in fake.calls:
        if 'current_scene' in payload:
            assert 'questions' not in payload
            assert not any('母亲' in x['statement'] for x in payload['bible']['claims'])
    with pytest.raises(ValueError, match='no_replay'):
        p.execute(run, fixture_client=fake)


def test_required_question_blocks_only_needed_generation(tmp_path):
    fake = ScopedFake(); fake.required_question = True
    run, result = setup(tmp_path, fake)
    assert result['error']['reason'] == 'episode_has_scoped_blockers'
    assert result['accepted_episodes'] == 0
    assert not any('current_scene' in x for _, x in fake.calls)
    index = read(run/'ARTIFACT_INDEX.json')
    assert 'EPISODE_000_BLOCKED.json' in index


def test_needed_question_lookup_can_resume_scene(tmp_path):
    fake = ScopedFake(); fake.required_question = fake.answer_question = True
    run, result = setup(tmp_path, fake)
    assert result['error'] is None, result
    assert sum('questions_to_resolve' in x for _, x in fake.calls) == 2
    assert result['accepted_episodes'] == 2


def test_unknown_lookup_cannot_smuggle_fact():
    from test_serial_story_v1 import claim
    with pytest.raises(ValueError, match='unknown_answer'):
        c.resolution_valid({'answers':[{'question_id':'Q','status':'unknown','claim':claim(1),'reason':'unclear'}]},
                           [{'id':'Q'}],source())


def test_whole_chapters_preserved():
    src = source(3)
    groups = c.reading_groups(src, len(src['chapters'][0]['text'].encode())+1)
    assert [x for group in groups for x in group] == src['chapters']
    assert len(groups) == 3
    with pytest.raises(ValueError, match='single_complete'):
        c.reading_groups(src, 1)


def test_question_cannot_be_hidden_in_usable_bible():
    v = {'bible': bible(), 'questions': []}
    v['bible']['unresolved'] = ['母亲未知']
    with pytest.raises(ValueError, match='put_unresolved'):
        c.foundation_valid(v, source())


def test_stable_identity_must_not_change():
    v = {'bible': bible(), 'questions': []}
    v['bible']['characters'][0]['id'] = 'new'
    with pytest.raises(ValueError, match='stable_entity_id'):
        c.foundation_valid(v, source(), bible())


def test_missing_fact_dependency_rejected():
    ep = episode(1)
    v = script(ep)
    v['scenes'] = [{**c.plain_brief(s), 'required_claim_ids': ['missing'], 'required_question_ids': []} for s in v['scenes']]
    with pytest.raises(ValueError, match='unknown_scene_dependency'):
        c.draft_valid(v, source(), {'bible': bible(), 'questions': []}, ep)


def test_scope_packet_omits_unrelated_claims():
    brief = {**c.plain_brief(script(episode(1))['scenes'][0]), 'required_claim_ids': ['F1'], 'required_question_ids': []}
    packet = c.scene_packet(brief, {'bible': bible(), 'questions': [{'id': 'Q', 'description': 'unknown'}]})
    assert [f['id'] for f in packet['claims']] == ['F1']
    assert packet['questions'] == []


def test_location_ids_not_arbitrary_prose():
    ep = episode(1); detail = script(ep)['scenes'][0]
    detail['introductions'].append({'id':'OFF','timeline':'CURRENT','kind':'location','subject':'林岚','item':'额外位置','value':'屋内某个地方','source_ids':['CH1-P001']})
    with pytest.raises(ValueError, match='location_value'):
        c.strict_scene_valid(detail, c.plain_brief(detail), source(), bible(), ep, [])


def test_cli_selects_frozen_v6(tmp_path):
    from scripts.run_serial_story import implementation_for
    fake = ScopedFake(); run, result = setup(tmp_path, fake)
    assert implementation_for(run) is p


def test_scope_repair_reuses_reading_and_targets_foundation(tmp_path):
    class Repair(ScopedFake):
        issued = False
        def call(self, role, messages, schema):
            payload = json.loads(messages[1]['content'])
            if 'review_sha256' in payload:
                issue = payload['review']['issues'][0]
                value = {'candidate_sha256':payload['candidate_sha256'], 'review_sha256':payload['review_sha256'],
                         'findings':[{'index':0,'verdict':'upheld','reason':'fixture only','source_ids':['CH1-P001'],'validated_issue':issue}]}
                self.calls.append((role,payload))
                return {'id':f'fixture-{len(self.calls)}','model':p.routes()[role]['model'],
                        'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20},
                        'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[{'function':{
                            'name':'submit_result','arguments':json.dumps(value,ensure_ascii=False)}}]}}]}
            result = super().call(role,messages,schema)
            if 'candidate' in payload and 'scene' in payload['candidate'] and not self.issued:
                value=native_value(result)
                value.update(decision='revise',issues=[{'owner':'bible','path':'/claims/0/statement','reason':'fixture only','source_ids':['CH1-P001']}])
                self.issued=True
                return set_value(result,value)
            if 'stable_identities' in payload and 'required_corrections' in payload:
                value=native_value(result); value['bible']['claims'][0]['statement']='交接钥匙，准确表述'
                return set_value(result,value)
            return result
    fake=Repair(); run,result=setup(tmp_path,fake)
    assert result['error'] is None,result
    reads=[x for _,x in fake.calls if 'complete_chapters' in x and 'episode' not in x and 'candidate' not in x and 'review_sha256' not in x]
    assert len(reads)==1
    invalidations=list((run/'attempts').glob('*/INVALIDATION.json'))
    assert read(invalidations[0])['targets']==['EPISODE_000_FOUNDATION']


def test_blocked_timeline_does_not_discard_independent_scene(tmp_path):
    class Independent(ScopedFake):
        def call(self, role, messages, schema):
            payload=json.loads(messages[1]['content'])
            result=super().call(role,messages,schema); value=native_value(result)
            if 'scenes' in value and 'current_scene' not in payload:
                first=value['scenes'][0]; first['seconds']=10; first['required_question_ids']=['Q']
                second=deepcopy(first); second.update(id='S2',timeline='MEMORY_1',required_question_ids=[])
                value['scenes']=[first,second]
            elif 'current_scene' in payload:
                for slot in value['introductions']:
                    slot['timeline']=value['timeline']
            return set_value(result,value)
    run,result=setup(tmp_path,Independent())
    assert result['error']['reason']=='episode_has_scoped_blockers'
    index=read(run/'ARTIFACT_INDEX.json')
    blocked=read(run/index['EPISODE_000_BLOCKED.json']['path'])
    assert blocked['completed_scene_ids']==['S2']
    assert blocked['episode_accepted'] is False


def test_effort_checkpoint_resume_does_not_repeat_reading(tmp_path):
    make_run(tmp_path); run=tmp_path/'effort'; fake=ScopedFake()
    plan=p.prepare(tmp_path/'manifest.json',run,user_statement='offline',writer_effort='max',
                   writer_max_tokens=65536,reading_checkpoint=True,episode_limit=1)
    result=p.execute(run,fixture_client=fake)
    assert result['state']['status']=='paused'
    assert result['state']['pending'] is None
    calls=result['state']['calls_started']
    assert calls==1
    assert read(run/'CALL_001.json')['max_completion_tokens']==65536
    result=p.execute(run,fixture_client=fake,resume=True)
    assert result['error'] is None,result
    assert result['accepted_episodes']==1
    reading_calls=[x for _,x in fake.calls if 'complete_chapters' in x and 'episode' not in x and 'candidate' not in x]
    assert len(reading_calls)==1
