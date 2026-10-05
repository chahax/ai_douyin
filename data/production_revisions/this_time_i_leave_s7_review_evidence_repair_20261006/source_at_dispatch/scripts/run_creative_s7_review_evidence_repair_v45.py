"""Focused complete performance with source-bound fixed scalar slots, no arrays."""
from copy import deepcopy
from pathlib import Path
import json,sys,types
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
if __package__ in (None,''):
 pkg=types.ModuleType('scripts');pkg.__path__=[str(PROJECT/'scripts')];sys.modules['scripts']=pkg
from scripts import run_creative_s7_shared_dialogue_review_v44 as previous
from scripts.creative_current_action_translation_v2 import messages as translator_messages,validate_consumed
from scripts.creative_atomic_event_group_lines_v2 import GroupLinesProseOrTools,decode as decode_lines,messages as line_messages
from scripts.creative_s7_native_event_policy_v2 import restrict_schema, messages as native_plan_messages
from scripts import run_creative_s7_outline_and_shots_v32 as director_base
from scripts import run_creative_s7_declared_windows_v33 as window_base
from scripts.creative_dialogue_prose_transport_v1 import ProseOrToolClients, prose_messages
parent=previous.parent;control=previous.control;source=previous.source;physical=previous.physical;compact=previous.compact
split=previous.split;local_contract=previous.local_contract;from scripts import creative_review_projection_v12 as view
from scripts import creative_review_id_transport_v19 as ids
from scripts import creative_joint_source_binding_v13 as joint
ROOT=PROJECT/'data/production_revisions/this_time_i_leave_s7_review_evidence_repair_20261006'
VERSION='s7_compact_review_wire_and_complete_evidence_repair/v45'
AUTH={**previous.AUTH,'scope':'same adopted S7 direction/state/policy and four compatible actual S7 locals; explicit zero-action dialogue plain prose; structural events and other scalar performance; deterministic compilation and full review','local_projection':'fixed slot key lookup, exact original seconds and prose, no action repair'}


def context():return control.read(ROOT/'CONTEXT.json')


def verify_cache_binding(rec,plan,inp):
 expected=control.digest(inp)
 if rec['request']['input_provenance']['local_input_sha256']!=expected or plan['request']['input_provenance']['local_input_sha256']!=expected:raise RuntimeError('cached local belongs to changed script/direction/start state')
 if rec['request']['input_provenance']['event_plan_sha256']!=control.digest(plan['output']):raise RuntimeError('cached local belongs to changed full event plan')


