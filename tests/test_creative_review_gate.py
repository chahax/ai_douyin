from copy import deepcopy
import pytest
from src.content_factory.creative_review_gate import validate_review,make_packet,template,confirmed_issues,digest,VERSION
from src.content_factory.creative_workflow_contract import CreativeContractError
from src.content_factory.creative_workflow import CreativeWorkflow,CREATE_REVIEW_PROFILE
from src.content_factory.creative_original_prompt import VERSION as WRITER_VERSION
from src.content_factory.reusable_production import read,write
from scripts.record_creative_text_review import record_decision
from test_creative_model_profile import setup
from test_creative_event_script import as_events
from test_creative_workflow import FakeClients
from test_reusable_production import design_for

def empty():return {'story_preserved':True,'issues':[],'suggestions':[],'calibration_focus':[]}
def issue(script):
    return {'id':'I01','owner':'writer','location':'B01','severity':'major',
            'evidence':script['beats'][0]['before'],'impact':'需要核实动作与要求的关系','proposal':'仅修B01开头动作',
            'rule':'本次简报的动作要求','contradiction':'测试用明确矛盾',
            'evidence_refs':[{'path':'script.beats.0.before','quote':script['beats'][0]['before']}]}
def review(script):
    r=empty();r['story_preserved']=False;r['issues']=[issue(script)];return r

def decision(root,confirm=True):
    pending=read(root/'state.json')['pending_evidence_review'];packet=read(root/pending['packet'])
    value=template(packet);value.update(reviewed_full_text=True,summary='测试核实回执：已逐项阅读当前剧本。')
    for row in value['decisions']:row.update(decision='confirm' if confirm else 'dismiss',reason='测试逐项核实原因')
    source=root/'decision_input.json';write(source,value);record_decision(root,source)
    return value

def wf(root,clients,**kwargs):
    return CreativeWorkflow(root,clients=clients,model_profile=CREATE_REVIEW_PROFILE,writer_prompt_version=WRITER_VERSION,**kwargs)

def prepared(tmp_path):
    a,b=setup(tmp_path);b.metadata['creative_brief']['duration_seconds']=[20,20]
    return a,b,as_events(a[2])

def test_new_default_stops_even_clean_review_then_resumes_without_extra_calls(tmp_path):
    a,b,raw=prepared(tmp_path);root=tmp_path/'run'
    c=FakeClients([a[0],a[1],raw,empty()]);state=wf(root,c).run(b)
    assert state['review_policy_version']==VERSION
    assert state['status']=='script_review_pending'
    assert [r for r,_ in c.calls]==['writer','writer','writer','director']
    assert not (root/'director_shots.json').exists()
    assert 'DeepSeek' in read(root/'script_review__story_00_00.json')['request']['messages'][0]['content']
    assert not wf(root,FakeClients([])).run(b).get('handoff_sha256')
    decision(root)
    c2=FakeClients([a[3],design_for(a[3]),empty()]);state=wf(root,c2).run(b)
    assert state['status']=='script_review_pending'
    assert state['pending_evidence_review']['key']=='writer_check__00'
    assert not (root/'MEDIA_HANDOFF.json').exists()
    decision(root)
    state=wf(root,FakeClients([])).run(b)
    assert state['status']=='media_handoff_pending_capability'
    assert state['calls_started']==7
    assert state['assistant_review_required'] is True
    assert len(read(root/'TEXT_REVIEW_HISTORY.json')['decisions'])==2

