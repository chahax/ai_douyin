"""One review, one scoped repair, one DeepSeek independent final audit."""
import argparse, hashlib, sys
from copy import deepcopy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation import integrated_revision as n, contracts as c, prose_patch
from src.content_factory.novel_adaptation.protocol_direct import DirectLedger,NativeClient
from src.content_factory.serial_story_transport_v6 import Ledger
from src.content_factory.serial_story_runtime_v2 import run_lock
from src.content_factory.novel_adaptation.stream_evidence import audit_folder


def prepare(run,prior):
    old=read(prior/'STATE.json')
    if old['pending'] is not None or not old.get('trial_ended'): raise ValueError('prior_not_terminal')
    plan=deepcopy(read(prior/'PLAN.json'))
    plan.pop('endpoint_override',None)
    plan.update(version='integrated_revision_v1',route='integrated_local_revision',
                baseline_calls=old['calls_started'],baseline_tokens=old['reported_tokens'],max_calls=old['calls_started']+3,
                endpoint_overrides={'writer':'https://api.minimax.cn/v1'},
                inference={'writer_effort':'xhigh','writer_max_tokens':32768,'wall_seconds':900,
                           'director_max_tokens':32768,'director_thinking':'enabled','director_effort':'high'})
    candidate=(prior/'xhigh/SCREENPLAY.md').read_text(encoding='utf-8')
    generation_call=old['variants']['xhigh']['generation_call']
    payload=read(prior/f'native_{generation_call:03}/REQUEST.json')['args']['messages'][1]['content']
    import json
    production_choices=json.loads(payload)['production_choices']
    plan['candidate_digest']=digest(candidate);plan['choices_digest']=digest(production_choices)
    paths=[Path(__file__),Path(n.__file__),Path(prose_patch.__file__),Path('src/content_factory/novel_adaptation/protocol_direct.py'),
           Path('src/content_factory/serial_story_transport_v6.py'),Path('scripts/serial_native_worker_v6.py')]
    plan['implementation_pin']={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    run.mkdir(exist_ok=False)
    for p in paths:(run/('SNAPSHOT_'+p.name)).write_bytes(p.read_bytes())
    for name in ['INPUT','SOURCE']:freeze(run/(name+'.json'),read(prior/(name+'.json')))
    freeze(run/'PRODUCTION_CHOICES.json',production_choices)
    (run/'ORIGINAL.md').write_text(candidate,encoding='utf-8')
    freeze(run/'PLAN.json',plan)
    freeze(run/'AUTHORIZATION.json',{'user':'这个流程再处理一遍看看效果，然后deepseek加入下之前说的审查',
        'scope':'同完整19前情20/21目标；MiniMax专项审查+局部返修，DeepSeek独立最终审查；最多3次文本调用；无媒体发布',
        'prior':str(prior),'candidate_digest':digest(candidate)})
    state={'status':'prepared','pending':None,'calls_started':old['calls_started'],'reported_tokens':old['reported_tokens'],
           'retained_unknowns':old.get('retained_unknowns',[]),'reported_usage_complete':False,'trial_ended':False,'completed_stages':[]}
    Ledger(run,plan,state,None).save()


def execute(run,stage,decision_path=None):
    with run_lock(run):
        plan,state=read(run/'PLAN.json'),read(run/'STATE.json')
        required={'review':'prepared','repair':'awaiting_issue_adjudication','final':'repaired_awaiting_final'}
        if state['pending'] is not None or state['status']!=required[stage]:raise ValueError('stage_not_ready')
        for p,h in plan['implementation_pin'].items():
            if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h:raise ValueError('changed_code')
        packet=read(run/'INPUT.json');choices=read(run/'PRODUCTION_CHOICES.json')
        original=(run/'ORIGINAL.md').read_text(encoding='utf-8')
        if digest(packet)!=plan['input_digest'] or digest(choices)!=plan['choices_digest'] or digest(original)!=plan['candidate_digest']:
            raise ValueError('changed_input')
        ledger=DirectLedger(run,plan,state,NativeClient(run,plan))
        base={'source':packet,'production_choices':choices}
        # Resolve all local preconditions before scheduling a new model call.
        spans=None
        if stage=='repair':
            decisions=read(decision_path)
            spans=n.span_plan(original,read(run/'review.json'),read(run/'REVIEW_DIAGNOSTICS.json'),decisions)
            freeze(run/'ISSUE_ADJUDICATION.json',decisions);freeze(run/'SPAN_PLAN.json',spans)
        if stage=='final':
            candidate=(run/'SCREENPLAY.md').read_text(encoding='utf-8')
            if digest(candidate)!=read(run/'PATCH_RECEIPT.json')['candidate_digest']:raise ValueError('changed_repaired_candidate')
        try:
            if stage=='review':
                review=ledger.call('review','writer',n.REVIEW,{**base,'candidate':original},n.REVIEW_SCHEMA)
                freeze(run/'REVIEW_DIAGNOSTICS.json',n.diagnose(packet,original,review))
                state['status']='awaiting_issue_adjudication'
            elif stage=='repair':
                patch=ledger.call('patch','writer',n.REPAIR,{**base,'candidate':original,'slots':spans['slots']},prose_patch.schema(spans))
                candidate=prose_patch.apply(original,spans,patch)
                (run/'SCREENPLAY.md').write_text(candidate,encoding='utf-8')
                freeze(run/'PATCH_RECEIPT.json',{'original_digest':digest(original),'candidate_digest':digest(candidate),
                    'span_plan_digest':digest(spans),'patch_digest':digest(patch),'unselected_text_preserved':True,'semantic_accepted':False})
                state['status']='repaired_awaiting_final'
            else:
                final=Ledger(run,plan,state,NativeClient(run,plan))
                value=final.call('FINAL_CONTENT_DEEPSEEK','director',n.FINAL,{**base,'candidate':candidate},c.obj(text=c.TEXT))
                folder=run/f"native_{state['calls_started']:03}"
                evidence=audit_folder(folder);freeze(run/f"STREAM_EVIDENCE_{state['calls_started']:03}.json",evidence)
                if evidence['completion_evidence']!='known':
                    state['pending']=state['calls_started'];raise ValueError('final_stream_unknown')
                errors=c.schema_issues(value,c.obj(text=c.TEXT),'final_report')
                if errors:raise c.ContractError(errors)
                if not value['text'].strip():raise ValueError('empty_final_report')
                (run/'DEEPSEEK_REVIEW.md').write_text(value['text'],encoding='utf-8')
                freeze(run/'FINAL_REVIEW_BINDING.json',{'candidate_digest':digest(candidate),'source_digest':digest(packet),
                    'review_digest':digest(value['text']),'prior_reviews_sent':False,'semantic_accepted':False})
                state.update(status='awaiting_primary_acceptance',trial_ended=True)
            state['completed_stages'].append(stage)
        except Exception as exc:
            state.update(status='outcome_unknown' if state['pending'] is not None else 'needs_attention',trial_ended=True)
            freeze(run/(stage+'_ERROR.json'),{'type':type(exc).__name__,'message':str(exc)[:2000]})
        finally:ledger.save()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','review','repair','final'])
    p.add_argument('--run',type=Path,required=True);p.add_argument('--prior',type=Path);p.add_argument('--decisions',type=Path)
    a=p.parse_args()
    if a.command=='prepare':prepare(a.run,a.prior)
    else:execute(a.run,a.command,a.decisions)
