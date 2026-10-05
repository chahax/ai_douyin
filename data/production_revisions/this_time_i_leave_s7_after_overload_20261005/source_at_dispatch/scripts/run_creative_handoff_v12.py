"""Independent full review and handoff continuation; parent v10 read-only."""
from copy import deepcopy
from pathlib import Path
import json,sys
from scripts import run_creative_handoff_v11 as parent
from scripts import run_creative_resume_v4 as source
from scripts import creative_resume_dispatch_v3 as control
from scripts import creative_joint_source_binding_v11 as joint
from scripts import creative_review_projection_v11 as view
from scripts import creative_compact_review_transport_v8 as compact
from scripts import creative_review_wire_v12 as wire_contract
PROJECT=Path(__file__).resolve().parents[1]
ROOT=parent.ROOT.parent/'resume_20261005_v12'
VERSION='s6_complete_review_handoff/v12'
AUTH={'user_quote':'开始实际表演窗口和制作交接','scope':'independent deterministic review view, complete necessary text review and handoff','automatic_retry':False,'aggregate_token_cap':None,'old_call70_resend':False,'media_calls_authorized':False,'old_budget_reset':False,'parent_governance_migrated':False}

def fingerprint():
    paths=set()
    for folder in (parent.ROOT.parent,PROJECT/'data/production_records/this_time_i_leave_s6_20261005',PROJECT/'data/production_trials/boundary_live_action_reference_v15_20261001/round_01'):
        for p in folder.rglob('*'):
            if p.is_file() and p.name!='DISPATCH.lock' and '__pycache__' not in p.parts and not p.is_relative_to(ROOT):paths.add(p)
    return {str(p.resolve()):control.sha_file(p) for p in sorted(paths)}

def prepare():
    if (ROOT/'INHERITED_ANCHOR.json').exists():return runtime().prepare()
    ctx=control.read(parent.ROOT/'ORIGINAL_FULL_CONTEXT.json');compiled=control.read(parent.ROOT/'ORIGINAL_COMPILED_PERFORMANCE.json')
    prior=parent.runtime();prior.check(control.read(prior.ledger));spend=parent.summary()
    snap=fingerprint();ledger=control.read(prior.ledger)
    anchor={'calls_started':spend['effective_calls_started'],'reported_tokens':spend['effective_reported_tokens'],'calls_with_known_usage':spend['calls_with_known_usage'],'unknown_token_reservations':64010,'pending_ordinals':[70],'parent_ledger_sha256':control.sha_file(prior.ledger),'parent_files':snap,'parent_sources':list(ledger['source_manifest']),'model_configs':deepcopy(ledger['model_configs']),'compiled_sha256':control.digest(compiled),'original_context_sha256':compact.context_digest(ctx)}
    projected=deepcopy(ctx);projected['shots']=view.project_storyboard(ctx['shots'],ctx)
    joint.preflight(projected);view.validate_projection(ctx['shots'],projected['shots'],ctx)
    control.write(ROOT/'INHERITED_ANCHOR.json',anchor,True)
    control.write(ROOT/'CREATIVE_CONTINUATION_AUTHORIZATION.json',AUTH,True)
    control.write(ROOT/'ORIGINAL_FULL_CONTEXT.json',ctx,True)
    control.write(ROOT/'ORIGINAL_COMPILED_PERFORMANCE.json',compiled,True)
    control.write(ROOT/'REVIEW_FULL_CONTEXT.json',projected,True)
    return runtime().prepare()

