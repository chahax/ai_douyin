"""Complete film outline, independent complete per-beat direction, then real performance."""
from copy import deepcopy
from pathlib import Path
import json,sys,types
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
if __package__ in (None,''):
 pkg=types.ModuleType('scripts');pkg.__path__=[str(PROJECT/'scripts')];sys.modules['scripts']=pkg
from scripts import run_creative_s7_native_array_v31 as previous
from scripts import run_creative_s7_review_v20 as parent
from scripts import creative_resume_dispatch_v3 as control
from scripts import creative_local_event_performance_v3 as split
from scripts import creative_synchronous_prop_contract_v3 as local_contract
from scripts import creative_director_frame_catalog_v1 as frame_catalog
from scripts import creative_review_projection_v11 as view
from scripts import creative_joint_source_binding_v11 as joint
from scripts import creative_review_id_transport_v15 as ids
source=parent.source;physical=source.physical;compact=source.compact
ROOT=PROJECT/'data/production_revisions/this_time_i_leave_s7_outline_and_shots_20261006'
VERSION='s7_complete_outline_then_complete_shot_modules/v32'
FILM=previous.FILM;STATE=previous.STATE;WINDOWS=previous.WINDOWS
DURATION_CLASSES=previous.DURATION_CLASSES;SCALAR_STATE=previous.SCALAR_STATE;SCALAR_WINDOWS=previous.SCALAR_WINDOWS
AUTH={'scope':'complete film outline, new independent complete direction for every original S7 beat, opening state, critical windows, full local events/performance, deterministic compilation and full review','automatic_retry':False,'aggregate_token_cap':None,'media_calls':0,'old_calls70_160_repeated':False,'old_budget_reset':False,'user_creative_quality_approval':False}
def require_reviewed_source():
    proof=control.read(parent.ROOT/'REVIEWED_SCRIPT_s7/STATUS.json')
    if proof.get('status')!='reviewed_complete_script_awaiting_new_director_and_actual_performance' or proof.get('script_sha256')!=control.digest(parent.latest('draft_s7_r')['output']):raise RuntimeError('reviewed complete S7 source required')
    review=parent.latest('script_review_s7_r');ctx=parent.script_context()
    result=source.review_wire.validate_script_review(parent.expand_review(review['output'],ctx),ctx)
    if result['issues'] or not result['story_preserved']:raise RuntimeError('unresolved full script review')
    if proof['review_ordinal']!=review['ordinal']:raise RuntimeError('script review superseded')
    return proof

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
    sources=[PROJECT/p for p in a['parent_sources']]+[Path(__file__).resolve(),PROJECT/'tests/test_creative_s7_outline_and_shots_v32.py']
    return control.ContinuationRuntime(PROJECT,ROOT,sources,inherited,a['model_configs'],inherited_guard=guard,quota_state=None,shared_lock=parent.identity.SHARED_LOCK)

def summary():
    rt=runtime();ledger=control.read(rt.ledger);value=rt.summary();a=control.read(ROOT/'ANCHOR.json')
    known=sum(type((rt.effective_receipt(row).get('response_metadata') or {}).get('total_tokens')) is int for row in ledger['calls'])
    value.update(calls_with_known_usage=a['calls_with_known_usage']+known,new_unknown_token_reservations=value['unknown_token_reservations'],unknown_token_reservations=93117+value['unknown_token_reservations'],inherited_unknown_token_reservations=93117,unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160],media_calls=0)
    return value

def wire(role,messages,schema,cap,provenance):
    value=source.wire(role,messages,schema,cap,provenance);value['operator_version']=VERSION;return value

def direction_wire(messages,schema,cap,provenance):
    c=source.legacy.role_config('writer')
    return {'role':'writer','model':c.model,'messages':deepcopy(messages),'structured_schema':deepcopy(schema),
      'parameters':{'max_completion_tokens':cap,'temperature':.4,'thinking':'disabled'},
      'input_provenance':{**deepcopy(provenance),'native_object_tool_schema':True,'server_strict_decoding_claimed':False},'operator_version':VERSION}

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