def test_confirmed_issue_revises_then_requires_fresh_review_and_preserves_other_beats(tmp_path):
    a,b,raw=prepared(tmp_path);root=tmp_path/'run'
    wf(root,FakeClients([a[0],a[1],raw,review(a[2])])).run(b)
    decision(root)
    modified=deepcopy(raw);modified['beats'][0]['events'][0]['text']='甲停下脚步'
    c=FakeClients([modified,empty()]);state=wf(root,c).run(b)
    assert [r for r,_ in c.calls]==['writer','director']
    assert state['revision_rounds']==1
    assert state['pending_evidence_review']['key']=='script_review__story_00_01'
    output=read(root/'writer_revise__preflight_story_00_01.json')['output']
    assert output['beats'][1]['before']==a[2]['beats'][1]['before']
    assert not (root/'director_shots.json').exists()
    # Cached committed revisions do not consume a second round or call.
    assert wf(root,FakeClients([])).run(b)['revision_rounds']==1

def test_dismissed_issue_and_optional_suggestion_do_not_trigger_writer_revision(tmp_path):
    a,b,raw=prepared(tmp_path);root=tmp_path/'run';r=review(a[2])
    r['suggestions']=[{'location':'B01','proposal':'可选表情细化','reason':'不影响因果'}]
    wf(root,FakeClients([a[0],a[1],raw,r])).run(b);decision(root,False)
    state=wf(root,FakeClients([a[3],design_for(a[3]),empty()])).run(b)
    assert state['revision_rounds']==0
    assert not list(root.glob('writer_revise*.json'))

def test_zero_revision_budget_stops_after_confirmed_issue(tmp_path):
    a,b,raw=prepared(tmp_path);root=tmp_path/'run'
    wf(root,FakeClients([a[0],a[1],raw,review(a[2])]),max_revisions=0).run(b);decision(root)
    state=wf(root,FakeClients([]),max_revisions=0).run(b)
    assert state['status']=='needs_revision'
    assert not (root/'MEDIA_HANDOFF.json').exists()
    assert state['revision_rounds']==0

def test_old_runs_keep_old_policy_and_cannot_silently_switch(tmp_path):
    write(tmp_path/'state.json',{'model_profile':CREATE_REVIEW_PROFILE,'writer_prompt_version':WRITER_VERSION})
    assert CreativeWorkflow(tmp_path).review_policy_version=='legacy'
    with pytest.raises(RuntimeError,match='审核流程版本'):CreativeWorkflow(tmp_path,review_policy_version=VERSION)

@pytest.mark.parametrize('mutation',['missing_proposal','array_evidence','invented_quote','missing_issues','minor','missing_suggestions','duplicate_id'])
def test_invalid_review_is_rejected(tmp_path,mutation):
    a,b,raw=prepared(tmp_path);context={'script':a[2]};r=review(a[2])
    if mutation=='missing_proposal':del r['issues'][0]['proposal']
    elif mutation=='array_evidence':r['issues'][0]['evidence_refs']=[{'path':'script.beats.0.dialogue','quote':'话'}]
    elif mutation=='invented_quote':r['issues'][0]['evidence_refs'][0]['quote']='完全不存在的原文'
    elif mutation=='missing_issues':del r['issues']
    elif mutation=='minor':r['issues'][0]['severity']='minor'
    elif mutation=='missing_suggestions':del r['suggestions']
    else:r['issues'].append(deepcopy(r['issues'][0]))
    with pytest.raises(CreativeContractError):validate_review(r,context)

def test_pending_template_stale_decision_and_missing_decisions_cannot_pass(tmp_path):
    a,b,raw=prepared(tmp_path);packet=make_packet('test',review(a[2]),{'script':a[2]});d=template(packet)
    with pytest.raises(CreativeContractError):confirmed_issues(packet,d)
    d.update(reviewed_full_text=True,summary='实际检查说明');d['decisions'][0].update(decision='dismiss',reason='具体误报原因')
    assert confirmed_issues(packet,d)==[]
    changed=deepcopy(packet);changed['context']['script']['beats'][0]['before']='changed'
    with pytest.raises(CreativeContractError):confirmed_issues(changed,d)
    d['decisions']=[]
    with pytest.raises(CreativeContractError):confirmed_issues(packet,d)

