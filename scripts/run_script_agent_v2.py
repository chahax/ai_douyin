"""Task-scoped revision pipeline. New runs only; historical trial evidence stays immutable."""
import argparse
import difflib
import hashlib
import sys
from copy import deepcopy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_runtime_v2 import run_lock
from src.content_factory.novel_adaptation import agent_revision_v2 as n, agent_capacity_v2 as cap
from src.content_factory.novel_adaptation import agent_transport_v2 as transport, integrated_screenplay as writer
from src.content_factory.novel_adaptation import prose_patch,contracts as c
from src.content_factory.novel_adaptation.audiovisual_transcription import packet as source_packet


def history_for_scope(prior,packet):
    """Carry evidence records across task continuations, never across target scopes."""
    target=[x['chapter'] for x in packet['chapters'] if x['role']=='target']
    visited=set();chain=[];cursor=prior
    while cursor.resolve() not in visited:
        visited.add(cursor.resolve())
        if not (cursor/'INPUT.json').exists():break
        previous=read(cursor/'INPUT.json')
        if [x['chapter'] for x in previous.get('chapters',[]) if x['role']=='target']!=target:break
        if (cursor/'ISSUE_REGISTRY.json').exists():chain.append(read(cursor/'ISSUE_REGISTRY.json'))
        if not (cursor/'AUTHORIZATION.json').exists():break
        parent=read(cursor/'AUTHORIZATION.json').get('prior')
        if not parent:break
        cursor=Path(parent)
    merged={}
    for rows in reversed(chain):
        for row in rows:merged[(row['id'],row['review_digest'],row['candidate_digest'])]=deepcopy(row)
    return list(merged.values())


