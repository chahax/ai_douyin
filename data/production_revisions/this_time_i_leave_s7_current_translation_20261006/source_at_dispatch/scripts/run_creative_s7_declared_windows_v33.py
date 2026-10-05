"""Explicit S7 window requirements compiled locally; original model events/performance."""
from copy import deepcopy
from pathlib import Path
import json,sys,types
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
if __package__ in (None,''):
 pkg=types.ModuleType('scripts');pkg.__path__=[str(PROJECT/'scripts')];sys.modules['scripts']=pkg
from scripts import run_creative_s7_outline_and_shots_v32 as previous
parent=previous.parent;control=previous.control;source=previous.source;physical=previous.physical;compact=previous.compact
split=previous.split;local_contract=previous.local_contract;view=previous.view;joint=previous.joint;ids=previous.ids
ROOT=PROJECT/'data/production_revisions/this_time_i_leave_s7_declared_windows_20261006'
VERSION='s7_explicit_window_policy_then_model_performance/v33'
AUTH={'scope':'complete adopted S7 director and opening state; declared minimum windows; full model-authored local events/performance; deterministic compilation and full joint review','automatic_retry':False,'aggregate_token_cap':None,'media_calls':0,'old_budget_reset':False,'user_creative_quality_approval':False,'window_author':'explicit production constraint, not a model-generated response'}
TARGETS=[
 {'key':'before_refusal','shot_id':'SH04','subject':'C01','stimulus_path':'raw_linear_script.beats.2.steps.2','reaction_path':'raw_linear_script.beats.3.steps.0','relation':'after','minimum_seconds':2.0},
 {'key':'refusal_reason','shot_id':'SH05','subject':'C01','stimulus_path':'raw_linear_script.beats.4.steps.0','reaction_path':'raw_linear_script.beats.4.steps.0','relation':'during','minimum_seconds':2.0},
 {'key':'title_refusal','shot_id':'SH05','subject':'C01','stimulus_path':'raw_linear_script.beats.4.steps.1','reaction_path':'raw_linear_script.beats.4.steps.1','relation':'during','minimum_seconds':1.5},
 {'key':'listener_after_refusal','shot_id':'SH06','subject':'C02','stimulus_path':'raw_linear_script.beats.4.steps.1','reaction_path':'raw_linear_script.beats.5.steps.0','relation':'after','minimum_seconds':2.0},
 {'key':'outside_release','shot_id':'SH09','subject':'C01','stimulus_path':'raw_linear_script.beats.7.steps.1','reaction_path':'raw_linear_script.beats.8.steps.0','relation':'after','minimum_seconds':2.0}]


def make_policy(ctx,film):
 return {'schema':'s7_directed_minimum_windows/v1','author':'assistant declared production constraints from user feedback and AGENTS timing rule','source_script_ordinal':161,'source_script_sha256':control.digest(ctx['raw_linear_script']),'film_sha256':control.digest(film),'targets':deepcopy(TARGETS),'actual_timing_verified':False,'model_authored':False,'human_quality_approval':False}


def compile_policy(ctx,film,opening,policy):
 if policy!=make_policy(ctx,film):raise RuntimeError('explicit source-bound S7 window policy changed; rebind and recheck downstream')
 catalog=previous.physical.source_contract.source_catalog(ctx);by_ref={r['ref']:r for r in catalog};shots={s['shot_id']:s for b in film['beats'] for s in b['shots']}
 direction=deepcopy(film);direction['schema']=physical.DIRECTION;direction.update(initial_state=deepcopy(opening['initial_state']),spatial_contract=deepcopy(opening['spatial_contract']))
 for shot in physical._shots(direction):shot['performance_requirements']=[]
 rows={s['shot_id']:s for s in physical._shots(direction)}
 for target in policy['targets']:
  stim=by_ref[target['stimulus_path']];reaction=by_ref[target['reaction_path']];shot=rows[target['shot_id']]
  if reaction['ref'] not in shot['source_step_refs']:raise RuntimeError('reaction outside declared shot')
  if target['relation']=='during':
   step=ctx['raw_linear_script']['beats'][reaction['beat_index']]['steps'][reaction['step_index']]
   chars={c['id']:c['name'] for c in ctx['static_visual_manifest']['characters']}
   if stim['ref']!=reaction['ref'] or step['kind']!='dialogue' or step['speaker']!=chars[target['subject']]:raise RuntimeError('during must original complete dialogue by current subject')
  else:
   if catalog.index(stim)>=catalog.index(reaction):raise RuntimeError('after window must follow completed stimulus')
  shot['performance_requirements'].append({'id':f"W_{shot['shot_id']}_{len(shot['performance_requirements'])+1}",'subject':target['subject'],'stimulus_ref':stim['ref'],'reaction_ref':reaction['ref'],'relation':target['relation'],'minimum_seconds':target['minimum_seconds']})
 physical.validate_direction(direction,ctx);return direction