def test_assistant_can_add_missed_issue(tmp_path):
    a,b,raw=prepared(tmp_path);packet=make_packet('test',empty(),{'script':a[2]});d=template(packet)
    d.update(reviewed_full_text=True,summary='发现模型漏检',additional_issues=[issue(a[2])])
    assert confirmed_issues(packet,d)==[issue(a[2])]

def test_invalid_reviewer_output_stops_before_directing(tmp_path):
    a,b,raw=prepared(tmp_path);root=tmp_path/'run';r=review(a[2]);r['issues'][0]['evidence_refs'][0]['quote']='伪造的证据'
    with pytest.raises((CreativeContractError,RuntimeError)):
        wf(root,FakeClients([a[0],a[1],raw,r]),max_contract_repairs=0).run(b)
    assert not (root/'director_shots.json').exists()
    assert not (root/'MEDIA_HANDOFF.json').exists()

def test_confirmed_issue_reserves_recheck_budget_before_writer_call(tmp_path):
    a,b,raw=prepared(tmp_path);root=tmp_path/'run'
    wf(root,FakeClients([a[0],a[1],raw,review(a[2])]),max_calls=5).run(b);decision(root)
    with pytest.raises(RuntimeError,match='预算不足'):wf(root,FakeClients([]),max_calls=5).run(b)
    assert read(root/'state.json')['revision_rounds']==0

def test_review_contract_repair_is_bounded_and_uses_reviewer(tmp_path):
    a,b,raw=prepared(tmp_path);root=tmp_path/'run';r=review(a[2]);del r['issues'][0]['proposal']
    c=FakeClients([a[0],a[1],raw,r,review(a[2])])
    state=wf(root,c,max_contract_repairs=1).run(b)
    assert state['status']=='script_review_pending'
    assert state['contract_repairs_used']==1
    assert [role for role,_ in c.calls][-2:]==['director','director']
    assert not (root/'director_shots.json').exists()

def test_joint_review_false_positive_can_be_dismissed_without_rewriting(tmp_path):
    a,b,raw=prepared(tmp_path);root=tmp_path/'run'
    wf(root,FakeClients([a[0],a[1],raw,empty()])).run(b);decision(root)
    wf(root,FakeClients([a[3],design_for(a[3]),review(a[2])])).run(b);decision(root,False)
    state=wf(root,FakeClients([])).run(b)
    assert state['status']=='media_handoff_pending_capability'
    assert state['revision_rounds']==0
    assert not list(root.glob('writer_revise*.json'))

def test_confirmed_receipt_cannot_be_changed_after_use(tmp_path):
    a,b,raw=prepared(tmp_path);root=tmp_path/'run'
    wf(root,FakeClients([a[0],a[1],raw,empty()])).run(b);d=decision(root)
    wf(root,FakeClients([a[3],design_for(a[3]),empty()])).run(b)
    d['summary']='被更换的旧回执';write(root/'script_review__story_00_00__assistant_decision.json',d)
    with pytest.raises(RuntimeError,match='不能修改'):wf(root,FakeClients([])).run(b)

def test_director_story_false_positive_gets_one_redraft_without_script_revision(tmp_path):
    a,b,raw=prepared(tmp_path);root=tmp_path/'run'
    wf(root,FakeClients([a[0],a[1],raw,empty()])).run(b);decision(root)
    r={'story_issues':[issue(a[2])]}
    state=wf(root,FakeClients([r])).run(b)
    assert state['pending_evidence_review']['key']=='director_shots'
    decision(root,False)
    state=wf(root,FakeClients([a[3],design_for(a[3]),empty()])).run(b)
    assert state['revision_rounds']==0
    assert (root/'director_shots__dismissed_retry.json').exists()
    assert not list(root.glob('writer_revise*.json'))