def prepare():
 if (ROOT/'ANCHOR.json').exists():return runtime().prepare()
 old=previous.runtime();old.check(control.read(old.ledger));spend=previous.summary()
 if spend['new_unknown_token_reservations']:raise RuntimeError('current provider outcome or usage unknown')
 ctx,d=previous.context(),previous.latest('direction_s7_r')['output'];proof=control.read(previous.ROOT/'DIRECTION_SOURCE_DECISION.json');assert proof['direction_sha256']==control.digest(d) and proof['approved_for_local_text'];cache=[]
 all_parent=previous.records();adopted=[]
 def parent_latest(prefix):
  rows=[r for r in all_parent if r['label'].startswith(prefix)]
  if not rows or rows[-1]['status']!='contract_valid':raise RuntimeError('complete valid prior source required')
  return rows[-1]
 for index in range(1,11):
  rec=parent_latest(f'local_s7_d1_p{index:03}_r');plan=parent_latest(f'plan_s7_d1_p{index:03}_r');inp=physical.build_local_input(ctx,d,adopted);verify_cache_binding(rec,plan,inp)
  proof=control.read(previous.decision_root(rec)/f"LOCAL_SOURCE_DECISION_call{rec['ordinal']}.json")
  if not proof.get('approved_for_next_local_text') or proof['derived_local_sha256']!=control.digest(rec['output']):raise RuntimeError('prior full local source decision changed')
  adopted.append(rec['output']);cache.append({'shot':index,'local_ordinal':rec['ordinal'],'event_plan_ordinal':plan['ordinal'],'local_input_sha256':control.digest(inp),'event_plan_sha256':control.digest(plan['output']),'derived_local_sha256':control.digest(rec['output']),'source_approved':True})
 physical.compile_prefix(ctx,d,adopted)
 snap=director_base.flatten_parent_evidence({str(p.resolve()):control.sha_file(p) for p in previous.ROOT.rglob('*') if p.is_file() and p.name!='DISPATCH.lock' and '__pycache__' not in p.parts})
 for p,h in snap.items():
  if control.sha_file(p)!=h:raise RuntimeError('frozen ancestor changed')
 fixed={'CONTEXT.json':ctx,'DIRECTION.json':d,'WINDOW_POLICY.json':control.read(previous.ROOT/'WINDOW_POLICY.json'),'COMPATIBLE_S7_CACHE.json':{'only_same_S7_source':True,'context_sha256':control.digest(ctx),'direction_sha256':control.digest(d),'locals':cache,'old_failed_outputs_spliced':False,'human_quality_approval':False},'CONTINUATION_SCOPE.json':AUTH,'DIRECTION_SOURCE_DECISION.json':control.read(previous.ROOT/'DIRECTION_SOURCE_DECISION.json')}
 for name,value in fixed.items():control.write(ROOT/name,value,True)
 ledger=control.read(old.ledger);a={'calls_started':spend['effective_calls_started'],'reported_tokens':spend['effective_reported_tokens'],'calls_with_known_usage':spend['calls_with_known_usage'],'unknown_token_reservations':93117,'pending_ordinals':[70,160],'parent_files':snap,'parent_sources':list(ledger['source_manifest']),'model_configs':ledger['model_configs'],'fixed_files':{name:control.sha_file(ROOT/name) for name in fixed},'current_parent':str(previous.ROOT),'same_director_and_local_input_preserved':True}
 control.write(ROOT/'ANCHOR.json',a,True);return runtime().prepare()


def runtime():
 a=control.read(ROOT/'ANCHOR.json');inherited={k:deepcopy(a[k]) for k in ('calls_started','reported_tokens','calls_with_known_usage','unknown_token_reservations','pending_ordinals')};inherited['parent_anchor_sha256']=control.sha_file(ROOT/'ANCHOR.json')
 def guard():
  for p,h in a['parent_files'].items():
   if control.sha_file(p)!=h:raise RuntimeError('frozen parent changed')
  for name,h in a['fixed_files'].items():
   if control.sha_file(ROOT/name)!=h:raise RuntimeError('current source/direction/window policy/cache changed')
  for role,cfg in a['model_configs'].items():
   live=source.legacy.role_config(role)
   if live.model!=cfg['model'] or live.base_url!=cfg['base_url']:raise RuntimeError('unverified model switch')
 sources=[PROJECT/p for p in a['parent_sources']]+[Path(__file__).resolve(),PROJECT/'scripts/creative_dialogue_prose_transport_v1.py',PROJECT/'tests/test_creative_dialogue_prose_transport_v1.py',PROJECT/'scripts/creative_atomic_event_group_lines_v2.py',PROJECT/'scripts/creative_current_action_translation_v2.py',PROJECT/'tests/test_creative_atomic_event_group_lines_v2.py',PROJECT/'scripts/creative_joint_source_binding_v12.py',PROJECT/'tests/test_creative_joint_timing_binding_v12.py',PROJECT/'scripts/creative_review_wire_v16.py',PROJECT/'scripts/creative_review_id_transport_v17.py',PROJECT/'tests/test_creative_review_full_wire_v17.py',PROJECT/'scripts/creative_review_projection_v12.py',PROJECT/'scripts/creative_joint_source_binding_v13.py',PROJECT/'scripts/creative_review_wire_v18.py',PROJECT/'scripts/creative_review_id_transport_v19.py',PROJECT/'tests/test_creative_shared_dialogue_scope_v44.py',PROJECT/'tests/test_creative_review_syntax_business_v45.py']
 return control.ContinuationRuntime(PROJECT,ROOT,sources,inherited,a['model_configs'],inherited_guard=guard,client_factory=GroupLinesProseOrTools,quota_state=None,shared_lock=parent.identity.SHARED_LOCK)