def prepare():
 if (ROOT/'ANCHOR.json').exists():return runtime().prepare()
 old=previous.runtime();old.check(control.read(old.ledger));spend=previous.summary()
 if spend['new_unknown_token_reservations']:raise RuntimeError('current provider outcome or usage unknown')
 ctx=previous.context();film_record=previous.assembled_film();film=film_record['output'];opening_record=previous.latest('opening_s7_r');opening=opening_record['output']
 proof=control.read(previous.ROOT/f"OPENING_SOURCE_AUDIT_call{opening_record['ordinal']}.json")
 if proof.get('source_accepted_for_critical_window_planning') is not True or proof['initial_state_sha256']!=control.digest(opening):raise RuntimeError('original opening source audit required')
 policy=make_policy(ctx,film);direction=compile_policy(ctx,film,opening,policy)
 snap=previous.flatten_parent_evidence({str(p.resolve()):control.sha_file(p) for p in previous.ROOT.rglob('*') if p.is_file() and p.name!='DISPATCH.lock' and '__pycache__' not in p.parts})
 for p,h in snap.items():
  if control.sha_file(p)!=h:raise RuntimeError('frozen parent changed')
 for name,value in [('CONTEXT.json',ctx),('DIRECTOR_FILM.json',film_record),('OPENING_STATE.json',opening_record),('WINDOW_POLICY.json',policy),('DIRECTION.json',direction),('CONTINUATION_SCOPE.json',AUTH)]:control.write(ROOT/name,value,True)
 ledger=control.read(old.ledger);a={'calls_started':spend['effective_calls_started'],'reported_tokens':spend['effective_reported_tokens'],'calls_with_known_usage':spend['calls_with_known_usage'],'unknown_token_reservations':93117,'pending_ordinals':[70,160],'parent_files':snap,'parent_sources':list(ledger['source_manifest']),'model_configs':ledger['model_configs'],'fixed_files':{name:control.sha_file(ROOT/name) for name in ['CONTEXT.json','DIRECTOR_FILM.json','OPENING_STATE.json','WINDOW_POLICY.json','DIRECTION.json','CONTINUATION_SCOPE.json']},'no_205_model_window_used':True}
 control.write(ROOT/'ANCHOR.json',a,True);return runtime().prepare()


def runtime():
 a=control.read(ROOT/'ANCHOR.json');inherited={k:deepcopy(a[k]) for k in ('calls_started','reported_tokens','calls_with_known_usage','unknown_token_reservations','pending_ordinals')};inherited['parent_anchor_sha256']=control.sha_file(ROOT/'ANCHOR.json')
 def guard():
  for p,h in a['parent_files'].items():
   if control.sha_file(p)!=h:raise RuntimeError('frozen ancestor changed')
  for name,h in a['fixed_files'].items():
   if control.sha_file(ROOT/name)!=h:raise RuntimeError('adopted context/director/state/policy changed')
  for role,cfg in a['model_configs'].items():
   live=source.legacy.role_config(role)
   if live.model!=cfg['model'] or live.base_url!=cfg['base_url']:raise RuntimeError('unverified model switch')
 sources=[PROJECT/p for p in a['parent_sources']]+[Path(__file__).resolve(),PROJECT/'tests/test_creative_s7_declared_windows_v33.py']
 return control.ContinuationRuntime(PROJECT,ROOT,sources,inherited,a['model_configs'],inherited_guard=guard,quota_state=None,shared_lock=parent.identity.SHARED_LOCK)


