"""S7 review continuation: explicit current/previous source IDs, no content patch."""
from copy import deepcopy
from pathlib import Path
import json,sys,types
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
if __package__ in (None,''):
    pkg=types.ModuleType('scripts');pkg.__path__=[str(PROJECT/'scripts')];sys.modules['scripts']=pkg
from scripts import run_creative_content_revision_v18 as old
from jsonschema import Draft202012Validator
source=old.source;control=old.control;identity=old.identity;parent=old.parent
ROOT=PROJECT/'data/production_revisions/this_time_i_leave_s7_review_binding_20261005'
FEEDBACK=old.FEEDBACK
VERSION='s7_script_review_comparisons/v20'
ID_VERSION='script_review_source_ids/v20'
AUTH={'scope':'necessary complete S7 script review with explicit source comparison schema','automatic_retry':False,'aggregate_text_token_cap':None,'media_calls':0,'old_budget_reset':False}
script_context=old.script_context
review_catalog=old.review_catalog


def prepare():
    if (ROOT/'ANCHOR.json').exists():return runtime().prepare()
    rt=old.runtime();rt.check(control.read(rt.ledger));spend=old.summary()
    if spend['new_unknown_token_reservations']:raise RuntimeError('current new result or usage unresolved')
    ledger=control.read(rt.ledger)
    a={'calls_started':spend['effective_calls_started'],'reported_tokens':spend['effective_reported_tokens'],'calls_with_known_usage':spend['calls_with_known_usage'],'unknown_token_reservations':93117,'pending_ordinals':[70,160],'parent_sources':list(ledger['source_manifest']),'model_configs':ledger['model_configs'],'parent_files':{str(p.resolve()):control.sha_file(p) for p in old.ROOT.rglob('*') if p.is_file() and p.name!='DISPATCH.lock' and '__pycache__' not in p.parts}}
    control.write(ROOT/'ANCHOR.json',a,True);control.write(ROOT/'CONTINUATION_SCOPE.json',AUTH,True)
    return runtime().prepare()


def runtime():
    a=control.read(ROOT/'ANCHOR.json');inherited={k:deepcopy(a[k]) for k in ('calls_started','reported_tokens','calls_with_known_usage','unknown_token_reservations','pending_ordinals')};inherited['parent_anchor_sha256']=control.sha_file(ROOT/'ANCHOR.json')
    def guard():
        old.runtime().check(control.read(old.runtime().ledger))
        for p,h in a['parent_files'].items():
            if control.sha_file(p)!=h:raise RuntimeError('frozen original script/review changed')
        if control.read(ROOT/'CONTINUATION_SCOPE.json')!=AUTH:raise RuntimeError('scope changed')
    sources=[PROJECT/p for p in a['parent_sources']]+[Path(__file__).resolve(),PROJECT/'tests/test_creative_s7_review_v20.py']
    return control.ContinuationRuntime(PROJECT,ROOT,sources,inherited,a['model_configs'],inherited_guard=guard,quota_state=None,shared_lock=identity.SHARED_LOCK)


def summary():
    rt=runtime();value=rt.summary();a=control.read(ROOT/'ANCHOR.json');ledger=control.read(rt.ledger)
    known=sum(type((rt.effective_receipt(row).get('response_metadata') or {}).get('total_tokens')) is int for row in ledger['calls'])
    value.update(calls_with_known_usage=a['calls_with_known_usage']+known,new_unknown_token_reservations=value['unknown_token_reservations'],unknown_token_reservations=93117+value['unknown_token_reservations'],unknown_outcome_ordinals=[70],unknown_usage_ordinals=[70,160],media_calls=0)
    return value


def latest(prefix):
    if prefix.startswith('draft_s7_r'):return old.latest(prefix)
    rt=runtime();ledger=control.read(rt.ledger);rt.check(ledger)
    matches=[rt.effective_receipt(row) for row in ledger['calls'] if row['label'].startswith(prefix)]
    if not matches or matches[-1]['status']!='contract_valid':raise RuntimeError('latest full review missing/rejected')
    return source.stage_record_view(matches[-1])


def comparison_groups(ctx,index,check_index):
    groups=[f'script.beats.{index}.']
    if check_index==2 and index>0:groups.append(f'script.beats.{index-1}.')
    if check_index==5:groups.append('static_visual_manifest.')
    return [[k for k,v in review_catalog(ctx).items() if v['path'].startswith(prefix)] for prefix in groups]


def review_schema(ctx):
    result=old.review_schema(ctx);result['properties']['schema']={'const':ID_VERSION}
    for index,row in enumerate(result['properties']['coverage']['prefixItems']):
        for ci,check in enumerate(row['prefixItems'][1:]):
            groups=comparison_groups(ctx,index,ci)
            if any(not options for options in groups):raise RuntimeError('comparison source missing from catalog')
            check['allOf']=[{'if':{'prefixItems':[{'enum':['pass','fail']}]},'then':{'prefixItems':[{}, {}, {'allOf':[{'contains':{'enum':options},'minContains':1} for options in groups]}]}}]
            check['prefixItems'][2]['description']='When pass/fail select a relevant current-beat source ID; continuity also immediately previous beat; assets also static asset source. No automatic evidence selection.'
    return result


