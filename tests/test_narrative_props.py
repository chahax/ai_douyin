from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.contracts import digest
from src.content_factory.novel_adaptation.narrative_presence import replay


def fixture():
    candidate={'scenes':[{'id':'S','place':'kitchen','entry_continuity':'甲在厨房。',
        'exit_continuity':'甲仍在厨房。','segments':[
        {'id':'B','action':'甲从盆中取出白菜。','camera':'白菜特写。',
         'continuity_obligations':[],'visible_people':['a'],'audio':[]}]}]}
    presence={'candidate_sha256':digest(candidate),'initial_locations':{'a':'kitchen'},
              'segments':[{'id':'B','moves':[]}],'uncertainties':[]}
    plan={'places':[{'id':'kitchen'}],'scenes':[{'id':'S','place':'kitchen'}],
          'initial_locations':{'a':'kitchen'},'container_actions':True,
          'props':[{'id':p,'owner':'kitchen'} for p in ('cabbage','basin','board')],
          'containers':{'cabbage':'basin'}}
    props={'candidate_sha256':digest(candidate),'plan_sha256':digest(plan),
           'segments':[{'id':'B','events':[{'kind':'unpacks','event':{
               'actor':'a','prop':'cabbage','container':'basin','destination':'a'},
               'evidence_ids':['B:action:0']}],
               'action_order':[{'field':'unpacks','index':0}]}], 'uncertainties':[]}
    return candidate,presence,plan,props


def run(c,p,plan,props):
    return replay(c,p,['a'],['kitchen'],prop_plan=plan,prop_projection=props)


def test_explicit_removal_uses_existing_container_engine_without_editing_prose():
    c,p,plan,props=fixture();before=deepcopy((c,p,plan,props));r=run(c,p,plan,props)
    assert r['end_state']['props']['cabbage']=='a'
    assert 'cabbage' not in r['end_state']['containers']
    assert r['prop_evidence_receipts'][0]['resolved_evidence'][0]['text']=='甲从盆中取出白菜。'
    assert (c,p,plan,props)==before


def test_scene_entry_can_establish_first_posture_but_not_authorize_other_actions():
    c,p,plan,props=fixture();c['scenes'][0]['entry_continuity']='甲站在厨房。'
    p['candidate_sha256']=props['candidate_sha256']=digest(c)
    row=props['segments'][0]
    row['events']=[{'kind':'gestures','event':{'actor':'a','target':'kitchen','verb':'甲站在厨房',
        'posture_change':{'before':'unknown','after':'standing','participants':['a']}},
        'evidence_ids':['B:entry_continuity:0']}]
    row['action_order']=[{'field':'gestures','index':0}]
    assert run(c,p,plan,props)['end_state']['postures']['a']=='standing'
    row['events'][0]['event'].pop('posture_change')
    with pytest.raises(ValueError,match='requires_action_evidence'):run(c,p,plan,props)


@pytest.mark.parametrize('case',['wrong_container','stale','missing_order','camera_only','wrong_initial','missing_pair'])
def test_bad_prop_continuity_or_binding_rejected(case):
    c,p,plan,props=fixture()
    if case=='wrong_container':props['segments'][0]['events'][0]['event']['container']='board'
    elif case=='stale':c['scenes'][0]['segments'][0]['action']='稿已更改'
    elif case=='missing_order':props['segments'][0]['action_order']=[]
    elif case=='camera_only':props['segments'][0]['events'][0]['evidence_ids']=['B:camera:0']
    elif case=='wrong_initial':
        plan['initial_locations']['a']='elsewhere';props['plan_sha256']=digest(plan)
    elif case=='missing_pair':props=None
    with pytest.raises(ValueError):run(c,p,plan,props)


def test_missing_events_not_claimed_as_full_prop_acceptance():
    c,p,plan,props=fixture();props['segments'][0].update(events=[],action_order=[])
    r=run(c,p,plan,props)
    assert r['end_state']['containers']['cabbage']=='basin'
    assert 'not_semantic_acceptance' in r['status']
    assert any('omissions' in text for text in r['limits'])


