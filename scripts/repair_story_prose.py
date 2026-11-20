"""One source-bound fixed-span repair; preserve original output and cumulative ledger."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation import prose_patch,contracts as c
from src.content_factory.novel_adaptation.protocol_direct import DirectLedger,NativeClient

def main():
    p=argparse.ArgumentParser()
    for key in ('prior','review','run'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--additional-calls',type=int,default=0)
    p.add_argument('--ledger-prior',type=Path)
    p.add_argument('--context-start',type=int,default=1);a=p.parse_args()
    old=read(a.prior/'STATE.json');plan=read(a.prior/'PLAN.json');review=read(a.review)
    if old['pending'] is not None or old['status'] in ('running','prepared','outcome_unknown'):raise ValueError('prior_unsettled')
    if a.ledger_prior:
        latest=read(a.ledger_prior/'STATE.json')
        if latest['pending'] is not None or latest['status'] in ('running','prepared','outcome_unknown'):
            raise ValueError('ledger_prior_unsettled')
        if latest['calls_started']<old['calls_started'] or latest['reported_tokens']<old['reported_tokens']:
            raise ValueError('ledger_regression')
        if latest.get('retained_unknowns',[])!=old.get('retained_unknowns',[]):raise ValueError('unknown_lineage_changed')
        old=latest;plan=read(a.ledger_prior/'PLAN.json')
    if a.additional_calls<0:raise ValueError('negative_extension')
    draft=read(a.prior/'STORY_DIRECT_NATIVE.json');source=read(a.prior/'SOURCE.json')
    if review['candidate_sha256']!=digest(draft):raise ValueError('review_candidate_changed')
    targets=read(a.prior/'TARGETS.json')
    # The ledger predecessor may belong to a different chapter. Carry usage,
    # but bind source metadata to the candidate actually being repaired.
    plan['source_sha256']=digest(source)
    plan['chapter_indices']=[x['index'] for x in source['chapters']]
    if not 1<=a.context_start<=min(targets):raise ValueError('invalid_repair_context')
    spans=prose_patch.prepare(draft['screenplay'],review['issues'])
    previous_ceiling=plan['max_calls'];plan['max_calls']=max(previous_ceiling,old['calls_started']+a.additional_calls)
    if plan['max_calls']<=old['calls_started']:raise ValueError('call_window_exhausted')
    a.run.mkdir(exist_ok=False)
    state={**old,'status':'prepared','pending':None,'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens']}
    for name,value in [('PLAN',plan),('SOURCE',source),('TARGETS',targets),
        ('REPAIR_CONTEXT',{'first_chapter':a.context_start,'last_chapter':max(targets),'full_source_sha256':digest(source)}),
        ('ORIGINAL',draft),('SPAN_PLAN',spans),('REVIEW',review),
        ('ENGINEERING_EXTENSION',{'previous_ceiling':previous_ceiling,'new_ceiling':plan['max_calls'],
          'net_extension':plan['max_calls']-previous_ceiling,'prior_state_sha256':digest(old),'prior':str(a.prior),
          'ledger_prior':str(a.ledger_prior or a.prior)})]:freeze(a.run/(name+'.json'),value)
    ledger=DirectLedger(a.run,plan,state,NativeClient(a.run,plan));ledger.save()
    try:
        result=ledger.call('PROSE_PATCH','writer','只修改slots指定的原文片段。每个edit键返回完整替换片段，保留对应剧情，修正具体问题。其他文字由程序原样保留，不输出全文。保留原文条件、否定、推测，不增加后续情节。',
            {'complete_source':[x for x in c.indexed_chapters(source) if a.context_start<=x['index']<=max(targets)],
             'current_screenplay':draft['screenplay'],'slots':spans['slots']},prose_patch.schema(spans))
        updated={**draft,'screenplay':prose_patch.apply(draft['screenplay'],spans,result)}
        freeze(a.run/'STORY_DIRECT_NATIVE.json',updated)
        freeze(a.run/'PATCH_RECEIPT.json',{'original_sha256':digest(draft),'updated_sha256':digest(updated),
            'native_patch_sha256':digest(result),'unselected_text_preserved':True,'semantic_acceptance':False})
        (a.run/'SCREENPLAY_UNACCEPTED.txt').write_text(updated['title']+'\n\n'+updated['screenplay'],encoding='utf-8')
        state['status']='prose_repaired_awaiting_primary_review'
    except Exception as exc:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:3000]})
    finally:ledger.save()

if __name__=='__main__':main()
