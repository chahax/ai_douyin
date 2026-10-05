"""Explicit S6 direction/performance/handoff continuation with inherited unknown70."""
from copy import deepcopy
from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,sys
from scripts import run_creative_resume_v4 as source
from scripts import creative_resume_dispatch_v3 as control
from scripts.prepare_creative_call_evidence_repair_v1 import inspect_original
from scripts import step_index_full_schema_adapter_v6 as physical
from scripts import run_creative_resume_v7 as previous
from scripts import creative_compact_local_contract_v2 as local_contract
from scripts import creative_joint_source_binding_v10 as joint
from scripts import creative_compact_review_transport_v8 as compact

VERSION='s6_director_performance_handoff_continuation/v8'
PROJECT=Path(__file__).resolve().parents[1]
ROOT=source.ROOT.parent/'resume_20261005_v8'
SHARED_LOCK=source.legacy.previous.definition.DIAGNOSTIC/'DISPATCH.lock'
ANCHOR=PROJECT/'data/qa/creative_response_live_acceptance_20261005/SPEND_CONTINUATION_ANCHOR.json'
USER_AUTH={'user_quote':'开始实际表演窗口和制作交接','scope':'S6 complete direction, local actual performance, deterministic compilation, necessary full text review and handoff',
 'writer_model':'MiniMax-M3','review_model':'deepseek-flash','aggregate_token_cap':None,'automatic_retry':False,
 'old_call70_result':'unknown','old_call70_reservation':64010,'old_call70_resend_authorized':False,
 'old_call70_resolved':False,'media_calls_authorized':False,'old_budget_reset':False,
 'prior_single_test_exception_not_used_as_authority':True,'continuation_of_v5_user_instruction':True,'local_validation_schema_repair':True,'compact_local_contract':True,'single_operation_local_contract':True,'new_instruction_required_for_this_continuation':True}

def _parent_binding_uncached():
    prior=previous.runtime();ledger=control.read(prior.ledger);prior.check(ledger)
    actual=previous.summary()
    if (actual['effective_calls_started'],actual['effective_reported_tokens'],actual['calls_with_known_usage'],actual['new_unknown_token_reservations'])!=(93,1131229,92,0):
        raise RuntimeError('v5 spend/source changed; reconcile before new dispatch')
    d=previous.latest('direction_s6_r')
    if d['ordinal']!=77 or d['label']!='direction_s6_r6':raise RuntimeError('validated inherited direction changed')
    decision=control.read(previous.previous.previous.ROOT/'DIRECTION_DECISION_call77.json')
    if not decision['approved_for_local_text_generation'] or decision['direction_sha256']!=control.digest(d['output']):raise RuntimeError('source direction adoption changed')
    old=inspect_original(PROJECT,PROJECT/'data/production_records/this_time_i_leave_s6_20261005/BASELINE_RECORD.json',PROJECT/'data/production_records/this_time_i_leave_s6_20261005/CODE_BINDING_MANIFEST.json')
    anchor={'schema':'s6_compact_local_inherited_anchor/v8','calls_started':93,'reported_tokens':1131229,'calls_with_known_usage':92,'unknown_token_reservations':64010,'pending_ordinals':[70],
      'prior_ledger_file':str(prior.ledger),'prior_ledger_sha256':control.sha_file(prior.ledger),
      'director_ordinal':77,'director_sha256':control.digest(d['output']),'director_decision_sha256':control.sha_file(previous.previous.previous.ROOT/'DIRECTION_DECISION_call77.json'),
      'adopted_local_decisions_sha256':{str(previous.ROOT/f'LOCAL_SOURCE_DECISION_call{n}.json'):control.sha_file(previous.ROOT/f'LOCAL_SOURCE_DECISION_call{n}.json') for n in (83,86)},
      'old49_frozen_budget':old['original_starting_spend'],'repair_scope':'exactly one operation object or null per group; original first two locals reused; no content patch'}
    saved=ROOT/'INHERITED_SPEND_ANCHOR.json'
    if saved.exists() and control.read(saved)!=anchor:raise RuntimeError('inherited v5 anchor changed')
    return old,anchor,ledger


