"""Structured successor scope, source-state and immutable-original regressions."""
import json
from copy import deepcopy
from pathlib import Path
import pytest
import test_visual_continuous_stage_v6 as stage_test
from src.content_factory import visual_continuous_repair_v6 as flow


class RepairClient:
    def __init__(self,mode='valid'):self.calls=[];self.mode=mode
    def binding(self):return dict(provider='fixture_only',model='not_a_real_model')
    def call(self,messages,schema):
        self.calls.append(messages);data=json.loads(messages[1]['content'])['materials'];ledger=data['current_physical_ledger']
        actors=[]
        for case in schema['properties']['actors']['items']['oneOf']:
            props=case['properties'];cid=props['id']['const'];pose=props['pose'].get('const',props['pose'].get('enum',['standing'])[0])
            actors.append(dict(id=cid,pose=pose,expression='pensive',action='手指轻轻收紧，视线自然落下。',visible_injury=props['visible_injury']['const']))
        candidate=dict(id=data['id'],place_view='front',actors=actors,source_ids=[schema['properties']['source_ids']['items']['enum'][0]])
        if self.mode=='injury':candidate['actors'][0]['action']='眼周出现青紫肿胀。'
        if self.mode=='extra_name':candidate['actors'][0]['action']='Bob走到身边。'
        if self.mode=='unknown':raise TimeoutError('Interrupted')
        return dict(text=json.dumps(candidate),native=dict(fixture=True),metadata=dict(finish_reason='stop'),completion_known=True)


def setup(tmp_path):
    run,_,_=stage_test.setup(tmp_path);flow.stage.plan(run,client=stage_test.Planner())
    repair=tmp_path/'visual_continuous_stage_repairs_v6'/'successor'
    return run,repair


def test_successor_only_changes_declared_visuals_and_preserves_native_source_audio(tmp_path):
    run,repair=setup(tmp_path);path=run/'STAGING_PACKET.json';before={str(p):p.read_bytes() for p in run.rglob('*') if p.is_file()};client=RepairClient()
    value=flow.repair(repair,path,{'F0001':['Correct current physical state only.']},user_statement='Authorized bounded visual successor.',client=client)
    assert len(client.calls)==1 and flow.stage.validate_packet(value)
    original=flow.stage.packet(run)
    assert value['shots'][1:]==original['shots'][1:]
    assert value['shots'][0]['audio']==original['shots'][0]['audio']
    assert value['shots'][0]['visual_prompt']!=original['shots'][0]['visual_prompt']
    assert before=={str(p):p.read_bytes() for p in run.rglob('*') if p.is_file()}
    assert value['shots'][0]['staging_provenance']==original['shots'][0]['staging_provenance']


@pytest.mark.parametrize('mode',['injury','extra_name'])
def test_unfounded_wound_or_nonvisible_named_actor_is_rejected(tmp_path,mode):
    run,repair=setup(tmp_path);client=RepairClient(mode)
    with pytest.raises(flow.stage.StageBlocked,match='known_successor_validation_failed'):
        flow.repair(repair,run/'STAGING_PACKET.json',{'F0001':['Fix visual state.']},user_statement='QA',client=client)
    assert len(client.calls)==2 and not (repair/'REPAIRED_PACKET.json').exists()


def test_unknown_successor_is_not_replayed(tmp_path):
    run,repair=setup(tmp_path);client=RepairClient('unknown')
    with pytest.raises(flow.stage.StageBlocked,match='unknown_successor'):flow.repair(repair,run/'STAGING_PACKET.json',{'F0001':['QA']},user_statement='QA',client=client)
    other=RepairClient()
    with pytest.raises(flow.stage.StageBlocked,match='unknown_successor'):flow.repair(repair,run/'STAGING_PACKET.json',{'F0001':['QA']},user_statement='QA',client=other)
    assert len(client.calls)==1 and not other.calls


def test_narration_does_not_change_pose_source_state(tmp_path):
    run,repair=setup(tmp_path);plan=flow.stage.status(run)['plan']
    ledger=flow.physical_ledger(plan,'F0001')
    assert ledger['source_current_physical_state']['a']['pose']=='lying'
    assert not ledger['visible_injury_source_ids'].get('a')


def test_caregiver_touching_named_patients_bruise_is_not_a_caregiver_injury():
    candidate=dict(actors=[dict(id='carer',visible_injury='none',action='一手扶住孩子的胳膊，另一手用棉签蘸取碘酒，轻轻点在青紫痕迹上。'),
        dict(id='patient',visible_injury='source_body_bruises',action='肩膀微微绷紧。')])
    ledger=dict(names={'carer':'护理者','patient':'孩子'},pure_voice_window=False)
    flow._check(candidate,dict(visible_cast=['carer','patient']),ledger)
    candidate['actors'][0]['action']='自己的眼周青紫肿胀，一手扶住孩子擦碘酒。'
    with pytest.raises(flow.stage.StageBlocked,match='unfounded_current_visible_injury'):flow._check(candidate,dict(visible_cast=['carer','patient']),ledger)


def test_explicit_source_pose_event_must_be_rendered():
    value=dict(actors=[dict(id='child',pose='standing',visible_injury='none',action='转身跑开。')])
    ledger=dict(names={'child':'孩子'},pure_voice_window=False)
    with pytest.raises(flow.stage.StageBlocked,match='required_current_source_pose_missing'):
        flow._check(value,dict(visible_cast=['child']),ledger,[dict(actor_id='child',pose='kneeling')])
    value['actors'][0]['action']='先跪倒在地，随后转身跑开。'
    flow._check(value,dict(visible_cast=['child']),ledger,[dict(actor_id='child',pose='kneeling')])


def test_readonly_exact_scope_derivatives_keep_parent_bytes_and_audio_clock(tmp_path):
    run,_=setup(tmp_path);parent=run/'STAGING_PACKET.json';before=parent.read_bytes()
    bg=flow.stage.derive_scope(parent,tmp_path/'backgrounds.json',purpose='backgrounds')
    assert bg['shots']==[] and bg['characters']==[] and flow.stage.validate_packet(bg)
    one=flow.stage.derive_scope(parent,tmp_path/'single.json',purpose='single_shot',shot_id='F0002')
    original=flow.stage.packet(run);shot=next(s for s in original['shots'] if s['id']=='F0002')
    assert one['shots']==[shot] and flow.stage.validate_packet(one) and parent.read_bytes()==before
    assert one['style_groups']==original['style_groups'] and len(one['places'])==len(original['places'])
    one['shots'][0]['audio'][0]['text']='Modified'
    with pytest.raises(flow.stage.StageBlocked,match='stage_scope_changes'):flow.stage.validate_packet(one)
