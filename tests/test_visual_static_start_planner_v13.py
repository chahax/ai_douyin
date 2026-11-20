"""Bounded real-request orchestration contracts with a CPU fixture client."""
from copy import deepcopy
import json
import hashlib
from pathlib import Path

import pytest
import test_visual_continuous_stage_v6 as stage_test
from src.content_factory import visual_static_start_planner_v13 as flow


def setup(tmp_path):
    origin,_,_=stage_test.setup(tmp_path);flow.stage.plan(origin,client=stage_test.Planner())
    parent=origin/'STAGING_PACKET.json';p=flow.stage.files.read(parent);rows=[]
    for shot in p['shots']:
        out=tmp_path/'scopes'/(shot['id']+'.json');flow.stage.derive_scope(parent,out,purpose='single_shot',shot_id=shot['id'])
        rows.append(dict(id=shot['id'],packet=str(out),packet_sha256=flow.stage.files.file_sha(out)))
    for row,shot in zip(rows,p['shots']):row.update(source_native_frames=shot['source_native_frames'],native_seconds=shot['source_native_frames']/24,asset_run='old_route')
    total=sum(s['source_native_frames'] for s in p['shots'])
    production=tmp_path/'production.json';flow.stage.files.write(production,dict(parent=dict(path=str(parent),sha256=flow.stage.files.file_sha(parent)),source=p['source'],shots=rows,fps=24,source_frame_total=total,source_seconds=total/24))
    run=tmp_path/'visual_static_start_plans_v13'/'trial';flow.prepare(run,production,user_statement='QA static-only authorization')
    return run


class Client:
    def __init__(self,mode='valid'):self.mode=mode;self.calls=[]
    def binding(self):return dict(provider='fixture',model='not_real')
    def call(self,messages,schema):
        self.calls.append(deepcopy(messages));data=json.loads(messages[1]['content'])['materials'];visible=data['current_shot']['visible_cast']
        if self.mode=='unknown':raise TimeoutError('Interrupted without terminal proof')
        prompt='One adult man lies on his back on the worn bed, eyes closed, brows slightly tense, in a head-and-shoulders close-up with a gray cotton shirt.'
        if self.mode=='future':prompt+=' He then stands up.'
        if self.mode=='children':prompt+=' A child is standing beside him.'
        if self.mode=='duplicate':prompt+=' Another man stands beside him.'
        return dict(text=json.dumps(dict(visible_cast=visible,depicted_moment='start',static_start_prompt=prompt)),native=dict(fixture=True),metadata=dict(finish_reason='stop'),completion_known=True)


def test_only_first_frame_by_default_native_prompt_and_original_scope_unchanged(tmp_path):
    run=setup(tmp_path);before={str(p):p.read_bytes() for p in (tmp_path/'scopes').glob('*.json')};client=Client()
    flow.plan(run,client=client)
    assert len(client.calls)==1 and flow.status(run)['state']['completed_shots']==['F0001']
    value=flow.stage.files.read(run/'plans/F0001.json');assert flow.verify_plan(run/'plans/F0001.json')
    assert value['schema']=='first_frame_static_plan/v13' and value['shots'][0]['visible_cast']==['a']
    assert 'camera_override' not in value['shots'][0]
    raw=flow.stage.files.read(run/'calls/F0001/attempt_00/RESULT.json')
    assert value['shots'][0]['static_start_prompt']==raw['static_start_prompt']
    payload=json.loads(client.calls[0][1]['content'])['materials'];encoded=json.dumps(payload)
    assert '"audio"' not in encoded and 'audio_fixed' not in encoded and 'hello' not in encoded
    assert before=={str(p):p.read_bytes() for p in (tmp_path/'scopes').glob('*.json')}
    flow.plan(run,client=client);assert len(client.calls)==1


def test_unknown_call_not_replayed_or_repaired(tmp_path):
    run=setup(tmp_path);one=Client('unknown')
    with pytest.raises(flow.StaticBlocked,match='unknown_static_call'):flow.plan(run,client=one)
    two=Client()
    with pytest.raises(flow.StaticBlocked,match='unknown_static_call'):flow.plan(run,client=two)
    assert len(one.calls)==1 and not two.calls and flow.status(run)['claimed_calls']==1


@pytest.mark.parametrize('mode',['future','duplicate'])
def test_dynamic_sequence_or_duplicate_body_is_bounded_by_two_global_repairs(tmp_path,mode):
    run=setup(tmp_path);client=Client(mode)
    with pytest.raises(flow.StaticBlocked,match='known_static_validation_failed'):flow.plan(run,client=client)
    assert len(client.calls)==3 and flow.status(run)['claimed_calls']==3
    # The next shot cannot take any more repair calls, even with primary slots left.
    with pytest.raises(flow.StaticBlocked,match='global_text_budget_exhausted'):
        flow.plan(run,shot_ids=['F0002'],client=client)
    assert len(client.calls)==4