def summary():
 rt=runtime();ledger=control.read(rt.ledger);value=rt.summary();a=control.read(ROOT/'ANCHOR.json');known=sum(type((rt.effective_receipt(row).get('response_metadata') or {}).get('total_tokens')) is int for row in ledger['calls'])
 value.update(calls_with_known_usage=a['calls_with_known_usage']+known,new_unknown_token_reservations=value['unknown_token_reservations'],unknown_token_reservations=93117+value['unknown_token_reservations'],inherited_unknown_token_reservations=93117,unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160],media_calls=0);return value


_PARENT_RECORDS=None

def records():
 global _PARENT_RECORDS
 if _PARENT_RECORDS is None:_PARENT_RECORDS=previous.records()
 values=[dict(rec) for rec in _PARENT_RECORDS]
 for rec in values:rec.setdefault('source_root',str(previous.ROOT))
 rt=runtime();ledger=control.read(rt.ledger);rt.check(ledger)
 for row in ledger['calls']:
  rec=source.stage_record_view(rt.effective_receipt(row));rec['source_root']=str(ROOT)
  if rec['label'].startswith('plan_') and rec['status']=='contract_valid':
   rec['original_event_line_model_document']=deepcopy(rec['output']);rec['output']=deepcopy(rec['validation']['canonical_event_plan'])
  if rec['label'].startswith('local_') and rec['status']=='contract_valid':
   rec['original_scalar_model_document']=deepcopy(rec['output']);rec['original_compact_model_document']=deepcopy(rec['validation']['canonical_performance_document']);rec['output']=deepcopy(rec['validation']['derived_local'])
  values.append(rec)
 return values


def latest(prefix):
 if prefix.startswith('direction_s7_r'):return {'label':'direction_s7_r1','output':control.read(ROOT/'DIRECTION.json'),'status':'contract_valid'}
 rows=[rec for rec in records() if rec['label'].startswith(prefix)]
 if not rows or rows[-1]['status']!='contract_valid':raise RuntimeError('latest missing/rejected; no failed-source fallback')
 return deepcopy(rows[-1])


def decision_root(rec):return Path(rec.get('source_root',str(ROOT)))


def direction_source(revision):
 if revision!=1:raise RuntimeError('direction changed')
 d=latest('direction_s7_r')['output'];proof=control.read(ROOT/'DIRECTION_SOURCE_DECISION.json')
 if proof.get('approved_for_local_text') is not True or proof['direction_sha256']!=control.digest(d):raise RuntimeError('same approved whole direction required')
 return context(),d


def local_sources(drevision,count):
 values=[]
 for index in range(1,count+1):
  rec=latest(f'local_s7_d{drevision}_p{index:03}_r');proof=control.read(decision_root(rec)/f"LOCAL_SOURCE_DECISION_call{rec['ordinal']}.json")
  if proof.get('approved_for_next_local_text') is not True or proof['derived_local_sha256']!=control.digest(rec['output']):raise RuntimeError('actual source local approval required')
  plan=latest(f'plan_s7_d{drevision}_p{index:03}_r');inp=physical.build_local_input(context(),latest('direction_s7_r')['output'],values);verify_cache_binding(rec,plan,inp);values.append(rec['output'])
 return values


