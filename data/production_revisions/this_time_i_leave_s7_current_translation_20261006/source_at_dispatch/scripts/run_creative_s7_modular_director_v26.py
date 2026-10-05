"""New S7 direction/events/performance/compile chain; S6 never reused."""
from copy import deepcopy
from pathlib import Path
import sys,json,types
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
if __package__ in (None,''):
    pkg=types.ModuleType('scripts');pkg.__path__=[str(PROJECT/'scripts')];sys.modules['scripts']=pkg
from scripts import run_creative_s7_review_v20 as parent
from scripts import run_creative_s7_modular_director_v25 as previous
from scripts import creative_resume_dispatch_v3 as control
from scripts import creative_local_event_performance_v2 as split
from scripts import creative_compact_local_contract_v2 as local_contract
from scripts import creative_review_projection_v11 as view
from scripts import creative_joint_source_binding_v11 as joint
from scripts import creative_review_id_transport_v15 as ids
source=parent.source;physical=source.physical;compact=source.compact
ROOT=PROJECT/'data/production_revisions/this_time_i_leave_s7_modular_scalar_20261005'
VERSION='s7_three_module_direction/v26_scalar'
AUTH={'scope':'new complete S7 film plan, separate opening physical state and critical source windows, deterministic direction assembly, local events/performance and full joint review','automatic_retry':False,'aggregate_token_cap':None,'media_calls':0,'old_calls70_160_repeated':False,'old_budget_reset':False,'user_creative_quality_approval':False}


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
    sources=[PROJECT/p for p in a['parent_sources']]+[Path(__file__).resolve(),PROJECT/'tests/test_creative_s7_modular_director_v26.py']
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
    # Each beat owns its own source and reaction refs; dynamic within-shot ownership
    # remains checked by the unchanged physical business validator.
    template=deepcopy(schema['properties']['beats']['items']);rows=[]
    requirement=deepcopy(template['properties']['shots']['items']['properties']['performance_requirements']['items'])
    schema.setdefault('$defs',{})['PerformanceRequirement']=requirement
    for bi,beat in enumerate(ctx['raw_linear_script']['beats']):
        row=deepcopy(template);row['properties']['beat_id']={'const':beat['id']}
        own=[r['ref'] for r in catalog if r['beat_index']==bi]
        shot=row['properties']['shots']['items']
        shot['properties']['source_step_refs']['items']={'enum':own}
        shot['properties']['performance_requirements']['items']={'allOf':[{'$ref':'#/$defs/PerformanceRequirement'},{'properties':{'reaction_ref':{'enum':own}}}]}
        rows.append(row)
    schema['properties']['beats'].update(prefixItems=rows,items=False)
    return schema


def direction_wire(messages,schema,cap,provenance):
    c=source.legacy.role_config('writer')
    return {'role':'writer','model':c.model,'messages':deepcopy(messages),'structured_schema':deepcopy(schema),
      'parameters':{'max_completion_tokens':cap,'temperature':.4,'thinking':'disabled'},
      'input_provenance':{**deepcopy(provenance),'native_object_tool_schema':True,'server_strict_decoding_claimed':False},'operator_version':VERSION}