def test_total29_claims_prevents_any_new_request(tmp_path):
    run=setup(tmp_path)
    for n in range(29):flow.stage.files.write(run/'calls'/f'old_{n}'/'attempt_00/CLAIM.json',dict(id=n))
    client=Client()
    with pytest.raises(flow.StaticBlocked,match='global_text_budget_exhausted'):flow.plan(run,client=client)
    assert not client.calls


def test_adult_scope_cannot_output_an_unseen_child():
    scope=dict(characters=[dict(id='a',age_band='adult')]);shot=dict(visible_cast=['a'])
    candidate=dict(static_start_prompt='One adult man rests on a bed. A child is standing beside him.')
    with pytest.raises(flow.StaticBlocked,match='nonvisible_child'):flow._check(candidate,shot,scope)


def test_one_known_local_successor_preserves_primary_and_uses_repair_budget(tmp_path):
    run=setup(tmp_path);flow.plan(run,client=Client());original=run/'plans/F0001.json';before=original.read_bytes();client=Client()
    result=flow.repair_static(run,'F0001',instructions='Keep only a positive short upper-body still.',constraints=dict(max_words=150,positive_only=True,forbidden_terms=['trousers','feet']),client=client)
    assert result.name=='F0001_r1.json' and flow.verify_plan(result) and original.read_bytes()==before
    assert len(client.calls)==1 and flow.status(run)['claimed_calls']==2
    flow.repair_static(run,'F0001',instructions='Keep only a positive short upper-body still.',constraints=dict(max_words=150,positive_only=True,forbidden_terms=['trousers','feet']),client=client)
    assert len(client.calls)==1


def test_nonfirst_model_response_selects_camera_in_same_request(tmp_path):
    run=setup(tmp_path)
    class CameraClient(Client):
        def call(self,messages,schema):
            raw=super().call(messages,schema);value=json.loads(raw['text']);data=json.loads(messages[1]['content'])['materials']
            value.update(camera_override=data['room']['spatial_layout']['cameras']['front'],camera_design_note='Frames the existing bed and the opening upper-body posture.')
            raw['text']=json.dumps(value);return raw
    client=CameraClient();flow.plan(run,shot_ids=['F0002'],client=client)
    value=flow.stage.files.read(run/'plans/F0002.json')
    assert len(client.calls)==1 and flow.verify_plan(run/'plans/F0002.json')
    assert 'camera_override' in value['shots'][0] and 'camera_geometry_review' in value['planning_provenance']
    assert value['planning_provenance']['camera_geometry_review']['real_image_review_required'] is True


@pytest.mark.parametrize('mode',['outside','inside','nonfinite'])
def test_camera_illegal_bounds_furniture_or_nonfinite_rejected(tmp_path,mode):
    run=setup(tmp_path);p=flow.status(run)['plan'];scope=flow.stage.files.read(p['shots'][0]['packet']['path']);shot=scope['shots'][0]
    camera=deepcopy(scope['places'][0]['spatial_layout']['cameras']['front'])
    if mode=='outside':camera['eye']=[100,1,1]
    elif mode=='inside':camera['eye']=[1.5,3,.5]
    else:camera['eye'][0]=float('nan')
    candidate=dict(static_start_prompt='One person on the existing bed in an upper-body close view.',camera_override=camera)
    with pytest.raises(ValueError,match='static_frame_camera'):flow.camera_report(scope,shot,candidate)


def test_routing_successor_allowed_but_packet_and_clock_changes_rejected(tmp_path):
    run=setup(tmp_path);flow.plan(run,client=Client());p=flow.status(run)['plan'];path=Path(p['production_plan']['path']);routing=flow.stage.files.read(path)
    routing['shots'][0]['asset_run']='explicit_successor_route';flow.stage.files.write(path,routing)
    assert flow.status(run)['routing_changed'] is True and flow.verify_plan(run/'plans/F0001.json')
    good=deepcopy(routing);routing['shots'][0]['source_native_frames']+=17;flow.stage.files.write(path,routing)
    with pytest.raises(flow.StaticBlocked,match='routing_changed_source_clock'):flow.status(run)
    routing=deepcopy(good);routing['shots'][0]['packet_sha256']='different_model_input';flow.stage.files.write(path,routing)
    with pytest.raises(flow.StaticBlocked,match='routing_changed_static_packet'):flow.status(run)


