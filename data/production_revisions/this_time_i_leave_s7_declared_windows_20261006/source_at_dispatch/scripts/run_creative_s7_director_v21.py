"""New S7 direction/events/performance/compile chain; S6 never reused."""
from copy import deepcopy
from pathlib import Path
import sys,json,types
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
if __package__ in (None,''):
    pkg=types.ModuleType('scripts');pkg.__path__=[str(PROJECT/'scripts')];sys.modules['scripts']=pkg
from scripts import run_creative_s7_review_v20 as parent
from scripts import run_creative_s7_director_v19 as previous
from scripts import creative_resume_dispatch_v3 as control
from scripts import creative_local_event_performance_v2 as split
from scripts import creative_compact_local_contract_v2 as local_contract
from scripts import creative_review_projection_v11 as view
from scripts import creative_joint_source_binding_v11 as joint
from scripts import creative_review_id_transport_v15 as ids
source=parent.source;physical=source.physical;compact=source.compact
ROOT=PROJECT/'data/production_revisions/this_time_i_leave_s7_direction_constraints_20261005'
VERSION='s7_reviewed_direction_performance/v21_constraints'
AUTH={'scope':'new complete S7 director, local model events and actual performance, deterministic compile and necessary full joint review','automatic_retry':False,'aggregate_token_cap':None,'media_calls':0,'old_calls70_160_repeated':False,'old_budget_reset':False,'user_creative_quality_approval':False}


def require_reviewed_source():
    proof=control.read(parent.ROOT/'REVIEWED_SCRIPT_s7/STATUS.json')
    if proof.get('status')!='reviewed_complete_script_awaiting_new_director_and_actual_performance' or proof.get('script_sha256')!=control.digest(parent.latest('draft_s7_r')['output']):raise RuntimeError('reviewed complete S7 source required')
    review=parent.latest('script_review_s7_r');ctx=parent.script_context()
    result=source.review_wire.validate_script_review(parent.expand_review(review['output'],ctx),ctx)
    if result['issues'] or not result['story_preserved']:raise RuntimeError('unresolved full script review')
    if proof['review_ordinal']!=review['ordinal']:raise RuntimeError('script review superseded')
    return proof


def prepare():
    require_reviewed_source()
    if (ROOT/'ANCHOR.json').exists():return runtime().prepare()
    prior=previous.runtime();prior.check(control.read(prior.ledger));spent=previous.summary()
    if spent['new_unknown_token_reservations']:raise RuntimeError('current outcome/usage unresolved')
    ledger=control.read(prior.ledger);snap={str(p.resolve()):control.sha_file(p) for p in previous.ROOT.rglob('*') if p.is_file() and p.name!='DISPATCH.lock' and '__pycache__' not in p.parts}
    a={'calls_started':spent['effective_calls_started'],'reported_tokens':spent['effective_reported_tokens'],'calls_with_known_usage':spent['calls_with_known_usage'],'unknown_token_reservations':93117,'pending_ordinals':[70,160],'parent_files':snap,'parent_sources':list(ledger['source_manifest']),'model_configs':ledger['model_configs'],'reviewed_source':require_reviewed_source()}
    control.write(ROOT/'ANCHOR.json',a,True);control.write(ROOT/'CONTINUATION_SCOPE.json',AUTH,True)
    return runtime().prepare()


def runtime():
    a=control.read(ROOT/'ANCHOR.json');inherited={k:deepcopy(a[k]) for k in ('calls_started','reported_tokens','calls_with_known_usage','unknown_token_reservations','pending_ordinals')};inherited['parent_anchor_sha256']=control.sha_file(ROOT/'ANCHOR.json')
    def guard():
        previous.runtime().check(control.read(previous.ROOT/'CALL_LEDGER.json'))
        if require_reviewed_source()!=a['reviewed_source']:raise RuntimeError('reviewed source changed')
        for p,h in a['parent_files'].items():
            if control.sha_file(p)!=h:raise RuntimeError('frozen script parent changed')
        if control.read(ROOT/'CONTINUATION_SCOPE.json')!=AUTH:raise RuntimeError('authorization scope changed')
    sources=[PROJECT/p for p in a['parent_sources']]+[Path(__file__).resolve(),PROJECT/'tests/test_creative_s7_director_v21.py']
    return control.ContinuationRuntime(PROJECT,ROOT,sources,inherited,a['model_configs'],inherited_guard=guard,quota_state=None,shared_lock=parent.identity.SHARED_LOCK)