def test_joint_writer_revision_is_preflight_reviewed_again_before_director(tmp_path):
    a,b,raw=prepared(tmp_path);root=tmp_path/'run'
    wf(root,FakeClients([a[0],a[1],raw,empty()])).run(b);decision(root)
    wf(root,FakeClients([a[3],design_for(a[3]),review(a[2])])).run(b);decision(root)
    revised=deepcopy(raw);revised['beats'][0]['events'][0]['text']='甲停下脚步'
    state=wf(root,FakeClients([revised,empty()])).run(b)
    assert state['pending_evidence_review']['key']=='script_review__joint_01_00'
    assert not (root/'director_revise__01.json').exists()
    decision(root)
    state=wf(root,FakeClients([a[3],design_for(a[3]),empty()])).run(b)
    assert state['pending_evidence_review']['key']=='writer_check__01'
    decision(root)
    state=wf(root,FakeClients([])).run(b)
    assert state['status']=='media_handoff_pending_capability'
    assert state['revision_rounds']==1
    assert state['calls_started']==12

def test_v1_review_prompt_remains_exactly_frozen():
    from src.content_factory.creative_review_gate import review_prompt,review_rules,SCRIPT_REVIEW_PROMPT
    assert digest(review_prompt('evidence_review_v1'))=='5cb9fa4f13db538436e860b457425f412904683a6a13013b9b58c126ce5a05a1'
    assert review_prompt('evidence_review_v2')==SCRIPT_REVIEW_PROMPT
    assert '规则边界复核' not in review_rules('evidence_review_v1')
    assert '规则边界复核' in review_rules('evidence_review_v2')

@pytest.mark.parametrize('version',['evidence_review_v1','evidence_review_v2'])
def test_bound_review_version_survives_resume_and_joint_review(tmp_path,version):
    from src.content_factory.creative_review_gate import review_prompt
    a,b,raw=prepared(tmp_path);root=tmp_path/'run'
    wf(root,FakeClients([a[0],a[1],raw,empty()]),review_policy_version=version).run(b)
    prompt=read(root/'script_review__story_00_00.json')['request']['messages'][0]['content']
    from src.content_factory.creative_narrative_focus import prompt_for_stage
    # The bound narrative layer already exists in v21; the policy base remains frozen.
    bound=read(root/'state.json')['narrative_focus_binding']
    assert prompt==review_prompt(version)+prompt_for_stage(bound,'script_review__story_00_00')
    resumed=CreativeWorkflow(root,clients=FakeClients([]))
    assert resumed.review_policy_version==version
    assert resumed.run(b)['calls_started']==4
    other='evidence_review_v1' if version=='evidence_review_v2' else 'evidence_review_v2'
    with pytest.raises(RuntimeError,match='审核流程版本'):CreativeWorkflow(root,review_policy_version=other)
    decision(root)
    restored=CreativeWorkflow(root,clients=FakeClients([a[3],design_for(a[3]),empty()]))
    restored.run(b)
    joint=read(root/'writer_check__00.json')['request']['messages'][0]['content']
    assert ('规则边界复核' in joint)==(version=='evidence_review_v2')
    decision(root)
    state=CreativeWorkflow(root,clients=FakeClients([])).run(b)
    assert state['status']=='media_handoff_pending_capability'
    assert read(root/'TEXT_REVIEW_HISTORY.json')['policy']==version