def test_english_typographic_punctuation_is_revalidated_without_rewriting_raw():
    schema=flow.response_schema(['a']);old=deepcopy(schema)
    old['properties']['static_start_prompt']['pattern']=flow.ASCII_PATTERN
    candidate=dict(visible_cast=['a'],depicted_moment='start',static_start_prompt='One adult man’s eyes are closed while he rests on the old bed.')
    before=json.dumps(candidate,ensure_ascii=False)
    proof=flow._validate_native_schema(candidate,old)
    assert proof['native_text_unchanged'] is True and proof['original_schema_sha256']!=proof['revised_schema_sha256']
    assert json.dumps(candidate,ensure_ascii=False)==before and old['properties']['static_start_prompt']['pattern']==flow.ASCII_PATTERN
    candidate['static_start_prompt']='One adult man 躺在床上 with eyes closed and a calm expression.'
    with pytest.raises(Exception):flow._validate_native_schema(candidate,old)


def test_nonfirst_word_target_is_soft_without_loosening_first_sample_limit():
    scope=dict(characters=[dict(id='a',age_band='adult')]);shot=dict(visible_cast=['a'])
    text='One adult man rests on the bed. '+'calm '*145
    candidate=dict(static_start_prompt=text)
    flow._check(candidate,shot,scope,dict(max_words=220,soft_target_words=150,positive_only=True))
    with pytest.raises(flow.StaticBlocked,match='word_budget_exceeded'):flow._check(candidate,shot,scope,dict(max_words=150,positive_only=True))
    candidate['static_start_prompt']='One adult man rests on the bed. '+'calm '*220
    flow._check(candidate,shot,scope,dict(max_words=220,soft_target_words=150,word_target_only=True,positive_only=True))


def test_physical_history_is_exact_ordered_same_scene_and_excludes_future_transfer():
    text='Alice holds a key. Another room. Current pause. Alice gives the key to Bob.'
    chunks=['Alice holds a key.','Another room.','Current pause.','Alice gives the key to Bob.']
    segments=[];parts=[]
    for n,chunk in enumerate(chunks,1):
        start=text.index(chunk);end=start+len(chunk);scene='S2' if n==2 else 'S1'
        segments.append(dict(id=f'F{n}',scene=scene,units=[dict(id=f'U{n}',parent=f'P{n}',start=start,end=end)]))
        if scene=='S1':parts.append(dict(start=start,end=end))
    history=flow._physical_history(text,segments,dict(id='S1',physical_actions=parts),'F3')
    assert [h['source_id'] for h in history]==['U1'] and 'gives' not in history[0]['text']
    assert history[0]['text']==text[history[0]['start']:history[0]['end']]
    assert history[0]['sha256']==hashlib.sha256(history[0]['text'].encode()).hexdigest()


def test_explicit_extension_preserves_original_plan_and_limits_to_known_successors(tmp_path):
    run=setup(tmp_path);flow.plan(run,client=Client());original=(run/'PLAN.json').read_bytes()
    status=flow.authorize_extension(run,['F0001'],root_authorization='Explicit bounded QA known successor authorization.')
    assert status['effective_max_calls']==30 and (run/'PLAN.json').read_bytes()==original
    with pytest.raises(flow.StaticBlocked,match='successor_slot_already_used'):
        flow.authorize_extension(run,['F0001'],root_authorization='Not a second slot for the same original.')
    flow.stage.files.write(run/'calls/unknown/attempt_00/CLAIM.json',dict(unknown=True))
    with pytest.raises(flow.StaticBlocked,match='unresolved_call'):
        flow.authorize_extension(run,['F0002'],root_authorization='Must not reallocate unknown.')


def test_successor_does_not_inherit_old_response_word_count_annotation(tmp_path):
    run=setup(tmp_path)
    class LongCameraClient(Client):
        def call(self,messages,schema):
            raw=super().call(messages,schema);value=json.loads(raw['text'])
            data=json.loads(messages[1]['content'])['materials']
            value.update(camera_override=data['room']['spatial_layout']['cameras']['front'],
                camera_design_note='Frames the existing bed and opening upper-body posture.')
            value['static_start_prompt']+=' Natural subtle fabric texture.'*38
            raw['text']=json.dumps(value);return raw
    flow.plan(run,shot_ids=['F0002'],client=LongCameraClient())
    original=run/'plans/F0002.json';before=original.read_bytes()
    assert flow.stage.files.read(original)['planning_provenance']['word_target_overrun']['actual_words']>150
    successor=flow.repair_static(run,'F0002',instructions='Keep the same positive opening with a short prompt.',
        constraints=dict(max_words=220,soft_target_words=150,word_target_only=True,positive_only=True),client=Client())
    result=flow.stage.files.read(successor)
    assert 'word_target_overrun' not in result['planning_provenance']
    assert result['planning_provenance']['camera_inherited_from_parent'] is True
    assert original.read_bytes()==before and flow.verify_plan(successor)
