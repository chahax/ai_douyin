from copy import deepcopy
import json
import pytest
from src.content_factory.creative_full_script_revision import bind_full_script_revision
from src.content_factory.creative_original_prompt import bind_original_prompt
from src.content_factory.creative_event_script import compile_event_script
from src.content_factory.creative_workflow import (
    CreativeWorkflow,CREATE_REVIEW_PROFILE,_writer_revision_result,_validate_writer_revision_result,
)
from src.content_factory.creative_workflow_contract import CreativeContractError,compile_beat_screenplay
from tests.test_creative_model_profile import setup
from tests.test_creative_workflow import FakeClients
from tests.test_creative_event_script import as_events
from tests.test_creative_event_recovery import sample,workflow
from src.content_factory.creative_event_recovery import repair_event_contract


def script_fixture(tmp_path):
    a,bundle=setup(tmp_path);before=deepcopy(a[2]);before['screenplay_markdown']=compile_beat_screenplay(before)
    return before,a[0]['candidates'][0],bundle


def test_full_revision_keeps_complete_model_reply_including_unmentioned_new_beats(tmp_path):
    before,candidate,_=script_fixture(tmp_path);after=deepcopy(before)
    after['premise']='整篇新版摘要'
    after['beats'][0]['id']='NEW01';after['beats'][1]['id']='NEW02'
    after['beats'][1]['before']='林屿听见拒绝后，收回文件夹。'
    result=_writer_revision_result(before,after,[before['beats'][0]['id']],revision_mode='full_script')
    assert result['beats']==after['beats'] and result['premise']==after['premise']
    assert '收回文件夹' in result['screenplay_markdown']
    _validate_writer_revision_result(result,before,[before['beats'][0]['id']],candidate,'','original',revision_mode='full_script')
    with pytest.raises(CreativeContractError):
        _writer_revision_result(before,after,[before['beats'][0]['id']])
    with pytest.raises(CreativeContractError,match='局部补丁'):
        _writer_revision_result(before,{'replace_beats':[]},[],revision_mode='full_script')


def test_actual_model_stage_has_full_scope_request_and_no_old_id_lock(tmp_path):
    before,candidate,bundle=script_fixture(tmp_path);after=as_events(before)
    after['beats'][0]['id']='NEW01';after['beats'][1]['id']='NEW02'
    after['beats'][1]['events'][0]['text']='林屿把文件夹抱回自己胸前。'
    w=CreativeWorkflow(tmp_path/'stage',clients=FakeClients([after]),model_profile=CREATE_REVIEW_PROFILE,
        writer_prompt_version='original_events_v3',review_policy_version='legacy',max_revisions=5)
    w.run_dir.mkdir(parents=True)
    w.state={'calls_started':0,'contract_repairs_used':0,'revision_rounds':0,'stages':[],
        'writer_prompt_binding':bind_original_prompt({'schema':'creative_brief/v1','theme':'关系变化'}),
        'script_revision_binding':bind_full_script_revision()}
    result=w._stage('writer_revise__01','writer',{'previous_script':before,
        'affected_beat_ids':[before['beats'][0]['id']],'issues':[]},
        lambda v:_validate_writer_revision_result(v,before,[],candidate,'','original',revision_mode='full_script'))
    assert [b['id'] for b in result['beats']]==['NEW01','NEW02']
    rec=json.loads((w.run_dir/'writer_revise__01.json').read_text(encoding='utf-8'))
    prompt=rec['request']['messages'][0]['content']
    assert '重新提交完整events剧本' in prompt
    assert '其他拍逐字保留原稿' not in prompt and '必须保持现有节拍ID' not in prompt
    assert json.loads(rec['request']['messages'][1]['content'])['revision_mode']=='full_script'


def test_full_event_recovery_preserves_line_moved_to_another_beat(tmp_path):
    original,corrected=sample();w=workflow(tmp_path,corrected)
    result=repair_event_contract(w,'writer_revise__01','writer',{'revision_mode':'full_script'},original,'three lines',lambda v:None)
    adopted=_writer_revision_result({'selected_candidate_id':'C01'},result,[],revision_mode='full_script')
    assert '这次你自己来。' in adopted['screenplay_markdown']
    assert len(adopted['beats'])==2


