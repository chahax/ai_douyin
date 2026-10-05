"""Independent complete S7 content revision; no media or automatic retry."""
from copy import deepcopy
from pathlib import Path
import json,sys
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
if __package__ in (None,''):
    import types
    package=types.ModuleType('scripts');package.__path__=[str(PROJECT/'scripts')];sys.modules['scripts']=package
from scripts import run_creative_resume_v4 as source
from scripts import run_creative_handoff_v15 as parent
from scripts import run_creative_resume_v10 as identity
from scripts import creative_resume_dispatch_v3 as control
from scripts import creative_review_wire_v12 as typed_review
from src.content_factory import creative_review_evidence_ids as ids
from jsonschema import Draft202012Validator
ROOT=PROJECT/'data/production_revisions/this_time_i_leave_s7_20261005'
VERSION='s7_complete_content_revision/v17'
ID_VERSION='script_review_source_ids/v17'
FEEDBACK=ROOT/'USER_FEEDBACK.json'
AUTH={'scope':'complete text revision consuming user feedback; no media','aggregate_text_token_cap':None,'automatic_retry':False,'old_call70_resend':False,'old_budget_reset':False,'user_quality_approval':False}


def prepare():
    if (ROOT/'INHERITED_ANCHOR.json').exists():return runtime().prepare()
    previous=parent.runtime();previous.check(control.read(previous.ledger));spend=parent.summary()
    if spend['effective_calls_started']!=158 or spend['effective_reported_tokens']!=2915735 or spend['new_unknown_token_reservations']!=0:raise RuntimeError('prior spend changed; reconcile before dispatch')
    ledger=control.read(previous.ledger);delivery=parent.ROOT/'DELIVERABLE_s6_d6'
    frozen={str(p.resolve()):control.sha_file(p) for p in parent.ROOT.rglob('*') if p.is_file() and p.name!='DISPATCH.lock' and '__pycache__' not in p.parts}
    anchor={'calls_started':158,'reported_tokens':2915735,'calls_with_known_usage':157,'unknown_token_reservations':64010,'pending_ordinals':[70],'parent_files':frozen,'parent_sources':list(ledger['source_manifest']),'model_configs':deepcopy(ledger['model_configs']),'parent_ledger_sha256':control.sha_file(previous.ledger),'feedback_sha256':control.sha_file(FEEDBACK),'source_script_sha256':control.digest(control.read(delivery/'FULL_SCRIPT.json'))}
    control.write(ROOT/'INHERITED_ANCHOR.json',anchor,True);control.write(ROOT/'CONTINUATION_SCOPE.json',AUTH,True)
    return runtime().prepare()


def runtime():
    a=control.read(ROOT/'INHERITED_ANCHOR.json')
    inherited={k:deepcopy(a[k]) for k in ('calls_started','reported_tokens','calls_with_known_usage','unknown_token_reservations','pending_ordinals')};inherited['parent_anchor_sha256']=control.sha_file(ROOT/'INHERITED_ANCHOR.json')
    sources=[PROJECT/p for p in a['parent_sources']]+[Path(__file__).resolve(),PROJECT/'tests/test_creative_content_revision_v17.py',PROJECT/'src/content_factory/creative_review_evidence_ids.py']
    def guard():
        parent.runtime().check(control.read(parent.ROOT/'CALL_LEDGER.json'))
        for p,h in a['parent_files'].items():
            if control.sha_file(p)!=h:raise RuntimeError('frozen S6 parent changed')
        if control.sha_file(FEEDBACK)!=a['feedback_sha256'] or control.read(ROOT/'CONTINUATION_SCOPE.json')!=AUTH:raise RuntimeError('feedback/scope changed')
        for role,cfg in a['model_configs'].items():
            live=source.legacy.role_config(role)
            if live.model!=cfg['model'] or live.base_url!=cfg['base_url']:raise RuntimeError('unverified model switch')
    return control.ContinuationRuntime(PROJECT,ROOT,sources,inherited,a['model_configs'],inherited_guard=guard,quota_state=None,shared_lock=identity.SHARED_LOCK)


def summary():
    rt=runtime();ledger=control.read(rt.ledger);value=rt.summary()
    known=sum(type((rt.effective_receipt(row).get('response_metadata') or {}).get('total_tokens')) is int for row in ledger['calls'])
    value.update(calls_with_known_usage=157+known,new_unknown_token_reservations=value['unknown_token_reservations'],unknown_token_reservations=64010+value['unknown_token_reservations'],inherited_pending_ordinals=[70],old_call70_resolved=False,media_calls=0)
    return value


