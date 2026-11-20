"""New, cumulative-ledger run adopting one known native typed scene after scoped repair."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_transport_v6 import Ledger,NativeClient
from src.content_factory.novel_adaptation.reference_repair import invalid_references,repair_schema,apply_reference_repair,checkpoint
from src.content_factory.novel_adaptation.workflow import run_workflow
from src.content_factory.novel_adaptation.render import episode_markdown
from src.content_factory.novel_adaptation.contracts import indexed_chapters


def main():
    p=argparse.ArgumentParser();p.add_argument('--prior',type=Path,required=True);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--additional-calls',type=int,default=0);a=p.parse_args()
    old=read(a.prior/'STATE.json')
    if old['pending'] is not None or old['status'] in ('running','prepared'):raise ValueError('prior_not_known_terminal')
    if not 0<=a.additional_calls<=4:raise ValueError('invalid_extension')
    source=read(a.prior/'SOURCE.json');packet=read(a.prior/'PACKET.json');design=read(a.prior/'DESIGN_COMPILED.json')
    if len(design['scenes'])!=1:raise ValueError('single_known_scene_only')
    scene=read(a.prior/('SCENE_'+design['scenes'][0]['id']+'.json'));previous=read(a.prior/'INITIAL_STATE.json')
    scope=invalid_references(scene,previous)
    if not scope:raise ValueError('no_invalid_references')
    plan=read(a.prior/'PLAN.json');ceiling=plan['max_calls'];plan['max_calls']+=a.additional_calls
    a.run.mkdir(exist_ok=False,parents=True)
    for name,value in [('PLAN',plan),('SOURCE',source),('PACKET',packet),('BEFORE',scene),('REPAIR_SCOPE',scope)]:freeze(a.run/(name+'.json'),value)
    freeze(a.run/'LINEAGE.json',{'prior':str(a.prior),'prior_state_sha256':digest(old),'native_sha256':digest(scene),
        'previous_ceiling':ceiling,'new_ceiling':plan['max_calls'],'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens']})
    snap=a.run/'implementation';snap.mkdir()
    for f in list(Path('src/content_factory/novel_adaptation').glob('*.py'))+[Path(__file__)]: (snap/f.name).write_bytes(f.read_bytes())
    state={'status':'prepared','calls_started':old['calls_started'],'reported_tokens':old['reported_tokens'],
        'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens'],'pending':None}
    ledger=Ledger(a.run,plan,state,NativeClient(a.run,plan));ledger.save()
    try:
        proposal=ledger.call('REFERENCE_REPAIR','writer','''只修未找到的信息引用编号。逐个核对当前表演实际依赖的信息，在该人物真实available_history里选择语义对应的event_id。
不得删除引用、改变人物或改写任何对白动作。若没有合理对应项，返回uncertain，不猜编号。reason说明对应的实际信息。''',
            {'complete_chapters':indexed_chapters(source),'candidate':scene,'scope':scope},repair_schema(scope))
        fixed=apply_reference_repair(scene,previous,proposal,digest(scene));freeze(a.run/'REFERENCE_FIXED.json',fixed)
        entry=checkpoint(fixed,source,design,previous)
        candidate,review=run_workflow(a.run,ledger,source,packet,read(a.prior/'BRIEF.json'),design_checkpoint=design,
            source_contract=read(a.prior/'SOURCE_EVENTS.json'),contract_review=read(a.prior/'SOURCE_EVENTS_REVIEW.json'),
            continuation=read(a.prior/'PREVIOUS_EPISODE_HANDOFF.json'),native_scene_checkpoints={fixed['id']:entry})
        (a.run/'EPISODE_UNACCEPTED.md').write_text(episode_markdown(candidate,{'entities':packet['entities']},production_views=read(a.run/'PRODUCTION_VIEWS_UNAPPROVED.json'),include_audit=False),encoding='utf-8')
        state['status']='episode_awaiting_primary_review'
    except Exception as e:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',{'type':type(e).__name__,'message':str(e)[:6000]})
    finally:ledger.save()

if __name__=='__main__':main()