_PARENT_CACHE=None

def _parent_fingerprint():
    # Frozen ancestors and workspace sources only. Current run and live locks excluded.
    paths=set()
    for folder in (previous.ROOT.parent,PROJECT/'data/production_records/this_time_i_leave_s6_20261005',PROJECT/'data/production_trials/boundary_live_action_reference_v15_20261001/round_01'):
        for p in folder.rglob('*'):
            if not p.is_file() or p.name=='DISPATCH.lock' or '__pycache__' in p.parts:continue
            if p.is_relative_to(ROOT):continue
            paths.add(p)
    ledger=control.read(previous.ROOT/'CALL_LEDGER.json')
    paths.update(PROJECT/rel for rel in ledger['source_manifest'])
    return {str(p.resolve()):control.sha_file(p) for p in sorted(paths)}


def parent_binding():
    global _PARENT_CACHE
    key=(str(ROOT.resolve()),str(previous.ROOT.resolve()))
    before=_parent_fingerprint()
    if _PARENT_CACHE is None or _PARENT_CACHE[0]!=key:
        value=_parent_binding_uncached()
        after=_parent_fingerprint()
        if before!=after:raise RuntimeError('frozen parents changed during full verification')
        _PARENT_CACHE=(key,after,value)
    elif before!=_PARENT_CACHE[1]:
        raise RuntimeError('verified frozen parent files changed; full reconciliation required')
    value=_PARENT_CACHE[2]
    saved=ROOT/'INHERITED_SPEND_ANCHOR.json'
    if saved.exists() and control.read(saved)!=value[1]:raise RuntimeError('inherited v8 anchor changed')
    return deepcopy(value)


def runtime():
    old,anchor,ledger=parent_binding()
    inherited={**deepcopy(old['original_starting_spend']),'calls_started':93,'reported_tokens':1131229,'calls_with_known_usage':92,
      'unknown_token_reservations':64010,'pending_ordinals':[70],'new_user_instruction':USER_AUTH['user_quote'],'schema_repair_anchor_sha256':control.digest(anchor)}
    sources=[PROJECT/rel for rel in ledger['source_manifest']]+[PROJECT/'scripts/creative_compact_local_contract_v2.py',Path(__file__).resolve(),PROJECT/'tests/test_creative_resume_v8.py']
    def guard():
        parent_binding()
        if control.read(ROOT/'CREATIVE_CONTINUATION_AUTHORIZATION.json')!=USER_AUTH:raise RuntimeError('continuation authorization changed')
    return control.ContinuationRuntime(PROJECT,ROOT,sources,inherited,old['model_configs'],inherited_guard=guard,quota_state=None,shared_lock=SHARED_LOCK)


def prepare():
    parent_binding();control.write(ROOT/'CREATIVE_CONTINUATION_AUTHORIZATION.json',USER_AUTH,True)
    value=runtime().prepare();control.write(ROOT/'INHERITED_SPEND_ANCHOR.json',parent_binding()[1],True)
    return summary()


def summary():
    r=runtime();value=r.summary();ledger=control.read(r.ledger)
    known=sum(type(r.effective_receipt(row).get('response_metadata',{}).get('total_tokens'))is int for row in ledger['calls'])
    value.update(inherited_unknown_token_reservations=64010,new_unknown_token_reservations=value['unknown_token_reservations'],
      unknown_token_reservations=64010+value['unknown_token_reservations'],calls_with_known_usage=92+known,
      inherited_pending_ordinals=[70],original_call70_recovered=False,media_calls=0)
    return value


_CONTEXT_CACHE=None