def test_director_story_issue_repair_uses_evidence_protocol_and_keeps_failed_receipt(tmp_path):
    from src.content_factory.creative_workflow import _hash
    a,b,raw=prepared(tmp_path);root=tmp_path/'story_repair'
    wf(root,FakeClients([a[0],a[1],raw,empty()])).run(b);decision(root)
    full=issue(a[2])
    original={k:v for k,v in full.items() if k not in ('id','rule','contradiction','evidence_refs')}
    bad={'story_issues':[original],'style':{'note':'unused'},'media_assumptions':[]}
    legacy=root/'director_shots__contract_repair.json'
    failed={'status':'response_received','repair_protocol':'generic_full_object/v1','response_text':'{"patches":[]}', 'source_sha256':_hash(bad)}
    write(legacy,failed)
    saved=read(root/'state.json')
    saved['calls_started'] += 1
    saved['contract_repairs_used'] += 1
    write(root/'state.json',saved)
    clients=FakeClients([bad,{'story_issues':[full]}])
    state=wf(root,clients).run(b)
    assert state['status']=='script_review_pending'
    assert state['pending_evidence_review']['key'].startswith('director_story_review') or 'director' in state['pending_evidence_review']['key']
    assert read(legacy)==failed
    fixes=[p for p in root.glob('director_shots__contract_repair_*.json') if '__local_' not in p.name]
    assert len(fixes)==1
    fix=read(fixes[0])
    assert fix['repair_protocol']=='director_story_issue_enrichment/v1'
    assert 'story_issues' in fix['request'][0]['content']
    assert fix['reconciliation']['preserved_issue_count']==1
    assert state['calls_started']==7
    assert state['contract_repairs_used']==2
    # Resume uses both original and successful repair receipts without calls.
    assert wf(root,FakeClients([])).run(b)['calls_started']==7


def test_story_issue_enrichment_cannot_dismiss_or_rewrite_and_maps_only_unique_ids():
    from src.content_factory.creative_workflow import _validate_story_issue_enrichment
    old={'story_issues':[{'location':'B01','evidence':'原证据','proposal':'原建议'}], 'style':{}}
    fixed={'story_issues':[{'location':'B1','evidence':'原证据','proposal':'原建议','id':'I1'}]}
    _validate_story_issue_enrichment(old,fixed,{'beats':[{'id':'B1'}]})
    for altered in ({'story_issues':[]},{'story_issues':[{**fixed['story_issues'][0],'evidence':'修改证据'}]}):
        with pytest.raises(CreativeContractError):
            _validate_story_issue_enrichment(old,altered,{'beats':[{'id':'B1'}]})
    with pytest.raises(CreativeContractError):
        _validate_story_issue_enrichment(old,fixed,{'beats':[{'id':'B1'},{'id':'B01'}]})


def test_story_issue_projection_keeps_original_complaint_and_rejects_bad_refs(tmp_path):
    from src.content_factory.creative_workflow import _project_story_issue_enrichment
    a, _, _ = prepared(tmp_path)
    full = issue(a[2])
    old = {k:v for k,v in full.items() if k not in ('id','rule','contradiction','evidence_refs')}
    rewritten = deepcopy(full)
    rewritten['evidence'] = [{'bad':'rewritten'}]
    rewritten['proposal'] = '未授权新建议'
    rewritten['evidence_refs'].append({'path':'nonexistent.constraints.0','quote':'不存在'})
    fixed, audit = _project_story_issue_enrichment({'story_issues':[old]}, {'story_issues':[rewritten]}, {'script':a[2]})
    assert fixed['story_issues'][0]['evidence'] == old['evidence']
    assert fixed['story_issues'][0]['proposal'] == old['proposal']
    assert len(audit['rejected_supplemental_references']) == 1
    validate_review({'story_preserved':False,'issues':fixed['story_issues'],'suggestions':[],'calibration_focus':[]},{'script':a[2]})
    rewritten['evidence_refs'] = [{'path':'nonexistent','quote':'错误'}]
    fixed, _ = _project_story_issue_enrichment({'story_issues':[old]}, {'story_issues':[rewritten]}, {'script':a[2]})
    with pytest.raises(CreativeContractError, match='evidence_refs'):
        validate_review({'story_preserved':False,'issues':fixed['story_issues'],'suggestions':[],'calibration_focus':[]},{'script':a[2]})


