from copy import deepcopy
import pytest
from src.content_factory.creative_event_script import compile_event_script
from src.content_factory.creative_workflow_contract import CreativeContractError,compile_beat_screenplay
from src.content_factory.creative_original_prompt import validate_brief_script,VERSION
from src.content_factory.creative_workflow import CreativeWorkflow,CREATE_REVIEW_PROFILE
from src.content_factory.reusable_production import read,write
from test_creative_model_profile import setup
from test_creative_workflow import FakeClients
from test_reusable_production import design_for


def raw(events):
    return {"title":"事件测试","premise":"按顺序","selected_candidate_id":"C01","duration_seconds":12,"beats":[{"id":"B01","duration_seconds":12,"event":"动作变化","trigger":"刺激","events":events}]}


def event(kind,text):return {"kind":kind,"speaker":"甲" if kind=="dialogue" else "","text":text}


@pytest.mark.parametrize("kinds",[[],['action'],['dialogue'],['action','action','action','action'],['action','dialogue','action'],['dialogue','action','action','dialogue','action']])
def test_order_and_text_are_lossless(kinds):
    events=[event(k,f"唯一事件{i}") for i,k in enumerate(kinds)]
    original=raw(events)
    if not kinds:
        with pytest.raises(CreativeContractError):compile_event_script(original)
        return
    compiled=compile_event_script(original);rendered=compile_beat_screenplay(compiled)
    assert original==raw(events)
    positions=[rendered.index(e['text']) for e in events]
    assert positions==sorted(positions)
    assert all(rendered.count(e['text'])==1 for e in events)


def test_unsupported_or_malformed_events_stop():
    with pytest.raises(CreativeContractError):compile_event_script(raw([event('dialogue','a')]*3))
    wrong=event('action','动作');wrong['speaker']='甲'
    with pytest.raises(CreativeContractError):compile_event_script(raw([wrong]))
    value=raw([event('action','动作')]);value['item']={}
    with pytest.raises(CreativeContractError):compile_event_script(value)


def test_brief_requirements_are_generic():
    script=compile_event_script(raw([event('dialogue','你好')]))
    with pytest.raises(CreativeContractError,match='无对白'):validate_brief_script(script,{'constraints':['全片零对白']})
    with pytest.raises(CreativeContractError,match='结尾'):validate_brief_script(script,{'constraints':['结尾最多10秒']})
    with pytest.raises(CreativeContractError,match='总时长'):validate_brief_script(script,{'duration_seconds':[20,30]})


def as_events(script):
    result={k:deepcopy(v) for k,v in script.items() if k!='screenplay_markdown'}
    for b in result['beats']:
        b.pop('consequence',None)
        lines=b.pop('dialogue');ev=[event('action',b.pop('before'))]
        if lines:ev.append({'kind':'dialogue',**lines[0]})
        ev.append(event('action',b.pop('during')))
        ev.extend({'kind':'dialogue',**line} for line in lines[1:])
        ev.append(event('action',b.pop('after')));b['events']=ev
    return result


def test_event_profile_full_flow_resume_and_legacy_preserved(tmp_path):
    answers,bundle=setup(tmp_path);original=deepcopy(answers[2]);answers[2]=as_events(answers[2])
    bundle.metadata['creative_brief']['duration_seconds']=[20,20]
    clients=FakeClients([*answers[:4],design_for(answers[3]),answers[4]])
    root=tmp_path/'events'
    state=CreativeWorkflow(root,clients=clients,model_profile=CREATE_REVIEW_PROFILE,writer_prompt_version=VERSION,review_policy_version="legacy").run(bundle)
    record=read(root/'writer_script.json')
    assert record['event_output']==answers[2]
    assert record['request']['parameters']['temperature']==0.2
    for b in original['beats']:b.pop('consequence',None)
    assert record['output']['beats']==original['beats']
    assert state['writer_prompt_binding']['version']==VERSION
    assert state['narrative_focus_binding']['version']=='narrative_expression_v3'
    for stage in ('writer_analysis','writer_script','director_shots','writer_check__00'):
        system=read(root/(stage+'.json'))['request']['messages'][0]['content']
        assert '叙事表达优先' in system
    assert '只顺读实际事件' in record['request']['messages'][0]['content']
    assert read(root/'writer_check__00.json')['request']['messages'][-1]['content'].find('creative_brief')>=0
    assert state['assistant_review_required'] is True
    resumed=CreativeWorkflow(root,clients=FakeClients([]))
    assert resumed.writer_prompt_version==VERSION
    assert resumed.run(bundle)['calls_started']==6
    with pytest.raises(RuntimeError,match='提示词版本'):CreativeWorkflow(root,writer_prompt_version='legacy')
    legacy=tmp_path/'legacy';write(legacy/'state.json',{'schema':'creative_workflow_state/v1'})
    assert CreativeWorkflow(legacy).writer_prompt_version=='legacy'
    with pytest.raises(RuntimeError,match='提示词版本'):CreativeWorkflow(legacy,writer_prompt_version=VERSION)


def test_event_writer_revision_returns_to_same_creator_and_preserves_other_beats(tmp_path):
    a,bundle=setup(tmp_path);bundle.metadata['creative_brief']['duration_seconds']=[20,20]
    initial=as_events(a[2]);revised=deepcopy(initial)
    revised['beats'][0]['events'][0]['text']='甲停下脚步'
    issue={'story_preserved':True,'issues':[{'owner':'writer','location':'B01','evidence':'开头动作不明确','impact':'观众不清楚行动','proposal':'写清动作','severity':'major'}],'calibration_focus':[]}
    clients=FakeClients([a[0],a[1],initial,a[3],design_for(a[3]),issue,revised,a[3],design_for(a[3]),a[4]])
    root=tmp_path/'revision'
    state=CreativeWorkflow(root,clients=clients,model_profile=CREATE_REVIEW_PROFILE,writer_prompt_version=VERSION,review_policy_version="legacy").run(bundle)
    revision=read(root/'writer_revise__01.json')
    assert revision['response_metadata']['transport_config_role']=='writer'
    assert revision['output']['beats'][0]['before']=='甲停下脚步'
    assert revision['output']['beats'][1]==compile_event_script(initial)['beats'][1]
    assert state['revision_rounds']==1
    assert state['assistant_review_required'] is True