def context():
    global _CONTEXT_CACHE
    if _CONTEXT_CACHE is not None:return deepcopy(_CONTEXT_CACHE)
    ctx=source.director_context(6)
    baseline=control.read(PROJECT/'data/production_records/this_time_i_leave_s6_20261005/BASELINE_RECORD.json')
    if control.digest(ctx['raw_linear_script'])!=baseline['script_sha256']:raise RuntimeError('S6 script changed')
    ctx['production_responsibility']={'whole_film_direction':'信息、观察、因果与情绪重心、切镜理由、源步骤覆盖、必要反应要求及开场初态',
      'local_performance':'逐镜完整动作、对白前中后与听者反应的实际窗口、状态转移，不改变原steps',
      'compiler':'验证原步骤、跨镜状态、时间及反应绑定并确定性生成实际全片排时',
      'editorial_intent':'真实克制的释放；拒绝后工作由林屿接回，方澄拿包携票真正离开；不新增惩罚、奖励、第三角色或走廊资产'}
    _CONTEXT_CACHE=deepcopy(ctx)
    return ctx


def network_identity(wire):
    return control.digest({k:wire.get(k) for k in ('model','messages','structured_schema','parameters')})


def wire(role,messages,schema,cap,provenance):
    cfg=source.legacy.role_config(role);expected=parent_binding()[0]['model_configs'][role]
    if cfg.model!=expected['model'] or cfg.base_url!=expected['base_url']:raise RuntimeError('unverified role model/endpoint change')
    value=source.wire(role,messages,schema,cap,provenance);value['operator_version']=VERSION
    old70=control.read(source.ROOT/'call_070_direction_s6_r2.json')
    if network_identity(value)==network_identity(old70['request']):raise RuntimeError('cannot resend unresolved original70 request')
    return value


def dispatch(label,request,validator):
    preview=ROOT/'request_previews'/f'{label}.json';control.write(preview,request,True)
    ctx=context()
    def contains(item,target):
        if type(item)is type(target) and item==target:return True
        if isinstance(item,dict):return any(contains(x,target) for x in item.values())
        if isinstance(item,list):return any(contains(x,target) for x in item)
        return False
    inputs=[]
    for message in request['messages']:
        try:inputs.append(json.loads(message['content']))
        except (ValueError,TypeError):pass
    if not any(contains(item,ctx['reference_pack']) for item in inputs):raise RuntimeError('full reference missing from actual messages')
    if not any(contains(item,ctx['raw_linear_script']) for item in inputs):raise RuntimeError('exact full S6 missing from actual messages')
    check={'request_sha256':control.digest(request),'full_reference_pack_in_actual_messages':True,
      'raw_s6_script_unchanged':True,'not_same_network_payload_as_unknown70':True,'old_unknown_reservation_preserved':64010}
    control.write(ROOT/'request_previews'/f'{label}_INPUT_VERIFICATION.json',check,True)
    return runtime().dispatch(label,request,validator)


def records():
    r=runtime();r.check(control.read(r.ledger));values=[v for v in previous.records() if v['ordinal'] in (77,83,86)]
    for row in control.read(r.ledger)['calls']:
        value=source.stage_record_view(r.effective_receipt(row))
        if value['label'].startswith('local_') and value['status']=='contract_valid':
            value['original_compact_model_document']=deepcopy(value['output'])
            value['output']=deepcopy(value['validation']['derived_local'])
        values.append(value)
    return values

def latest(prefix):
    matches=[r for r in records() if r['label'].startswith(prefix)]
    if not matches:raise RuntimeError('stage missing: '+prefix)
    result=max(matches,key=lambda r:r['ordinal'])
    if result['status']!='contract_valid':raise RuntimeError('latest stage is not valid: '+result['label'])
    return result


def direction(revision=1,feedback=None):
    ctx=context();messages=physical.build_direction_messages(ctx)
    if feedback:messages.append({'role':'user','content':json.dumps({'verified_direction_faults':feedback,'request':'提交完整新导演稿，保持原steps，不修补旧输出。'},ensure_ascii=False)})
    request=wire('writer',messages,physical.build_direction_schema(ctx),8000,
      {'raw_script_sha256':control.digest(ctx['raw_linear_script']),'reference_pack_sha256':control.digest(ctx['reference_pack']),
       'full_reference_pack_in_messages':True,'source_script_ordinal':67,'source_script_review_ordinal':68,'actual_selected_images':[]})
    def validate(raw):
        physical.validate_direction(raw,ctx)
        return {'source_coverage_valid':True,'shots':len(physical._shots(raw)),'semantic_approval':False}
    return dispatch(f'direction_s6_r{revision}',request,validate)


