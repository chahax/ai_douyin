"""Source-only cumulative analysis, then full script agent, from chapter one."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.platform_adapter.fanqie_book_corpus import atomic
from src.content_factory.serial_story_runtime_v2 import run_lock
from src.content_factory.novel_adaptation import chapter_memory_v4 as m,agent_transport_v2 as transport,contracts as c
from scripts import run_autonomous_revision_v3 as scripts_v3
from src.content_factory.novel_adaptation import script_specification as spec_rules


def prepare(run,prior,end_chapter=3,reuse_analysis=False,reuse_reviewed_analysis=False,resume_failed_analysis=False,resume_script_review=None,advance_known_failed_script=False,specification=False,request_text=None,resume_script_check=None,source_only_after_rejection=False):
    state=read(prior/'STATE.json')
    if not state['trial_ended'] or state['pending'] is not None:raise ValueError('prior_not_terminal')
    corpus=read(prior/'SOURCE.json');m.packet(corpus,end_chapter)
    if not 2<=end_chapter<=3:raise ValueError('trial_scope_is_first_two_or_three')
    plan=deepcopy(read(prior/'PLAN.json'));imported=None;initial_memory=[];completed=[];start_chapter=1;resumed=None;script_resume=None
    if source_only_after_rejection:
        from src.content_factory.novel_adaptation.stream_evidence import audit_folder
        if any([reuse_analysis,reuse_reviewed_analysis,resume_failed_analysis,resume_script_review,resume_script_check,advance_known_failed_script,specification]):raise ValueError('choose_one_resume')
        if not plan.get('specification'):raise ValueError('fallback_requires_explicit_specification')
        failed=Path(state['current_run']);fs=read(failed/'STATE.json')
        if fs['pending'] is not None or not fs['trial_ended'] or fs['status']!='analysis_failed' or read(failed/'ERROR.json')['message']!='analysis_not_approved':raise ValueError('analysis_not_known_rejection')
        if audit_folder(failed/f"native_{fs['calls_started']:03}")['completion_evidence']!='known':raise ValueError('analysis_unknown')
        completed=deepcopy(state['chapters']);start_chapter=len(completed)+1
        if read(failed/'INPUT.json')!=m.packet(corpus,start_chapter):raise ValueError('fallback_requires_complete_source')
        initial_memory=read(prior/f'MEMORY_{start_chapter-1:03}.json');m.validate_memory(initial_memory,corpus,start_chapter)
        resumed=dict(method='quarantine_rejected_analysis_use_complete_original',chapter=start_chapter,origin_run=str(failed),
            call=fs['calls_started'],analysis_approved=False,original_state_digest=digest(fs))
    if advance_known_failed_script:
        from src.content_factory.novel_adaptation.stream_evidence import audit_folder
        if any([reuse_analysis,reuse_reviewed_analysis,resume_failed_analysis,resume_script_review]):raise ValueError('choose_one_resume')
        failed=Path(state['current_run']);fs=read(failed/'STATE.json')
        if state['status']!='trial_failed' or not fs['trial_ended'] or fs['pending'] is not None or fs['status'] not in ('known_invalid_output','auto_failed_contract'):
            raise ValueError('only_known_failed_script_can_be_retained')
        if audit_folder(failed/f"native_{fs['calls_started']:03}")['completion_evidence']!='known':raise ValueError('script_unknown')
        completed=deepcopy(state['chapters']);start_chapter=len(completed)+1
        if start_chapter>end_chapter:raise ValueError('no_more_trial_chapters')
        initial_memory=read(prior/f'MEMORY_{start_chapter-1:03}.json');m.validate_memory(initial_memory,corpus,start_chapter)
        resumed=dict(origin_run=str(failed),call=fs['calls_started'],chapter=start_chapter-1,
            method='retain_failed_script_continue_only_source_analysis_chain',script_accepted=False)
    if resume_script_review or resume_script_check:
        if resume_script_review and resume_script_check:raise ValueError('choose_one_resume')
        if reuse_analysis or reuse_reviewed_analysis or resume_failed_analysis:raise ValueError('choose_one_resume')
        failed=Path(state['current_run']);fs=read(failed/'STATE.json')
        if state['status']!='trial_failed' or not fs['trial_ended'] or fs['pending'] is not None:raise ValueError('script_not_terminal_known')
        completed=deepcopy(state['chapters'])
        # execute records the failed chapter before stopping; retain earlier chapters only.
        chapter=max(ch['chapter'] for ch in read(failed/'INPUT.json')['chapters'] if ch['role']=='target')
        completed=[x for x in completed if x['chapter']<chapter];start_chapter=chapter
        initial_memory=read(prior/f'MEMORY_{chapter:03}.json');m.validate_memory(initial_memory,corpus,chapter+1)
        script_resume=dict(origin_run=str(failed),chapter=chapter,review_node=resume_script_review,check_node=resume_script_check,
            analysis_run=str(prior/f'chapter_{chapter:03}_analysis'))
    if resume_failed_analysis:
        from src.content_factory.novel_adaptation.stream_evidence import audit_folder
        if reuse_analysis or reuse_reviewed_analysis:raise ValueError('choose_one_resume')
        failed=Path(state['current_run']);fs=read(failed/'STATE.json')
        if state['status']!='trial_failed' or fs['status']!='known_invalid_output' or fs['pending'] is not None:raise ValueError('not_known_analysis_format_failure')
        number=fs['calls_started'];call=read(failed/f'CALL_{number:03}.json')
        if call['node']!='analyze' or read(failed/f'ERROR_{number:03}.json')['type']!='JSONDecodeError':raise ValueError('only_first_analysis_json_failure')
        if audit_folder(failed/f'native_{number:03}')['completion_evidence']!='known':raise ValueError('analysis_unknown')
        completed=deepcopy(state['chapters']);start_chapter=len(completed)+1
        initial_memory=read(prior/f'MEMORY_{start_chapter-1:03}.json');m.validate_memory(initial_memory,corpus,start_chapter)
        payload=json.loads(call['messages'][1]['content'])
        if payload['source']!=m.packet(corpus,start_chapter) or payload['previous_memory']!=initial_memory:raise ValueError('failed_analysis_input_changed')
        resumed=dict(origin_run=str(failed),call=number,chapter=start_chapter,known_invalid_retained=True,
            original_response_digest=digest(read(failed/f'RESPONSE_{number:03}.json')))
    if reuse_analysis and reuse_reviewed_analysis:raise ValueError('choose_one_analysis_import')
    if reuse_reviewed_analysis:
        from src.content_factory.novel_adaptation.stream_evidence import audit_folder
        if state['status']!='analysis_failed' or read(prior/'ERROR.json')['message']!='analysis_not_approved':raise ValueError('not_completed_analysis_rejection')
        rec=state['nodes']['analysis_recheck'];number=rec['call']
        if rec['status']!='complete' or audit_folder(prior/f'native_{number:03}')['completion_evidence']!='known':raise ValueError('review_unknown')
        payload=json.loads(read(prior/f'CALL_{number:03}.json')['messages'][1]['content'])
        if payload['source']!=m.packet(corpus,1) or payload['previous_memory']!=[]:raise ValueError('analysis_source_changed')
        if payload['analysis']!=read(prior/'analysis_repair.json'):raise ValueError('review_analysis_changed')
        imported=dict(value=payload['analysis'],review=read(prior/'analysis_recheck.json'),call=number,
            source_digest=digest(payload['source']),origin_run=str(prior),method='reuse_analysis_and_rejection_for_one_adjudication',semantic_approved=False)
    if reuse_analysis:
        from src.content_factory.novel_adaptation.stream_evidence import audit_folder
        if state['status']!='known_invalid_output' or state['nodes']['analyze']['status']!='known_invalid_output':raise ValueError('not_known_analysis_failure')
        number=state['nodes']['analyze']['call'];call=read(prior/f'CALL_{number:03}.json')
        if read(prior/f'ERROR_{number:03}.json')['type']!='ContractError':raise ValueError('not_schema_failure')
        if audit_folder(prior/f'native_{number:03}')['completion_evidence']!='known':raise ValueError('analysis_unknown')
        payload=json.loads(call['messages'][1]['content'])
        if payload['source']!=m.packet(corpus,1) or payload['previous_memory']!=[]:raise ValueError('analysis_source_changed')
        raw=json.loads(read(prior/f'RESPONSE_{number:03}.json')['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
        faults=c.schema_issues(raw,m.schema(payload['source']),'imported_analysis')
        if faults:raise c.ContractError(faults)
        imported=dict(value=raw,call=number,source_digest=digest(payload['source']),origin_run=str(prior),
            method='revalidate_unchanged_native_under_expanded_classification',semantic_approved=False)
    plan.update(version='chapter_memory_v4',end_chapter=end_chapter,baseline_calls=state['calls_started'],
        baseline_tokens=state['reported_tokens'],max_calls=plan['max_calls'] if imported or resumed or script_resume else state['calls_started']+60,corpus_digest=digest(corpus),
        start_chapter=start_chapter,initial_memory_chapter=len(initial_memory),initial_memory_digest=digest(initial_memory),resumed_analysis=resumed,resumed_script=script_resume)
    plan['imported_analysis_digest']=digest(imported) if imported else None
    if specification:
        if imported or resumed or script_resume:raise ValueError('new_spec_requires_new_trial')
        plan['specification']=spec_rules.config()
    spec_rules.validate(plan.get('specification'))
    paths=[Path(__file__),Path(m.__file__),Path(scripts_v3.__file__),Path(transport.__file__),Path(spec_rules.__file__),
        Path(scripts_v3.n.__file__),Path(scripts_v3.base.__file__),Path(scripts_v3.prose_patch.__file__),
        Path('src/content_factory/novel_adaptation/agent_capacity_v2.py'),Path('src/content_factory/serial_story_transport_v6.py'),Path('scripts/serial_native_worker_v6.py')]
    plan['implementation_pin']={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    run.mkdir(exist_ok=False)
    for p in paths:(run/('SNAPSHOT_'+p.name)).write_bytes(p.read_bytes())
    freeze(run/'PLAN.json',plan);freeze(run/'SOURCE.json',corpus)
    if plan.get('specification'):(run/'SPECIFICATION.md').write_text(plan['specification']['text'],encoding='utf-8')
    if imported:freeze(run/'IMPORTED_ANALYSIS.json',imported)
    if resumed:freeze(run/'KNOWN_INVALID_PREDECESSOR.json',resumed)
    freeze(run/'AUTHORIZATION.json',dict(user=request_text or '后续应该有个前段分析越往后的内容分析内容应该越多，修改后从第一章开始测试',
        scope=f'第1—{end_chapter}章按序累积原文分析，各章完整文本剧本Agent测试；不生成媒体或发布。',
        prior=str(prior),max_calls=plan['max_calls'],max_analysis_repairs=1,max_script_repairs_per_chapter=2,no_budget_reset=bool(imported or resumed or script_resume)))
    atomic(run/'STATE.json',dict(status='prepared',trial_ended=False,pending=None,calls_started=state['calls_started'],
        reported_tokens=state['reported_tokens'],retained_unknowns=state.get('retained_unknowns',[]),chapters=completed,
        current_run=None,semantic_accepted=False))
    freeze(run/f'MEMORY_{len(initial_memory):03}.json',initial_memory)


def analyze(run,plan,ledger,corpus,memory,chapter,imported=None):
    source=m.packet(corpus,chapter);m.validate_memory(memory,corpus,chapter)
    run.mkdir(exist_ok=False)
    active=deepcopy(plan);active.update(baseline_calls=ledger['calls_started'],baseline_tokens=ledger['reported_tokens'])
    state=dict(status='prepared',pending=None,trial_ended=False,calls_started=ledger['calls_started'],
        reported_tokens=ledger['reported_tokens'],retained_unknowns=ledger.get('retained_unknowns',[]),nodes={})
    for name,value in [('PLAN',active),('SOURCE',corpus),('INPUT',source),('PRODUCTION_CHOICES',[]),('PREVIOUS_MEMORY',memory)]:freeze(run/(name+'.json'),value)
    t=transport.Transport(run,active,state);t.save()
    try:
        payload=dict(source=source,previous_memory=memory,current_chapter=chapter)
        if imported:
            if chapter!=1 or memory or imported['source_digest']!=digest(source):raise ValueError('invalid_analysis_import')
            analysis=imported['value'];freeze(run/'ANALYSIS_IMPORT.json',imported)
        else:
            resumed=plan.get('resumed_analysis') and plan['resumed_analysis']['chapter']==chapter
            try:analysis=t.call('analyze_format_retry' if resumed else 'analyze','writer',m.ANALYZE,payload,m.schema(source))
            except json.JSONDecodeError:
                if resumed or state['pending'] is not None or state['status']!='known_invalid_output':raise
                freeze(run/'FORMAT_RETRY_RECEIPT.json',dict(previous_state=deepcopy(state),method='one_new_analysis_request_after_known_complete_invalid_json'))
                state.update(trial_ended=False,status='retrying_known_format');t.save()
                analysis=t.call('analyze_format_retry','writer',m.ANALYZE,payload,m.schema(source))
        audit=imported['review'] if imported and 'review' in imported else t.call('analysis_review','writer',m.AUDIT,{**payload,'analysis':analysis},m.audit_schema(source))
        if audit['passed']!=(not bool(audit['issues'])):raise ValueError('analysis_review_verdict_conflict')
        if not audit['passed'] and not (imported and 'review' in imported):
            analysis=t.call('analysis_repair','writer',m.ANALYZE+'\n根据审核意见仅修本章delta，旧章memory不改，返回完整本章分析。',
                {**payload,'analysis':analysis,'review':audit},m.schema(source))
            audit=t.call('analysis_recheck','writer',m.AUDIT,{**payload,'analysis':analysis},m.audit_schema(source))
            if audit['passed']!=(not bool(audit['issues'])):raise ValueError('analysis_review_verdict_conflict')
        evidence=None
        if not audit['passed']:
            resolution=t.call('analysis_resolution','writer',m.RESOLVE,{**payload,'analysis':analysis,'review':audit},m.resolution_schema(source,audit))
            evidence=dict(original_review=audit,resolution=resolution)
            audit=m.resolved_audit(source,audit,resolution)
        updated=m.append(memory,corpus,chapter,analysis,audit,evidence)
        freeze(run/'MEMORY.json',updated);freeze(run/'ANALYSIS_FINAL.json',analysis)
        state['status']='analysis_approved_by_model'
        return updated
    except Exception as exc:
        if state['pending'] is None and state['status'] not in ('known_truncated','known_invalid_output','model_mismatch'):
            state['status']='analysis_failed'
        freeze(run/'ERROR.json',dict(type=type(exc).__name__,message=str(exc)[:2000]));raise
    finally:state['trial_ended']=True;t.save()


def execute(run):
    with run_lock(run):
        state=read(run/'STATE.json');plan=read(run/'PLAN.json');corpus=read(run/'SOURCE.json')
        start=plan.get('start_chapter',1);memory=read(run/f"MEMORY_{plan['initial_memory_chapter']:03}.json")
        if digest(memory)!=plan['initial_memory_digest']:raise ValueError('initial_memory_changed')
        if state['status']!='prepared' or state['trial_ended']:raise ValueError('run_not_fresh')
        if digest(corpus)!=plan['corpus_digest']:raise ValueError('corpus_changed')
        for path,sha in plan['implementation_pin'].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha:raise ValueError('implementation_changed')
        def sync(child):
            s=read(child/'STATE.json')
            for key in ('calls_started','reported_tokens','pending'):state[key]=s[key]
            atomic(run/'STATE.json',state)
            return s
        try:
            for chapter in range(start,plan['end_chapter']+1):
                arun=run/f'chapter_{chapter:03}_analysis';srun=run/f'chapter_{chapter:03}_script'
                resumed_script=plan.get('resumed_script')
                if resumed_script and resumed_script['chapter']==chapter:
                    arun=Path(resumed_script['analysis_run'])
                    scripts_v3.prepare(srun,Path(resumed_script['origin_run']),resume_review=resumed_script['review_node'],resume_check=resumed_script.get('check_node'),request_text=read(run/'AUTHORIZATION.json')['user'])
                elif plan.get('resumed_analysis') and plan['resumed_analysis'].get('method')=='quarantine_rejected_analysis_use_complete_original' and plan['resumed_analysis']['chapter']==chapter:
                    rejection=plan['resumed_analysis'];arun=Path(rejection['origin_run'])
                    if digest(read(arun/'STATE.json'))!=rejection['original_state_digest']:raise ValueError('rejection_record_changed')
                    memory=m.append_source_only(memory,corpus,chapter,rejection)
                    freeze(run/f'MEMORY_{chapter:03}.json',memory)
                    scripts_v3.prepare(srun,arun,mode='full',request_text=read(run/'AUTHORIZATION.json')['user'],
                        source_packet=m.packet(corpus,chapter),chapter_memory=m.author_context(memory,corpus,chapter),shared_max_calls=plan['max_calls'])
                else:
                    state.update(status='running',current_run=str(arun));atomic(run/'STATE.json',state)
                    imported=read(run/'IMPORTED_ANALYSIS.json') if chapter==1 and plan.get('imported_analysis_digest') else None
                    if imported and digest(imported)!=plan['imported_analysis_digest']:raise ValueError('imported_analysis_changed')
                    try:memory=analyze(arun,plan,state,corpus,memory,chapter,imported)
                    finally:
                        if (arun/'STATE.json').exists():sync(arun)
                    freeze(run/f'MEMORY_{chapter:03}.json',memory)
                    scripts_v3.prepare(srun,arun,mode='full',request_text=read(run/'AUTHORIZATION.json')['user'],
                        source_packet=m.packet(corpus,chapter),chapter_memory=m.author_context(memory,corpus,chapter),shared_max_calls=plan['max_calls'])
                state.update(current_run=str(srun));atomic(run/'STATE.json',state)
                scripts_v3.execute(srun);s=sync(srun)
                state['chapters'].append(dict(chapter=chapter,analysis_run=str(arun),script_run=str(srun),
                    script_status=s['status'],memory_digest=digest(memory),cumulative_analyses=len(memory)))
                atomic(run/'STATE.json',state)
                if s['pending'] is not None:raise RuntimeError('unknown_call_no_next_chapter')
                if s['status'] in ('known_invalid_output','known_truncated','model_mismatch','auto_failed_contract'):
                    raise RuntimeError('script_contract_failed_no_next_chapter')
                # Failed screenplay is never memory. Only approved source analysis
                # advances this evaluation sequence; no failed media is released.
            state['status']='trial_complete'
        except Exception as exc:
            state['status']='outcome_unknown' if state['pending'] is not None else 'trial_failed'
            freeze(run/'ERROR.json',dict(type=type(exc).__name__,message=str(exc)[:2000]))
        finally:
            state.update(trial_ended=True,semantic_accepted=False);atomic(run/'STATE.json',state)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','execute']);p.add_argument('--run',required=True,type=Path)
    p.add_argument('--prior',type=Path);p.add_argument('--end-chapter',type=int,default=3)
    p.add_argument('--reuse-analysis',action='store_true');p.add_argument('--reuse-reviewed-analysis',action='store_true')
    p.add_argument('--resume-failed-analysis',action='store_true');p.add_argument('--resume-script-review')
    p.add_argument('--advance-known-failed-script',action='store_true');p.add_argument('--specification',action='store_true');p.add_argument('--request-text');p.add_argument('--resume-script-check');p.add_argument('--source-only-after-rejection',action='store_true');a=p.parse_args()
    if a.command=='prepare':prepare(a.run,a.prior,a.end_chapter,a.reuse_analysis,a.reuse_reviewed_analysis,a.resume_failed_analysis,a.resume_script_review,a.advance_known_failed_script,a.specification,a.request_text,a.resume_script_check,a.source_only_after_rejection)
    else:execute(a.run)