def direction(revision=1,feedback=None):
    ctx=context();messages=physical.build_direction_messages(ctx)
    messages[0]['content']+='\n窗口合同：during仅同一完整对白；after的reaction原步骤必须晚于stimulus原步骤；before必须早于。普通action不能用同一自身步骤声明before/during/after最短窗口。仅为重要可读反应和关键对白填写performance_requirements，其余动作的可读表演由局部排时，勿逐动作机械加窗口。不要把观察普通动作的时长写成反应关系；当前编译器不支持动作自引用期间窗。'
    if feedback:messages.append({'role':'user','content':json.dumps({'verified_direction_faults':feedback,'request':'提交完整新导演稿，保持原steps，不修补旧输出。'},ensure_ascii=False)})
    request=direction_wire(messages,direction_schema(ctx),8000,
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


FILM='s7_film_plan/v24'
STATE='s7_opening_state/v24'
WINDOWS='s7_critical_windows/v24'
DURATION_CLASSES={'1s':1.0,'1.5s':1.5,'2s':2.0,'2.5s':2.5,'3s':3.0}


def context():
    p=ROOT/'CONTEXT.json'
    return control.read(p) if p.exists() else previous.context()


def flatten_parent_evidence(initial):
    result=deepcopy(initial);queue=[p for p in result if Path(p).suffix=='.json' and any(w in Path(p).name.lower() for w in ('anchor','prior','inherited'))];seen=set()
    def walk(value):
        if isinstance(value,dict):
            for key,v in value.items():
                if isinstance(key,str) and Path(key).is_absolute() and isinstance(v,str) and len(v)==64 and all(c in '0123456789abcdef' for c in v):
                    if key in result and result[key]!=v:raise RuntimeError('conflicting frozen ancestor hash')
                    if key not in result:
                        result[key]=v
                        if Path(key).suffix=='.json' and any(w in Path(key).name.lower() for w in ('anchor','prior','inherited')):queue.append(key)
                else:walk(v)
        elif isinstance(value,list):
            for v in value:walk(v)
    while queue:
        p=queue.pop()
        if p in seen:continue
        seen.add(p);walk(control.read(p))
    return result


def prepare():
    if (ROOT/'ANCHOR.json').exists():return runtime().prepare()
    require_reviewed_source();old=previous.runtime();old.check(control.read(old.ledger));spend=previous.summary()
    if spend['new_unknown_token_reservations']:raise RuntimeError('current provider outcome or usage unknown')
    ledger=control.read(old.ledger);ctx=previous.context();snap={str(p.resolve()):control.sha_file(p) for p in previous.ROOT.rglob('*') if p.is_file() and p.name!='DISPATCH.lock' and '__pycache__' not in p.parts};snap=flatten_parent_evidence(snap)
    for p,h in snap.items():
        if control.sha_file(p)!=h:raise RuntimeError('frozen parent hash changed')
    control.write(ROOT/'CONTEXT.json',ctx,True)
    a={'calls_started':spend['effective_calls_started'],'reported_tokens':spend['effective_reported_tokens'],'calls_with_known_usage':spend['calls_with_known_usage'],'unknown_token_reservations':93117,'pending_ordinals':[70,160],'parent_files':snap,'parent_sources':list(ledger['source_manifest']),'model_configs':ledger['model_configs'],'context_sha256':control.sha_file(ROOT/'CONTEXT.json'),'reviewed_source':require_reviewed_source(),'lineage_check':'flat immutable ancestor hashes; old lineages validated once at prepare, never migrated'}
    control.write(ROOT/'ANCHOR.json',a,True);control.write(ROOT/'CONTINUATION_SCOPE.json',AUTH,True)
    return runtime().prepare()


def runtime():
    a=control.read(ROOT/'ANCHOR.json');inherited={k:deepcopy(a[k]) for k in ('calls_started','reported_tokens','calls_with_known_usage','unknown_token_reservations','pending_ordinals')};inherited['parent_anchor_sha256']=control.sha_file(ROOT/'ANCHOR.json')
    def guard():
        for p,h in a['parent_files'].items():
            if control.sha_file(p)!=h:raise RuntimeError('frozen ancestor changed')
        if control.sha_file(ROOT/'CONTEXT.json')!=a['context_sha256'] or control.read(ROOT/'CONTINUATION_SCOPE.json')!=AUTH:raise RuntimeError('context or scope changed')
        for role,cfg in a['model_configs'].items():
            live=source.legacy.role_config(role)
            if live.model!=cfg['model'] or live.base_url!=cfg['base_url']:raise RuntimeError('model switch unverified')
    sources=[PROJECT/p for p in a['parent_sources']]+[Path(__file__).resolve(),PROJECT/'tests/test_creative_s7_modular_director_v26.py']
    return control.ContinuationRuntime(PROJECT,ROOT,sources,inherited,a['model_configs'],inherited_guard=guard,quota_state=None,shared_lock=parent.identity.SHARED_LOCK)


def film_schema(ctx):
    result=physical.build_direction_schema(ctx);result['properties']['schema']={'const':FILM}
    for k in ('initial_state','spatial_contract'):result['properties'].pop(k);result['required'].remove(k)
    shot=result['properties']['beats']['items']['properties']['shots']['items'];shot['properties'].pop('performance_requirements');shot['required'].remove('performance_requirements')
    template=deepcopy(result['properties']['beats']['items']);rows=[]
    catalog=physical.source_contract.source_catalog(ctx)
    for index,b in enumerate(ctx['raw_linear_script']['beats']):
        row=deepcopy(template);row['properties']['beat_id']={'const':b['id']}
        row['properties']['shots']['items']['properties']['source_step_refs']['items']={'enum':[v['ref'] for v in catalog if v['beat_index']==index]};rows.append(row)
    result['properties']['beats'].update(prefixItems=rows,items=False);result['description']='Complete whole-film editorial plan only. Do not generate physical state or durations or performance_requirements.'
    return result


def validate_film(raw,ctx):
    from jsonschema import Draft202012Validator
    Draft202012Validator(film_schema(ctx)).validate(raw)
    if '<模型完整填写>' in json.dumps(raw,ensure_ascii=False):raise RuntimeError('film template placeholder is not authored content')
    simple=deepcopy(raw);simple['schema']=physical.source_contract.DIRECTION
    for b in simple['beats']:
        for shot in b['shots']:
            for k in ('purpose','composition','dialogue_mode'):shot.pop(k)
    physical.source_contract.validate_direction(simple,ctx)
    return {'whole_source_coverage_valid':True,'shots':sum(len(b['shots']) for b in raw['beats']),'physical_state_not_generated_here':True,'actual_windows_available':False,'semantic_approval':False}


def state_schema(ctx):
    fields=physical.build_direction_schema(ctx)['properties']
    return physical.obj({'schema':{'const':STATE},'context_sha256':{'const':control.digest(ctx)},'initial_state':deepcopy(fields['initial_state']),'spatial_contract':deepcopy(fields['spatial_contract'])})


def source_ids(ctx):
    return {f'S{i+1:02}':row for i,row in enumerate(physical.source_contract.source_catalog(ctx))}


def window_schema(ctx,film):
    catalog=source_ids(ctx);order=list(catalog);chars=[c['id'] for c in ctx['static_visual_manifest']['characters']];rows=[]
    for shot in [s for b in film['beats'] for s in b['shots']]:
        own=[key for key,row in catalog.items() if row['ref'] in shot['source_step_refs']]
        req=physical.obj({'subject':{'enum':chars},'stimulus_id':{'enum':order},'reaction_id':{'enum':own},'relation':{'enum':['before','during','after']},'duration_class':{'enum':list(DURATION_CLASSES)}})
        clauses=[]
        for rid in own:
            index=order.index(rid);choices=[]
            if catalog[rid]['kind']=='dialogue':choices.append({'properties':{'relation':{'const':'during'},'stimulus_id':{'const':rid}}})
            if index:choices.append({'properties':{'relation':{'const':'after'},'stimulus_id':{'enum':order[:index]}}})
            # before window can only reference a future stimulus within THIS shot.
            future=[key for key in own if order.index(key)>index]
            if future:choices.append({'properties':{'relation':{'const':'before'},'stimulus_id':{'enum':future}}})
            clauses.append({'if':{'properties':{'reaction_id':{'const':rid}}},'then':{'anyOf':choices} if choices else False})
        req['allOf']=clauses
        rows.append(physical.obj({'shot_id':{'const':shot['shot_id']},'requirements':{'type':'array','items':req}}))
    return physical.obj({'schema':{'const':WINDOWS},'context_sha256':{'const':control.digest(ctx)},'film_plan_sha256':{'const':control.digest(film)},'shots':{'type':'array','minItems':len(rows),'maxItems':len(rows),'prefixItems':rows,'items':False}})


def assemble_direction(ctx,film,state,windows):
    from jsonschema import Draft202012Validator
    validate_film(film,ctx);Draft202012Validator(state_schema(ctx)).validate(state);Draft202012Validator(window_schema(ctx,film)).validate(windows)
    out=deepcopy(film);out['schema']=physical.DIRECTION;out.update(initial_state=deepcopy(state['initial_state']),spatial_contract=deepcopy(state['spatial_contract']))
    catalog=source_ids(ctx)
    for shot,row in zip([s for b in out['beats'] for s in b['shots']],windows['shots']):
        shot['performance_requirements']=[{'id':f"W_{shot['shot_id']}_{i+1}",'subject':q['subject'],'stimulus_ref':catalog[q['stimulus_id']]['ref'],'reaction_ref':catalog[q['reaction_id']]['ref'],'relation':q['relation'],'minimum_seconds':DURATION_CLASSES[q['duration_class']]} for i,q in enumerate(row['requirements'])]
    physical.validate_direction(out,ctx);return out


def native_request(messages,schema,cap,prov):
    req=source.wire('writer',messages,schema,cap,prov);req['operator_version']=VERSION;return req


def film_shape_template(ctx):
    catalog=physical.source_contract.source_catalog(ctx)
    rows=[]
    for index,beat in enumerate(ctx['raw_linear_script']['beats']):
        row={'shot_id':f'SH{index+1:02}','source_step_refs':[v['ref'] for v in catalog if v['beat_index']==index]}
        for k in ('new_information','observation_object','camera','cut_reason','purpose','composition'):row[k]='<模型完整填写>'
        row['dialogue_mode']='画内对白' if any(s['kind']=='dialogue' for s in beat['steps']) else '无对白'
        rows.append({'beat_id':beat['id'],'shots':[row]})
    return {'schema':FILM,'context_sha256':control.digest(ctx),'raw_linear_script_sha256':control.digest(ctx['raw_linear_script']),'emotional_arc':'<模型完整填写>','causal_chain':['<模型完整填写>'],'ending_intent':'<模型完整填写>','beats':rows}


def film_plan(revision=1,feedback=None):
    ctx=context();rules=physical.source_contract.RULES+'\n本次只交完整整片情绪/因果/分镜计划，逐镜新增信息、观察对象、构图、摄影、切镜理由和对白模式。初态、道具持有与最短窗口在独立后续模块处理，勿输出这些字段。普通动作尽量同镜完整观察，避免为看清同一事实反复切镜。原十拍正文及R01全文必须读；便利贴整体展示，拒绝两句同镜，门外看票呼气落在方澄身上，仍两人。时长由局部模型后排，不写秒数。'
    payload={'context':ctx,'source_catalog':physical.source_contract.source_catalog(ctx),'verified_feedback':feedback,'complete_shape_template':film_shape_template(ctx),'template_policy':'模板仅演示完整字段与最小每拍一镜的源覆盖，不是正文导演答案。填写所有创作字段，不保留占位词；可因有意义的观察切换新增镜头，但仍按原源覆盖。勿输出item对象包裹数组或把镜头字段放到根。'}
    req=native_request([{'role':'system','content':rules},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],film_schema(ctx),6000,{'stage':'whole_film_editorial_plan','raw_script_sha256':control.digest(ctx['raw_linear_script']),'full_reference_pack_in_messages':True})
    return dispatch(f'film_s7_r{revision}',req,lambda raw:validate_film(raw,ctx))


def opening_state(revision=1,feedback=None):
    from jsonschema import Draft202012Validator
    ctx=context();film=latest('film_s7_r')['output']
    payload={'context':ctx,'whole_film_plan':film,'verified_feedback':feedback,'request':'完整输出首个源步骤开始之前的物理状态和合法空间约定。owner不是holder。三张便利贴在方澄桌E01角、包挂E09椅背、票E01角；明细P05在林屿桌E02上尚未推向两人之间。不要提前推单/取物/递笔。初态仅人物和移动道具；固定门/桌/椅无新增状态。source已有C02坐E10，不必额外安排坐下。所有affect字段完整；位置/朝向是身体，不用视线替代。'}
    req=native_request([{'role':'system','content':'只负责完整开场物理状态；不改正文或导演镜头，不细排动作或秒数。工具字段完整，不默认归属等于手持。'},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],state_schema(ctx),2400,{'stage':'opening_physical_state','film_plan_sha256':control.digest(film),'raw_script_sha256':control.digest(ctx['raw_linear_script']),'full_reference_pack_in_messages':True})
    def validate(raw):
        Draft202012Validator(state_schema(ctx)).validate(raw)
        d=deepcopy(film);d.update(schema=physical.DIRECTION,initial_state=raw['initial_state'],spatial_contract=raw['spatial_contract'])
        for b in d['beats']:
            for shot in b['shots']:shot['performance_requirements']=[]
        physical.validate_direction(d,ctx);return {'initial_state_shape_valid':True,'source_semantics_pending_explicit_adoption':True}
    return dispatch(f'opening_s7_r{revision}',req,validate)


def critical_windows(revision=1,feedback=None):
    from jsonschema import Draft202012Validator
    ctx=context();film=latest('film_s7_r')['output'];state=latest('opening_s7_r')['output'];catalog=source_ids(ctx)
    payload={'context':ctx,'whole_film_plan':film,'opening_physical_state':state,'source_directory':catalog,'verified_feedback':feedback,'request':'每镜requirements数组，只为真正重要的对白/反应声明可读下界：拒绝前方澄看笔抬眼，拒绝两句完整对白，林屿真正听到最后一句后的反应，以及真正出门之后看票呼气。普通推纸/摊贴/取笔/走门/改单不机械加最短反应窗，数组可空。during仅同一完整对白；after反应晚于刺激、before只当前镜内反应早于刺激；reaction_id只能来自所在镜。duration_class填写工具枚举字符串，由程序映射正秒数，不填写数字或minimum_seconds。这只是待满足要求，不代表实际窗口已生成。'}
    req=native_request([{'role':'system','content':'仅完整生成关键表演窗口要求；不重写剧本或镜头、初态。不将普通动作的持续时长写成自引用反应窗口。源ID由真实目录查表，不是剧情内容。'},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],window_schema(ctx,film),2600,{'stage':'critical_performance_requirements','film_plan_sha256':control.digest(film),'opening_state_sha256':control.digest(state),'raw_script_sha256':control.digest(ctx['raw_linear_script']),'full_reference_pack_in_messages':True})
    def validate(raw):
        Draft202012Validator(window_schema(ctx,film)).validate(raw);d=assemble_direction(ctx,film,state,raw)
        return {'complete_source_window_contract_valid':True,'requirements':sum(len(s['performance_requirements']) for s in physical._shots(d)),'actual_windows_available':False,'semantic_approval':False}
    return dispatch(f'windows_s7_r{revision}',req,validate)


def composed_direction():
    ctx=context();f=latest('film_s7_r');s=latest('opening_s7_r');w=latest('windows_s7_r')
    if s['request']['input_provenance']['film_plan_sha256']!=control.digest(f['output']) or w['request']['input_provenance']['film_plan_sha256']!=control.digest(f['output']) or w['request']['input_provenance']['opening_state_sha256']!=control.digest(s['output']):raise RuntimeError('component superseded; complete downstream module revision required')
    d=assemble_direction(ctx,f['output'],s['output'],w['output']);components={key:{'ordinal':rec['ordinal'],'model_document_sha256':control.digest(rec['output'])} for key,rec in (('film',f),('opening',s),('windows',w))}
    control.write(ROOT/f'COMPOSED_DIRECTION_{control.digest(d)[:12]}.json',{'direction':d,'components':components,'deterministic_field_assembly_only':True,'no_old_failed_direction_used':True,'source_script_ordinal':161,'semantic_approval':False},True)
    return {'ordinal':w['ordinal'],'label':'direction_s7_r1','status':'contract_valid','output':d,'source_components':components}


_regular_latest=latest

def latest(prefix):
    if prefix.startswith('direction_s7_r'):return composed_direction()
    return _regular_latest(prefix)


def direction(revision=1,feedback=None):raise RuntimeError('use separate film_plan/opening_state/critical_windows; no monolithic director retry')

SCALAR_FILM='s7_film_scalars/v26'
SCALAR_STATE='s7_opening_scalars/v26'
SCALAR_WINDOWS='s7_window_scalars/v26'
FILM_FIELDS=('new_information','observation_object','camera','cut_reason','purpose','composition','dialogue_mode')


def scalar_film_schema(ctx):
    props={'schema':{'const':SCALAR_FILM},'emotional_arc':physical.text(),'causal_chain':physical.text(),'ending_intent':physical.text()}
    for beat in ctx['raw_linear_script']['beats']:
        for k in FILM_FIELDS:props[beat['id']+'_'+k]={'enum':['画内对白','画外对白','混合对白','无对白']} if k=='dialogue_mode' else physical.text()
    return physical.obj(props)


def decode_scalar_film(raw,ctx):
    from jsonschema import Draft202012Validator
    Draft202012Validator(scalar_film_schema(ctx)).validate(raw)
    if '<模型完整填写>' in json.dumps(raw,ensure_ascii=False):raise RuntimeError('placeholder not authored')
    catalog=physical.source_contract.source_catalog(ctx);rows=[]
    for index,beat in enumerate(ctx['raw_linear_script']['beats']):
        shot={k:raw[beat['id']+'_'+k] for k in FILM_FIELDS}
        shot.update(shot_id=f'SH{index+1:02}',source_step_refs=[v['ref'] for v in catalog if v['beat_index']==index])
        rows.append({'beat_id':beat['id'],'shots':[shot]})
    value={'schema':FILM,'context_sha256':control.digest(ctx),'raw_linear_script_sha256':control.digest(ctx['raw_linear_script']),'emotional_arc':raw['emotional_arc'],'causal_chain':[raw['causal_chain']],'ending_intent':raw['ending_intent'],'beats':rows}
    validate_film(value,ctx);return value


def seat_ids(ctx):
    return [e['id'] for e in ctx['static_visual_manifest']['scene']['elements'] if any(w in e['name'] for w in ('椅','凳','沙发'))]


def scalar_state_schema(ctx):
    canonical=state_schema(ctx)['properties']['initial_state']['properties'];props={'schema':{'const':SCALAR_STATE}}
    for entity,shape in canonical.items():
        for field,typ in shape['properties'].items():props[entity+'_'+field]=deepcopy(typ)
    for sid in seat_ids(ctx):
        props[sid+'_access_positions']=physical.text();props[sid+'_required_facing']=physical.text()
    return physical.obj(props)


def decode_scalar_state(raw,ctx):
    from jsonschema import Draft202012Validator
    Draft202012Validator(scalar_state_schema(ctx)).validate(raw)
    canonical=state_schema(ctx)['properties']['initial_state']['properties'];state={}
    for entity,shape in canonical.items():state[entity]={field:raw[entity+'_'+field] for field in shape['properties']}
    seats=[]
    for sid in seat_ids(ctx):
        positions=raw[sid+'_access_positions'];facing=raw[sid+'_required_facing']
        if positions=='NONE':continue
        choices=[x.strip() for x in positions.split(',')]
        if any(not x for x in choices) or len(set(choices))!=len(choices):raise RuntimeError('invalid seat position scalar')
        seats.append({'seat_id':sid,'access_positions':choices,'required_facing':None if facing=='NONE' else facing})
    value={'schema':STATE,'context_sha256':control.digest(ctx),'initial_state':state,'spatial_contract':{'seats':seats}}
    Draft202012Validator(state_schema(ctx)).validate(value);return value


def scalar_window_schema(ctx,film):
    props={'schema':{'const':SCALAR_WINDOWS}}
    for shot in [s for b in film['beats'] for s in b['shots']]:
        for slot in (1,2):props[shot['shot_id']+'_w'+str(slot)]=physical.text()
    return physical.obj(props)


def decode_scalar_windows(raw,ctx,film):
    from jsonschema import Draft202012Validator
    Draft202012Validator(scalar_window_schema(ctx,film)).validate(raw);rows=[]
    for shot in [s for b in film['beats'] for s in b['shots']]:
        reqs=[]
        for slot in (1,2):
            value=raw[shot['shot_id']+'_w'+str(slot)]
            if value=='NONE':continue
            parts=[x.strip() for x in value.split(',')]
            if len(parts)!=5:raise RuntimeError('window scalar must subject,stimulusID,reactionID,relation,durationClass')
            reqs.append(dict(zip(('subject','stimulus_id','reaction_id','relation','duration_class'),parts)))
        if len({tuple(sorted(q.items())) for q in reqs})!=len(reqs):raise RuntimeError('duplicate window scalar')
        rows.append({'shot_id':shot['shot_id'],'requirements':reqs})
    value={'schema':WINDOWS,'context_sha256':control.digest(ctx),'film_plan_sha256':control.digest(film),'shots':rows}
    Draft202012Validator(window_schema(ctx,film)).validate(value);return value


_previous_latest=latest

def latest(prefix):
    if prefix.startswith('direction_s7_r'):return composed_direction()
    record=_regular_latest(prefix);record=deepcopy(record);raw=record['output'];ctx=context()
    if prefix.startswith('film_s7_r'):record['output']=decode_scalar_film(raw,ctx)
    elif prefix.startswith('opening_s7_r'):record['output']=decode_scalar_state(raw,ctx)
    elif prefix.startswith('windows_s7_r'):record['output']=decode_scalar_windows(raw,ctx,latest('film_s7_r')['output'])
    else:return record
    record['original_scalar_model_document']=deepcopy(raw);return record


def scalar_wire(messages,schema,cap,prov):return direction_wire(messages,schema,cap,{**prov,'scalar_only_model_output':True,'deterministic_projection_no_text_rewrite':True})


def film_plan(revision=1,feedback=None):
    ctx=context();catalog=physical.source_contract.source_catalog(ctx)
    payload={'context':ctx,'source_catalog':catalog,'output_fields':list(scalar_film_schema(ctx)['properties']),'verified_feedback':feedback,'source_allocation_policy':'本次十个完整叙事拍各一个镜头单元，程序按原拍完整steps分配SH01..SH10，不拆原action或句子。导演填写各拍创作字段，不能在camera里偷偷切成多镜。需要改变该策略时完整修订合同，不本地补剪。'}
    rules='用指定工具交一次完整扁平对象，所有创作值为字符串。字段B01_camera等只放根级，绝不beats/shots/item数组，绝不payload_json内再写JSON。本次仅整片情绪、因果、结尾和十镜新增信息/观察对象/构图/摄影/切镜理由/对白模式。全部字段完整，原S7台词和动作不改、参考R01表达机制不照搬剧情。无初态、操作、秒数或窗口字段。前三项反馈已在剧本，导演让便利贴信息整体可见、拒绝两句同镜、林屿真正听到后的反应及门外看票呼气可读，仍两个人。'
    req=scalar_wire([{'role':'system','content':rules},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],scalar_film_schema(ctx),6000,{'stage':'whole_film_editorial_scalars','raw_script_sha256':control.digest(ctx['raw_linear_script']),'full_reference_pack_in_messages':True,'source_allocation_policy':'one complete source beat per shot for this S7 trial'})
    def validate(raw):
        film=decode_scalar_film(raw,ctx);return {**validate_film(film,ctx),'deterministic_source_projection':True,'actor_text_manually_patched':False}
    return dispatch(f'film_s7_r{revision}',req,validate)


def opening_state(revision=1,feedback=None):
    ctx=context();film=latest('film_s7_r')['output']
    payload={'context':ctx,'whole_film_plan':film,'output_fields':list(scalar_state_schema(ctx)['properties']),'verified_feedback':feedback,'source_preconditions':'第一个源步骤之前，C01站自己工位、C02已坐E10。包P01在E09椅背、票P02和一叠三色便利贴在E01桌角，全部无人手持；P05明细单在E02桌面尚未推至两人之间，P06结算单/P07笔/P04杯在林屿桌上无人手持。owner不等于holder，不提前取拿/推单。','seat_scalar_dictionary':'E09_access_positions等填逗号分隔合法身体位置名；不声明该座位填NONE。required_facing填真正身体朝向，未知填NONE；程序原样查表，不把gaze代替facing。'}
    req=scalar_wire([{'role':'system','content':'完整开场物理状态，仅填根级扁平标量字段C01_posture/P01_holder等；无嵌套JSON、items数组。所有字段完整，holder填写清单ID或none，归属与当前持有分开。不得写首动作完成后的状态。'},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],scalar_state_schema(ctx),2400,{'stage':'opening_state_scalars','film_plan_sha256':control.digest(film),'raw_script_sha256':control.digest(ctx['raw_linear_script']),'full_reference_pack_in_messages':True})
    def validate(raw):
        state=decode_scalar_state(raw,ctx);d=deepcopy(film);d.update(schema=physical.DIRECTION,initial_state=state['initial_state'],spatial_contract=state['spatial_contract'])
        for b in d['beats']:
            for shot in b['shots']:shot['performance_requirements']=[]
        physical.validate_direction(d,ctx);return {'opening_physical_contract_valid':True,'source_semantics_pending':True,'deterministic_field_projection_only':True}
    return dispatch(f'opening_s7_r{revision}',req,validate)


def critical_windows(revision=1,feedback=None):
    ctx=context();film=latest('film_s7_r')['output'];state=latest('opening_s7_r')['output'];catalog=source_ids(ctx)
    payload={'context':ctx,'whole_film_plan':film,'opening_physical_state':state,'source_directory':catalog,'output_fields':list(scalar_window_schema(ctx,film)['properties']),'verified_feedback':feedback,'field_grammar':'每镜两个标量槽，值为NONE或subject,stimulusID,reactionID,relation,durationClass；例如另一场景C01,S02,S03,after,2s（示例不得照抄）。durationClass只取1s/1.5s/2s/2.5s/3s。','critical_targets':'只为真正重要的对白/反应：SH04方澄看笔抬眼在递笔之后；SH05两个完整拒绝对白分别during本句；SH06林屿听到最后题句之后可读至少2秒；SH09她真正出门后看票呼气可读1.5–2秒。普通推单/摊贴/取笔/走门/改单不机械声明自引用窗，其余槽填NONE。reactionID归属所在镜，during仅同一完整dialogue，after反应源晚于刺激，before当前镜内早于刺激。'}
    req=scalar_wire([{'role':'system','content':'完整关键窗口要求，根级扁平字符串字段SH01_w1等，不输出数组/对象或内嵌JSON。按目录选择真正源ID和人物，仅选择有意义要求。程序查表源ID、秒数类和结构，不生成新的表演正文。尚无实际秒数窗口，不能自称实际通过。'},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],scalar_window_schema(ctx,film),2400,{'stage':'critical_windows_scalars','film_plan_sha256':control.digest(film),'opening_state_sha256':control.digest(state),'raw_script_sha256':control.digest(ctx['raw_linear_script']),'full_reference_pack_in_messages':True})
    def validate(raw):
        windows=decode_scalar_windows(raw,ctx,film);d=assemble_direction(ctx,film,state,windows)
        return {'critical_windows_source_contract_valid':True,'requirements':sum(len(s['performance_requirements']) for s in physical._shots(d)),'actual_windows_available':False,'deterministic_projection_only':True}
    return dispatch(f'windows_s7_r{revision}',req,validate)

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');op=sys.argv[1]
    if op=='prepare':value=prepare()
    elif op=='film':value=film_plan(int(sys.argv[2]))
    elif op=='opening':value=opening_state(int(sys.argv[2]))
    elif op=='windows':value=critical_windows(int(sys.argv[2]))
    elif op=='compose':value=composed_direction()
    elif op=='plan':value=plan(*map(int,sys.argv[2:5]))
    elif op=='local':value=local(*map(int,sys.argv[2:5]))
    elif op=='report':value=summary()
    else:raise ValueError('unsupported standalone operation')
    if isinstance(value,dict) and 'ordinal' in value:value={k:value.get(k) for k in ('ordinal','label','status','validation','validation_error','response_metadata')}
    print(json.dumps(value,ensure_ascii=False,indent=2))
