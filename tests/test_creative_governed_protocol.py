"""Offline integration: protocol dispatch, immutable production receipts and repair scope."""
import json
from copy import deepcopy
import pytest
from src.content_factory.creative_workflow import CreativeWorkflow, CREATE_REVIEW_PROFILE
from src.content_factory.creative_workflow_contract import CreativeContractError
from src.content_factory.creative_plan_patch import apply_plan_patch, plan_digest, editable_paths, patch_recheck_scope
from src.content_factory.creative_state_plan_v6 import validate_state_plan
from tests.test_creative_action_plan_v2 import sample
from tests.test_creative_workflow import FakeClients


@pytest.fixture(scope='module')
def current_source_governance_fixture(tmp_path_factory):
    """Build a test-only pack; production v23 and its source hashes stay frozen."""
    import shutil
    from scripts.manage_creative_governance import build, ROOT
    fixture_root = tmp_path_factory.mktemp('current_source_governance')
    pack = fixture_root / 'governance'
    build(pack)
    runtime = json.loads((pack / 'runtime_sources.json').read_text(encoding='utf-8'))
    rules = json.loads((pack / 'rules.json').read_text(encoding='utf-8'))
    sources = {r['path'] for r in runtime['sources']}
    sources |= {s['path'] for r in rules['rules'] for s in r['source_refs']}
    for relative in sources:
        target = fixture_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    return fixture_root


@pytest.fixture(autouse=True)
def isolate_governance_binding(current_source_governance_fixture, monkeypatch):
    import src.content_factory.creative_governed_runtime as runtime
    monkeypatch.setattr(runtime, 'ROOT', current_source_governance_fixture)
    monkeypatch.setattr(runtime, 'REGISTRY_DIRECTORY', 'governance')


def workflow(tmp_path, answers):
    clients = FakeClients(answers)
    w = CreativeWorkflow(tmp_path, clients=clients, model_profile=CREATE_REVIEW_PROFILE,
        writer_prompt_version='original_events_v3', review_policy_version='evidence_review_v6',
        production_protocol='governed_production_v1', max_calls=5, max_contract_repairs=2,
        max_total_tokens=250000)
    w.state = {'production_protocol':'governed_production_v1',
        'review_packet_version':'focused_review_packet_v1', 'calls_started':0,
        'max_calls':5,'max_total_tokens':250000,'budget_policy_version':'v4_20260923',
        'max_contract_repairs':2,'contract_repairs_used':0,'format_repairs_used':0,
        'revision_rounds':0,'stages':[]}
    from src.content_factory.creative_governed_runtime import bind_new_task
    w.state["rule_registry_binding"] = bind_new_task()
    return w,clients


def test_explicit_protocol_rejects_wrong_policy_and_resume_switch(tmp_path):
    with pytest.raises(ValueError,match='仅适用于'):
        CreativeWorkflow(tmp_path,clients=FakeClients([]),production_protocol='governed_production_v1')
    (tmp_path/'state.json').write_text(json.dumps({'production_protocol':'legacy',
        'model_profile':CREATE_REVIEW_PROFILE,'writer_prompt_version':'original_events_v3',
        'review_policy_version':'evidence_review_v6'}),encoding='utf-8')
    with pytest.raises(RuntimeError,match='生产协议'):
        workflow(tmp_path,[])


def test_v2_full_stage_then_local_patch_replay(tmp_path):
    plan,script,manifest=sample()
    patch={'source_sha256':plan_digest(plan),'patches':[{'path':'beats.0.groups.0.duration_seconds','value':2}]}
    w,clients=workflow(tmp_path,[plan,patch])
    payload={'state_plan_version':plan['schema'],'script':script,'static_visual_manifest':manifest,
        'plan_thinking_mode':'disabled'}
    validate=lambda value:validate_state_plan(value,script,manifest)
    assert w._stage('director_state_plan__00','director',payload,validate)==plan
    second={**payload,'plan_patch_base':plan,'issues':[{'reason':'give the action enough time'}]}
    result=w._stage('director_state_plan__01','director',second,validate)
    assert result['beats'][0]['groups'][0]['duration_seconds']==2
    assert w._stage('director_state_plan__01','director',second,validate)==result
    assert len(clients.calls)==2
    receipt=json.loads((tmp_path/'director_state_plan__01__action_patch_merge.json').read_text(encoding='utf-8'))
    assert receipt['dependency_recheck']['affected_beat_ids']==[b['beat_id'] for b in plan['beats']]
    assert receipt['semantic_approval'] is False