def latest(prefix):
    rt=runtime();ledger=control.read(rt.ledger);rt.check(ledger)
    matches=[rt.effective_receipt(row) for row in ledger['calls'] if row['label'].startswith(prefix)]
    if not matches or matches[-1]['status']!='contract_valid':raise RuntimeError('latest stage missing/rejected; no old fallback')
    return source.stage_record_view(matches[-1])


def writer_request(revision,repair=None):
    ctx=source.original();old=control.read(parent.ROOT/'DELIVERABLE_s6_d6/FULL_SCRIPT.json');ctx.pop('script')
    feedback=control.read(FEEDBACK)
    issues={'user_feedback':feedback,'response_repair':repair,'request':'完整重写全片，不能仅改第三/五/八拍或拼接新旧。先减无叙事重复，再补被记住的选择和门外情绪落点；不添第三人。本稿不填写秒数，5–6秒和门外1–2秒是后续导演/表演目标，不能声称已实现。'}
    messages=source.linear.build_linear_script_messages(ctx,old,issues)
    schema=source.linear.build_linear_script_schema(source.original())
    wire=source.wire('writer',messages,schema,6500,{'stage':'complete_content_revision','parent_script_sha256':control.digest(old),'feedback_sha256':control.sha_file(FEEDBACK),'full_reference_pack_in_messages':True,'reference_pack_sha256':control.digest(ctx['reference_pack']),'complete_new_script_required':True})
    wire['operator_version']=VERSION
    actual=json.loads(wire['messages'][1]['content'])
    if actual['context']['reference_pack']!=ctx['reference_pack'] or actual['previous_script']!=old or actual['issues']['user_feedback']!=feedback:raise RuntimeError('full source/feedback absent from actual request')
    return wire


def dispatch(label,request,validator):
    old70=control.read(source.ROOT/'call_070_direction_s6_r2.json')['request']
    if identity.network_identity(request)==identity.network_identity(old70):raise RuntimeError('unknown70 resend forbidden')
    control.write(ROOT/'request_previews'/f'{label}.json',request,True)
    control.write(ROOT/'request_previews'/f'{label}_INPUT_VERIFICATION.json',{'full_original_reference_pack_verified_in_actual_request':True,'feedback_sha256':control.sha_file(FEEDBACK),'no_old_response_resend':True,'old_unknown_reservation_preserved':64010,'automatic_retry':False},True)
    return runtime().dispatch(label,request,validator)


def draft(revision=1,repair=None):
    req=writer_request(revision,repair)
    def validate(raw):
        result=source.derive(raw)
        return {'complete_model_authored_new_script':True,'derived_sha256':control.digest(result),'beats':len(raw['beats']),'timing_status':source.linear.TIMING_STATUS,'creative_quality_passed':False}
    return dispatch(f'draft_s7_r{revision}',req,validate)


def script_context():
    receipt=latest('draft_s7_r');ctx=source.original();ctx['script']=source.derive(receipt['output']);ctx['script'].pop('screenplay_markdown')
    ctx['user_content_feedback']=control.read(FEEDBACK);ctx['raw_linear_script']=deepcopy(receipt['output'])
    ctx['script_revision_source']={'ordinal':receipt['ordinal'],'raw_sha256':control.digest(receipt['output']),'complete_model_authored':True,'protocol':source.linear.VERSION}
    ctx['script_timing_status']=source.linear.TIMING_STATUS;ctx['script_preliminary_timing']=source.linear.preliminary_timing_estimates(receipt['output'])
    return ctx


def review_catalog(ctx):return ids.build_evidence_catalog(ctx)['entries']


def review_schema(ctx):
    result=typed_review.schema(ctx);catalog=review_catalog(ctx)
    result['properties']['schema']={'const':ID_VERSION};result['$defs']={'EvidenceID':{'type':'string','enum':list(catalog)}}
    refs=[result['properties']['issues']['items']['properties']['evidence_refs']]+[c['prefixItems'][2] for row in result['properties']['coverage']['prefixItems'] for c in row['prefixItems'][1:]]
    for ref in refs:ref['items']={'$ref':'#/$defs/EvidenceID'}
    return result


