"""Opt-in authorized story-first text trial; never changes production defaults."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation.protocol_direct import DirectLedger,NativeClient
from src.content_factory.novel_adaptation.story_text import generate
from src.content_factory.serial_story_runtime_v2 import run_lock


def prepare(run,prior,packet_path,authorization,targets,reviewed_materials=False,scope_guard=False,direct_story=False):
    state=read(prior/'STATE.json');plan=read(prior/'PLAN.json');source=read(prior/'SOURCE.json');packet=read(packet_path)
    if state['status'] in ('prepared','running'):raise ValueError('prior_still_running')
    unknown=list(state.get('retained_unknowns',[]))
    auth=read(authorization) if authorization else None
    if state['pending'] is not None or state['status']=='outcome_unknown':
        if (not auth or auth.get('authorized') is not True or auth.get('call')!=state['pending']
                or auth.get('original_state_sha256')!=digest(state) or auth.get('original_unknown_preserved') is not True):
            raise ValueError('unknown_disposition_authorization_missing')
        unknown.append({'call':state['pending'],'prior':str(prior.resolve()),'state_sha256':digest(state),'usage':None})
    if packet['source_sha256']!=digest(source):raise ValueError('packet_source_mismatch')
    if not targets or not set(targets)<={c['index'] for c in source['chapters']}:raise ValueError('target_missing')
    if plan['max_calls']-state['calls_started']<(1 if direct_story else 2):raise ValueError('stage_window_unavailable')
    plan['inference']['writer_effort']='medium'
    plan.update(baseline_calls=state['calls_started'],baseline_tokens=state['reported_tokens'])
    run.mkdir(exist_ok=False)
    for name,value in [('PLAN',plan),('SOURCE',source),('PACKET',packet),('TARGETS',targets),
        ('CONFIG',{'use_reviewed_materials':reviewed_materials,'scope_guard':scope_guard,'direct_story':direct_story}),
        ('AUTHORIZATION',auth),('LINEAGE',{'prior':str(prior.resolve()),'prior_state_sha256':digest(state),
        'retained_unknowns':unknown,'source_sha256':digest(source),'max_calls_unchanged':True})]:freeze(run/(name+'.json'),value)
    initial={'status':'prepared','pending':None,'calls_started':state['calls_started'],'reported_tokens':state['reported_tokens'],
        'baseline_calls':state['calls_started'],'baseline_tokens':state['reported_tokens'],'retained_unknowns':unknown,
        'reported_usage_complete':not unknown}
    ledger=DirectLedger(run,plan,initial,None);ledger.save()


def execute(run):
    with run_lock(run):
        state=read(run/'STATE.json');plan=read(run/'PLAN.json')
        if state['status']!='prepared' or state['pending'] is not None:raise ValueError('trial_not_fresh_prepared')
        ledger=DirectLedger(run,plan,state,NativeClient(run,plan))
        try:
            result=generate(ledger,read(run/'SOURCE.json'),read(run/'PACKET.json'),read(run/'TARGETS.json'),
                lambda name,value:freeze(run/(name+'.json'),value),
                use_reviewed_materials=read(run/'CONFIG.json')['use_reviewed_materials'],
                scope_guard=read(run/'CONFIG.json').get('scope_guard',False),
                direct_story=read(run/'CONFIG.json').get('direct_story',False))
            state['status']=result['status']
        except Exception as exc:
            state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
            freeze(run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:3000]})
        finally:ledger.save()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','execute']);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--prior',type=Path);p.add_argument('--packet',type=Path);p.add_argument('--authorization',type=Path)
    p.add_argument('--target-chapters',type=int,nargs='+');p.add_argument('--reviewed-materials',action='store_true');p.add_argument('--scope-guard',action='store_true');p.add_argument('--direct-story',action='store_true');a=p.parse_args()
    if a.command=='prepare':
        if not all((a.prior,a.packet,a.target_chapters)):p.error('prepare requires prior, packet, target-chapters')
        prepare(a.run,a.prior,a.packet,a.authorization,a.target_chapters,a.reviewed_materials,a.scope_guard,a.direct_story)
    else:execute(a.run)
