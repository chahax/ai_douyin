"""Bounded repair of approved event rows without rewriting plans or prose."""
import argparse,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation import prop_row_patch as patch
from src.content_factory.novel_adaptation.narrative_props import audit_event_structure
from src.content_factory.novel_adaptation.narrative_presence import replay,error_record
from src.content_factory.novel_adaptation.protocol_envelope import StringEnvelopeLedger,StringEnvelopeClient


def main():
    p=argparse.ArgumentParser()
    for field in ('prior','run'):p.add_argument('--'+field,type=Path,required=True)
    p.add_argument('--segment-ids',nargs='+',required=True)
    p.add_argument('--review-file',type=Path,required=True)
    p.add_argument('--artifact-from',type=Path,help='Explicit known complete artifacts when the latest accounted call produced no valid patch.')
    p.add_argument('--additional-calls',type=int,default=0)
    a=p.parse_args();old=read(a.prior/'STATE.json');plan=read(a.prior/'PLAN.json')
    if old['pending'] is not None or old['status'] in ('running','prepared'):raise ValueError('prior_not_terminal')
    if a.additional_calls<0:raise ValueError('negative_extension')
    ceiling=plan['max_calls'];plan['max_calls']=max(ceiling,old['calls_started']+a.additional_calls)
    artifact=a.artifact_from or a.prior
    artifact_state=read(artifact/'STATE.json')
    if artifact_state['pending'] is not None or artifact_state['status'] in ('running','prepared'):raise ValueError('artifact_source_not_terminal')
    candidate=read(artifact/'CANDIDATE.json');props=read(artifact/'PROP_PLAN.json')
    if digest(candidate)!=digest(read(a.prior/'CANDIDATE.json')) or digest(read(artifact/'SOURCE.json'))!=digest(read(a.prior/'SOURCE.json')):
        raise ValueError('accounting_artifact_source_mismatch')
    presence=read(artifact/'PRESENCE.json');events=read(artifact/'PROP_PROJECTION.json');inputs=read(artifact/'INPUT.json')
    places=[r['id'] for r in props['places']];people=inputs['people']
    identity={'candidate_sha256':digest(candidate),'plan_sha256':digest(props),'projection_sha256':digest(events)}
    entities={'entities':[{'id':id,'kind':'character'} for id in people]}
    schema=patch.schema(candidate,props,people,a.segment_ids)
    review=read(a.review_file)
    if review['request_identity']!=identity:raise ValueError('review_inputs_changed')
    a.run.mkdir(exist_ok=False)
    for name,value in [('PLAN',plan),('SOURCE',read(a.prior/'SOURCE.json')),('CANDIDATE',candidate),
        ('INPUT',inputs),('PRESENCE',presence),('ORIGINAL_PROP_PLAN',props),('ORIGINAL_PROP_PROJECTION',events),
        ('REPAIR_SCOPE',{'segment_ids':a.segment_ids,'request_identity':identity,'review':review}),
        ('ACCOUNTING',{'prior':str(a.prior),'prior_state_sha256':digest(old),'artifact_from':str(artifact),'artifact_state_sha256':digest(artifact_state),'old_ceiling':ceiling,
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
        body=ledger.call('EVENT_ROW_PATCH','writer',
            "只修复批准的事件投影行，完整剧本、人物移动、道具注册与recipes均不可变。根据confirmed_findings定位动作进行/完成时点以及使用与持有区别。不要编造原稿没有的动作。遇到候选自身矛盾或当前合同不能忠实表达的情况，追加new_uncertainties；不为了重放通过而删去实质动作或编造过渡。gestures.execution_place可显式指定物理发生地点而非机位，双方仍需同处该地点；transforms.participants可列共同操作或共同进食的人，必须包括actor且全部在场，actor不可拿父亲代替真正进食的孩子。所有指定行必须返回，其他行程序不变。保留必要事实，不靠删除检查项过关；动作证据引用当前段。连续进行的处理动作不能在开始段提前完成后又处理同一原料。phase优先于action_order，同phase才按顺序执行；每段全部事件和只读moves必须在action_order恰好出现一次。",
            {'candidate':candidate,'prop_plan':props,'presence':presence,
             'selected_projection_rows':[r for r in events['segments'] if r['id'] in a.segment_ids],'confirmed_findings':review['findings'],'selected_segment_ids':a.segment_ids},schema)
        bound=patch.apply(candidate,props,events,body,people,a.segment_ids,identity)
        revised=props
        freeze(a.run/'PROP_PLAN.json',revised);freeze(a.run/'PROP_PROJECTION.json',bound)
        freeze(a.run/'UNCHANGED_RECEIPT.json',{'candidate_sha256':digest(candidate),
            'unselected_segments_unchanged':[r for r in bound['segments'] if r['id'] not in a.segment_ids]==[r for r in events['segments'] if r['id'] not in a.segment_ids],
            'presence_sha256':digest(presence),'semantic_acceptance':False})
        freeze(a.run/'EVENT_STRUCTURE_AUDIT.json',audit_event_structure(presence,bound))
        freeze(a.run/'COMBINED_REPLAY.json',replay(candidate,presence,people,places,prop_plan=revised,prop_projection=bound))
        state['status']='replayed_awaiting_semantic_review'
    except Exception as e:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',error_record(e))
    finally:ledger.save()


if __name__=='__main__':main()