def scalar_wire(messages,schema,cap,prov):return direction_wire(messages,schema,cap,{**prov,'scalar_only_model_output':True,'deterministic_projection_no_text_rewrite':True})

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

def composed_direction():
    ctx=context();f=latest('film_s7_r');s=latest('opening_s7_r');w=latest('windows_s7_r')
    if s['request']['input_provenance']['film_plan_sha256']!=control.digest(f['output']) or w['request']['input_provenance']['film_plan_sha256']!=control.digest(f['output']) or w['request']['input_provenance']['opening_state_sha256']!=control.digest(s['output']):raise RuntimeError('component superseded; complete downstream module revision required')
    d=assemble_direction(ctx,f['output'],s['output'],w['output']);components={key:{'ordinal':rec['ordinal'],'model_document_sha256':control.digest(rec['output'])} for key,rec in (('film',f),('opening',s),('windows',w))}
    control.write(ROOT/f'COMPOSED_DIRECTION_{control.digest(d)[:12]}.json',{'direction':d,'components':components,'deterministic_field_assembly_only':True,'no_old_failed_direction_used':True,'source_script_ordinal':161,'semantic_approval':False},True)
    return {'ordinal':w['ordinal'],'label':'direction_s7_r1','status':'contract_valid','output':d,'source_components':components}

def creative_source_packet(ctx):
    return {key:deepcopy(ctx[key]) for key in ('raw_linear_script','reference_pack','static_visual_manifest','production_responsibility')}

def ordinary_latest(prefix):
    rows=[x for x in records() if x['label'].startswith(prefix)]
    if not rows or rows[-1]['status']!='contract_valid':raise RuntimeError('latest missing/rejected; no old director fallback')
    return deepcopy(rows[-1])


def outline_schema():return physical.obj({key:physical.text() for key in ('emotional_arc','causal_chain','ending_intent')})


def shot_schema(ctx,index):
    beat=ctx['raw_linear_script']['beats'][index-1]
    return physical.obj({'new_information_and_purpose':physical.text(),'observation_object':physical.text(),'frame_id':{'enum':frame_catalog.ALLOWED[beat['id']]},'cut_reason':physical.text()})


def assemble_film_documents(ctx,outline,shot_documents):
    from jsonschema import Draft202012Validator
    Draft202012Validator(outline_schema()).validate(outline)
    beats=ctx['raw_linear_script']['beats']
    if len(shot_documents)!=len(beats):raise ValueError('all new complete shot modules required')
    catalog=physical.source_contract.source_catalog(ctx);rows=[]
    names={c['name']:c['id'] for c in ctx['static_visual_manifest']['characters']}
    for i,(beat,doc) in enumerate(zip(beats,shot_documents),1):
        Draft202012Validator(shot_schema(ctx,i)).validate(doc);frame=frame_catalog.FRAMES[doc['frame_id']]
        mouths=[names[s['speaker']]+'_mouth' in frame['visible'] for s in beat['steps'] if s['kind']=='dialogue']
        mode='无对白' if not mouths else '画内对白' if all(mouths) else '画外对白' if not any(mouths) else '混合对白'
        if mode not in frame['dialogue_modes']:raise ValueError('source speaker and chosen frame mismatch')
        shot={'shot_id':f'SH{i:02}','source_step_refs':[s['ref'] for s in catalog if s['beat_index']==i-1],
          'new_information':doc['new_information_and_purpose'],'purpose':doc['new_information_and_purpose'],
          'observation_object':doc['observation_object'],'camera':frame['camera'],'composition':frame['composition'],
          'cut_reason':doc['cut_reason'],'dialogue_mode':mode}
        rows.append({'beat_id':beat['id'],'shots':[shot]})
    film={'schema':FILM,'context_sha256':control.digest(ctx),'raw_linear_script_sha256':control.digest(ctx['raw_linear_script']),
          'emotional_arc':outline['emotional_arc'],'causal_chain':[outline['causal_chain']],'ending_intent':outline['ending_intent'],'beats':rows}
    validate_film(film,ctx);return film