def test_v2_spatial_patch_and_no_change(tmp_path):
    plan,script,manifest=sample()
    target='spatial_contract.seats.0.access_positions'
    assert target in editable_paths(plan)
    patch={'source_sha256':plan_digest(plan),'patches':[{'path':target,'value':['桌旁','另一可坐侧']}]}
    merged=apply_plan_patch(plan,patch)
    assert plan!=merged and patch_recheck_scope(plan,patch)['requires_asset_recheck']
    patch['patches'][0]['value']=deepcopy(plan['spatial_contract']['seats'][0]['access_positions'])
    with pytest.raises(CreativeContractError,match='PLAN_PATCH_NO_CHANGE'):
        apply_plan_patch(plan,patch)


def test_v2_late_patch_rechecks_following_boundary():
    plan,_,_=sample()
    patch={'source_sha256':plan_digest(plan),'patches':[{'path':'beats.1.purpose','value':'新的镜头表达目的'}]}
    scope=patch_recheck_scope(plan,patch)
    assert scope['affected_beat_ids']==[plan['beats'][1]['beat_id']]
    assert scope['requires_full_compile'] and scope['requires_semantic_review']

def review_fixture():
    from src.content_factory.creative_state_plan_v6 import compile_state_plan
    from src.content_factory.creative_action_plan_v2 import schedule_action_plan
    from src.content_factory.creative_review_packet import build_packet
    p,s,m=sample();scheduled,report=schedule_action_plan(p,s,m)
    context={'creative_brief':{'theme':'平静表达界限'},'script':s,
        'shots':compile_state_plan(p,s,m),'state_plan':p,'static_visual_manifest':m,
        'scheduled_state_plan':scheduled,'scheduling_report':report}
    packet=build_packet(context)
    raw={'schema':'focused_semantic_review/v1','context_sha256':packet['context_sha256'],
        'checks':[{'check_id':c['check_id'],'status':'passed','reason':'fixture only; no real semantic approval',
                   'issue_ids':[],'unknown':None} for c in packet['checks']],
        'issues':[],'suggestions':[],'calibration_focus':[],'pending':[]}
    return context,packet,raw


def test_focused_stage_replay_and_existing_assistant_gate(tmp_path):
    context,packet,raw=review_fixture();w,clients=workflow(tmp_path,[raw])
    from src.content_factory.creative_narrative_focus import bind_narrative_focus
    w.state['narrative_focus_binding']=bind_narrative_focus()
    key='writer_check__state_plan_00'
    from src.content_factory.creative_narrative_transfer import enrich_review_context, digest
    raw['context_sha256']=digest(enrich_review_context(w.state['narrative_focus_binding'],key,context))
    result=w._stage(key,'writer',context,lambda v:None)
    assert w._stage(key,'writer',context,lambda v:None)==result
    assert len(clients.calls)==1
    assert '文本审查：' in clients.calls[0][1][0]['content']
    assert '沿用现有输出合同' in clients.calls[0][1][0]['content']
    assert 'state_plan' not in json.loads(clients.calls[0][1][1]['content'])
    assert w._verified_review(key,result,context) is None
    assert w.state['status']=='script_review_pending'
    assert not (tmp_path/'STATE_PLAN.json').exists()
    assert json.loads((tmp_path/(key+'.json')).read_text(encoding='utf-8'))['output']==raw


