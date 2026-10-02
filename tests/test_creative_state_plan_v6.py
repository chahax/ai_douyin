from copy import deepcopy
import pytest
from src.content_factory.creative_state_plan_v6 import validate_state_plan,compile_state_plan,VERSION
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_creative_static_visual_manifest import manifest


def sample():
    script={'beats':[{'id':'B1','duration_seconds':10,'event':'拿起文件夹','dialogue':[{'speaker':'陈禾','text':'明天见。'}]},
                     {'id':'B2','duration_seconds':10,'event':'坐下','dialogue':[]}]}
    state={'C01':{'posture':'standing','position':'桌前两步','gaze':'C02','affect':'平静'},
           'C02':{'posture':'standing','position':'桌旁','gaze':'C01','affect':'平静'},
           'P01':{'holder':'none','location':'桌面'}}
    def row(bid,action,changes,dialogue):
        return {'beat_id':bid,'purpose':'关系有新的变化','composition':'固定双人中景留出行动空间','camera':'固定单机位',
                'dialogue_mode':'画内对白' if dialogue else '无对白','cut_reason':'反应已可见','reaction_window':{'start':5,'end':8,'subject':'C01','meaning':'听到回答后松肩'},
                'events':[{'start':0,'end':2,'action':action,'changes':changes}], 'dialogue_windows':dialogue}
    plan={'schema':VERSION,'initial_state':state,'beats':[
        row('B1','陈禾拿起文件夹',[{'entity':'P01','field':'holder','from':'none','to':'C02'},
                                 {'entity':'P01','field':'location','from':'桌面','to':'右手'}],[{'start':2,'end':4}]),
        row('B2','陈禾坐下',[{'entity':'C02','field':'posture','from':'standing','to':'sitting'}],[])]}
    return plan,script,manifest()


def test_cross_beat_state_is_derived_and_original_immutable():
    p,s,m=sample(); original=deepcopy(p);result=compile_state_plan(p,s,m)
    assert p==original
    assert result['shots'][0]['end_state']==result['shots'][1]['start_state']
    assert 'sitting' not in result['shots'][1]['start_state']
    assert 'sitting' in result['shots'][1]['end_state']
    assert result['shots'][0]['dialogue_lock']==s['beats'][0]['dialogue']
    assert '对白2–4秒' in result['shots'][0]['visible_performance']


def test_later_sitting_precondition_rejects_already_sitting():
    p,s,m=sample();p['initial_state']['C02']['posture']='sitting'
    with pytest.raises(CreativeContractError,match='from与当时状态'): validate_state_plan(p,s,m)


def test_dialogue_window_not_whole_shot_controls_rate():
    p,s,m=sample();p['beats'][0]['dialogue_windows'][0]={'start':2,'end':2.1}
    with pytest.raises(CreativeContractError,match='对白'): validate_state_plan(p,s,m)


def test_state_does_not_pretend_to_interpret_action_semantics():
    p,s,m=sample();p['beats'][0]['events'][0]['action']='陈禾忽然坐下（与changes冲突，必须真实审核）'
    validate_state_plan(p,s,m)  # Intentional: typed state checks cannot prove prose correctness.
    assert '冲突' in compile_state_plan(p,s,m)['shots'][0]['visible_performance']


@pytest.mark.parametrize('field,value',[('holder','C99'),('location','')])
def test_invalid_prop_changes(field,value):
    p,s,m=sample();change=p['beats'][0]['events'][0]['changes'][0 if field=='holder' else 1];change['to']=value
    with pytest.raises(CreativeContractError): validate_state_plan(p,s,m)


def test_noop_transition_cannot_fake_action():
    p,s,m=sample();p['beats'][1]['events'][0]['changes'][0]['to']='standing'
    with pytest.raises(CreativeContractError,match='伪变化'): validate_state_plan(p,s,m)