def outline(revision=1,feedback=None):
    ctx=context();payload={'read_only_creative_source':creative_source_packet(ctx),'verified_feedback':feedback,
      'task':'只写整片情绪、事件因果和结尾意义，完整三个根字段，不写分镜、动作、秒数、数组或逐拍内容。'}
    messages=[{'role':'system','content':'MiniMax创作完整整片规划，只有emotional_arc/causal_chain/ending_intent三个字符串字段。基于本次完整S7与原R01。仍两人，拒绝现场这次我先走，门外看票轻呼气释放，他自己对账；不新增剧情台词动作。白话清楚，不复制长篇原文。'},
              {'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}]
    req=direction_wire(messages,outline_schema(),1200,{'stage':'complete_film_outline_only','raw_script_sha256':control.digest(ctx['raw_linear_script']),'full_reference_pack_in_messages':True})
    def validate(doc):
        from jsonschema import Draft202012Validator
        Draft202012Validator(outline_schema()).validate(doc);return {'complete_outline_contract_valid':True,'source_semantics_pending':True,'actual_windows_available':False}
    return dispatch(f'outline_s7_r{revision}',req,validate)


def adopt_outline(evidence):
    rec=ordinary_latest('outline_s7_r');source.verify_assistant_evidence(rec['output'],evidence)
    value={'approved_for_shot_direction_text':True,'outline_sha256':control.digest(rec['output']),'evidence':evidence,'human_quality_approval':False}
    control.write(ROOT/f"OUTLINE_SOURCE_DECISION_call{rec['ordinal']}.json",value,True);return value


def reviewed_outline():
    rec=ordinary_latest('outline_s7_r');decision=control.read(ROOT/f"OUTLINE_SOURCE_DECISION_call{rec['ordinal']}.json")
    if decision.get('approved_for_shot_direction_text') is not True or decision['outline_sha256']!=control.digest(rec['output']):raise RuntimeError('actual complete outline source decision required')
    return rec


def shot_direction(index,revision=1,feedback=None):
    ctx=context();outline_record=reviewed_outline();beat=ctx['raw_linear_script']['beats'][index-1]
    options=frame_catalog.ALLOWED[beat['id']]
    payload={'read_only_creative_source':creative_source_packet(ctx),'complete_reviewed_film_outline':outline_record['output'],
      'current_complete_source_beat':beat,'current_source_refs':[s for s in physical.source_contract.source_catalog(ctx) if s['beat_index']==index-1],
      'available_camera_frames':{k:frame_catalog.FRAMES[k] for k in options},'verified_feedback':feedback,
      'task':'只提交当前原拍的完整四字段导演模块。信息目的、观察重点、一个机位ID、切镜意义；全片只作上下文，不能写别的拍或新的动作。'}
    rule='当前拍完整导演稿，仅new_information_and_purpose/observation_object/frame_id/cut_reason四个根字段，无B01等编号键，无数组或拼接字符串。白话短句。仅当前原拍，原动作对白不改，仍两人无新增道具。机位只选一个表中ID，摄影构图由方案库负责，不在目的/切镜理由偷偷改拍法。'
    req=direction_wire([{'role':'system','content':rule},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}],shot_schema(ctx,index),1200,
      {'stage':'complete_current_beat_direction','beat_id':beat['id'],'beat_sha256':control.digest(beat),'outline_sha256':control.digest(outline_record['output']),
       'context_sha256':control.digest(ctx),'raw_script_sha256':control.digest(ctx['raw_linear_script']),'frame_catalog_sha256':control.digest(frame_catalog.FRAMES),'full_reference_pack_in_messages':True})
    def validate(doc):
        from jsonschema import Draft202012Validator
        Draft202012Validator(shot_schema(ctx,index)).validate(doc);return {'complete_current_beat_direction_valid':True,'source_semantics_pending':True,'not_complete_film_alone':True}
    return dispatch(f'shot_direction_s7_p{index:03}_r{revision}',req,validate)


def adopt_shot_direction(index,evidence):
    rec=ordinary_latest(f'shot_direction_s7_p{index:03}_r');source.verify_assistant_evidence(rec['output'],evidence)
    value={'approved_for_film_assembly':True,'module_sha256':control.digest(rec['output']),'evidence':evidence,'human_quality_approval':False}
    control.write(ROOT/f"SHOT_DIRECTION_SOURCE_DECISION_call{rec['ordinal']}.json",value,True);return value


def check_shot_binding(rec,outline_record,ctx,index):
    beat=ctx['raw_linear_script']['beats'][index-1];prov=rec['request']['input_provenance']
    required={'outline_sha256':control.digest(outline_record['output']),'context_sha256':control.digest(ctx),'beat_sha256':control.digest(beat),'beat_id':beat['id'],
      'raw_script_sha256':control.digest(ctx['raw_linear_script']),'frame_catalog_sha256':control.digest(frame_catalog.FRAMES),'full_reference_pack_in_messages':True}
    if any(prov.get(k)!=v for k,v in required.items()):raise RuntimeError('shot belongs to superseded full source/outline/camera library')


def assembled_film():
    ctx=context();outline_record=reviewed_outline();modules=[];bindings=[];snapshot=records()
    for index,beat in enumerate(ctx['raw_linear_script']['beats'],1):
        matches=[rec for rec in snapshot if rec['label'].startswith(f'shot_direction_s7_p{index:03}_r')]
        if not matches or matches[-1]['status']!='contract_valid':raise RuntimeError('all latest complete current shot modules required')
        rec=matches[-1];decision=control.read(ROOT/f"SHOT_DIRECTION_SOURCE_DECISION_call{rec['ordinal']}.json")
        if decision.get('approved_for_film_assembly') is not True or decision['module_sha256']!=control.digest(rec['output']):raise RuntimeError('each complete current module source decision required')
        check_shot_binding(rec,outline_record,ctx,index)
        modules.append(rec['output']);bindings.append({'ordinal':rec['ordinal'],'label':rec['label'],'module_sha256':control.digest(rec['output'])})
    film=assemble_film_documents(ctx,outline_record['output'],modules)
    value={'ordinal':bindings[-1]['ordinal'],'label':'film_s7_r1','status':'contract_valid','output':film,
      'source_components':{'outline_ordinal':outline_record['ordinal'],'outline_sha256':control.digest(outline_record['output']),'shot_modules':bindings},
      'authoring':'all independent complete new modules bound to one reviewed outline; no failed old director fragments','automatic_retry':False}
    control.write(ROOT/f"COMPOSED_FILM_{control.digest(film)[:12]}.json",value,True);return value


def latest(prefix):
    if prefix.startswith('film_s7_r'):return assembled_film()
    if prefix.startswith('direction_s7_r'):return composed_direction()
    rec=ordinary_latest(prefix);raw=deepcopy(rec['output']);ctx=context()
    if prefix.startswith('opening_s7_r'):rec['output']=decode_scalar_state(raw,ctx);rec['original_scalar_model_document']=raw
    elif prefix.startswith('windows_s7_r'):rec['output']=decode_scalar_windows(raw,ctx,assembled_film()['output']);rec['original_scalar_model_document']=raw
    return rec


def film_plan(*args,**kwargs):raise RuntimeError('Use complete outline and independent complete shot_direction modules; monolithic director disabled')


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');op=sys.argv[1];args=[int(x) for x in sys.argv[2:]]
    if op=='prepare':value=prepare()
    elif op=='outline':value=outline(*args)
    elif op=='shot':value=shot_direction(*args)
    elif op=='opening':value=opening_state(*args)
    elif op=='windows':value=critical_windows(*args)
    elif op=='compose':value=composed_direction()
    elif op=='plan':value=plan(*args)
    elif op=='local':value=local(*args)
    elif op=='report':value=summary()
    else:raise ValueError('unsupported single operation')
    if isinstance(value,dict) and 'request' in value:value={k:value.get(k) for k in ('ordinal','label','status','validation','validation_error','error','response_metadata')}
    print(json.dumps(value,ensure_ascii=False,indent=2))