def plan(drevision,index,revision=1,feedback=None):
 ctx,d=direction_source(drevision);prior=local_sources(drevision,index-1);inp=physical.build_local_input(ctx,d,prior);schema=restrict_schema(window_base.supported_plan_schema(inp),inp)
 messages=translator_messages(inp,feedback);
 payload=json.loads(messages[1]['content']);payload['source_binding'].update(raw_script_sha256=control.digest(ctx['raw_linear_script']),reference_pack_sha256=control.digest(ctx['reference_pack']));messages[1]['content']=json.dumps(payload,ensure_ascii=False,separators=(',',':'));messages[0]['content']+=' 情绪只写自然表演，不使用affect状态操作。'
 req=director_base.direction_wire(messages,schema,1800,{'raw_script_sha256':control.digest(ctx['raw_linear_script']),'reference_pack_sha256':control.digest(ctx['reference_pack']),'local_input_sha256':control.digest(inp),'current_shot':inp['shot_id'],'stage':'model_authored_atomic_events'})
 req['operator_version']=VERSION;req['structured_schema']=None;req['output_contract']='atomic_event_group_lines/v2';req['input_provenance']['stage']='mechanical_current_action_translation';req['input_provenance']['reference_consumed_by_creative_upstream']=True
 def validate(raw):
  if set(raw)!={'event_lines'}:raise ValueError('only event_lines wrapper')
  doc=decode_lines(raw['event_lines'],inp)
  from jsonschema import Draft202012Validator
  Draft202012Validator(schema).validate(doc);derived=local_contract.derive_local(split.plan_as_compact(doc,inp),inp);physical.compile_prefix(ctx,d,prior+[derived]);return {'planning_physical_preflight':True,'not_actual_performance':True,'semantic_approval':False,'canonical_event_plan':doc,'original_event_lines_sha256':control.digest(raw)}
 return dispatch(f'plan_s7_d{drevision}_p{index:03}_r{revision}',req,validate)


def scalar_performance_schema(plan):
 props={'dialogue_performance':physical.text()}
 for slot in split.slots(plan):
  props[slot['slot']+'_seconds']={'type':'number','exclusiveMinimum':0};props[slot['slot']+'_performance']=physical.text()
 return physical.obj(props)


def decode_performance(raw,plan):
 from jsonschema import Draft202012Validator
 Draft202012Validator(scalar_performance_schema(plan)).validate(raw)
 return {'dialogue_performance':raw['dialogue_performance'],'performances':[{'slot':s['slot'],'seconds':raw[s['slot']+'_seconds'],'performance':raw[s['slot']+'_performance']} for s in split.slots(plan)]}


def focused_performance_messages(inp,plan,feedback):
 ctx=inp['context'];focus=split.focus(inp);outline={k:deepcopy(inp['direction'][k]) for k in ('emotional_arc','causal_chain','ending_intent')}
 payload={'read_only_complete_creative_source':{k:deepcopy(ctx[k]) for k in ('raw_linear_script','reference_pack','static_visual_manifest','production_responsibility')},'whole_film_outline':outline,'current_direction_and_complete_steps':focus,'complete_same_model_event_plan':plan,'fixed_current_slots':split.slots(plan),'verified_fault_memory':feedback or {},'task':'提交完整根级标量字段，对每个已核对slot填写实际秒数与可制作自然表演。当前事件不能删改或重复；不夹新状态，不重述整段服装和动作清单。'}
 rule='MiniMax完整当前镜表演。根字段dialogue_performance以及各slotID_seconds/slotID_performance全部齐全。秒数为数字，表演为字符串，禁止数组、slot对象、payload_json内嵌串。程序按固定slot查表组合，不改原值。各slot仅对应原事件，没有新增视线、道具转移或说话。对白程序插原句；dialogue_performance只原话语气/面部/呼吸，无新动作。重要反应自然可读且满足最低时间。'
 return [{'role':'system','content':rule},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}]


