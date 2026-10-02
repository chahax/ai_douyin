from copy import deepcopy
import pytest
from tests.test_creative_state_plan_v2 import sample as old_sample
from src.content_factory.creative_action_plan_v1 import (VERSION,schedule_action_plan,compile_action_plan,build_action_plan_schema)
from src.content_factory.creative_state_plan_v6 import build_state_plan_prompt,build_state_plan_schema,validate_state_plan,compile_state_plan
from src.content_factory.creative_segmented_director import bind_segmented_director
from src.content_factory.creative_workflow_contract import CreativeContractError


def sample():
    prior,script,manifest=old_sample()
    result={'schema':VERSION,'initial_state':deepcopy(prior['initial_state']),'beats':[]}
    for i,old in enumerate(prior['beats']):
        row={k:deepcopy(old[k]) for k in ['beat_id','purpose','composition','camera','dialogue_mode','cut_reason']}
        group={'id':f'A{i+1}','script_slot':'before' if i==0 else 'after','kind':'action','duration_seconds':1,
            'hold_subject':'','performance':'自然完成既定动作','operations':deepcopy(old['events'][0]['operations'])}
        row.update(groups=[group],dialogue_performance='原说话人自然说出原对白，面部可读',
            reaction={'anchor':group['id'],'subject':'C01','meaning':'可见反应'})
        result['beats'].append(row)
    return result,script,manifest


def test_complete_plan_is_scheduled_without_mutating_script_or_actions():
    plan,script,manifest=sample();before=deepcopy((plan,script,manifest))
    scheduled,report=schedule_action_plan(plan,script,manifest)
    assert (plan,script,manifest)==before
    shots=compile_action_plan(plan,script,manifest)
    assert shots['shots'][0]['dialogue_lock']==script['beats'][0]['dialogue']
    assert shots['shots'][0]['end_state']==shots['shots'][1]['start_state']
    assert scheduled['beats'][0]['dialogue_windows'][0]['start']==1
    assert report['beats'][0]['preferred_dialogue_seconds']==report['beats'][0]['actual_dialogue_seconds']


def test_hold_starts_after_action_completion_and_is_never_compressed():
    plan,script,manifest=sample()
    hold={'id':'H1','script_slot':'before','kind':'hold','duration_seconds':2,'hold_subject':'C01',
        'performance':'保持已经建立的对视两秒','operations':[]}
    plan['beats'][0]['groups'].append(hold)
    plan['beats'][0]['reaction']['anchor']='H1'
    scheduled,report=schedule_action_plan(plan,script,manifest)
    row=scheduled['beats'][0]
    assert row['events'][0]['end']==1
    assert row['events'][1]['start']==1 and row['events'][1]['end']==3
    assert row['reaction_window']['start']==1 and row['reaction_window']['end']==3
    assert row['dialogue_windows'][0]['start']==3


def test_only_dialogue_compresses_within_five_unit_limit():
    plan,script,manifest=sample()
    plan['beats'][0]['groups'][0]['duration_seconds']=7
    script['beats'][0]['dialogue'][0]['text']='一二三四五六七八九十'
    scheduled,report=schedule_action_plan(plan,script,manifest)
    row=report['beats'][0]
    assert row['preferred_dialogue_seconds'][0]>row['actual_dialogue_seconds'][0]
    assert row['actual_dialogue_seconds'][0]==3
    assert scheduled['beats'][0]['events'][0]['end']==7


def test_impossible_budget_has_exact_shortfall_and_preserves_durations():
    plan,script,manifest=sample();plan['beats'][0]['groups'][0]['duration_seconds']=9
    script['beats'][0]['dialogue'][0]['text']='一二三四五六七八九十'
    before=deepcopy(plan)
    with pytest.raises(CreativeContractError,match='shortfall_seconds.*1.0'):
        schedule_action_plan(plan,script,manifest)
    assert plan==before


@pytest.mark.parametrize('kind',['missing_anchor','duplicate_id','hold_operations','already_holding','phase_order'])
def test_invalid_action_plan_fails_before_review(kind):
    plan,script,manifest=sample()
    if kind=='missing_anchor': plan['beats'][0]['reaction']['anchor']='absent'
    elif kind=='duplicate_id': plan['beats'][1]['groups'][0]['id']='A1'
    elif kind=='hold_operations': plan['beats'][0]['groups'][0].update(kind='hold',hold_subject='C01')
    elif kind=='already_holding': plan['initial_state']['P01']['holder']='C02'
    elif kind=='phase_order':
        group=deepcopy(plan['beats'][0]['groups'][0]);group['id']='A3'
        plan['beats'][0]['groups'][0]['script_slot']='after';plan['beats'][0]['groups'].append(group)
    with pytest.raises(CreativeContractError): schedule_action_plan(plan,script,manifest)


def test_new_dispatch_and_schema_are_opt_in_and_complete():
    import jsonschema
    plan,script,manifest=sample()
    context={'state_plan_version':VERSION,'script':script,'static_visual_manifest':manifest}
    jsonschema.validate(plan,build_state_plan_schema(context))
    assert '不生成任何start/end' in build_state_plan_prompt(context)
    binding=bind_segmented_director(state_plan=True,state_plan_version=VERSION,plan_thinking_mode='disabled')
    assert binding['state_plan_version']==VERSION
    validate_state_plan(plan,script,manifest)
    assert compile_state_plan(plan,script,manifest)==compile_action_plan(plan,script,manifest)
