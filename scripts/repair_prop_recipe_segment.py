"""Bounded repair of one recipe partition and its affected segment events."""
import argparse,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation import prop_recipe_patch as patch
from src.content_factory.novel_adaptation.narrative_props import audit_event_structure
from src.content_factory.novel_adaptation.narrative_presence import replay,error_record
from src.content_factory.novel_adaptation.protocol_envelope import StringEnvelopeLedger,StringEnvelopeClient


def main():
    p=argparse.ArgumentParser()
    for field in ('prior','run'):p.add_argument('--'+field,type=Path,required=True)
    for field in ('recipe-id','segment-id'):p.add_argument('--'+field,required=True)
    p.add_argument('--additional-calls',type=int,default=0)
    a=p.parse_args();old=read(a.prior/'STATE.json');plan=read(a.prior/'PLAN.json')
    if old['pending'] is not None or old['status'] in ('running','prepared'):raise ValueError('prior_not_terminal')
    if a.additional_calls<0:raise ValueError('negative_extension')
    ceiling=plan['max_calls'];plan['max_calls']=max(ceiling,old['calls_started']+a.additional_calls)
    candidate=read(a.prior/'CANDIDATE.json');props=read(a.prior/'PROP_PLAN.json')
    presence=read(a.prior/'PRESENCE.json');events=read(a.prior/'PROP_PROJECTION.json');inputs=read(a.prior/'INPUT.json')
    places=[r['id'] for r in props['places']];people=inputs['people']
    identity={'candidate_sha256':digest(candidate),'plan_sha256':digest(props),'projection_sha256':digest(events)}
    entities={'entities':[{'id':id,'kind':'character'} for id in people]}
    schema=patch.schema(candidate,props,entities,a.recipe_id,a.segment_id)
    a.run.mkdir(exist_ok=False)
    for name,value in [('PLAN',plan),('SOURCE',read(a.prior/'SOURCE.json')),('CANDIDATE',candidate),
        ('INPUT',inputs),('PRESENCE',presence),('ORIGINAL_PROP_PLAN',props),('ORIGINAL_PROP_PROJECTION',events),
        ('REPAIR_SCOPE',{'recipe_id':a.recipe_id,'segment_id':a.segment_id,'request_identity':identity}),
        ('ACCOUNTING',{'prior':str(a.prior),'prior_state_sha256':digest(old),'old_ceiling':ceiling,
                      'new_ceiling':plan['max_calls'],'net_extension':plan['max_calls']-ceiling,
                      'calls_carried':old['calls_started'],'tokens_carried':old['reported_tokens']})]:freeze(a.run/(name+'.json'),value)
    snap=a.run/'implementation';snap.mkdir();manifest={}
    for f in [Path(__file__),*Path('src/content_factory/novel_adaptation').glob('*.py')]:
        b=f.read_bytes();(snap/f.name).write_bytes(b);manifest[str(f)]=hashlib.sha256(b).hexdigest()
    freeze(snap/'MANIFEST.json',manifest)
    state={'status':'prepared','calls_started':old['calls_started'],'reported_tokens':old['reported_tokens'],
        'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens'],'pending':None}
    ledger=StringEnvelopeLedger(a.run,plan,state,StringEnvelopeClient(a.run,plan));ledger.save()
    try:
        body=ledger.call('RECIPE_SEGMENT_PATCH','writer',
            '''修复固定剧本的状态投影，不改剧本。一个双食材预处理recipe被叶东和叶南各调用一次导致重复消耗；将其分成分别处理白菜与土豆的两条规则，输入/输出各恰好保留一次，不增删物品。使用Schema指定的新ID。只返回指定segment的事件与action_order，其他段程序保持不变。
该段还把叶嫣儿拉着弟弟离开厨房的gesture排在两人离场之后；请按同一动作的真实先后安排gesture与已有moves。人物moves本身只读，索引照原表，不能删掉既有移动、改人物位置或通过删去拉手事实来规避检查。
保留该段已有必要道具动作，不新增原稿没有的交接。phase优先于action_order，只有同phase才能按action_order先后执行。全部事件、全部moves在action_order恰好出现一次。原存在的白菜同袋、盆与案板未决问题不因本次机械修订被认可。''',
            {'candidate':candidate,'prop_plan':props,'presence':presence,
             'selected_events':next(r for r in events['segments'] if r['id']==a.segment_id),
             'recipe_id':a.recipe_id,'segment_id':a.segment_id},schema)
        revised,bound=patch.apply(candidate,props,events,body,people,a.recipe_id,a.segment_id,identity)
        freeze(a.run/'PROP_PLAN.json',revised);freeze(a.run/'PROP_PROJECTION.json',bound)
        freeze(a.run/'UNCHANGED_RECEIPT.json',{'candidate_sha256':digest(candidate),
            'unselected_segments_unchanged':[r for r in bound['segments'] if r['id']!=a.segment_id]==[r for r in events['segments'] if r['id']!=a.segment_id],
            'presence_sha256':digest(presence),'semantic_acceptance':False})
        freeze(a.run/'EVENT_STRUCTURE_AUDIT.json',audit_event_structure(presence,bound))
        freeze(a.run/'COMBINED_REPLAY.json',replay(candidate,presence,people,places,prop_plan=revised,prop_projection=bound))
        state['status']='replayed_awaiting_semantic_review'
    except Exception as e:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',error_record(e))
    finally:ledger.save()


if __name__=='__main__':main()