def summary():
 rt=runtime();ledger=control.read(rt.ledger);value=rt.summary();a=control.read(ROOT/'ANCHOR.json');known=sum(type((rt.effective_receipt(row).get('response_metadata') or {}).get('total_tokens')) is int for row in ledger['calls'])
 value.update(calls_with_known_usage=a['calls_with_known_usage']+known,new_unknown_token_reservations=value['unknown_token_reservations'],unknown_token_reservations=93117+value['unknown_token_reservations'],inherited_unknown_token_reservations=93117,unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160],media_calls=0);return value


def context():return control.read(ROOT/'CONTEXT.json')


def latest(prefix):
 if prefix.startswith('direction_s7_r'):
  return {'label':'direction_s7_r1','output':control.read(ROOT/'DIRECTION.json'),'status':'contract_valid','authoring':'adopted full model direction/state plus explicit local window policy; no paid model window response'}
 rows=[rec for rec in records() if rec['label'].startswith(prefix)]
 if not rows or rows[-1]['status']!='contract_valid':raise RuntimeError('latest missing/rejected; no earlier local fallback')
 return deepcopy(rows[-1])


def direction_source(revision):
 if revision!=1:raise RuntimeError('declared direction revision superseded')
 d=latest('direction_s7_r')['output'];decision=control.read(ROOT/'DIRECTION_SOURCE_DECISION.json')
 if decision.get('approved_for_local_text') is not True or decision.get('direction_sha256')!=control.digest(d):raise RuntimeError('full direction source approval required')
 ctx=context();physical.validate_direction(d,ctx);return ctx,d


def adopt_direction(evidence):
 d=latest('direction_s7_r')['output'];source.verify_assistant_evidence(d,evidence)
 value={'approved_for_local_text':True,'direction_sha256':control.digest(d),'window_policy_sha256':control.sha_file(ROOT/'WINDOW_POLICY.json'),'evidence':evidence,'minimum_windows_author':'explicit production constraint','human_quality_approval':False}
 control.write(ROOT/'DIRECTION_SOURCE_DECISION.json',value,True);return value


def supported_plan_schema(inp):
 schema=split.plan_schema(inp)
 for action in schema['properties']['actions'].get('prefixItems',[]):
  for option in action['properties']['events']['items']['properties']['operation']['anyOf']:
   kinds=option.get('properties',{}).get('kind',{}).get('enum',[])
   if 'affect' in kinds:kinds.remove('affect')
 return schema


def plan(drevision,index,revision=1,feedback=None):
 ctx,d=direction_source(drevision);prior=local_sources(drevision,index-1);inp=physical.build_local_input(ctx,d,prior);schema=supported_plan_schema(inp)
 messages=split.plan_messages(inp,feedback);messages[0]['content']+=' 情绪不写affect状态操作，写在自然表演里。'
 req=wire('writer',messages,schema,3000,{'raw_script_sha256':control.digest(ctx['raw_linear_script']),'reference_pack_sha256':control.digest(ctx['reference_pack']),'local_input_sha256':control.digest(inp),'current_shot':inp['shot_id'],'window_policy_sha256':control.sha_file(ROOT/'WINDOW_POLICY.json'),'stage':'model_authored_atomic_events'})
 def validate(doc):
  from jsonschema import Draft202012Validator
  Draft202012Validator(schema).validate(doc);compact_doc=split.plan_as_compact(doc,inp);derived=local_contract.derive_local(compact_doc,inp);physical.compile_prefix(ctx,d,prior+[derived])
  return {'planning_physical_preflight':True,'not_actual_performance':True,'semantic_approval':False,'unsupported_affect_rejected_before_performance':True}
 return dispatch(f'plan_s7_d{drevision}_p{index:03}_r{revision}',req,validate)

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
 sys.stdout.reconfigure(encoding='utf-8');op=sys.argv[1];args=[int(x) for x in sys.argv[2:]]
 if op=='prepare':value=prepare()
 elif op=='plan':value=plan(*args)
 elif op=='local':value=local(*args)
 elif op=='report':value=summary()
 else:raise ValueError('explicit one-step operation required')
 print(json.dumps(value,ensure_ascii=False,indent=2))