def runtime():
    anchor=control.read(ROOT/'INHERITED_ANCHOR.json')
    inherited={k:deepcopy(anchor[k]) for k in ('calls_started','reported_tokens','calls_with_known_usage','unknown_token_reservations','pending_ordinals')}
    inherited['parent_anchor_sha256']=control.sha_file(ROOT/'INHERITED_ANCHOR.json')
    sources=[PROJECT/r for r in anchor['parent_sources']]+[PROJECT/'scripts/creative_review_projection_v11.py',PROJECT/'scripts/creative_joint_source_binding_v11.py',Path(__file__).resolve(),PROJECT/'tests/test_creative_review_projection_v11.py',PROJECT/'scripts/creative_review_wire_v12.py',PROJECT/'tests/test_creative_review_wire_v12.py']
    def guard():
        if fingerprint()!=anchor['parent_files']:raise RuntimeError('frozen parent files changed')
        if control.read(ROOT/'CREATIVE_CONTINUATION_AUTHORIZATION.json')!=AUTH:raise RuntimeError('authorization changed')
        original=control.read(ROOT/'ORIGINAL_FULL_CONTEXT.json');compiled=control.read(ROOT/'ORIGINAL_COMPILED_PERFORMANCE.json')
        if compact.context_digest(original)!=anchor['original_context_sha256'] or control.digest(compiled)!=anchor['compiled_sha256']:raise RuntimeError('original source changed')
        current=control.read(ROOT/'REVIEW_FULL_CONTEXT.json')
        wanted=deepcopy(original);wanted['shots']=view.project_storyboard(original['shots'],original)
        if current!=wanted:raise RuntimeError('review context changed or content rewritten')
        for role,cfg in anchor['model_configs'].items():
            live=source.legacy.role_config(role)
            if live.model!=cfg['model'] or live.base_url!=cfg['base_url']:raise RuntimeError('unverified model or endpoint switch')
    return control.ContinuationRuntime(PROJECT,ROOT,sources,inherited,anchor['model_configs'],inherited_guard=guard,quota_state=None,shared_lock=parent.parent.SHARED_LOCK)

def summary():
    rt=runtime();ledger=control.read(rt.ledger);value=rt.summary()
    known=sum(type((rt.effective_receipt(c).get('response_metadata') or {}).get('total_tokens'))is int for c in ledger['calls'])
    value.update(calls_with_known_usage=control.read(ROOT/'INHERITED_ANCHOR.json')['calls_with_known_usage']+known,inherited_unknown_token_reservations=64010,new_unknown_token_reservations=value['unknown_token_reservations'],unknown_token_reservations=64010+value['unknown_token_reservations'],inherited_pending_ordinals=[70],original_call70_recovered=False,media_calls=0)
    return value

def review(revision):
    ctx=control.read(ROOT/'REVIEW_FULL_CONTEXT.json');joint.preflight(ctx)
    messages=source.joint_review_messages(ctx)
    messages[0]['content']+='\n'+wire_contract.format_addendum(ctx)+'\n'+joint.build_messages_addendum(ctx)
    messages[0]['content']+='\n返修合同：suggestions每项恰location/proposal/reason，不能加evidence_refs。issue仅列有真实矛盾的必修项，验证无违反的发现写coverage pass或suggestion，不列major问题；有必修项story_preserved=false。每个quote必须来自该path实际叶子，首态末态和各镜索引不要互换。当前视图只显示实际声明窗口，全部动作和对白原样保留；未建模affect初态在原编译保留但不是当前演技结论。纸面左右/行号、递笔跨镜保持、告别cue与原句、重要说话反应时序都按真实全文重新核对。不得沿用失败审查的结论或删真问题以求通过。'
    schema=wire_contract.schema(ctx)
    request=source.wire('director',messages,schema,24000,{'compiled_sha256':control.read(ROOT/'INHERITED_ANCHOR.json')['compiled_sha256'],'review_context_sha256':compact.context_digest(ctx),'whole_film_full_text_review':True,'raw_script_sha256':control.digest(ctx['raw_linear_script']),'reference_pack_sha256':control.digest(ctx['reference_pack']),'full_reference_pack_in_messages':True,'deterministic_view_version':view.VERSION})
    request['operator_version']=VERSION
    # The exact full raw script and reference must appear in actual sent JSON.
    actual=json.loads(request['messages'][1]['content'])
    if actual['raw_linear_script']!=ctx['raw_linear_script'] or actual['reference_pack']!=ctx['reference_pack']:raise RuntimeError('full source missing')
    if parent.parent.network_identity(request)==parent.parent.network_identity(control.read(source.ROOT/'call_070_direction_s6_r2.json')['request']):raise RuntimeError('unknown70 resend forbidden')
    label=f'full_review_s6_d6_view12_r{revision}'
    control.write(ROOT/'request_previews'/f'{label}.json',request,True)
    control.write(ROOT/'request_previews'/f'{label}_INPUT_VERIFICATION.json',{'raw_s6_script_unchanged':True,'full_reference_pack_in_actual_messages':True,'source_binding_version':joint.VERSION,'old_unknown_reservation_preserved':64010,'all_original_events_and_dialogue_preserved':True},True)
    def validate(raw):
        expanded=compact.expand_review(raw,ctx);joint.validate_joint_review(expanded,ctx)
        return {'complete_joint_review_valid':True,'issue_count':len(expanded['issues']),'story_preserved':expanded['story_preserved'],'semantic_approval':False}
    return runtime().dispatch(label,request,validate)