def direction_source(revision):
    record=latest('direction_s6_r')
    if record['label']!=f'direction_s6_r{revision}':raise RuntimeError('direction superseded')
    ctx=context();physical.validate_direction(record['output'],ctx)
    return ctx,record['output']


def local_sources(drevision,count):
    values=[]
    for i in range(1,count+1):
        rec=latest(f'local_s6_d{drevision}_p{i:03}_r')
        decision_root=previous.ROOT if rec['ordinal'] in (83,86) else ROOT
        decision=control.read(decision_root/f"LOCAL_SOURCE_DECISION_call{rec['ordinal']}.json")
        if not decision.get('approved_for_next_local_text'):raise RuntimeError('source local approval required')
        if rec['ordinal'] not in (83,86) and decision.get('derived_local_sha256')!=control.digest(rec['output']):raise RuntimeError('source approval binding changed')
        values.append(rec['output'])
    return values


def local(drevision,index,revision=1,feedback=None):
    ctx,d=direction_source(drevision);previous=local_sources(drevision,index-1)
    inp=physical.build_local_input(ctx,d,previous);messages=local_contract.build_messages(inp)
    if feedback:messages.append({'role':'user','content':json.dumps({'verified_local_faults':feedback,'request':'基于真实首态提交本镜完整新表演方案，不改原steps或拼接旧输出。'},ensure_ascii=False)})
    request=wire('writer',messages,local_contract.build_schema(inp),4096,
      {'local_input_sha256':control.digest(inp),'current_shot':inp['shot_id'],'previous_locals_sha256':[control.digest(x) for x in previous],
       'raw_script_sha256':control.digest(ctx['raw_linear_script']),'reference_pack_sha256':control.digest(ctx['reference_pack']),'full_reference_pack_in_messages':True})
    def validate(raw):
        derived=local_contract.derive_local(raw,inp)
        compiled=physical.compile_prefix(ctx,d,previous+[derived])
        control.write(ROOT/f'PREFIX_d{drevision}_p{index:03}_{control.digest(compiled)[:12]}.json',compiled,True)
        return {'compiled_prefix_shots':len(previous)+1,'physical_state_checked':True,'declared_windows_checked':True,'semantic_approval':False,'derived_local':derived,'original_compact_document_sha256':control.digest(raw),'deterministic_projection_only':True}
    return dispatch(f'local_s6_d{drevision}_p{index:03}_r{revision}',request,validate)


def complete(drevision):
    ctx,d=direction_source(drevision);locals_=local_sources(drevision,len(physical._shots(d)))
    compiled=physical.compile_complete(ctx,d,locals_)
    control.write(ROOT/f'COMPLETE_d{drevision}_{control.digest(compiled)[:12]}.json',compiled,True)
    return ctx,d,locals_,compiled


def final_context(drevision):
    ctx,d,locals_,compiled=complete(drevision)
    ctx['script']=source.derive(ctx['raw_linear_script']);ctx['script'].pop('screenplay_markdown')
    ctx.update(shots=deepcopy(compiled['storyboard']),state_plan=deepcopy(compiled['derived_action_plan']),
      whole_film_direction=deepcopy(d),execution_script=deepcopy(compiled['derived_execution_script']),
      execution_bindings=[{k:deepcopy(t[k]) for k in ('shot_id','source_ref','anchor','kind','start','end')} for t in compiled['source_trace']],
      declared_performance_window_checks=deepcopy(compiled['performance_checks']))
    return ctx,compiled


def final_review(drevision,revision=1):
    ctx,compiled=final_context(drevision);joint.preflight(ctx)
    messages=source.review_wire.joint_messages(ctx,source.joint_review_messages(ctx),joint.build_messages_addendum(ctx))
    request=wire('director',messages,source.review_wire.schema(ctx),24000,
      {'compiled_sha256':control.digest(compiled),'review_context_sha256':compact.context_digest(ctx),'whole_film_full_text_review':True,
       'raw_script_sha256':control.digest(ctx['raw_linear_script']),'reference_pack_sha256':control.digest(ctx['reference_pack']),'full_reference_pack_in_messages':True})
    def validate(raw):
        expanded=compact.expand_review(raw,ctx);joint.validate_joint_review(expanded,ctx)
        return {'complete_joint_review_valid':True,'issue_count':len(expanded['issues']),'story_preserved':expanded['story_preserved'],'semantic_approval':False}
    return dispatch(f'final_review_s6_d{drevision}_r{revision}',request,validate)


