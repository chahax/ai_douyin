"""Two calls: exact source -> audiovisual candidate -> independent comparison."""
import argparse,hashlib,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.run_faithful_video_agent import TextLedger,NativeClient
from src.content_factory.corpus_screenplay_v1 import read,freeze
from src.content_factory.novel_adaptation import audiovisual_transcription as a, contracts as c
from src.content_factory.serial_story_runtime_v2 import run_lock

def prepare(run,prior):
    state=read(prior/'STATE.json');plan=read(prior/'PLAN.json');source=read(prior/'SOURCE.json')
    if state['pending'] is not None or state['status'] in ['prepared','running','outcome_unknown']:raise ValueError('prior_not_terminal')
    if state['calls_started']+2>plan['max_calls']:raise ValueError('insufficient_remaining_window')
    run.mkdir(exist_ok=False)
    plan.update(version='audiovisual_transcription_v1',chapter_indices=[20,21],context_chapter_indices=[19],
                baseline_calls=state['calls_started'],baseline_tokens=state['reported_tokens'])
    paths=[Path(__file__),Path(a.__file__),Path('scripts/run_faithful_video_agent.py')]
    plan['implementation_pin']={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for name,value in [('PLAN',plan),('SOURCE',source),('INPUT',a.packet(source,[19],[20,21])),
        ('AUTHORIZATION',{'user':'可以','scope':'将自由编剧替换为原文视听转写并测试；MiniMax文本，使用原304工程边界剩余2次','abandoned_call_290':'历史留档，不再等待/追查/重发'})]:freeze(run/(name+'.json'),value)
    state.update(status='prepared',completed_stages=[],stage=None)
    TextLedger(run,plan,state,None).save()

def execute(run):
    with run_lock(run):
        state=read(run/'STATE.json');plan=read(run/'PLAN.json')
        if state['status']!='prepared' or state['pending'] is not None:raise ValueError('not_fresh')
        for path,sha in plan['implementation_pin'].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=sha:raise ValueError('changed_code')
        ledger=TextLedger(run,plan,state,NativeClient(run,plan));original=read(run/'INPUT.json')
        try:
            candidate=ledger.call('transcription','writer',a.TRANSCRIBE,original,c.obj(text=c.TEXT))['text']
            (run/'screenplay.md').write_text(candidate,encoding='utf-8')
            state['completed_stages'].append('transcription');ledger.save()
            review=ledger.call('comparison','writer',a.REVIEW,a.review_input(original,candidate),c.obj(text=c.TEXT))
            (run/'review.md').write_text(review['text'],encoding='utf-8')
            freeze(run/'REVIEW_BINDING.json',{'candidate_sha256':c.digest(candidate),'review':review,'semantic_acceptance':False})
            state['completed_stages'].append('comparison');state['status']='awaiting_primary_full_review'
        except Exception as exc:
            state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
            freeze(run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:2000]})
        finally:ledger.save()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','execute']);p.add_argument('--run',type=Path,required=True);p.add_argument('--prior',type=Path);x=p.parse_args()
    if x.command=='prepare':prepare(x.run,x.prior)
    else:execute(x.run)