def test_unknown_stops_without_paid_retry_and_resolution_is_bound(tmp_path):
    from src.content_factory.creative_review_packet import iter_source_map
    from src.content_factory.creative_review_gate import digest
    context,packet,raw=review_fixture()
    raw['checks'][0].update(status='unknown',unknown={'reason_code':'AMBIGUOUS_ACTION',
        'missing_evidence':['需核对原文动作含义'],'owner_stage':'action_plan','action':'读取对应原文人工复核'})
    w,clients=workflow(tmp_path,[raw]);key='writer_check__state_plan_00'
    for _ in range(2):
        with pytest.raises(CreativeContractError,match='NEEDS_RESOLUTION'):
            w._stage(key,'writer',context,lambda v:None)
    assert len(clients.calls)==1 and w.state['pending_focused_review']['key']==key
    ref=next(sid for path,sid in iter_source_map(packet) if path=='shots.shots.0.visible_performance')
    resolution={'schema':'focused_review_resolution/v1','context_sha256':digest(context),
        'raw_review_sha256':digest(raw),'reviewed_by':'assistant','reviewed_full_text':True,
        'resolutions':[{'check_id':raw['checks'][0]['check_id'],'status':'passed',
            'reason':'test-only explicit resolution, not a production approval','evidence_ids':[ref],'issue_ids':[]}],
        'additional_issues':[]}
    (tmp_path/(key+'__focused_resolution.json')).write_text(json.dumps(resolution),encoding='utf-8')
    result=w._stage(key,'writer',context,lambda v:None)
    assert len(clients.calls)==1 and 'pending_focused_review' not in w.state
    assert w._verified_review(key,result,context) is None
    resolution['raw_review_sha256']='stale'
    (tmp_path/(key+'__focused_resolution.json')).write_text(json.dumps(resolution),encoding='utf-8')
    with pytest.raises(CreativeContractError,match='当前上下文和原审核'):
        w._verified_review(key,result,context)


@pytest.mark.parametrize('reason',['SOURCE_MISSING','EXPRESSION_UNSUPPORTED','REQUIREMENT_CONFLICT','source_missing',' expression_unsupported '])
def test_blocked_unknown_cannot_be_manually_overridden(reason):
    from src.content_factory.creative_review_resolution import apply_resolution
    context,packet,raw=review_fixture()
    raw['checks'][0].update(status='unknown',unknown={'reason_code':reason,
        'missing_evidence':['缺失'],'owner_stage':'writer','action':'修复源内容'})
    with pytest.raises(CreativeContractError,match='不能人工覆盖'):
        apply_resolution(raw,context,{})


@pytest.mark.parametrize('artifact',['request','raw','disposition','input'])
def test_focused_receipt_tampering_cannot_reach_assistant_gate(tmp_path,artifact):
    context,packet,raw=review_fixture();w,clients=workflow(tmp_path,[raw]);key='writer_check__state_plan_00'
    result=w._stage(key,'writer',context,lambda v:None)
    suffix={'request':'.json','raw':'.json','disposition':'__disposition.json','input':'__focused_input.json'}[artifact]
    path=tmp_path/(key+suffix);saved=json.loads(path.read_text(encoding='utf-8'))
    if artifact=='request':saved['request']['messages'][0]['content']='tampered'
    elif artifact=='raw':saved['response_text']='{}'
    elif artifact=='disposition':saved['can_handoff']=False
    else:saved['context_sha256']='tampered'
    path.write_text(json.dumps(saved),encoding='utf-8')
    with pytest.raises((RuntimeError,CreativeContractError)):
        w._verified_review(key,result,context)
    assert len(clients.calls)==1

def test_unsupported_response_stops_before_contract_repair(tmp_path):
    plan,script,manifest=sample()
    unavailable={'status':'unsupported','code':'EXPRESSION_UNSUPPORTED',
        'source_paths':['script.beats.0.event'],'reason':'test-only source cannot be expressed'}
    w,clients=workflow(tmp_path,[unavailable])
    payload={'state_plan_version':plan['schema'],'script':script,'static_visual_manifest':manifest,
        'creative_brief':{'theme':'测试'},'plan_thinking_mode':'disabled'}
    for _ in range(2):
        with pytest.raises(CreativeContractError,match='EXPRESSION_UNSUPPORTED'):
            w._stage('director_state_plan__00','director',payload,
                lambda value:validate_state_plan(value,script,manifest))
    assert len(clients.calls)==1
    assert w.state['contract_repairs_used']==0
    assert not list(tmp_path.glob('*contract_repair*'))
    receipt=json.loads((tmp_path/'director_state_plan__00__unavailable.json').read_text(encoding='utf-8'))
    assert receipt['detail']['semantic_judgment_verified'] is False
    assert receipt['automatic_retry'] is False