def finalize(drevision,evidence):
    ctx,compiled=final_context(drevision);record=latest(f'final_review_s6_d{drevision}_r')
    review=compact.expand_review(record['output'],ctx);joint.validate_joint_review(review,ctx)
    if review['issues'] or not review['story_preserved']:raise RuntimeError('unresolved full text review issues')
    evidence=source.verify_assistant_evidence(ctx,evidence)
    out=ROOT/f'DELIVERABLE_s6_d{drevision}';out.mkdir(parents=True,exist_ok=True)
    raw=ctx['raw_linear_script']
    for name,value in [('FULL_SCRIPT.json',raw),('WHOLE_FILM_DIRECTION.json',ctx['whole_film_direction']),
        ('COMPILED_PERFORMANCE.json',compiled),('FULL_TEXT_REVIEW.json',review),
        ('STATIC_ASSET_DEFINITIONS.json',ctx['static_visual_manifest'])]:control.write(out/name,value,True)
    for name,text in [('FULL_SCRIPT.md',source.linear.render_linear_screenplay(raw)+'\n'),
        ('DIRECTOR_PERFORMANCE_PLAN.md',source.render_production_plan(ctx,compiled))]:
        path=out/name
        if path.exists():
            if path.read_text(encoding='utf-8')!=text:raise RuntimeError('delivery text changed')
        else:path.write_text(text,encoding='utf-8')
    handoff={'schema':'creative_text_handoff/resume_v8','status':'text_reviewed_awaiting_human_content_and_aesthetic_confirmation',
      'script_sha256':control.digest(raw),'compiled_sha256':control.digest(compiled),'review_sha256':control.digest(review),
      'assistant_verified_evidence':deepcopy(evidence),'narrative_beats':len(raw['beats']),
      'shots':compiled['execution_shot_count'],'compiled_duration_seconds':compiled['total_duration_seconds'],
      'text_production_handoff_complete':True,'creative_quality_passed':False,'user_quality_confirmation':None,
      'actual_selected_images':[],'actual_images_returned_to_director':False,'component_registry':deepcopy(ctx['component_registry']),
      'asset_sample_selection_status':'awaiting_human_aesthetic_approval','media_calls':0,
      'video_human_review_required':True,'automatic_media_submit':False,'cost_ledger':summary(),
      'old_call70_still_unknown':True,'old_unknown_reservation_preserved':64010,'old_task_or_budget_reset':False,
      'next_steps':['human text/content review','few aesthetic samples under media authorization','human selection',
        'return actually selected images to director and revalidate','generate current video segment only after media scope check',
        'save awaiting_human_review; continue only after explicit user approval with original service tail frame']}
    control.write(out/'PRODUCTION_HANDOFF.json',handoff,True)
    return handoff


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');command=sys.argv[1]
    feedback=control.read(sys.argv[-1]) if sys.argv[-1].endswith('.json') else None
    args=[int(v) for v in sys.argv[2:] if not v.endswith('.json')]
    if command=='prepare':value=prepare()
    elif command=='direction':value=direction(*args,feedback=feedback)
    elif command=='local':value=local(*args,feedback=feedback)
    elif command=='complete':value=complete(*args)[3]
    elif command=='final-review':value=final_review(*args)
    elif command=='report':value=summary()
    else:raise SystemExit('prepare | direction REV | local D INDEX REV | complete D | final-review D REV | report')
    if 'status' in value:print(json.dumps({k:value.get(k) for k in ('ordinal','label','status','validation','failure','validation_error','response_metadata')},ensure_ascii=False,indent=2))
    else:print(json.dumps(value,ensure_ascii=False,indent=2))