def expand_review(raw,ctx):
    Draft202012Validator(review_schema(ctx)).validate(raw)
    catalog=review_catalog(ctx);out=deepcopy(raw);out['schema']=source.compact.VERSION
    for refs in [row['evidence_refs'] for row in out['issues']]+[c[2] for row in out['coverage'] for c in row[1:]]:
        refs[:]=[[catalog[key]['path'],catalog[key]['quote']] for key in refs]
    return out


def review(revision=1,repair=None):
    ctx=script_context();messages=source.review_wire.script_messages(ctx);catalog=review_catalog(ctx)
    messages[0]['content']+='\n本次唯一证据外观：每项只写下面目录ID字符串，不写path/quote；schema为'+ID_VERSION+'。ID选择完整真实叶子，程序查表展开，全部旧业务验收保持。全文独立核对反馈落实、拿笔保持/纸面位置、门外动作先后、无新增同事及无补偿。对白开口之后要有听者反应；正文初步预算不是实际窗口。真实问题必须报告，不能为通过删问题。'
    messages.append({'role':'user','content':json.dumps({'source_directory':[{'id':key,'path':value['path'],'excerpt':value['quote'][:64]} for key,value in catalog.items()]},ensure_ascii=False,separators=(',',':'))})
    if repair:messages.append({'role':'user','content':json.dumps({'prior_invalid_review':repair,'request':'独立全文重审并交完整响应；不本地改旧响应。'},ensure_ascii=False)})
    req=source.wire('director',messages,review_schema(ctx),20000,{'review_context_sha256':source.compact.context_digest(ctx),'script_sha256':control.digest(ctx['raw_linear_script']),'reference_pack_sha256':control.digest(ctx['reference_pack']),'full_reference_pack_in_messages':True,'evidence_catalog_sha256':control.digest(catalog)})
    req['operator_version']=VERSION
    if json.loads(req['messages'][1]['content'])!=ctx:raise RuntimeError('full review context absent')
    def validate(raw):
        decoded=expand_review(raw,ctx);result=source.review_wire.validate_script_review(decoded,ctx)
        control.write(ROOT/f'VALIDATED_SCRIPT_REVIEW_r{revision}.json',result,True)
        return {'complete_review_evidence_valid':True,'issue_count':len(result['issues']),'story_preserved':result['story_preserved'],'creative_quality_passed':False,'actual_performance_windows_available':False}
    return dispatch(f'script_review_s7_r{revision}',req,validate)


def save_reviewed_script(evidence):
    ctx=script_context();r=latest('script_review_s7_r');result=source.review_wire.validate_script_review(expand_review(r['output'],ctx),ctx)
    if result['issues'] or not result['story_preserved']:raise RuntimeError('unresolved full review')
    source.verify_assistant_evidence(ctx,evidence)
    raw=ctx['raw_linear_script'];out=ROOT/'REVIEWED_SCRIPT_s7';out.mkdir(parents=True,exist_ok=True)
    control.write(out/'FULL_SCRIPT.json',raw,True);control.write(out/'FULL_TEXT_REVIEW.json',result,True)
    text=source.linear.frozen_v2.render_linear_screenplay(raw)+'\n';p=out/'FULL_SCRIPT.md'
    if p.exists() and p.read_text(encoding='utf-8')!=text:raise RuntimeError('existing new script changed')
    if not p.exists():p.write_text(text,encoding='utf-8')
    state={'schema':VERSION,'status':'reviewed_complete_script_awaiting_new_director_and_actual_performance','script_sha256':control.digest(raw),'review_ordinal':r['ordinal'],'assistant_source_evidence':evidence,'user_quality_confirmation':None,'creative_quality_passed':False,'old_s6_handoff_invalid_for_s7':True,'old_s6_preserved':True,'new_director_required':True,'actual_performance_windows_available':False,'media_calls':0,'cost_ledger':summary()}
    control.write(out/'STATUS.json',state,True);return state


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');op=sys.argv[1]
    if op=='prepare':result=prepare()
    elif op=='draft':result=draft(int(sys.argv[2]))
    elif op=='review':result=review(int(sys.argv[2]))
    elif op=='report':result=summary()
    elif op=='save':result=save_reviewed_script(control.read(sys.argv[2]))
    else:raise ValueError('prepare | draft REV | review REV | report | save EVIDENCE')
    if isinstance(result,dict) and 'ordinal' in result:result={key:result.get(key) for key in ('ordinal','label','status','validation','validation_error','response_metadata')}
    print(json.dumps(result,ensure_ascii=False,indent=2))