def local(drevision,index,revision=1,feedback=None):
 ctx,d=direction_source(drevision);prior=local_sources(drevision,index-1);inp=physical.build_local_input(ctx,d,prior);plan_record=latest(f'plan_s7_d{drevision}_p{index:03}_r');plan=plan_record['output'];proof=control.read(decision_root(plan_record)/f"EVENT_PLAN_SOURCE_DECISION_call{plan_record['ordinal']}.json")
 if not proof.get('approved_for_performance_text') or proof['plan_sha256']!=control.digest(plan) or plan_record['request']['input_provenance']['local_input_sha256']!=control.digest(inp):raise RuntimeError('same complete source approved event plan required')
 req=director_base.direction_wire(focused_performance_messages(inp,plan,feedback),scalar_performance_schema(plan),3000,{'raw_script_sha256':control.digest(ctx['raw_linear_script']),'reference_pack_sha256':control.digest(ctx['reference_pack']),'local_input_sha256':control.digest(inp),'event_plan_sha256':control.digest(plan),'event_plan_ordinal':plan_record['ordinal'],'current_shot':inp['shot_id'],'stage':'complete_fixed_scalar_performance','projection':'fixed slot key lookup, original values only'})
 req['operator_version']=VERSION
 if index==5 and not plan['actions']:
  req['messages']=prose_messages(inp,feedback);req['structured_schema']=None;req['output_contract']='dialogue_prose/v1';req['input_provenance']['stage']='complete_dialogue_prose';req['input_provenance']['projection']='exact original prose wrapped as dialogue_performance; no fallback'
 def validate(raw):
  doc=decode_performance(raw,plan);compact_doc=split.performance_as_compact(doc,plan,inp);derived=local_contract.derive_local(compact_doc,inp);compiled=physical.compile_prefix(ctx,d,prior+[derived]);control.write(ROOT/f'PREFIX_d{drevision}_p{index:03}_{control.digest(compiled)[:12]}.json',compiled,True)
  return {'compiled_prefix_shots':index,'physical_state_checked':True,'declared_windows_checked':True,'semantic_approval':False,'derived_local':derived,'canonical_performance_document':doc,'original_scalar_model_document_sha256':control.digest(raw),'original_event_plan_sha256':control.digest(plan),'deterministic_projection_only':True}
 return dispatch(f'local_s7_d{drevision}_p{index:03}_r{revision}',req,validate)


def adopt_local(drevision,index,evidence):
 rec=latest(f'local_s7_d{drevision}_p{index:03}_r');source.verify_assistant_evidence(rec['original_compact_model_document'],evidence)
 value={'approved_for_next_local_text':True,'derived_local_sha256':control.digest(rec['output']),'evidence':evidence,'human_quality_approval':False,'scalar_model_document_sha256':control.digest(rec['original_scalar_model_document']) if 'original_scalar_model_document' in rec else None,'all_seconds_and_performance_from_original_model':True}
 control.write(ROOT/f"LOCAL_SOURCE_DECISION_call{rec['ordinal']}.json",value,True);return value

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
    if request['input_provenance'].get('stage')=='mechanical_current_action_translation':
      d=latest('direction_s7_r')['output'];index=int(request['input_provenance']['current_shot'][2:]);inp=physical.build_local_input(ctx,d,local_sources(1,index-1));verify=validate_consumed(inp,request,control.digest(ctx['raw_linear_script']),control.digest(ctx['reference_pack']))
      actual_binding=json.loads(request['messages'][1]['content'])['source_binding']
      if actual_binding['raw_script_sha256']!=verify['raw_script_sha256'] or actual_binding['reference_pack_sha256']!=verify['reference_pack_sha256']:raise RuntimeError('source digest mismatch')
    else:
      if not any(contains(p,ctx['reference_pack']) for p in payloads) or not any(contains(p,ctx['raw_linear_script']) for p in payloads):raise RuntimeError('exact full source/reference missing')
      verify={'exact_new_s7_and_full_R01_in_actual_messages':True,'full_reference_in_this_translation':None}

    for oldroot,n in ((source.ROOT,70),(parent.parent.ROOT,160)):
        old=next(oldroot.glob(f'call_{n:03}_*.json'))
        if parent.identity.network_identity(request)==parent.identity.network_identity(control.read(old)['request']):raise RuntimeError('old request repeated')
    control.write(ROOT/'request_previews'/f'{label}.json',request,True)
    control.write(ROOT/'request_previews'/f'{label}_INPUT_VERIFICATION.json',{**verify,'no_s6_performance_reused':True,'old_unknown_reservations':93117,'no_automatic_retry':True},True)
    return runtime().dispatch(label,request,validator)