def latest_review():
    rt=runtime();ledger=control.read(rt.ledger);rt.check(ledger)
    records=[rt.effective_receipt(c) for c in ledger['calls'] if c['label'].startswith('full_review_s6_d6_view11_')]
    if not records or records[-1]['status']!='contract_valid':raise RuntimeError('latest complete review not valid')
    return records[-1]

def finalize(evidence):
    ctx=control.read(ROOT/'REVIEW_FULL_CONTEXT.json');compiled=control.read(ROOT/'ORIGINAL_COMPILED_PERFORMANCE.json')
    record=latest_review();review_doc=compact.expand_review(record['output'],ctx);joint.validate_joint_review(review_doc,ctx)
    if review_doc['issues'] or not review_doc['story_preserved']:raise RuntimeError('unresolved full text issues')
    source.verify_assistant_evidence(ctx,evidence)
    out=ROOT/'DELIVERABLE_s6_d6';out.mkdir(parents=True,exist_ok=True)
    for name,value in [('FULL_SCRIPT.json',ctx['raw_linear_script']),('WHOLE_FILM_DIRECTION.json',ctx['whole_film_direction']),('COMPILED_PERFORMANCE.json',compiled),('REVIEWED_EXECUTION_VIEW.json',ctx['shots']),('FULL_TEXT_REVIEW.json',review_doc),('STATIC_ASSET_DEFINITIONS.json',ctx['static_visual_manifest'])]:control.write(out/name,value,True)
    for name,value in [('FULL_SCRIPT.md',source.linear.render_linear_screenplay(ctx['raw_linear_script'])+'\n'),('DIRECTOR_PERFORMANCE_PLAN.md',source.render_production_plan(ctx,{**compiled,'storyboard':ctx['shots']}))]:
        p=out/name
        if p.exists() and p.read_text(encoding='utf-8')!=value:raise RuntimeError('delivery changed')
        if not p.exists():p.write_text(value,encoding='utf-8')
    handoff={'schema':VERSION,'status':'text_reviewed_awaiting_human_content_and_aesthetic_confirmation','script_sha256':control.digest(ctx['raw_linear_script']),'compiled_sha256':control.digest(compiled),'reviewed_view_sha256':control.digest(ctx['shots']),'review_sha256':control.digest(review_doc),'review_context_sha256':compact.context_digest(ctx),'assistant_verified_evidence':deepcopy(evidence),'narrative_beats':9,'shots':compiled['execution_shot_count'],'compiled_duration_seconds':compiled['total_duration_seconds'],'text_production_handoff_complete':True,'creative_quality_passed':False,'user_quality_confirmation':None,'actual_selected_images':[],'actual_images_returned_to_director':False,'component_registry':deepcopy(ctx['component_registry']),'asset_sample_selection_status':'awaiting_human_aesthetic_approval','media_calls':0,'video_human_review_required':True,'automatic_media_submit':False,'cost_ledger':summary(),'old_call70_still_unknown':True,'old_unknown_reservation_preserved':64010,'old_task_or_budget_reset':False,'legacy_compiled_prompt_not_media_instruction':True,'reviewed_execution_view_is_authoritative_text_projection':True,'next_steps':['human content and aesthetic review','few selected aesthetic images under media authorization','return actually selected images to director','validate long dialogue media duration','generate current segment then await human review','continue only with approved original service tail frame']}
    control.write(out/'PRODUCTION_HANDOFF.json',handoff,True);return handoff

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');op=sys.argv[1]
    if op=='prepare':result=prepare()
    elif op=='review':result=review(int(sys.argv[2]))
    elif op=='finalize':result=finalize(control.read(sys.argv[2]))
    elif op=='report':result=summary()
    else:raise ValueError('unsupported operation')
    if isinstance(result,dict) and 'ordinal' in result:result={k:result.get(k) for k in ('ordinal','label','status','validation','validation_error','response_metadata')}
    print(json.dumps(result,ensure_ascii=False,indent=2))
