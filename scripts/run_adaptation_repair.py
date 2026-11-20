"""Explicit source-reviewed field repair using an existing cumulative ledger."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.serial_story_transport_v6 import Ledger,NativeClient
from src.content_factory.novel_adaptation.repair_workflow import repair_episode
from src.content_factory.novel_adaptation.render import episode_markdown
from src.content_factory.novel_adaptation.workflow import REVIEW_POLICY
from src.content_factory.novel_adaptation import contracts as c

def main():
    parser=argparse.ArgumentParser()
    for key in ('run','candidate','source','packet','review-plan','events-run'):parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--ledger-prior',type=Path)
    parser.add_argument('--additional-calls',type=int,default=0)
    a=parser.parse_args();ledger_prior=a.ledger_prior or a.events_run;prior=read(ledger_prior/'STATE.json')
    if prior['pending'] is not None or prior['status']=='running':raise ValueError('prior_not_known')
    plan=read(ledger_prior/'PLAN.json');source=read(a.source);packet=read(a.packet);candidate=read(a.candidate)
    contract=read(a.events_run/'SOURCE_EVENTS.json');review=read(a.events_run/'PRIMARY_REVIEW.json');scope=read(a.review_plan)
    if scope['candidate_sha256']!=digest(candidate) or packet['source_sha256']!=digest(source):raise ValueError('stale_input')
    if a.additional_calls<0:raise ValueError('negative_extension')
    a.run.mkdir(exist_ok=False,parents=True)
    if a.additional_calls:
        old_ceiling=plan['max_calls'];plan['max_calls']+=a.additional_calls
        freeze(a.run/'ENGINEERING_EXTENSION.json',{'previous_ceiling':old_ceiling,'new_ceiling':plan['max_calls'],
            'cumulative_calls_preserved':prior['calls_started'],'reason':'source-reviewed audio kind-only contract and full-candidate review; ongoing authorized text goal',
            'no_unknown_replay':True})
    for name,value in [('PLAN',plan),('SOURCE',source),('PACKET',packet),('BEFORE',candidate),('REVIEW_PLAN',scope),('SOURCE_EVENTS',contract)]:freeze(a.run/(name+'.json'),value)
    freeze(a.run/'CONTINUATION.json',{'prior':str(ledger_prior),'calls_carried':prior['calls_started'],
        'tokens_carried':prior['reported_tokens'],'same_ceiling':plan['max_calls'],'no_replay':True})
    snap=a.run/'implementation';snap.mkdir()
    for file in list((Path(__file__).resolve().parents[1]/'src/content_factory/novel_adaptation').glob('*.py'))+[Path(__file__)]:
        (snap/file.name).write_bytes(file.read_bytes())
    state={'status':'prepared','calls_started':prior['calls_started'],'reported_tokens':prior['reported_tokens'],
        'baseline_calls':prior['calls_started'],'baseline_tokens':prior['reported_tokens'],'pending':None}
    ledger=Ledger(a.run,plan,state,NativeClient(a.run,plan));ledger.save()
    try:
        result,views=repair_episode(a.run,ledger,source,packet,candidate,contract,review,scope)
        (a.run/'EPISODE_UNACCEPTED.md').write_text(episode_markdown(result,{'entities':packet['entities']},production_views=views,include_audit=False),encoding='utf-8')
        schema=c.obj(verdict=c.choices(['pass','revise','uncertain']),issues=c.array(c.obj(path=c.TEXT,problem=c.TEXT,
            source_ids=c.refs(c.catalog(source)),severity=c.choices(['must_fix','suggestion','uncertain']))))
        # State access history is stored, but not duplicated in the textual review request.
        audit={**result,'end_state':{k:v for k,v in result['end_state'].items() if k!='information'}}
        review=ledger.call('FINAL_REVIEW','writer',REVIEW_POLICY+'''独立对照原文检查完整第一章改编稿。检查事实关系、说话人、时间层、原文强制动作、空间与持物、视觉前后一致和时长信息密度。
允许合理影视设计，不把未被原文明示但明确属于设计的普通细节当成事实错误。叙述追溯先前事件不等于事件倒序发生。
指出当前具体文字与原文依据，审核不改写稿件，不借用旧问题清单。''',
            {'complete_chapters':c.indexed_chapters(source),'candidate':audit,'candidate_sha256':digest(result),'target_chapters':scope['target_chapters']},schema)
        errors=c.schema_issues(review,schema,'review')
        if errors:raise c.ContractError(errors)
        state['status']='episode_awaiting_primary_review'
    except Exception as exc:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:6000]})
    finally:ledger.save()

if __name__=='__main__':main()