def test_unconfirmed_focused_transport_never_retries(tmp_path):
    context,packet,raw=review_fixture();w,clients=workflow(tmp_path,[])
    def uncertain(*args,**kwargs):
        clients.calls.append('started')
        raise TimeoutError('provider response uncertain')
    w._call_model=uncertain
    with pytest.raises(TimeoutError):w._stage('writer_check__state_plan_00','writer',context,lambda v:None)
    with pytest.raises(RuntimeError,match='禁止自动重复付费'):
        w._stage('writer_check__state_plan_00','writer',context,lambda v:None)
    assert len(clients.calls)==1


def test_focused_budget_exhaustion_no_submission(tmp_path):
    context,packet,raw=review_fixture();w,clients=workflow(tmp_path,[raw])
    w.state['calls_started']=w.max_calls
    with pytest.raises(RuntimeError,match='预算已满'):
        w._stage('writer_check__state_plan_00','writer',context,lambda v:None)
    assert not clients.calls

@pytest.mark.parametrize('tamper',['none','source_status','source_hash','pending','raw_review'])
def test_handoff_rechecks_original_source_and_review(tmp_path,tamper):
    from src.content_factory.creative_state_plan_binding import bind_reviewed_state_plan
    context,packet,raw=review_fixture();plan=context['state_plan']
    w,clients=workflow(tmp_path,[plan,raw])
    w.state['segmented_director_binding']={'version':'reviewed_beat_storyboard_v6',
        'state_plan_version':'whole_film_action_plan_v2'}
    source='director_state_plan__00';review='writer_check__state_plan_00'
    payload={'state_plan_version':plan['schema'],'script':context['script'],
        'static_visual_manifest':context['static_visual_manifest'],'plan_thinking_mode':'disabled'}
    w._stage(source,'director',payload,lambda p:validate_state_plan(p,context['script'],context['static_visual_manifest']))
    result=w._stage(review,'writer',context,lambda v:None)
    assert w._verified_review(review,result,context) is None
    decision=json.loads((tmp_path/(review+'__decision_template.json')).read_text(encoding='utf-8'))
    decision.update(reviewed_full_text=True,summary='Offline fixture only, not real production approval')
    (tmp_path/(review+'__assistant_decision.json')).write_text(json.dumps(decision),encoding='utf-8')
    assert w._verified_review(review,result,context)==[]
    for name,value in [('STATE_PLAN',{'schema':'creative_reviewed_state_plan/v1','source_stage':source,'review_stage':review,'plan':plan}),
                       ('static_visual_manifest',{'output':context['static_visual_manifest']}),
                       ('SCHEDULED_STATE_PLAN',context['scheduled_state_plan']),('SCHEDULING_REPORT',context['scheduling_report'])]:
        (tmp_path/(name+'.json')).write_text(json.dumps(value),encoding='utf-8')
    from src.content_factory.creative_governed_runtime import focused_artifacts
    artifacts=focused_artifacts(w)
    assert review+'.json' in artifacts and source+'.json' in artifacts
    if tamper in ('source_status','source_hash'):
        path=tmp_path/(source+'.json');record=json.loads(path.read_text(encoding='utf-8'))
        record['status' if tamper=='source_status' else 'output_sha256']='tampered'
        path.write_text(json.dumps(record),encoding='utf-8')
    elif tamper=='pending':w.state['pending_focused_review']={'key':review}
    elif tamper=='raw_review':
        path=tmp_path/(review+'.json');record=json.loads(path.read_text(encoding='utf-8'));record['response_text']='{}'
        path.write_text(json.dumps(record),encoding='utf-8')
    if tamper=='none':
        bound,_=bind_reviewed_state_plan(w,context['script'],context['shots'])
        assert bound['state_plan']==plan
    else:
        with pytest.raises((RuntimeError,CreativeContractError)):
            bind_reviewed_state_plan(w,context['script'],context['shots'])
    if tamper in ('pending','raw_review'):
        with pytest.raises((RuntimeError,CreativeContractError)):
            focused_artifacts(w)
    assert len(clients.calls)==2
