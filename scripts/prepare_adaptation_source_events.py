"""Generate source-event obligations for independent review, never auto-dispatch scenes."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_transport_v6 import Ledger,NativeClient
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation.events import event_schema


def main():
    p=argparse.ArgumentParser()
    for key in ('prior','prepared','run'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--feedback',type=Path)
    a=p.parse_args();old=read(a.prior/'STATE.json')
    if old['pending'] is not None or old['status'] in ('running','prepared'):raise ValueError('prior_not_terminal')
    source=read(a.prepared/'SOURCE.json');packet=read(a.prepared/'PACKET.json');design=read(a.prepared/'DESIGN.json')
    brief=read(a.prepared/'BRIEF.json');plan=read(a.prior/'PLAN.json');plan['max_calls']=old['calls_started']+1
    a.run.mkdir(parents=True,exist_ok=False)
    for name,obj in [('SOURCE',source),('PACKET',packet),('DESIGN',design),('BRIEF',brief),('PLAN',plan)]:freeze(a.run/(name+'.json'),obj)
    freeze(a.run/'LINEAGE.json',{'prior':str(a.prior),'state_sha256':digest(old),'calls_carried':old['calls_started'],
        'tokens_carried':old['reported_tokens'],'engineering_extension':1,'authorization':'MiniMax同书文本持续授权，无媒体发布'})
    state={'status':'prepared','calls_started':old['calls_started'],'reported_tokens':old['reported_tokens'],
        'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens'],'pending':None}
    ledger=Ledger(a.run,plan,state,NativeClient(a.run,plan));ledger.save()
    try:
        schema=event_schema(source,design,{'entities':packet['entities']},brief['target_chapters'])
        result=ledger.call('SOURCE_EVENTS','writer','''从完整原文与本集设计中提取本集必须实际发生的状态事件，供独立审查。
enter/leave用于人物跨场进出，transfer用于已经存在的物件拿起放下递交，transform用于已登记配方制作及分餐。每件事只登记一次，原文未明确的普通连接动作用最少必要量，不把对白提及当发生。
第二章厨房前两个孩子在另一间屋，苏墨在自己屋；实际入厨房要登记。被推出厨房与门外说话要分开空间。厨房做饭完成才能端菜，随后六个孩子在饭桌场；只写本集剩余CH2-P013至P145，不重写已完成拿袋开场。
制作成品分餐使用transform配方，不要求尚未生成物品先transfer；将成品端到桌上才是transfer。制作米饭属普通影视补足，若无必要原文事件不强行列必需。每个source_ids必须支持动作，历史内心不列当前人物进出。
transfer的origin/destination是有效持有人，人物拿物换房间时持有人仍是这个人，不得把两个房间当物件交接两端。叶东当前持袋及袋中土豆，走入厨房不会改变持有人。端菜需在厨房先拿起给苏墨、到饭桌放下，从苏墨交给饭桌地点。一次跨场移动只限定一端场次，不能在相邻场次重复要求同一次进入。
用给定人物/物品/配方/场次ID，所有数组原生JSON数组。这里只产事件合同，不判剧本通过。''',
            {'complete_chapters':c.indexed_chapters(source),'design':{k:v for k,v in design.items() if k not in ('source_constraints','world_framework')},
             'entities':packet['entities'],'brief':brief,
             'feedback':read(a.feedback) if a.feedback else None},schema)
        errors=c.schema_issues(result,schema,'source_events')
        if errors:raise c.ContractError(errors)
        # Ledger.call already freezes the native parsed result under this stage name.
        state['status']='events_awaiting_primary_review'
    except Exception as e:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',{'type':type(e).__name__,'message':str(e)[:6000]})
    finally:ledger.save()

if __name__=='__main__':main()
