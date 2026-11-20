"""Extract only source-required actions; no screenplay repair in this step."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_transport_v6 import Ledger,NativeClient
from src.content_factory.novel_adaptation.events import event_schema
from src.content_factory.novel_adaptation import contracts as c

def main():
    p=argparse.ArgumentParser()
    for key in ('run','source','episode','packet','prior'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--chapters',type=int,nargs='+',required=True)
    p.add_argument('--additional-calls',type=int,default=6)
    a=p.parse_args();prior=read(a.prior/'STATE.json')
    if prior['pending'] is not None or prior['status']=='running':raise ValueError('prior_not_terminal')
    source=read(a.source);episode=read(a.episode);entities={'entities':read(a.packet)['entities']}
    plan=read(a.prior/'PLAN.json');plan.update(max_calls=prior['calls_started']+a.additional_calls,
        version='novel_adaptation/source_event_contract',source_sha256=digest(source))
    plan['inference']['writer_max_tokens']=16384
    a.run.mkdir(exist_ok=False,parents=True)
    state={'status':'prepared','calls_started':prior['calls_started'],'reported_tokens':prior['reported_tokens'],'pending':None,
        'baseline_calls':prior['calls_started'],'baseline_tokens':prior['reported_tokens']}
    for name,value in [('PLAN',plan),('SOURCE',source),('DESIGN',episode['design']),('ENTITIES',entities)]:freeze(a.run/(name+'.json'),value)
    freeze(a.run/'ENGINEERING_EXTENSION.json',{'basis':'持续重构与同书MiniMax文本实测授权；新证据要求独立原文动作合同',
        'prior':str(a.prior),'prior_state_sha256':digest(prior),'previous_calls':prior['calls_started'],
        'previous_tokens':prior['reported_tokens'],'additional_engineering_window':a.additional_calls,
        'old_run_replayed':False,'media':False,'publish':False})
    ledger=Ledger(a.run,plan,state,NativeClient(a.run,plan));ledger.save()
    try:
        schema=event_schema(source,episode['design'],entities,a.chapters)
        result=ledger.call('SOURCE_EVENTS','writer','''只从指定目标章提取本集必须发生的跨房间进出和道具交接，不写剧本、不审核已有稿。
原文是唯一依据，场次计划只用于匹配编号，若计划叙述与原文冲突按原文。
只列当前实际发生的动作。想去、被拦住未走、过去经历、原书未来都不是本场实际离场。
同房间走到床边/围上去不是跨房间移动。人物拿着物品走路不是道具交接。
leave表示某人必须离开该场房间，enter表示必须进入该场房间，不要求推定源文没有交代的场外位置。
transfer表示原文明示的实际持有变化。只用已有道具实例ID和人物/地点ID。
一个事件可列同时进出的多人。source_ids选真正支持动作的原段。没有明确依据的影视动作不列作强制要求。''',
            {'complete_chapters':c.indexed_chapters(source),'target_chapters':a.chapters,
             'entities':entities,'scene_assignments':episode['design']['scenes'],'places':episode['design']['places'],'props':episode['design']['props']},schema)
        errors=c.schema_issues(result,schema,'source_events')
        if errors:raise c.ContractError(errors)
        state['status']='source_events_awaiting_primary_review'
    except Exception as exc:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:5000]})
    finally:ledger.save()

if __name__=='__main__':main()