def test_program_binding_rejects_changed_plan_and_does_not_trust_model_hash():
    from src.content_factory.novel_adaptation.narrative_props import bind_body
    c,p,plan,props=fixture();body=deepcopy(props)
    identity={key:body.pop(key) for key in ('candidate_sha256','plan_sha256')}
    entities={'entities':[{'id':'a','kind':'character'}]}
    assert bind_body(c,plan,body,identity,entities)==props
    altered=deepcopy(plan);altered['containers']={}
    with pytest.raises(ValueError):bind_body(c,altered,body,identity,entities)
    with pytest.raises(ValueError):bind_body(c,plan,props,identity,entities)


def test_absent_audio_anchor_cannot_execute_prop_event():
    c,p,plan,props=fixture()
    props['segments'][0]['events'][0]['event'].update(phase='after_audio',after_audio_index=0)
    with pytest.raises(ValueError,match='transition_audio_anchor_missing'):run(c,p,plan,props)


def test_cross_segment_evidence_does_not_authorize_prop_movement():
    c,p,plan,props=fixture()
    second=deepcopy(c['scenes'][0]['segments'][0]);second['id']='C'
    c['scenes'][0]['segments'].append(second)
    p['candidate_sha256']=props['candidate_sha256']=digest(c)
    p['segments'].append({'id':'C','moves':[]})
    props['segments'].append({'id':'C','events':[],'action_order':[]})
    props['segments'][0]['events'][0]['evidence_ids']=['C:action:0']
    with pytest.raises(ValueError,match='prop_evidence_wrong_segment'):run(c,p,plan,props)


def test_consumption_runs_through_combined_projection_and_cannot_be_reused():
    c,p,plan,props=fixture()
    c['scenes'][0]['segments'][0]['action']='甲从盆里吃掉白菜。'
    p['candidate_sha256']=props['candidate_sha256']=digest(c)
    plan.update(allow_consumption_recipes=True,action_contract_version=2,recipes=[{
        'id':'eat','kind':'consumption','inputs':['cabbage'],'outputs':[],
        'retained_inputs':[],'input_containers':{'cabbage':'basin'},'source_ids':['CH1-P001']}])
    props['plan_sha256']=digest(plan)
    props['segments'][0]={'id':'B','events':[{'kind':'transforms','event':{
        'actor':'a','recipe':'eat','destination':'kitchen','completion_action':'甲从盆里吃掉白菜。'},
        'evidence_ids':['B:action:0']}],'action_order':[{'field':'transforms','index':0}]}
    result=run(c,p,plan,props)
    assert result['end_state']['prop_status']['cabbage']=='consumed'
    assert result['end_state']['prop_status']['basin']=='present'
    props['segments'][0]['events'].append({'kind':'prop_uses','event':{'prop':'cabbage','holder':'kitchen'},
                                         'evidence_ids':['B:action:0']})
    props['segments'][0]['action_order'].append({'field':'prop_uses','index':0})
    with pytest.raises(ValueError,match='prop_not_present'):run(c,p,plan,props)


def test_replay_error_retains_exact_prop_and_safe_presegment_state():
    from src.content_factory.novel_adaptation.narrative_presence import error_record
    c,p,plan,props=fixture()
    props['segments'][0]['events'][0]['event']['container']='board'
    with pytest.raises(ValueError) as caught:run(c,p,plan,props)
    report=error_record(caught.value)
    assert report['issues'][0]['code']=='unpack_wrong_container'
    diagnostic=report['replay_diagnostic']
    assert diagnostic['failed_segment_id']=='B' and diagnostic['completed_segment_count']==0
    assert diagnostic['state_before_failed_segment']['containers']['cabbage']=='basin'
    assert diagnostic['attempted_events']['unpacks'][0]['prop']=='cabbage'
    assert diagnostic['partial_after_state_accepted'] is False
