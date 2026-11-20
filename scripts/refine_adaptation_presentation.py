"""Model-proposed prop display labels; recompile known typed native, then review."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_transport_v6 import Ledger,NativeClient
from src.content_factory.novel_adaptation.presentation import label_schema,apply_labels
from src.content_factory.novel_adaptation.reference_repair import checkpoint
from src.content_factory.novel_adaptation.workflow import run_workflow
from src.content_factory.novel_adaptation.render import episode_markdown
from src.content_factory.novel_adaptation.contracts import indexed_chapters
from src.content_factory.novel_adaptation.blocking import blocking_schema
from src.content_factory.novel_adaptation.patching import field_patch_schema,apply_field_patches
from src.content_factory.novel_adaptation.workflow import require_schema


def main():
    p=argparse.ArgumentParser()
    for key in ('prior','run','brief'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--prop-id',action='append',default=[]);p.add_argument('--additional-calls',type=int,default=2)
    p.add_argument('--patch-scope',type=Path)
    a=p.parse_args();old=read(a.prior/'STATE.json')
    if old['pending'] is not None or old['status'] in ('running','prepared'):raise ValueError('prior_not_known_terminal')
    if not 0<=a.additional_calls<=4:raise ValueError('invalid_extension')
    source=read(a.prior/'SOURCE.json');packet=read(a.prior/'PACKET.json');design=read(a.prior/'DESIGN_COMPILED.json')
    raw_path=a.prior/'REFERENCE_FIXED.json'
    if not raw_path.exists():raw_path=a.prior/'BEFORE_NATIVE.json'
    raw=read(raw_path);previous=read(a.prior/'INITIAL_STATE.json');brief=read(a.brief)
    if bool(a.prop_id)==bool(a.patch_scope):raise ValueError('choose_labels_or_scoped_shot_patch')
    plan=read(a.prior/'PLAN.json');ceiling=plan['max_calls'];plan['max_calls']+=a.additional_calls
    a.run.mkdir(exist_ok=False,parents=True)
    for name,value in [('PLAN',plan),('SOURCE',source),('PACKET',packet),('BEFORE_NATIVE',raw),('BRIEF',brief)]:freeze(a.run/(name+'.json'),value)
    freeze(a.run/'LINEAGE.json',{'prior':str(a.prior),'state_sha256':digest(old),'native_sha256':digest(raw),
        'previous_ceiling':ceiling,'new_ceiling':plan['max_calls'],'prior_calls':old['calls_started'],'prior_tokens':old['reported_tokens']})
    snap=a.run/'implementation';snap.mkdir()
    for f in list(Path('src/content_factory/novel_adaptation').glob('*.py'))+[Path(__file__)]: (snap/f.name).write_bytes(f.read_bytes())
    state={'status':'prepared','calls_started':old['calls_started'],'reported_tokens':old['reported_tokens'],
        'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens'],'pending':None}
    ledger=Ledger(a.run,plan,state,NativeClient(a.run,plan));ledger.save()
    try:
        if a.patch_scope:
            scope=read(a.patch_scope)
            if scope['native_sha256']!=digest(raw):raise ValueError('stale_shot_scope')
            permissions={k:set(v) for k,v in scope['fields'].items()}
            if any(not fields<= {'shot','source_ids','fact_ids'} for fields in permissions.values()):raise ValueError('shot_scope_only')
            spec=design['scenes'][0];ids=spec['fact_ids']
            schema=blocking_schema(design,{'entities':packet['entities']},ids,source,previous,
                [sid for f in packet['facts'] if f['id'] in ids for sid in f['source_ids']])
            patch_schema=field_patch_schema(schema,permissions)
            freeze(a.run/'PATCH_SCOPE.json',scope)
            proposal=ledger.call('SHOT_PATCH','writer','只修指定镜头构图与原文证据关联，使已有动作参与者清晰入画。不得修改动作、音轨、人物、时序或其他beat。',
                {'complete_chapters':indexed_chapters(source),'candidate':raw,'design':design,'scope':scope},patch_schema)
            require_schema(proposal,patch_schema,'shot_patch')
            raw=apply_field_patches(raw,proposal['patches'],permissions,digest(raw))
            freeze(a.run/'SHOT_FIXED.json',raw);updated=design
        else:
            proposal=ledger.call('PROP_LABELS','writer','''只为指定道具提供简洁可拍的中文显示名，例如白色塑料袋。依据既有外观与原文，不增加材料、来历、动作或关系。
不改实体ID、身份、归属或资产描述。给出支持物体名称的source_ids。''',
                {'complete_chapters':indexed_chapters(source),'props':[x for x in design['props'] if x['id'] in a.prop_id]},label_schema(a.prop_id,source))
            updated=apply_labels(design,proposal,a.prop_id,source,digest(design))
        freeze(a.run/'PRESENTATION_DESIGN.json',updated)
        entry=checkpoint(raw,source,updated,previous)
        candidate,review=run_workflow(a.run,ledger,source,packet,brief,design_checkpoint=updated,
            source_contract=read(a.prior/'SOURCE_EVENTS.json'),contract_review=read(a.prior/'SOURCE_EVENTS_REVIEW.json'),
            continuation=read(a.prior/'PREVIOUS_EPISODE_HANDOFF.json'),native_scene_checkpoints={raw['id']:entry})
        (a.run/'EPISODE_UNACCEPTED.md').write_text(episode_markdown(candidate,{'entities':packet['entities']},production_views=read(a.run/'PRODUCTION_VIEWS_UNAPPROVED.json'),include_audit=False),encoding='utf-8')
        state['status']='episode_awaiting_primary_review'
    except Exception as e:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',{'type':type(e).__name__,'message':str(e)[:6000]})
    finally:ledger.save()

if __name__=='__main__':main()
