"""Cumulative known-run statement-only refinement, preserving all other card fields."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_transport_v6 import Ledger,NativeClient
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation.patching import bind_patches


def main():
    p=argparse.ArgumentParser()
    for key in ('prior','run','artifact','scope'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();old=read(a.prior/'STATE.json')
    if old['pending'] is not None or old['status'] in ('running','prepared'):raise ValueError('prior_not_known_terminal')
    source=read(a.prior/'SOURCE.json');artifact=read(a.artifact);scope=read(a.scope)
    if scope['artifact_sha256']!=digest(artifact) or scope['source_sha256']!=digest(source):raise ValueError('stale_scope')
    ids=set(scope['findings']);rows={r['id']:r for r in artifact['facts']}
    if not ids or not ids<=rows.keys():raise ValueError('invalid_scope')
    plan=read(a.prior/'PLAN.json');ceiling=plan['max_calls'];plan['max_calls']=max(ceiling,old['calls_started']+1)
    a.run.mkdir(exist_ok=False,parents=True)
    for name,value in [('PLAN',plan),('SOURCE',source),('BEFORE',artifact),('SCOPE',scope)]:freeze(a.run/(name+'.json'),value)
    freeze(a.run/'LINEAGE.json',{'prior':str(a.prior),'prior_state_sha256':digest(old),'previous_ceiling':ceiling,'new_ceiling':plan['max_calls'],
        'actual_calls_carried':old['calls_started'],'actual_tokens_carried':old['reported_tokens']})
    snap=a.run/'implementation';snap.mkdir()
    for f in list(Path('src/content_factory/novel_adaptation').glob('*.py'))+[Path(__file__)]: (snap/f.name).write_bytes(f.read_bytes())
    state={'status':'prepared','calls_started':old['calls_started'],'reported_tokens':old['reported_tokens'],
        'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens'],'pending':None}
    ledger=Ledger(a.run,plan,state,NativeClient(a.run,plan));ledger.save()
    try:
        schema=c.obj(corrections=c.array(c.obj(id=c.choices(sorted(ids)),statement=c.TEXT),len(ids)))
        proposal=ledger.call('STATEMENT_REPAIR','writer','''只修给定资料卡的statement。依据完整原文核对条件、主观/客观、人物归属和语气时点。
不扩写故事，不修改ID、来源编号、实体或时间层字段；未选资料不返回。保留原卡已正确的信息。每个选中ID返回一次。''',
            {'complete_chapters':c.indexed_chapters(source),'selected_cards':[rows[k] for k in sorted(ids)],'findings':scope['findings']},schema)
        errors=c.schema_issues(proposal,schema,'statement_repair')
        if errors:raise c.ContractError(errors)
        actual=[r['id'] for r in proposal['corrections']]
        if set(actual)!=ids or len(actual)!=len(ids):raise ValueError('statement_scope_coverage')
        replacements=[{'id':r['id'],'replacement':{**rows[r['id']],'statement':r['statement']}} for r in proposal['corrections']]
        bound=bind_patches(artifact,replacements,ids,digest(artifact))
        result=c.apply_record_patches(artifact,bound,ids,digest(artifact),lambda value:None)
        freeze(a.run/'AFTER.json',result);freeze(a.run/'BOUND_PATCHES.json',bound)
        state['status']='awaiting_primary_material_review'
    except Exception as e:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',{'type':type(e).__name__,'message':str(e)[:6000]})
    finally:ledger.save()

if __name__=='__main__':main()
