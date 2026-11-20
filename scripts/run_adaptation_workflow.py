"""Explicit independent entry; no default migration, no unknown replay."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_transport_v6 import Ledger,NativeClient
from src.content_factory.novel_adaptation.workflow import run_workflow
from src.content_factory.novel_adaptation.render import episode_markdown
from src.content_factory.novel_adaptation.protocol_envelope import StringEnvelopeClient,StringEnvelopeLedger


def main():
    parser=argparse.ArgumentParser()
    for arg in ('run','source','packet','routes','brief'):parser.add_argument('--'+arg,required=True,type=Path)
    parser.add_argument('--prior-run',action='append',type=Path,default=[])
    parser.add_argument('--ledger-prior',type=Path)
    parser.add_argument('--additional-calls',type=int,default=8)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--string-envelope',action='store_true')
    parser.add_argument('--design-only',action='store_true')
    for arg in ('design-checkpoint','source-events','event-review','handoff','native-checkpoints','checkpoint-review'):parser.add_argument('--'+arg,type=Path)
    args=parser.parse_args()
    if not 0<=args.additional_calls<=24:raise ValueError('invalid_engineering_window')
    source=read(args.source);packet=read(args.packet);brief=read(args.brief);routes=read(args.routes)
    if digest(source)!=packet['source_sha256'] or packet.get('semantic_status')!='selected_dependencies_reviewed':
        raise ValueError('packet_source_not_reviewed')
    prior=[]
    for path in args.prior_run:
        state=read(path/'STATE.json')
        if state['pending'] is not None or state['status']=='running':raise ValueError('prior_unknown_or_running_no_replay')
        prior.append({'path':str(path.resolve()),'state_sha256':digest(state),
            'calls':state['calls_started']-state.get('baseline_calls',0),
            'tokens':state['reported_tokens']-state.get('baseline_tokens',0)})
    if len({p['path'] for p in prior})!=len(prior):raise ValueError('duplicate_prior_run')
    baseline=sum(p['calls'] for p in prior);tokens=sum(p['tokens'] for p in prior)
    if args.ledger_prior:
        if prior:raise ValueError('choose_ledger_prior_or_disjoint_prior_runs')
        carried=read(args.ledger_prior/'STATE.json')
        if carried['pending'] is not None or carried['status']=='running':raise ValueError('prior_unknown_or_running_no_replay')
        baseline=carried['calls_started'];tokens=carried['reported_tokens']
        prior=[{'path':str(args.ledger_prior.resolve()),'state_sha256':digest(carried),'cumulative_ledger':True,
                'calls_carried':baseline,'tokens_carried':tokens}]
    previous_ceiling=read(args.ledger_prior/'PLAN.json')['max_calls'] if args.ledger_prior else baseline
    ceiling=max(previous_ceiling,baseline+args.additional_calls)
    if args.additional_calls==0:
        if not args.ledger_prior:raise ValueError('existing_window_requires_ledger_prior')
        ceiling=read(args.ledger_prior/'PLAN.json')['max_calls']
        if ceiling<=baseline:raise ValueError('existing_window_exhausted')
    checkpoints=read(args.native_checkpoints) if args.native_checkpoints else None
    if checkpoints is not None:
        review=read(args.checkpoint_review) if args.checkpoint_review else {}
        if (review.get('verdict')!='accepted_for_continuation' or review.get('checkpoint_sha256')!=digest(checkpoints)
            or review.get('source_sha256')!=digest(source)):raise ValueError('native_checkpoints_unreviewed')
    args.run.mkdir(exist_ok=False,parents=True)
    plan={**routes,'version':'novel_adaptation/compiled_workflow','max_calls':ceiling,
        'source_sha256':digest(source),'baseline_calls':baseline,'baseline_tokens':tokens}
    plan['inference']['writer_max_tokens']=32768
    for name,value in [('SOURCE',source),('PACKET',packet),('BRIEF',brief),('PLAN',plan),('LINEAGE',prior)]:freeze(args.run/(name+'.json'),value)
    freeze(args.run/'ENGINEERING_EXTENSION.json',{'basis':'用户授权MiniMax同书文本无需逐轮确认；当前长目标要求继续完成重构与真实验收',
        'previous_calls_preserved':baseline,'previous_tokens_preserved':tokens,'previous_ceiling':previous_ceiling,
        'requested_calls_available':args.additional_calls,'additional_engineering_window':ceiling-previous_ceiling,
        'cumulative_call_ceiling':plan['max_calls'],'fresh_compiled_workflow':True,'old_tasks_replayed':False,
        'media':False,'publish':False,'provider_budget_not_reset':True})
    snap=args.run/'implementation';snap.mkdir()
    files=list((Path(__file__).resolve().parents[1]/'src/content_factory/novel_adaptation').glob('*.py'))+[Path(__file__)]
    for file in files:(snap/file.name).write_bytes(file.read_bytes())
    state={'status':'prepared','calls_started':baseline,'reported_tokens':tokens,'pending':None,
        'baseline_calls':baseline,'baseline_tokens':tokens}
    ledger=(StringEnvelopeLedger(args.run,plan,state,StringEnvelopeClient(args.run,plan)) if args.string_envelope
            else Ledger(args.run,plan,state,NativeClient(args.run,plan)));ledger.save()
    if not args.execute:return
    try:
        candidate,review=run_workflow(args.run,ledger,source,packet,brief,
            design_checkpoint=read(args.design_checkpoint) if args.design_checkpoint else None,
            source_contract=read(args.source_events) if args.source_events else None,
            contract_review=read(args.event_review) if args.event_review else None,
            continuation=read(args.handoff) if args.handoff else None,native_scene_checkpoints=checkpoints,design_only=args.design_only)
        if args.design_only:state['status']='design_awaiting_primary_review'
        else:
            views=read(args.run/'PRODUCTION_VIEWS_UNAPPROVED.json')
            (args.run/'EPISODE_UNACCEPTED.md').write_text(episode_markdown(candidate,{'entities':packet['entities']},production_views=views,include_audit=False),encoding='utf-8')
            state['status']='episode_awaiting_primary_review'
    except Exception as exc:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(args.run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:6000]})
    finally:ledger.save()

if __name__=='__main__':main()
