"""Bounded r2 source-state successors without altering v13 artifacts."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
import test_visual_static_start_planner_v13 as fixtures
from src.content_factory import visual_static_state_repair_v16 as flow


def setup(tmp_path):
    old=fixtures.setup(tmp_path)
    class CameraClient(fixtures.Client):
        def call(self,messages,schema):
            raw=super().call(messages,schema);value=json.loads(raw['text'])
            if 'camera_override' in schema['properties']:
                material=json.loads(messages[1]['content'])['materials']
                value.update(camera_override=material['room']['spatial_layout']['cameras']['front'],camera_design_note='Frames the existing bed and source upper-body posture.')
            raw['text']=json.dumps(value);return raw
    flow.base.plan(old,shot_ids=[r['shot_id'] for r in flow.base.status(old)['plan']['shots']],client=CameraClient());flow.base.selected_plans(old)
    target=dict(shot_id='F0001',instructions='Use the already established open eyes and lying posture.',
        expected_opening_states=[dict(character_id='a',posture='lying_supine',eyes='open')],
        constraints=dict(max_words=220,word_target_only=True,positive_only=True,required_patterns=[r'eyes.{0,25}open'],forbidden_patterns=[r'eyes.{0,25}closed']))
    run=tmp_path/'visual_static_state_repairs_v16'/'trial';flow.prepare(run,old,[target],root_authorization='CPU-only known state successor test, at most two calls.')
    return run,old


class Client:
    def __init__(self,mode='valid'):self.mode=mode;self.calls=[]
    def binding(self):return dict(provider='fixture',model='not-real')
    def call(self,messages,schema):
        self.calls.append(deepcopy(messages));data=json.loads(messages[1]['content']);expected=data['expected_opening_states'];states=[]
        if self.mode=='unknown':raise TimeoutError('No terminal native proof')
        for item in expected:states.append(dict(character_id=item['character_id'],posture=item['posture'],eyes=item['eyes'],held_items=''))
        text='One adult man lies on his back on the old bed, eyes open, with a faintly tense brow and the established gray shirt.'
        if self.mode=='closed' or self.mode=='repair' and len(self.calls)==1:
            states[0]['eyes']='closed';text=text.replace('eyes open','eyes closed')
        return dict(text=json.dumps(dict(visible_cast=[s['character_id'] for s in states],depicted_moment='start',opening_states=states,static_start_prompt=text)),
            completion_known=True,metadata=dict(finish_reason='stop'),native=dict(fixture=True))


def test_source_boundary_separates_completed_history_current_action_and_old_model_summary():
    material=dict(current_shot=dict(id='F2',dynamic_stage_context_only='old kneeling proposal'),
        initial_source_context='original eyes closed',previous_end_state_context_only='old closed summary',
        current_physical_source=[dict(id='U2',text='Alice kneels down.')],
        source_physical_history_before_current_window=[dict(source_id='U1',text='Alice opens her eyes.')])
    before=deepcopy(material);result=flow.base.start_boundary_materials(material)
    assert result['start_boundary']['source_actions_already_happened'][0]['source_id']=='U1'
    assert result['start_boundary']['source_actions_to_begin_after_opening_instant'][0]['id']=='U2'
    assert result['model_proposals_not_source_facts']['dynamic_motion_path']=='old kneeling proposal'
    assert 'dynamic_stage_context_only' not in result['current_shot'] and material==before


def test_r2_is_native_v13_compatible_keeps_camera_and_original_ledger_and_selected_index(tmp_path):
    run,old=setup(tmp_path);before={p:p.read_bytes() for p in [old/'PLAN.json',old/'SELECTED_PLANS.json',old/'CALL_LEDGER.json',old/'plans/F0001.json']}
    client=Client();binding=flow.plan(run,client=client);index=flow.base.stage.files.read(binding['path'])
    row=index['plans'][0];result=flow.base.stage.files.read(row['path']);original=flow.base.stage.files.read(old/'plans/F0001.json')
    assert Path(row['path']).name=='F0001_r2.json' and len(client.calls)==1
    assert flow.verify_plan(row['path']) and flow.base.verify_plan(row['path'])
    assert result['shots'][0].get('camera_override')==original['shots'][0].get('camera_override')
    assert result['shots'][0]['shot_sha256']==original['shots'][0]['shot_sha256']
    assert all(p.read_bytes()==content for p,content in before.items())
    data=json.loads(client.calls[0][1]['content'])
    assert 'source_actions_already_happened' in data['materials']['start_boundary']
    assert index['state_successor_layer']['new_claimed_calls']==1
    flow.plan(run,client=client);assert len(client.calls)==1


def test_wrong_closed_state_can_use_one_known_repair_without_accepting_wrong_first_candidate(tmp_path):
    run,_=setup(tmp_path);client=Client('repair');flow.plan(run,client=client)
    assert len(client.calls)==2 and flow.status(run)['claimed_calls']==2
    assert (run/'calls/F0001/attempt_00/VALIDATION_ERROR.json').exists()
    assert flow.verify_plan(run/'plans/F0001_r2.json')


def test_two_wrong_states_stop_without_more_calls(tmp_path):
    run,_=setup(tmp_path);client=Client('closed')
    with pytest.raises(flow.base.StaticBlocked,match='known_state_successor_validation_failed'):flow.plan(run,client=client)
    assert len(client.calls)==2 and not (run/'plans/F0001_r2.json').exists()


def test_unknown_state_call_not_replayed_and_old_records_preserved(tmp_path):
    run,old=setup(tmp_path);before=(old/'CALL_LEDGER.json').read_bytes();client=Client('unknown')
    with pytest.raises(flow.base.StaticBlocked,match='unknown_state_successor'):flow.plan(run,client=client)
    other=Client()
    with pytest.raises(flow.base.StaticBlocked,match='unknown_state_successor'):flow.plan(run,client=other)
    assert len(client.calls)==1 and not other.calls and (old/'CALL_LEDGER.json').read_bytes()==before


def test_opening_state_actor_alias_or_early_kneel_rejected():
    shot=dict(visible_cast=['a']);scope=dict(characters=[dict(id='a',age_band='adult')])
    target=dict(expected_opening_states=[dict(character_id='a',posture='standing')],constraints=dict(max_words=220,word_target_only=True,positive_only=True,forbidden_patterns=[r'kneel']))
    candidate=dict(visible_cast=['a'],depicted_moment='start',opening_states=[dict(character_id='a',posture='kneeling',eyes='open',held_items='same bag')],static_start_prompt='One adult man kneels in the established room with the same bag.')
    with pytest.raises(flow.base.StaticBlocked,match='expected_initial_state_missing'):flow._check(candidate,shot,scope,target)
    candidate['opening_states'][0]['posture']='standing'
    with pytest.raises(flow.base.StaticBlocked,match='contradicts_initial_state'):flow._check(candidate,shot,scope,target)


def current_index_fixture(tmp_path):
    first,old=setup(tmp_path);binding=flow.plan(first,client=Client());index=flow.base.stage.files.read(binding['path'])
    path=tmp_path/'CURRENT_SELECTION.json';flow.base.stage.files.freeze(path,index)
    target=flow.status(first)['plan']['targets'][0]
    # prepare reconstructs its own frozen parent/source fields.
    target={k:deepcopy(target[k]) for k in ('shot_id','instructions','expected_opening_states','constraints')}
    return old,path,index,target


def test_explicit_current_index_inherits_latest_r2_and_keeps_unrelated_rows(tmp_path):
    old,path,index,target=current_index_fixture(tmp_path);before=path.read_bytes()
    run=tmp_path/'visual_static_state_repairs_v16'/'next'
    selected=dict(path=str(path),sha256=flow.base.stage.files.file_sha(path))
    flow.prepare(run,old,[target],root_authorization='Only this fixture successor, two calls.',selected_index=selected)
    current=next(r for r in index['plans'] if r['shot_id']==target['shot_id'])
    plan=flow.status(run)['plan']
    assert plan['parent_selected']==selected and plan['targets'][0]['parent_static_plan']=={k:current[k] for k in ('path','sha256')}
    assert Path(current['path']).name=='F0001_r2.json'
    result=flow.plan(run,client=Client());assert flow.verify_plan(run/'plans/F0001_r2.json')
    value=flow.base.stage.files.read(result['path'])
    for row in index['plans']:
        if row['shot_id']!=target['shot_id']:assert next(r for r in value['plans'] if r['shot_id']==row['shot_id'])==row
    assert path.read_bytes()==before


@pytest.mark.parametrize('kind',['foreign_source','missing_id','duplicate_id','native_mismatch'])
def test_explicit_index_rejects_foreign_source_incomplete_ids_or_non_native_parent_before_writes(tmp_path,kind):
    old,path,index,target=current_index_fixture(tmp_path)
    if kind=='foreign_source':index['source']=dict(path='foreign-book',sha256='0'*64)
    elif kind=='missing_id':index['plans']=index['plans'][1:]
    elif kind=='duplicate_id':index['plans'].append(deepcopy(index['plans'][0]))
    else:
        row=index['plans'][0];bad=tmp_path/'NOT_NATIVE.json';value=flow.base.stage.files.read(row['path'])
        value['shots'][0]['static_start_prompt']='Changed text without a corresponding native result.'
        flow.base.stage.files.freeze(bad,value);row.update(path=str(bad),sha256=flow.base.stage.files.file_sha(bad))
    flow.base.stage.files.write(path,index);run=tmp_path/'visual_static_state_repairs_v16'/'blocked'
    with pytest.raises(flow.base.StaticBlocked):
        flow.prepare(run,old,[target],root_authorization='No foreign source or old row permitted.',
            selected_index=dict(path=str(path),sha256=flow.base.stage.files.file_sha(path)))
    assert not run.exists()