def test_empty_director_issues_repairs_missing_shots_without_inventing_issues(tmp_path):
    a,b,raw=prepared(tmp_path);root=tmp_path/'missing_shots'
    wf(root,FakeClients([a[0],a[1],raw,empty()])).run(b);decision(root)
    bad={'story_issues':[]}
    failed={'status':'response_received','repair_protocol':'director_story_issue_enrichment/v1','response_text':'{"story_issues":[{"invented":true}]}'}
    legacy=root/'director_shots__contract_repair.json';write(legacy,failed)
    clients=FakeClients([bad,a[3],design_for(a[3]),empty()])
    state=wf(root,clients).run(b)
    assert state['pending_evidence_review']['key']=='writer_check__00'
    assert read(legacy)==failed
    paths=[p for p in root.glob('director_shots__contract_repair_*.json') if '__local_' not in p.name]
    assert len(paths)==1
    record=read(paths[0]);assert record['repair_protocol']=='director_missing_shots/v1'
    import json
    request=json.loads(record['request'][-1]['content'])
    assert request['original_request']['script']['beats']==read(root/'writer_script.json')['output']['beats']
    assert request['original_request']['creative_brief']==b.metadata['creative_brief']
    assert 'director_brief' in request['original_request']
    assert 'executor_constraints' in request['original_request']
    assert 'shots' in request['expected_shape']
    assert '原文旁白' not in record['request'][0]['content']
    assert state['contract_repairs_used']==1
    assert wf(root,FakeClients([])).run(b)['calls_started']==8


def test_missing_shots_repair_rejects_new_complaints(tmp_path):
    a,b,raw=prepared(tmp_path);root=tmp_path/'missing_reject'
    wf(root,FakeClients([a[0],a[1],raw,empty()])).run(b);decision(root)
    with pytest.raises(CreativeContractError,match='不能制造新问题'):
        wf(root,FakeClients([{'story_issues':[]},{'story_issues':[issue(a[2])]}])).run(b)
    assert not (root/'MEDIA_HANDOFF.json').exists()


def test_missing_optional_suggestions_projects_locally_without_dropping_issues(tmp_path):
    from src.content_factory.creative_workflow import _project_missing_review_suggestions
    a,b,raw=prepared(tmp_path)
    source=review(a[2]);source.pop('suggestions')
    projected=_project_missing_review_suggestions(source,{'script':a[2]})
    assert projected['suggestions']==[]
    assert projected['issues']==source['issues']
    assert 'suggestions' not in source
    for mutation in ('bad_evidence','bad_focus','missing_issues','null_suggestions'):
        invalid=deepcopy(source)
        if mutation=='bad_evidence':invalid['issues'][0]['evidence_refs'][0]['quote']='不存在的原文'
        if mutation=='bad_focus':invalid['calibration_focus']=[{}]
        if mutation=='missing_issues':invalid.pop('issues')
        if mutation=='null_suggestions':invalid['suggestions']=None
        assert _project_missing_review_suggestions(invalid,{'script':a[2]}) is None


def test_missing_suggestions_resume_keeps_old_repair_receipt_and_requires_assistant(tmp_path):
    a,b,raw=prepared(tmp_path);root=tmp_path/'missing_suggestions'
    wf(root,FakeClients([a[0],a[1],raw,empty()])).run(b);decision(root)
    missing=empty();missing.pop('suggestions')
    state=wf(root,FakeClients([a[3],design_for(a[3]),missing])).run(b)
    assert state['status']=='script_review_pending'
    assert state['pending_evidence_review']['key']=='writer_check__00'
    assert state['contract_repairs_used']==0
    assert state['calls_started']==7
    receipt=list(root.glob('writer_check__00__local_empty_suggestions_*.json'))
    assert len(receipt)==1 and read(receipt[0])['automatic_approval'] is False
    # A previously charged failed repair remains untouched and is not recalled.
    failed=root/'writer_check__00__contract_repair.json';write(failed,{'status':'response_received','response_text':'{}'})
    assert wf(root,FakeClients([])).run(b)['calls_started']==7
    assert read(failed)=={'status':'response_received','response_text':'{}'}
