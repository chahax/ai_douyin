"""One bounded model repair of confirmed initial owners, not manuscript edits."""
import argparse,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation import initial_prop_patch as patch
from src.content_factory.novel_adaptation.narrative_props import audit_event_structure
from src.content_factory.novel_adaptation.narrative_presence import replay,error_record
from src.content_factory.novel_adaptation.protocol_envelope import StringEnvelopeLedger,StringEnvelopeClient


def main():
    p=argparse.ArgumentParser()
    for field in ('prior','run'):p.add_argument('--'+field,type=Path,required=True)
    p.add_argument('--prop-ids',nargs='+',required=True)
    p.add_argument('--additional-calls',type=int,default=0)
    a=p.parse_args();old=read(a.prior/'STATE.json');plan=read(a.prior/'PLAN.json')
    if old['pending'] is not None or old['status'] in ('running','prepared'):raise ValueError('prior_not_terminal')
    if a.additional_calls<0:raise ValueError('negative_extension')
    ceiling=plan['max_calls'];plan['max_calls']=max(ceiling,old['calls_started']+a.additional_calls)
    candidate=read(a.prior/'CANDIDATE.json');props=read(a.prior/'PROP_PLAN.json')
    presence=read(a.prior/'PRESENCE.json');events=read(a.prior/'PROP_PROJECTION.json');inputs=read(a.prior/'INPUT.json')
    places=[r['id'] for r in props['places']];people=inputs['people']
    request_sha=digest(props);out_schema=patch.schema(props,a.prop_ids,people+places)
    a.run.mkdir(exist_ok=False)
    for name,value in [('PLAN',plan),('SOURCE',read(a.prior/'SOURCE.json')),('CANDIDATE',candidate),
        ('INPUT',inputs),('PRESENCE',presence),('ORIGINAL_PROP_PLAN',props),('ORIGINAL_PROP_PROJECTION',events),
        ('REPAIR_SCOPE',{'prop_ids':a.prop_ids,'paths':patch.owner_paths(props,a.prop_ids),'plan_sha256':request_sha}),
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
        body=ledger.call('INITIAL_OWNER_PATCH','writer',
            '''仅修正已确认的开场道具归属冲突。剧本第一段是叶北带袋进入厨房并交给叶嫣儿，初态却把袋子登记为已在厨房。初态是第一段开始前；按实际携带者修正指定owner字段，袋中内容物与容器有效持有者须一致。不得修改人物移动、剧本、recipes、容器关系或未指定字段。返回全部指定路径的新owner值。原稿是否确有白菜同袋等未决问题仍保留，本次归属修正不构成对这些关系的认可。''',
            {'candidate':candidate,'prop_plan':props,'initial_people':presence['initial_locations'],
             'approved_paths':patch.owner_paths(props,a.prop_ids),'first_segment_events':events['segments'][0]},out_schema)
        revised=patch.apply(props,body,a.prop_ids,people+places,request_sha)
        bound=patch.reuse_events(candidate,props,revised,events,a.prop_ids,people)
        freeze(a.run/'PROP_PLAN.json',revised);freeze(a.run/'PROP_PROJECTION.json',bound)
        freeze(a.run/'EVENT_STRUCTURE_AUDIT.json',audit_event_structure(presence,bound))
        freeze(a.run/'EVENT_REUSE.json',{'origin':str(a.prior),'original_sha256':digest(events),
            'semantic_body_unchanged':{k:v for k,v in events.items() if k!='plan_sha256'}=={k:v for k,v in bound.items() if k!='plan_sha256'},
            'semantic_acceptance':False})
        freeze(a.run/'COMBINED_REPLAY.json',replay(candidate,presence,people,places,prop_plan=revised,prop_projection=bound))
        state['status']='replayed_awaiting_semantic_review'
    except Exception as e:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',error_record(e))
    finally:ledger.save()


if __name__=='__main__':main()
