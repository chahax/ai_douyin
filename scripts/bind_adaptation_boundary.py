"""One boundary asset proposal, scoped bindings, then complete known-scene replay."""
import argparse,sys
from copy import deepcopy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_transport_v6 import Ledger,NativeClient
from src.content_factory.novel_adaptation import contracts as c,scenes as sc
from src.content_factory.novel_adaptation.fixture_binding import apply
from src.content_factory.novel_adaptation.blocking import blocking_schema,compile_blocking
from src.content_factory.novel_adaptation.handoff import continue_state
from src.content_factory.novel_adaptation.workflow import scene_evidence_ids
from src.content_factory.novel_adaptation.reference_repair import checkpoint
from src.content_factory.novel_adaptation.patching import schedule_audio
from src.content_factory.novel_adaptation.events import validate_requirements


def main():
    p=argparse.ArgumentParser()
    for key in ('prior','run','scope','natives'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();old=read(a.prior/'STATE.json')
    if old['pending'] is not None or old['status'] in ('running','prepared'):raise ValueError('prior_not_terminal')
    source=read(a.prior/'SOURCE.json');packet=read(a.prior/'PACKET.json');design=read(a.prior/'DESIGN_COMPILED.json')
    natives=read(a.natives);scope=read(a.scope);brief=read(a.prior/'BRIEF.json');handoff=read(a.prior/'PREVIOUS_EPISODE_HANDOFF.json')
    contract=read(a.prior/'SOURCE_EVENTS.json');plan=read(a.prior/'PLAN.json')
    if old['calls_started']>=plan['max_calls']:raise ValueError('engineering_window_exhausted')
    a.run.mkdir(parents=True,exist_ok=False)
    for name,value in [('SOURCE',source),('PACKET',packet),('BEFORE_DESIGN',design),('BEFORE_NATIVES',natives),('SCOPE',scope),('PLAN',plan),
        ('BRIEF',brief),('SOURCE_EVENTS',contract),('SOURCE_EVENTS_REVIEW',read(a.prior/'SOURCE_EVENTS_REVIEW.json')),('PREVIOUS_EPISODE_HANDOFF',handoff)]:freeze(a.run/(name+'.json'),value)
    freeze(a.run/'LINEAGE.json',{'prior':str(a.prior),'state_sha256':digest(old),'calls_carried':old['calls_started'],
        'tokens_carried':old['reported_tokens'],'max_calls_preserved':plan['max_calls']})
    state={'status':'prepared','calls_started':old['calls_started'],'reported_tokens':old['reported_tokens'],
        'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens'],'pending':None}
    ledger=Ledger(a.run,plan,state,NativeClient(a.run,plan));ledger.save()
    try:
        schema=c.obj(verdict=c.choices(['supported','uncertain']),fixture=c.obj(id=c.choices([scope['fixture_id']]),kind=c.TEXT,
            owner=c.choices(scope['visible_from']),description=c.TEXT,display_name=c.TEXT,
            stationary={'type':'boolean','const':True},visible_from=c.refs(scope['visible_from'],len(scope['visible_from']))),
            reference_ids=c.refs(scope['references'],len(scope['references'])),source_ids=c.refs(c.catalog(source)))
        proposal=ledger.call('BOUNDARY_ASSET','writer','''依据完整原文与既有场景设计，判断选中引用是否实际指向同一扇厨房门，而非厨房内部。
若成立，登记这扇固定门的物理外观，stationary=true，可从厨房和紧邻走廊看见门；这不代表能看见门后的房间、人物或物品。
description只写结构材质外观，不把开着/关着状态永久写进外观；门的开关由实际镜头动作决定。使用既有半旧木门设定，不新增故事或改任何对白动作。
支持则返回全部给定reference_ids，程序仅替换对应目标编号；不支持则uncertain。source_ids引用支撑门和厨房隔断的原段。''',
            {'complete_chapters':c.indexed_chapters(source),'places':design['places'],'scenes':natives,'scope':scope},schema)
        errors=c.schema_issues(proposal,schema,'boundary')
        if errors:raise c.ContractError(errors)
        updated,raws=apply(design,natives,proposal,scope);freeze(a.run/'DESIGN_COMPILED.json',updated);freeze(a.run/'NATIVES_BOUND.json',raws)
        entities={'entities':packet['entities']};previous=continue_state(handoff,brief['handoff_sha256'],updated,entities,
            book_id=brief['book_id'],episode_id=brief['episode_id'],timeline_id=brief['timeline_id'])
        freeze(a.run/'INITIAL_STATE.json',previous);checks={}
        for spec in updated['scenes']:
            if spec['id'] not in raws:break
            raw=raws[spec['id']];checks[raw['id']]=checkpoint(raw,source,updated,previous)
            events=[e for e in contract['events'] if e['scene_id']==raw['id']];facts=[f for f in packet['facts'] if f['id'] in spec['fact_ids']]
            bs=blocking_schema(updated,entities,spec['fact_ids'],source,previous,scene_evidence_ids(facts,events,source))
            scene=compile_blocking(raw,updated,entities,bs);scene,timing=schedule_audio(scene);spec['duration_seconds']=timing['duration_seconds'];effects=[]
            end=sc.advance(scene,spec,updated,entities,spec['fact_ids'],source,previous,effects=effects)
            validate_requirements({'scenes':[scene]},{'events':events},transition_effects=effects)
            freeze(a.run/(raw['id']+'_FINAL.json'),scene);freeze(a.run/(raw['id']+'_END_STATE.json'),end);previous=end
        freeze(a.run/'NATIVE_CHECKPOINTS.json',checks);state['status']='boundary_scenes_awaiting_primary_review'
    except Exception as e:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',{'type':type(e).__name__,'message':str(e)[:6000]})
    finally:ledger.save()

if __name__=='__main__':main()