def expand_review(raw,ctx):
    Draft202012Validator(review_schema(ctx)).validate(raw);catalog=review_catalog(ctx);out=deepcopy(raw);out['schema']=source.compact.VERSION
    for refs in [row['evidence_refs'] for row in out['issues']]+[c[2] for row in out['coverage'] for c in row[1:]]:refs[:]=[[catalog[key]['path'],catalog[key]['quote']] for key in refs]
    return out


def review(revision=1):
    ctx=script_context();messages=source.review_wire.script_messages(ctx);catalog=review_catalog(ctx)
    # Replace the transport-only format appendix; retain all semantic review rules.
    legacy=source.review_wire.format_addendum(ctx)
    messages[0]['content']=messages[0]['content'].replace(legacy,'')
    shape=['B实际编号',['pass','逐项核对理由',['实际目录ID'],[]],['pass','刺激对白反应先后',['实际目录ID'],[]],['pass','本拍与紧邻前拍对照',['本拍ID','前拍ID'],[]],['not_applicable','尚无实际窗口',[],[]],['not_applicable','剧本阶段',[],[]],['pass','正文与资产对照',['本拍ID','资产ID'],[]]]
    messages[0]['content']+='\n唯一工具输出格式：schema='+ID_VERSION+'，coverage每行七列、每检查四列普通数组。evidence_refs每项仅目录ID字符串，绝不写[path,quote]或[id,quote]。结构示例（占位词不得提交）：'+json.dumps(shape,ensure_ascii=False)+'\n每项pass/fail必须选本拍正文ID；continuity同时选紧邻前拍正文ID（不能用更早同道具状态代替紧邻前拍）；assets同时选本拍正文和资产定义ID。这些组合现在写入Schema，本地仍执行完整v6/v7业务验收。正文与静态归属不证明动作持有、声音或质量通过。完整十拍独立重审，不删真问题、不改剧本。'
    messages.append({'role':'user','content':json.dumps({'source_directory':[{'id':k,'path':v['path'],'excerpt':v['quote'][:64]} for k,v in catalog.items()]},ensure_ascii=False,separators=(',',':'))})
    req=source.wire('director',messages,review_schema(ctx),20000,{'review_context_sha256':source.compact.context_digest(ctx),'script_sha256':control.digest(ctx['raw_linear_script']),'full_reference_pack_in_messages':True,'reference_pack_sha256':control.digest(ctx['reference_pack']),'evidence_catalog_sha256':control.digest(catalog),'source_comparison_schema_version':VERSION});req['operator_version']=VERSION
    if json.loads(req['messages'][1]['content'])!=ctx:raise RuntimeError('full context absent')
    control.write(ROOT/'request_previews'/f'script_review_s7_r{revision}.json',req,True)
    def validate(raw):
        result=source.review_wire.validate_script_review(expand_review(raw,ctx),ctx)
        control.write(ROOT/f'VALIDATED_SCRIPT_REVIEW_r{revision}.json',result,True)
        return {'complete_review_evidence_valid':True,'issue_count':len(result['issues']),'story_preserved':result['story_preserved'],'actual_performance_windows_available':False,'creative_quality_passed':False}
    return runtime().dispatch(f'script_review_s7_r{revision}',req,validate)


def save_reviewed_script(evidence):
    ctx=script_context();rec=latest('script_review_s7_r');result=source.review_wire.validate_script_review(expand_review(rec['output'],ctx),ctx)
    if result['issues'] or not result['story_preserved']:raise RuntimeError('unresolved script review')
    source.verify_assistant_evidence(ctx,evidence);raw=ctx['raw_linear_script'];out=ROOT/'REVIEWED_SCRIPT_s7'
    control.write(out/'FULL_SCRIPT.json',raw,True);control.write(out/'FULL_TEXT_REVIEW.json',result,True)
    p=out/'FULL_SCRIPT.md';text=source.linear.frozen_v2.render_linear_screenplay(raw)+'\n'
    if p.exists() and p.read_text(encoding='utf-8')!=text:raise RuntimeError('script changed')
    if not p.exists():p.write_text(text,encoding='utf-8')
    state={'schema':VERSION,'status':'reviewed_complete_script_awaiting_new_director_and_actual_performance','script_sha256':control.digest(raw),'review_ordinal':rec['ordinal'],'assistant_source_evidence':evidence,'user_quality_confirmation':None,'creative_quality_passed':False,'old_s6_handoff_invalid_for_s7':True,'old_s6_preserved':True,'new_director_required':True,'actual_performance_windows_available':False,'media_calls':0,'cost_ledger':summary()}
    control.write(out/'STATUS.json',state,True);return state


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');op=sys.argv[1]
    if op=='prepare':result=prepare()
    elif op=='review':result=review(int(sys.argv[2]))
    elif op=='report':result=summary()
    else:raise ValueError('prepare | review REV | report')
    if isinstance(result,dict) and 'ordinal' in result:result={k:result.get(k) for k in ('ordinal','status','validation','validation_error','failure','response_metadata')}
    print(json.dumps(result,ensure_ascii=False,indent=2))