def summary():
    rt=runtime();ledger=control.read(rt.ledger);value=rt.summary();a=control.read(ROOT/'ANCHOR.json')
    known=sum(type((rt.effective_receipt(row).get('response_metadata') or {}).get('total_tokens')) is int for row in ledger['calls'])
    value.update(calls_with_known_usage=a['calls_with_known_usage']+known,new_unknown_token_reservations=value['unknown_token_reservations'],unknown_token_reservations=93117+value['unknown_token_reservations'],inherited_unknown_token_reservations=93117,unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160],media_calls=0)
    return value


def context():
    require_reviewed_source();ctx=source.original();ctx.pop('script');ctx['raw_linear_script']=deepcopy(parent.latest('draft_s7_r')['output'])
    bundle=source.component_registry.build_p03_registry(ctx['static_visual_manifest']);ctx['static_visual_manifest']=source.component_registry.validate_component_bundle(bundle);ctx['component_registry']=bundle
    ctx['linear_script_protocol']=source.linear.VERSION;ctx['script_timing_status']=source.linear.TIMING_STATUS
    ctx['user_content_feedback']=control.read(parent.FEEDBACK)
    ctx['production_responsibility']={'whole_film_direction':'情绪、因果、每镜新增信息/观察主体/切镜理由/必要反应要求；不细排秒数','local_events':'只负责正文合法有用事件与首态前提；临时预检秒数不是表演','local_performance':'完整各slot表演与真实秒数，不改事件、不删对白','compiler':'确定性投影、跨镜状态、真实排时和窗口','editorial_intent':'便利贴信息整体呈现，避免反复揭起压角；拒绝现场标题句，门外看票轻呼气，仍两人；不照搬参考剧情、不加补偿或奖惩','timing_targets_not_yet_verified':{'three_notes_and_list_seconds':'5–6秒目标，实际由局部表演检验','doorway_release_seconds':'1–2秒可读目标，不能生硬定为一秒'}}
    return ctx


def wire(role,messages,schema,cap,provenance):
    value=source.wire(role,messages,schema,cap,provenance);value['operator_version']=VERSION;return value


def dispatch(label,request,validator):
    ctx=context()
    def contains(node,target):
        if type(node)is type(target) and node==target:return True
        if isinstance(node,dict):return any(contains(value,target) for value in node.values())
        if isinstance(node,list):return any(contains(value,target) for value in node)
        return False
    payloads=[]
    for message in request['messages']:
        try:payloads.append(json.loads(message['content']))
        except (ValueError,TypeError):pass
    if not any(contains(p,ctx['reference_pack']) for p in payloads) or not any(contains(p,ctx['raw_linear_script']) for p in payloads):raise RuntimeError('exact full source/reference missing')
    for oldroot,n in ((source.ROOT,70),(parent.parent.ROOT,160)):
        old=next(oldroot.glob(f'call_{n:03}_*.json'))
        if parent.identity.network_identity(request)==parent.identity.network_identity(control.read(old)['request']):raise RuntimeError('old request repeated')
    control.write(ROOT/'request_previews'/f'{label}.json',request,True)
    control.write(ROOT/'request_previews'/f'{label}_INPUT_VERIFICATION.json',{'exact_new_s7_and_full_R01_in_actual_messages':True,'no_s6_performance_reused':True,'old_unknown_reservations':93117,'no_automatic_retry':True},True)
    return runtime().dispatch(label,request,validator)


def records():
    rt=runtime();ledger=control.read(rt.ledger);rt.check(ledger);values=[]
    for row in ledger['calls']:
        rec=source.stage_record_view(rt.effective_receipt(row))
        if rec['label'].startswith('local_') and rec['status']=='contract_valid':
            rec['original_compact_model_document']=deepcopy(rec['output']);rec['output']=deepcopy(rec['validation']['derived_local'])
        values.append(rec)
    return values


def latest(prefix):
    matches=[r for r in records() if r['label'].startswith(prefix)]
    if not matches or matches[-1]['status']!='contract_valid':raise RuntimeError('latest missing/rejected; no S6 fallback')
    return matches[-1]