def prepare(run,prior,mode,context_chapters=None,target_chapters=None,capabilities=None,observations=None):
    old=read(prior/'STATE.json')
    if old['pending'] is not None or not old.get('trial_ended'):raise ValueError('prior_not_terminal')
    source=read(prior/'SOURCE.json')
    packet=read(prior/'INPUT.json') if mode=='recover-review' and not target_chapters else source_packet(source,context_chapters,target_chapters)
    choices=read(prior/'PRODUCTION_CHOICES.json') if mode=='recover-review' else []
    candidate=(prior/'SCREENPLAY.md').read_text(encoding='utf-8') if mode=='recover-review' else None
    history=history_for_scope(prior,packet) if mode=='recover-review' else []
    imported=read(observations) if observations else None
    independent_import=False
    if imported:
        if candidate is None or imported['candidate_digest']!=digest(candidate):raise ValueError('observations_candidate_mismatch')
        n.validate_report(packet,candidate,imported['report'])
        node=imported.get('known_review_node')
        if node:
            from src.content_factory.novel_adaptation.stream_evidence import audit_folder
            import json
            rec=old['nodes'][node]
            call=read(prior/f"CALL_{rec['call']:03}.json")
            if rec['status']!='complete' or call['role']!='director':raise ValueError('imported_review_not_complete_director')
            original_payload=json.loads(call['messages'][1]['content'])
            if digest(original_payload['source'])!=digest(packet) or original_payload['candidate']!=candidate or original_payload['production_choices']!=choices:
                raise ValueError('imported_review_input_mismatch')
            if read(prior/(node+'.json'))!=imported['report']:raise ValueError('imported_review_changed')
            if audit_folder(prior/f"native_{rec['call']:03}")['completion_evidence']!='known':raise ValueError('imported_review_stream_unknown')
            independent_import=True
    if mode=='recover-review':
        receipt=read(prior/'PATCH_RECEIPT.json') if (prior/'PATCH_RECEIPT.json').exists() else read(prior/'CANDIDATE_BINDING.json')
        if receipt['candidate_digest']!=digest(candidate):raise ValueError('prior_candidate_changed')
    profiles=read(capabilities) if capabilities else cap.profiles()
    for role,effort in [('writer','xhigh'),('director','high')]:
        cap.validate_profile(profiles[role],cap.PROFILES[role]['model'],effort,profiles[role]['recommended_output_tokens'])
    paths=[Path(__file__),Path(n.__file__),Path(cap.__file__),Path(transport.__file__),Path(writer.__file__),
           Path(prose_patch.__file__),Path('src/content_factory/serial_story_transport_v6.py'),
           Path('scripts/serial_native_worker_v6.py')]
    plan=dict(version='script_agent_v2',mode=mode,routes={k:dict(provider=v['provider'],model=v['model'],base_url=v['base_url']) for k,v in profiles.items()},
        capabilities=profiles,budgets={k:[v['recommended_output_tokens'],min(v['recommended_output_tokens']*2,v['max_output_tokens'])] for k,v in profiles.items()},
        inference=dict(writer_effort='xhigh',director_effort='high',director_thinking='enabled'),
        endpoint_overrides={'writer':'https://api.minimax.cn/v1'},
        baseline_calls=old['calls_started'],baseline_tokens=old['reported_tokens'],
        max_calls=read(prior/'PLAN.json')['max_calls'] if imported else old['calls_started']+24,
        max_repair_rounds=2,source_digest=digest(packet),choices_digest=digest(choices),
        observations_digest=digest(imported) if imported else None,
        imported_independent_review=independent_import,
        history_digest=digest(history),
        implementation_pin={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    run.mkdir(exist_ok=False)
    for p in paths:(run/('SNAPSHOT_'+p.name)).write_bytes(p.read_bytes())
    for name,value in [('PLAN',plan),('INPUT',packet),('SOURCE',source),('PRODUCTION_CHOICES',choices),
                       ('AUTHORIZATION',dict(user='执行方案',scope='模型能力、任务上下文、分级审核、多范围返修、定向复核及独立终审；当前稿恢复与另一组完整章节实测。仅文本，无媒体发布。',
                        prior=str(prior),prior_state_sha256=hashlib.sha256((prior/'STATE.json').read_bytes()).hexdigest(),
                        engineering_stop='最多两轮局部修复，每节点至多一次已知length扩容；24次为工程停止边界，非用户套餐额度'))]:
        freeze(run/(name+'.json'),value)
    if candidate is not None:(run/'ORIGINAL.md').write_text(candidate,encoding='utf-8')
    if imported:freeze(run/'OPEN_OBSERVATIONS.json',imported)
    freeze(run/'HISTORY_REGISTRY.json',history)
    state=dict(status='prepared',pending=None,calls_started=old['calls_started'],reported_tokens=old['reported_tokens'],
        retained_unknowns=old.get('retained_unknowns',[]),reported_usage_complete=False,trial_ended=False,nodes={})
    transport.Transport(run,plan,state).save()


def execute(run):
    with run_lock(run):
        state,plan=read(run/'STATE.json'),read(run/'PLAN.json')
        if state['status']!='prepared' or state['pending'] is not None or state['trial_ended']:raise ValueError('run_not_fresh')
        for p,h in plan['implementation_pin'].items():
            if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h:raise ValueError('implementation_changed')
        source=read(run/'INPUT.json');choices=read(run/'PRODUCTION_CHOICES.json')
        if digest(source)!=plan['source_digest'] or digest(choices)!=plan['choices_digest']:raise ValueError('source_or_choices_changed')
        registry=read(run/'HISTORY_REGISTRY.json')
        if digest(registry)!=plan['history_digest']:raise ValueError('history_changed')
        t=transport.Transport(run,plan,state);candidate=None;carried_review=None
        try:
            if plan['mode']=='recover-review':candidate=(run/'ORIGINAL.md').read_text(encoding='utf-8')
            else:
                value=t.call('generate','writer',writer.WRITE,n.context('generate',source,choices),c.obj(text=c.TEXT))
                candidate=value['text'];(run/'ORIGINAL.md').write_text(candidate,encoding='utf-8')
            if plan.get('observations_digest'):
                imported=read(run/'OPEN_OBSERVATIONS.json')
                if digest(imported)!=plan['observations_digest']:raise ValueError('observations_changed')
                carried_review=imported['report']
                n.remember_observations(registry,source,candidate,carried_review,0)
            (run/'SCREENPLAY.md').write_text(candidate,encoding='utf-8')
            for round_index in range(plan['max_repair_rounds']+1):
                prefix=f'round_{round_index}'
                if carried_review is None:
                    review=t.call(prefix+'_review','director',n.REVIEW,n.context('review',source,choices,candidate),n.REPORT)
                    independent=True
                else:
                    review=carried_review;carried_review=None
                    independent=round_index==0 and plan.get('imported_independent_review',False)
                    freeze(run/(prefix+'_CARRIED_REVIEW.json'),review)
                binding=n.validate_report(source,candidate,review)
                binding['independent']=independent
                freeze(run/(prefix+'_REVIEW_BINDING.json'),binding)
                if review['issues']:
                    verification=t.call(prefix+'_verify','writer',n.VERIFY_PROMPT,
                        n.context('verify',source,choices,candidate,review=review,relevant_history=n.relevant_history(registry,review['issues'])),n.VERIFY)
                else:verification=dict(decisions=[],summary='空问题清单，无须调用核验模型')
                adjudication=n.adjudicate(source,candidate,review,verification)
                freeze(run/(prefix+'_ADJUDICATION.json'),adjudication)
                n.record_issues(registry,adjudication,round_index)
                state['production_observations']=[x for x in registry if x['decision']=='supported' and x['verified_severity']=='production']
                if adjudication['unresolved_blocking']:
                    state['status']='unresolved_evidence';break
                if not adjudication['accepted'] and independent:
                    state['status']='ready_for_primary_review'
                    state['production_todos']=[x for x in registry if x['decision']=='supported' and x['verified_severity']=='production' and x['status']=='open']
                    state['style_suggestions']=[x for x in registry if x['decision']=='supported' and x['verified_severity']=='style' and x['status']=='open']
                    state['final_review_binding']=binding;break
                if not adjudication['accepted']:
                    # A rejected directed allegation is not an independent final audit.
                    if round_index==plan['max_repair_rounds']:
                        state['status']='independent_review_still_required';break
                    continue
                if round_index==plan['max_repair_rounds']:
                    state['status']='revision_rounds_exhausted';break
                spans=n.multi_span_plan(candidate,adjudication)
                freeze(run/(prefix+'_SPANS.json'),spans)
                history=n.relevant_history(registry,adjudication['accepted'])
                patch=t.call(prefix+'_patch','writer',n.REPAIR_PROMPT,
                    n.context('repair',source,choices,candidate,confirmed_issues=adjudication['accepted'],slots=spans['slots'],relevant_history=history),prose_patch.schema(spans))
                before=candidate;candidate=prose_patch.apply(before,spans,patch)
                (run/(prefix+'_BEFORE.md')).write_text(before,encoding='utf-8')
                (run/(prefix+'_AFTER.md')).write_text(candidate,encoding='utf-8')
                (run/(prefix+'_PATCH.diff')).write_text(''.join(difflib.unified_diff(before.splitlines(True),candidate.splitlines(True))),encoding='utf-8')
                freeze(run/(prefix+'_PATCH_BINDING.json'),dict(before_digest=digest(before),candidate_digest=digest(candidate),patch_digest=digest(patch),unselected_text_preserved=True))
                (run/'SCREENPLAY.md').write_text(candidate,encoding='utf-8')
                check=t.call(prefix+'_check','writer',n.CHECK_PROMPT,
                    n.context('check',source,choices,candidate,before=before,confirmed_issues=adjudication['accepted'],patches=patch,relevant_history=history),n.CHECK)
                n.validate_report(source,candidate,dict(issues=check['regressions'],summary=check['summary']))
                passed=n.apply_check(registry,adjudication,check,digest(candidate))
                freeze(run/(prefix+'_CHECK_BINDING.json'),dict(before_digest=digest(before),candidate_digest=digest(candidate),check_digest=digest(check),passed=passed))
                # Always review the new full candidate independently; failed checks remain
                # explicit obligations, never disappear solely because the blind review missed them.
                state['unresolved_check']=not passed
                if check['regressions']:
                    carried_review=dict(issues=check['regressions'],summary=check['summary'])
                    n.remember_observations(registry,source,candidate,carried_review,round_index+1)
                if not passed:
                    unresolved={x['id'] for x in check['results'] if x['result']=='unresolved'}
                    covered={x['id'] for x in check['regressions']}
                    if not unresolved.issubset(covered):
                        state['status']='targeted_check_missing_current_ranges';break
        except Exception as exc:
            if state['pending'] is None and state['status'] not in ['known_truncated','known_invalid_output','model_mismatch']:
                state['status']='needs_attention'
            freeze(run/'ERROR.json',dict(type=type(exc).__name__,message=str(exc)[:2500]))
        finally:
            if candidate is not None:
                freeze(run/'CANDIDATE_BINDING.json',dict(candidate_digest=digest(candidate),source_digest=digest(source)))
            freeze(run/'ISSUE_REGISTRY.json',registry)
            state.update(trial_ended=True,semantic_accepted=False,requires_primary_acceptance=True,video_released=False)
            t.save()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','execute'])
    p.add_argument('--run',type=Path,required=True);p.add_argument('--prior',type=Path)
    p.add_argument('--mode',choices=['recover-review','full'],default='recover-review')
    p.add_argument('--context',type=int,nargs='+');p.add_argument('--target',type=int,nargs='+')
    p.add_argument('--capabilities',type=Path)
    p.add_argument('--observations',type=Path)
    a=p.parse_args()
    if a.command=='prepare':prepare(a.run,a.prior,a.mode,a.context,a.target,a.capabilities,a.observations)
    else:execute(a.run)