def test_malformed_events_use_existing_bounded_repair_budget(tmp_path):
    a,bundle=setup(tmp_path);bundle.metadata['creative_brief']['duration_seconds']=[20,20]
    invalid=as_events(a[2]);invalid['beats'][0]['events'][0]['oops']='unexpected'
    repair=as_events(a[2])
    clients=FakeClients([a[0],a[1],invalid,repair,a[3],design_for(a[3]),a[4]])
    root=tmp_path/'repair'
    state=CreativeWorkflow(root,clients=clients,model_profile=CREATE_REVIEW_PROFILE,writer_prompt_version=VERSION,review_policy_version="legacy").run(bundle)
    assert state['contract_repairs_used']==1
    assert state['calls_started']==7
    assert read(root/'writer_script.json')['event_compilation_error']
    assert state['assistant_review_required'] is True


def test_summary_revision_is_explicit_and_does_not_expand_beat_scope(tmp_path):
    from src.content_factory.creative_workflow import _writer_revision_result
    a, _ = setup(tmp_path)
    previous = a[2]
    proposed = deepcopy(previous)
    proposed['premise'] = '修订后的准确摘要'
    proposed['title'] = '不允许的新标题'
    proposed['selected_candidate_id'] = 'C99'
    proposed['beats'][0]['before'] = '修复首拍'
    proposed['beats'][1]['before'] = '不允许的其他拍改动'
    legacy = _writer_revision_result(previous, proposed, ['B01'])
    updated = _writer_revision_result(previous, proposed, ['B01'], allow_summary_update=True)
    assert legacy['premise'] == previous['premise']
    assert updated['premise'] == proposed['premise']
    assert updated['title'] == previous['title']
    assert updated['selected_candidate_id'] == previous['selected_candidate_id']
    assert updated['beats'][1] == previous['beats'][1]
    assert updated['beats'][0]['before'] == '修复首拍'
    proposed['premise'] = ''
    with pytest.raises(CreativeContractError, match='premise'):
        _writer_revision_result(previous, proposed, ['B01'], allow_summary_update=True)


def test_summary_stage_binding_preserves_cached_request_semantics(tmp_path):
    from src.content_factory.creative_original_prompt import stage_summary_update_allowed
    path = tmp_path/'stage.json'
    assert stage_summary_update_allowed(path, eligible=True)
    assert not stage_summary_update_allowed(path, eligible=False)
    write(path, {'request': {'messages': [{'role':'user','content':'{}'}]}})
    assert not stage_summary_update_allowed(path, eligible=True)
    write(path, {'request': {'messages': [{'role':'user','content':'{"allow_summary_update":true}'}]}})
    assert stage_summary_update_allowed(path, eligible=True)
    assert not stage_summary_update_allowed(path, eligible=False)


def test_new_original_priority_is_bound_but_old_receipts_replay(tmp_path):
    import json
    a, bundle = setup(tmp_path)
    bundle.metadata['creative_brief']['duration_seconds'] = [20,20]
    a[2] = as_events(a[2])
    root = tmp_path/'priority'
    state = CreativeWorkflow(root, clients=FakeClients([*a[:4],design_for(a[3]),a[4]]), model_profile=CREATE_REVIEW_PROFILE, writer_prompt_version=VERSION, review_policy_version='legacy').run(bundle)
    binding = state['original_brief_priority_binding']
    assert binding['version'] == 'original_brief_priority_v1'
    assert binding['director_execution_version'] == 'original_director_execution_v1'
    assert state['original_director_binding']['prompt'] in read(root/'director_shots.json')['request']['messages'][0]['content']
    for stage in ('writer_analysis', 'director_brief', 'writer_script'):
        record = read(root/f'{stage}.json')
        assert binding['prompt'] in record['request']['messages'][0]['content']
        assert json.loads(record['request']['messages'][-1]['content'])['creative_brief'] == bundle.metadata['creative_brief']
    assert CreativeWorkflow(root, clients=FakeClients([])).run(bundle)['calls_started'] == 6
    # Simulate pre-version receipts exactly, including their prompt/input hashes.
    from src.content_factory.creative_workflow import _hash
    state.pop('original_brief_priority_binding')
    write(root/'state.json', state)
    for stage in ('writer_analysis', 'director_brief', 'writer_script'):
        path = root/f'{stage}.json'
        record = read(path)
        messages = record['request']['messages']
        messages[0]['content'] = messages[0]['content'].replace('\n'+binding['prompt'], '')
        payload = json.loads(messages[-1]['content'])
        if stage != 'writer_script': payload.pop('creative_brief')
        messages[-1]['content'] = json.dumps(payload, ensure_ascii=False)
        record['prompt_sha256'] = _hash(messages[0]['content'])
        record['input_sha256'] = _hash(payload)
        write(path, record)
    workflow = CreativeWorkflow(root, clients=FakeClients([]))
    workflow.state = state
    for stage in ('writer_analysis', 'director_brief', 'writer_script'):
        record = read(root/f'{stage}.json')
        payload = json.loads(record['request']['messages'][-1]['content'])
        assert workflow._stage(stage, record['role'], payload, lambda value: None) == record['output']
    assert workflow.state['calls_started'] == 6


