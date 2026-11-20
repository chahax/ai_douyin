"""Four effort levels, identical complete source/prompt; fixed max review each."""
import argparse
from copy import deepcopy
import hashlib
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_faithful_video_agent import TextLedger, NativeClient
from src.content_factory.corpus_screenplay_v1 import read, freeze
from src.content_factory.serial_story_runtime_v2 import run_lock
from src.content_factory.novel_adaptation import integrated_screenplay as n, contracts as c


def prepare(run, prior, endpoint=None, authorization=None):
    if endpoint is not None and endpoint != 'https://api.minimax.cn/v1':
        raise ValueError('unsupported_endpoint_override')
    old = read(prior/'STATE.json')
    if old['pending'] is not None or old['status'] in ('prepared', 'running', 'outcome_unknown'):
        raise ValueError('prior_not_terminal')
    prior_plan = read(prior/'PLAN.json')
    plan = {k: deepcopy(prior_plan[k]) for k in ('routes', 'context', 'source_sha256')}
    plan.update(version='integrated_effort_v1', route='integrated_screenplay',
                efforts=list(n.EFFORTS), review_effort='max',
                inference={'writer_effort':'medium', 'writer_max_tokens':32768, 'wall_seconds':900},
                baseline_calls=old['calls_started'], baseline_tokens=old['reported_tokens'],
                max_calls=old['calls_started']+2*len(n.EFFORTS),
                context_chapter_indices=[19], chapter_indices=[20,21])
    if endpoint is not None:
        plan['endpoint_override'] = endpoint
        plan['routes']['writer']['base_url'] = endpoint
    run.mkdir(exist_ok=False)
    paths = [Path(__file__), Path(n.__file__), Path('scripts/run_faithful_video_agent.py'),
             Path('src/content_factory/novel_adaptation/protocol_direct.py'),
             Path('src/content_factory/serial_story_transport_v6.py'),
             Path('scripts/serial_native_worker_v6.py')]
    plan['implementation_pin'] = {str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for p in paths:
        (run/('SNAPSHOT_'+p.name)).write_bytes(p.read_bytes())
    for name in ('SOURCE', 'INPUT'):
        freeze(run/(name+'.json'), read(prior/(name+'.json')))
    plan['input_digest'] = c.digest(read(run/'INPUT.json'))
    plan['writer_payload_digest'] = c.digest(n.writer_payload(read(run/'INPUT.json')))
    (run/'WRITER_PROMPT.txt').write_text(n.WRITE, encoding='utf-8')
    (run/'REVIEW_PROMPT.txt').write_text(n.REVIEW, encoding='utf-8')
    freeze(run/'PLAN.json', plan)
    freeze(run/'AUTHORIZATION.json', {'user':authorization or '调整不同强度minimax测试一轮',
        'scope':'同完整19前情20/21目标，完整剧本单节点；medium/high/xhigh/max各1次生成和1次固定max审查；仅文本，无重试、视频或发布',
        'baseline_calls':old['calls_started'], 'max_calls':plan['max_calls'], 'prior':str(prior),
        'endpoint_override':endpoint})
    state = deepcopy(old)
    state.update(status='prepared', stage=None, completed_stages=[], variants={}, trial_ended=False)
    state.pop('primary_comparison', None)
    TextLedger(run, plan, state, None).save()


def execute(run):
    with run_lock(run):
        state, plan = read(run/'STATE.json'), read(run/'PLAN.json')
        if state['status']!='prepared' or state['pending'] is not None:
            raise ValueError('not_fresh')
        for p,h in plan['implementation_pin'].items():
            if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h:
                raise ValueError('changed_code')
        packet = read(run/'INPUT.json')
        if c.digest(packet)!=plan['input_digest'] or c.digest(n.writer_payload(packet))!=plan['writer_payload_digest']:
            raise ValueError('changed_source_or_choices')
        active = deepcopy(plan)
        ledger = TextLedger(run, active, state, NativeClient(run, active))
        try:
            for effort in plan['efforts']:
                folder = run/effort
                folder.mkdir(exist_ok=False)
                result = state['variants'][effort] = {'status':'started', 'semantic_accepted':False}
                active['inference']['writer_effort'] = effort
                start_call = state['calls_started']
                try:
                    value = ledger.call('screenplay_'+effort, 'writer', n.WRITE, n.writer_payload(packet), c.obj(text=c.TEXT))
                    result['generation_call'] = state['calls_started']
                    freeze(folder/'PROTOCOL.json', n.validate_result(value))
                    candidate = value['text']
                    (folder/'SCREENPLAY.md').write_text(candidate, encoding='utf-8')
                    result['candidate_digest'] = c.digest(candidate)
                except Exception as exc:
                    result.update(status='generation_failed', error=str(exc)[:1000])
                    freeze(folder/'ERROR.json', result)
                    if state['pending'] is not None or state['calls_started']==start_call:
                        raise
                    ledger.save()
                    continue
                active['inference']['writer_effort'] = plan['review_effort']
                try:
                    review = ledger.call('review_'+effort, 'writer', n.REVIEW, n.review_payload(packet, candidate), c.obj(text=c.TEXT))
                    n.validate_result(review)
                    (folder/'REVIEW.md').write_text(review['text'], encoding='utf-8')
                    result.update(status='awaiting_primary_review', review_call=state['calls_started'])
                    freeze(folder/'REVIEW_BINDING.json', {'candidate_digest':c.digest(candidate), 'source_digest':c.digest(packet),
                        'review_digest':c.digest(review['text']), 'review_effort':plan['review_effort'], 'semantic_accepted':False})
                except Exception as exc:
                    result.update(status='review_failed', error=str(exc)[:1000])
                    freeze(folder/'REVIEW_ERROR.json', result)
                    if state['pending'] is not None:
                        raise
                state['completed_stages'].append(effort)
                ledger.save()
            state.update(status='awaiting_primary_comparison', trial_ended=True)
        except Exception as exc:
            state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
            freeze(run/'ERROR.json', {'type':type(exc).__name__, 'message':str(exc)[:2000]})
        finally:
            ledger.save()


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=['prepare','execute'])
    p.add_argument('--run',required=True,type=Path)
    p.add_argument('--prior',type=Path)
    p.add_argument('--endpoint')
    p.add_argument('--authorization')
    args=p.parse_args()
    if args.command=='prepare': prepare(args.run,args.prior,args.endpoint,args.authorization)
    else: execute(args.run)