@pytest.mark.parametrize('pass_at',[3,None])
def test_five_round_loop_reviews_every_complete_revision_and_stops_early(tmp_path,pass_at):
    initial,candidate,bundle=script_fixture(tmp_path)
    w=CreativeWorkflow(tmp_path/'loop',clients=FakeClients([]),model_profile=CREATE_REVIEW_PROFILE,
        writer_prompt_version='original_events_v3',review_policy_version='evidence_review_v2',max_revisions=5)
    w.run_dir.mkdir(parents=True)
    w.state={'writer_prompt_binding':bind_original_prompt({'schema':'creative_brief/v1','theme':'关系变化'}),
        'script_revision_binding':bind_full_script_revision(),'revision_rounds':0,'calls_started':0,'revision_committed':[]}
    calls=[];latest=deepcopy(initial)
    def stage(name,role,payload,validator):
        nonlocal latest
        calls.append(name);w.state['calls_started']+=1
        if name.startswith('writer_revise'):
            assert payload['previous_script']==latest
            latest=deepcopy(latest);n=w.state['revision_rounds'];latest['premise']=f'完整第{n}稿'
            latest['beats'][0]['id']=f'N{n}A';latest['beats'][1]['id']=f'N{n}B'
            latest['screenplay_markdown']=compile_beat_screenplay(latest);validator(latest)
            return deepcopy(latest)
        assert payload['script']==latest
        issues=[] if pass_at is not None and w.state['revision_rounds']>=pass_at else [{'owner':'writer','location':latest['beats'][0]['id'],'evidence':'需求缺失','impact':'情绪不成立','proposal':'完整返修','severity':'major'}]
        return {'issues':issues}
    w._stage=stage;w._verified_review=lambda name,review,context:review['issues']
    result=w._review_script_before_directing(initial,key='story',bundle=bundle,candidate=candidate,
        selected_excerpt='',excerpt_record={},analysis={},brief={},context_ref={})
    assert w.state['revision_rounds']==(pass_at or 5)
    assert len([x for x in calls if x.startswith('writer_revise')])==(pass_at or 5)
    if pass_at is None:
        assert result is None and w.state['status']=='needs_revision'
    else:
        assert result==latest


def test_new_cli_budget_is_five_rounds_with_existing_total_caps():
    from scripts.run_creative_workflow import DEFAULT_BUDGET,parser
    assert DEFAULT_BUDGET['policy_version']=='v5_20261001'
    assert DEFAULT_BUDGET['max_revisions']==5
    assert DEFAULT_BUDGET['max_calls']==20 and DEFAULT_BUDGET['max_total_tokens']==500000


def test_full_storyboard_rebuild_accepts_new_ids_and_does_not_send_old_shots(tmp_path):
    script,candidate,bundle=script_fixture(tmp_path)
    answers,_=setup(tmp_path)
    script['beats'][0]['id']='NEW01';script['beats'][1]['id']='NEW02'
    shots=deepcopy(answers[3])
    mapping={before['id']:after['id'] for before,after in zip(answers[2]['beats'],script['beats'])}
    for shot in shots['shots']:
        shot['beat_id']=mapping[shot['beat_id']]
    w=CreativeWorkflow(tmp_path/'director',clients=FakeClients([shots]),model_profile=CREATE_REVIEW_PROFILE)
    w.run_dir.mkdir()
    w.state={'calls_started':0,'contract_repairs_used':0,'revision_rounds':0,'stages':[]}
    assert w._regenerate_full_storyboard('test',script,answers[1],answers[0],candidate,{}, {}, '')==shots
    record=json.loads((w.run_dir/'director_shots__full_revision_test.json').read_text(encoding='utf-8'))
    payload=json.loads(record['request']['messages'][-1]['content'])
    assert payload['script']==script
    assert 'previous_shots' not in payload and 'affected_beat_ids' not in payload


def test_cli_resume_keeps_saved_budget_and_explicit_flags(tmp_path):
    from scripts.run_creative_workflow import parser,_inherit_saved_budget
    saved={'max_revisions':2,'max_calls':16,'budget_policy_version':'v4_20260923',
           'max_contract_repairs':None}
    (tmp_path/'state.json').write_text(json.dumps(saved),encoding='utf-8')
    flags=['--source-driver','original','--title','test','--run-dir',str(tmp_path)]
    args=parser().parse_args(flags);_inherit_saved_budget(args,flags)
    assert args.max_revisions==2 and args.max_calls==16
    assert args.budget_policy_version=='v4_20260923' and args.max_contract_repairs==8
    flags+=['--max-revisions=5'];args=parser().parse_args(flags);_inherit_saved_budget(args,flags)
    assert args.max_revisions==5