def assert_plan_binding(local_record,plan_record):
    expected=control.digest(plan_record['output'])
    if local_record['request']['input_provenance'].get('event_plan_sha256')!=expected:
        raise RuntimeError('event plan changed; complete performance revision required')

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
    ctx['director_input_script_timing_status']=ctx['script_timing_status']
    ctx['script_timing_status']='actual_compiled_local_schedule'
    return ctx,compiled

def adopt_plan(drevision,index,evidence):
    record=latest(f'plan_s7_d{drevision}_p{index:03}_r');source.verify_assistant_evidence(record['output'],evidence)
    value={'approved_for_performance_text':True,'plan_sha256':control.digest(record['output']),'evidence':evidence,'actual_timing_verified':False,'human_quality_approval':False}
    control.write(ROOT/f"EVENT_PLAN_SOURCE_DECISION_call{record['ordinal']}.json",value,True);return value

def reviewed_final_context(drevision):
    ctx,compiled=final_context(drevision);projected=deepcopy(ctx);projected['shots']=view.project_storyboard(ctx['shots'],ctx);view.validate_projection(ctx['shots'],projected['shots'],ctx);joint.preflight(projected)
    return projected,compiled

def transport_schema(ctx):
    """Compact syntax on the wire; unchanged complete business Schema locally."""
    schema=deepcopy(ids.schema(ctx))
    schema['$defs']={'EvidenceID':{'type':'string','pattern':ids.id_pattern(ids.catalog(ctx))}}
    for row in schema['properties']['coverage']['prefixItems']:
        for check in row['prefixItems'][1:]:
            check['prefixItems'][2].pop('allOf',None)
            check['prefixItems'][2]['items']={'$ref':'#/$defs/EvidenceID'}
    return schema

def final_review(drevision,revision=1,feedback=None):
    ctx,compiled=reviewed_final_context(drevision);messages=source.joint_review_messages(ctx);catalog=ids.catalog(ctx)
    messages[0]['content']+='\n'+joint.build_messages_addendum(ctx)+'\n引用每项只填本次证据目录ID字符串，schema为'+ids.VERSION+'。全部'+str(len(compact._rows(ctx)))+'镜全文独立核对；目录仅导航，完整原文在输入，程序原样展开并执行全部业务验收。不能把无错发现列major，suggestions只能location/proposal/reason。新稿便利贴、拒绝两句及听者反应、门外释放必须对应实际排时；不能删真问题求通过。'
    messages.append({'role':'user','content':json.dumps({'source_directory':[{'id':k,'path':v['path'],'excerpt':v['quote'][:48]} for k,v in catalog.items()]},ensure_ascii=False,separators=(',',':'))})
    if feedback:messages.append({'role':'user','content':json.dumps({'prior_protocol_fault':feedback,'request':'完整独立重审，不在本地修响应。'},ensure_ascii=False)})
    req=wire('director',messages,transport_schema(ctx),24000,{'compiled_sha256':control.digest(compiled),'review_context_sha256':compact.context_digest(ctx),'evidence_catalog_sha256':control.digest(catalog),'whole_film_full_text_review':True})
    def validate(raw):
        from jsonschema import Draft202012Validator
        Draft202012Validator(ids.schema(ctx)).validate(raw)
        prior=next(previous.ROOT.glob('call_264_*.json'))
        ids.validate_repair_preserves_conclusions(control.read(prior)['output'],raw)
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
 else:raise ValueError('one explicit step required')
 print(json.dumps(value,ensure_ascii=False,indent=2))