def direction_schema(ctx):
    schema=physical.build_direction_schema(ctx)
    catalog=physical.source_contract.source_catalog(ctx)
    refs=[row['ref'] for row in catalog];kinds={row['ref']:row['kind'] for row in catalog}
    item=schema['properties']['beats']['items']['properties']['shots']['items']['properties']['performance_requirements']['items']
    clauses=[]
    for index,ref in enumerate(refs):
        choices=[]
        if kinds[ref]=='dialogue':choices.append({'properties':{'relation':{'const':'during'},'stimulus_ref':{'const':ref}}})
        if index:choices.append({'properties':{'relation':{'const':'after'},'stimulus_ref':{'enum':refs[:index]}}})
        if index<len(refs)-1:choices.append({'properties':{'relation':{'const':'before'},'stimulus_ref':{'enum':refs[index+1:]}}})
        clauses.append({'if':{'properties':{'reaction_ref':{'const':ref}}},'then':{'anyOf':choices}})
    item['allOf']=clauses
    item['description']='Exact serial source relation: after reaction later than stimulus; before earlier; during SAME full dialogue only. Ordinary action duration is local performance, not a self-reference reaction window.'
    return schema


def direction(revision=1,feedback=None):
    ctx=context();messages=physical.build_direction_messages(ctx)
    messages[0]['content']+='\n窗口合同：during仅同一完整对白；after的reaction原步骤必须晚于stimulus原步骤；before必须早于。普通action不能用同一自身步骤声明before/during/after最短窗口。仅为重要可读反应和关键对白填写performance_requirements，其余动作的可读表演由局部排时，勿逐动作机械加窗口。不要把观察普通动作的时长写成反应关系；当前编译器不支持动作自引用期间窗。'
    if feedback:messages.append({'role':'user','content':json.dumps({'verified_direction_faults':feedback,'request':'提交完整新导演稿，保持原steps，不修补旧输出。'},ensure_ascii=False)})
    request=wire('writer',messages,direction_schema(ctx),8000,
      {'raw_script_sha256':control.digest(ctx['raw_linear_script']),'reference_pack_sha256':control.digest(ctx['reference_pack']),
       'full_reference_pack_in_messages':True,'source_script_ordinal':parent.latest('draft_s7_r')['ordinal'],'source_script_review_ordinal':parent.latest('script_review_s7_r')['ordinal'],'actual_selected_images':[]})
    def validate(raw):
        physical.validate_direction(raw,ctx)
        return {'source_coverage_valid':True,'shots':len(physical._shots(raw)),'semantic_approval':False}
    return dispatch(f'direction_s7_r{revision}',request,validate)


def direction_source(revision):
    record=latest('direction_s7_r')
    if record['label']!=f'direction_s7_r{revision}':raise RuntimeError('direction superseded')
    decision=control.read(ROOT/f"DIRECTION_SOURCE_DECISION_call{record['ordinal']}.json")
    if decision.get('approved_for_local_text') is not True or decision.get('direction_sha256')!=control.digest(record['output']):raise RuntimeError('whole direction source approval required')
    ctx=context();physical.validate_direction(record['output'],ctx)
    return ctx,record['output']


def assert_plan_binding(local_record,plan_record):
    expected=control.digest(plan_record['output'])
    if local_record['request']['input_provenance'].get('event_plan_sha256')!=expected:
        raise RuntimeError('event plan changed; complete performance revision required')


def local_sources(drevision,count):
    values=[]
    for i in range(1,count+1):
        rec=latest(f'local_s7_d{drevision}_p{i:03}_r')
        decision=control.read(ROOT/f"LOCAL_SOURCE_DECISION_call{rec['ordinal']}.json")
        if decision.get('approved_for_next_local_text') is not True or decision.get('derived_local_sha256')!=control.digest(rec['output']):raise RuntimeError('source local approval required')
        assert_plan_binding(rec,latest(f'plan_s7_d{drevision}_p{i:03}_r'))
        values.append(rec['output'])
    return values


def plan(drevision,index,revision=1,feedback=None):
    ctx,d=direction_source(drevision);prior=local_sources(drevision,index-1)
    inp=physical.build_local_input(ctx,d,prior)
    req=wire('writer',split.plan_messages(inp,feedback),split.plan_schema(inp),3000,
      {'raw_script_sha256':control.digest(ctx['raw_linear_script']),'reference_pack_sha256':control.digest(ctx['reference_pack']),'local_input_sha256':control.digest(inp),'current_shot':inp['shot_id'],'stage':'model_authored_atomic_events'})
    def validate(doc):
        compact_doc=split.plan_as_compact(doc,inp)
        derived=local_contract.derive_local(compact_doc,inp)
        physical.compile_prefix(ctx,d,prior+[derived])
        return {'planning_physical_preflight':True,'not_actual_performance':True,'semantic_approval':False}
    return dispatch(f'plan_s7_d{drevision}_p{index:03}_r{revision}',req,validate)


