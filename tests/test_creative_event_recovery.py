from copy import deepcopy
import json
import pytest
from src.content_factory.creative_event_recovery import repair_event_contract
from src.content_factory.creative_event_script import compile_event_script
from src.content_factory.creative_original_prompt import bind_original_prompt
from src.content_factory.creative_workflow import CreativeWorkflow, CREATE_REVIEW_PROFILE
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_creative_workflow import FakeClients

def sample():
    events=[{'kind':'action','speaker':'','text':'甲看向乙。'},
            {'kind':'dialogue','speaker':'甲','text':'今晚我先走。'},
            {'kind':'dialogue','speaker':'乙','text':'你不是每次都留下吗？'},
            {'kind':'action','speaker':'','text':'甲拿起自己的包。'},
            {'kind':'dialogue','speaker':'甲','text':'这次你自己来。'}]
    original={'title':'拒绝','premise':'第一次拒绝','selected_candidate_id':'C01','duration_seconds':12,
        'beats':[{'id':'B01','duration_seconds':12,'event':'拒绝','trigger':'请求','events':events}]}
    corrected=deepcopy(original)
    corrected['beats']=[{**deepcopy(original['beats'][0]),'duration_seconds':7,'events':deepcopy(events[:3])},
                        {**deepcopy(original['beats'][0]),'id':'B02','duration_seconds':5,'events':deepcopy(events[3:])}]
    return original,corrected

def workflow(tmp_path,answer):
    w=CreativeWorkflow(tmp_path,clients=FakeClients([answer]),model_profile=CREATE_REVIEW_PROFILE,
        writer_prompt_version='original_events_v3',review_policy_version='legacy',
        max_calls=5,max_total_tokens=200000,max_contract_repairs=2)
    w.state={'calls_started':0,'contract_repairs_used':0,'stages':[],
             'writer_prompt_binding':bind_original_prompt({'theme':'拒绝'})}
    w._active_stage_name='writer_script'
    return w

def test_event_repair_preserves_all_lines_and_replays_without_another_call(tmp_path):
    original,corrected=sample();w=workflow(tmp_path,corrected)
    result=repair_event_contract(w,'writer_script','writer',{},original,'three lines',lambda v:None)
    assert result==compile_event_script(corrected)
    assert repair_event_contract(w,'writer_script','writer',{},original,'three lines',lambda v:None)==result
    assert w.state['calls_started']==1 and w.state['contract_repairs_used']==1
    record=json.loads((tmp_path/'writer_script__event_contract_repair.json').read_text(encoding='utf-8'))
    assert record['actual_events_preserved'] is True and record['semantic_approval'] is False

def test_event_repair_cannot_drop_dialogue_to_satisfy_schema(tmp_path):
    original,corrected=sample();corrected['beats'][1]['events'][1]['text']='明天再说。'
    w=workflow(tmp_path,corrected)
    with pytest.raises(CreativeContractError,match='改变了实际动作'):
        repair_event_contract(w,'writer_script','writer',{},original,'three lines',lambda v:None)
    assert w.state['calls_started']==1


def test_issue_routing_uses_actual_structured_ids_not_only_B_prefix():
    from src.content_factory.creative_workflow import _issue_beat_ids
    script={'beats':[{'id':'beat_1'},{'id':'beat_3'}]}
    issues=[{'location':'beat_3','proposal':'保持beat_1不变'}]
    assert _issue_beat_ids(script,issues)==['beat_3']
    assert _issue_beat_ids(script,[{'location':'custom_shot'}],{'shots':[{'id':'custom_shot','beat_id':'beat_1'}]})==['beat_1']


def test_revision_recovery_cannot_move_dialogue_into_an_unaccepted_beat():
    from src.content_factory.creative_event_recovery import validate_revision_recovery_scope
    before={'beats':[{'id':'beat_3','events':[{'kind':'dialogue','speaker':'乙','text':'每次都……'}]},
                     {'id':'beat_3b','events':[{'kind':'action','speaker':'','text':'甲拎包。'}]}]}
    after=deepcopy(before)
    after['beats'][1]['events'].insert(0,after['beats'][0]['events'].pop())
    with pytest.raises(CreativeContractError,match='跨拍移动'):
        validate_revision_recovery_scope('writer_revise__01',before,after)
    validate_revision_recovery_scope('writer_script',before,after)

def test_revision_recovery_allows_only_timing_changes_within_existing_beats():
    from src.content_factory.creative_event_recovery import validate_revision_recovery_scope
    before,after=sample();after=deepcopy(before);after['beats'][0]['duration_seconds']=13
    validate_revision_recovery_scope('writer_revise__01',before,after)


def test_exact_location_does_not_hide_explicit_whole_film_timing_scope():
    from src.content_factory.creative_workflow import _issue_beat_ids
    script={'beats':[{'id':'B01'},{'id':'B02'}]}
    assert _issue_beat_ids(script,[{'location':'B01','evidence':'全片总时长超出上限'}])==['B01','B02']