def local(drevision,index,revision=1,feedback=None):
    ctx,d=direction_source(drevision);prior=local_sources(drevision,index-1)
    inp=physical.build_local_input(ctx,d,prior)
    plan_record=latest(f'plan_s7_d{drevision}_p{index:03}_r')
    decision=control.read(ROOT/f"EVENT_PLAN_SOURCE_DECISION_call{plan_record['ordinal']}.json")
    if not decision.get('approved_for_performance_text') or decision.get('plan_sha256')!=control.digest(plan_record['output']):raise RuntimeError('complete event plan source approval required')
    if plan_record['request']['input_provenance']['local_input_sha256']!=control.digest(inp):raise RuntimeError('event plan belongs to superseded previous local state')
    plan_doc=plan_record['output']
    req=wire('writer',split.performance_messages(inp,plan_doc,feedback),split.performance_schema(plan_doc),4096,
      {'raw_script_sha256':control.digest(ctx['raw_linear_script']),'reference_pack_sha256':control.digest(ctx['reference_pack']),'local_input_sha256':control.digest(inp),'event_plan_sha256':control.digest(plan_doc),'event_plan_ordinal':plan_record['ordinal'],'current_shot':inp['shot_id'],'stage':'complete_fixed_event_performance'})
    def validate(doc):
        compact_doc=split.performance_as_compact(doc,plan_doc,inp)
        derived=local_contract.derive_local(compact_doc,inp)
        compiled=physical.compile_prefix(ctx,d,prior+[derived])
        control.write(ROOT/f'PREFIX_d{drevision}_p{index:03}_{control.digest(compiled)[:12]}.json',compiled,True)
        return {'compiled_prefix_shots':index,'physical_state_checked':True,'declared_windows_checked':True,'semantic_approval':False,'derived_local':derived,'combined_compact_document':compact_doc,'original_event_plan_sha256':control.digest(plan_doc),'original_performance_document_sha256':control.digest(doc),'deterministic_projection_only':True}
    return dispatch(f'local_s7_d{drevision}_p{index:03}_r{revision}',req,validate)


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
    ctx['script_timing_status']='actual_compiled_local_schedule'
    return ctx,compiled



def adopt_direction(evidence):
    record=latest('direction_s7_r');source.verify_assistant_evidence(record['output'],evidence)
    value={'approved_for_local_text':True,'direction_sha256':control.digest(record['output']),'evidence':evidence,'human_quality_approval':False}
    control.write(ROOT/f"DIRECTION_SOURCE_DECISION_call{record['ordinal']}.json",value,True);return value


def adopt_plan(drevision,index,evidence):
    record=latest(f'plan_s7_d{drevision}_p{index:03}_r');source.verify_assistant_evidence(record['output'],evidence)
    value={'approved_for_performance_text':True,'plan_sha256':control.digest(record['output']),'evidence':evidence,'actual_timing_verified':False,'human_quality_approval':False}
    control.write(ROOT/f"EVENT_PLAN_SOURCE_DECISION_call{record['ordinal']}.json",value,True);return value


def adopt_local(drevision,index,evidence):
    record=latest(f'local_s7_d{drevision}_p{index:03}_r');source.verify_assistant_evidence(record['original_compact_model_document'],evidence)
    value={'approved_for_next_local_text':True,'derived_local_sha256':control.digest(record['output']),'evidence':evidence,'human_quality_approval':False}
    control.write(ROOT/f"LOCAL_SOURCE_DECISION_call{record['ordinal']}.json",value,True);return value


def reviewed_final_context(drevision):
    ctx,compiled=final_context(drevision);projected=deepcopy(ctx);projected['shots']=view.project_storyboard(ctx['shots'],ctx);view.validate_projection(ctx['shots'],projected['shots'],ctx);joint.preflight(projected)
    return projected,compiled


def final_review(drevision,revision=1,feedback=None):
    ctx,compiled=reviewed_final_context(drevision);messages=source.joint_review_messages(ctx);catalog=ids.catalog(ctx)
    messages[0]['content']+='\n'+joint.build_messages_addendum(ctx)+'\n引用每项只填本次证据目录ID字符串，schema为'+ids.VERSION+'。全部'+str(len(compact._rows(ctx)))+'镜全文独立核对；目录仅导航，完整原文在输入，程序原样展开并执行全部业务验收。不能把无错发现列major，suggestions只能location/proposal/reason。新稿便利贴、拒绝两句及听者反应、门外释放必须对应实际排时；不能删真问题求通过。'
    messages.append({'role':'user','content':json.dumps({'source_directory':[{'id':k,'path':v['path'],'excerpt':v['quote'][:48]} for k,v in catalog.items()]},ensure_ascii=False,separators=(',',':'))})
    if feedback:messages.append({'role':'user','content':json.dumps({'prior_protocol_fault':feedback,'request':'完整独立重审，不在本地修响应。'},ensure_ascii=False)})
    req=wire('director',messages,ids.schema(ctx),24000,{'compiled_sha256':control.digest(compiled),'review_context_sha256':compact.context_digest(ctx),'evidence_catalog_sha256':control.digest(catalog),'whole_film_full_text_review':True})
    def validate(raw):
        review=compact.expand_review(ids.expand(raw,ctx),ctx);joint.validate_joint_review(review,ctx)
        control.write(ROOT/f'VALIDATED_FULL_REVIEW_d{drevision}_r{revision}.json',review,True)
        return {'complete_joint_review_valid':True,'issue_count':len(review['issues']),'story_preserved':review['story_preserved'],'creative_quality_passed':False}
    return dispatch(f'full_review_s7_d{drevision}_r{revision}',req,validate)


def finalize(drevision,evidence):
    ctx,compiled=reviewed_final_context(drevision);record=latest(f'full_review_s7_d{drevision}_r');review=compact.expand_review(ids.expand(record['output'],ctx),ctx);joint.validate_joint_review(review,ctx)
    if review['issues'] or not review['story_preserved']:raise RuntimeError('unresolved full review')
    source.verify_assistant_evidence(ctx,evidence);out=ROOT/f'DELIVERABLE_s7_d{drevision}';out.mkdir(parents=True,exist_ok=True)
    for name,value in [('FULL_SCRIPT.json',ctx['raw_linear_script']),('WHOLE_FILM_DIRECTION.json',ctx['whole_film_direction']),('COMPILED_PERFORMANCE.json',compiled),('REVIEWED_EXECUTION_VIEW.json',ctx['shots']),('FULL_TEXT_REVIEW.json',review),('STATIC_ASSET_DEFINITIONS.json',ctx['static_visual_manifest'])]:control.write(out/name,value,True)
    for name,text in [('FULL_SCRIPT.md',source.linear.frozen_v2.render_linear_screenplay(ctx['raw_linear_script'])+'\n'),('DIRECTOR_PERFORMANCE_PLAN.md',source.render_production_plan(ctx,{**compiled,'storyboard':ctx['shots']}))]:
        p=out/name
        if p.exists() and p.read_text(encoding='utf-8')!=text:raise RuntimeError('delivery changed')
        if not p.exists():p.write_text(text,encoding='utf-8')
    status={'schema':VERSION,'status':'text_reviewed_awaiting_human_content_and_aesthetic_confirmation','script_sha256':control.digest(ctx['raw_linear_script']),'compiled_sha256':control.digest(compiled),'reviewed_view_sha256':control.digest(ctx['shots']),'review_sha256':control.digest(review),'adopted_review_ordinal':record['ordinal'],'shots':compiled['execution_shot_count'],'compiled_duration_seconds':compiled['total_duration_seconds'],'text_production_handoff_complete':True,'creative_quality_passed':False,'user_quality_confirmation':None,'actual_selected_images':[],'actual_images_returned_to_director':False,'media_calls':0,'video_human_review_required':True,'automatic_media_submit':False,'old_s6_preserved':True,'old_unknown_billing_reservations':93117,'cost_ledger':summary(),'assistant_verified_evidence':evidence}
    control.write(out/'PRODUCTION_HANDOFF.json',status,True);return status


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');op=sys.argv[1]
    if op=='prepare':value=prepare()
    elif op=='direction':value=direction(int(sys.argv[2]))
    elif op=='plan':value=plan(*map(int,sys.argv[2:5]))
    elif op=='local':value=local(*map(int,sys.argv[2:5]))
    elif op=='report':value=summary()
    else:raise ValueError('unsupported standalone operation')
    if isinstance(value,dict) and 'ordinal' in value:value={k:value.get(k) for k in ('ordinal','label','status','validation','validation_error','response_metadata')}
    print(json.dumps(value,ensure_ascii=False,indent=2))
