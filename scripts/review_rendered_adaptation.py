"""Review every emitted word/action of a completed candidate, without duplicate runtime arrays."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation.render import episode_markdown
from src.content_factory.novel_adaptation.action_windows import action_windows
from src.content_factory.novel_adaptation.protocol_envelope import StringEnvelopeLedger,StringEnvelopeClient
from src.content_factory.novel_adaptation.review_semantics import RULES,prompt as semantics_prompt


def main():
    parser=argparse.ArgumentParser()
    for key in ('prior','candidate','run'):parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--narrative',action='store_true')
    parser.add_argument('--target-chapters',type=int,nargs='+')
    parser.add_argument('--estimate-timing',action='store_true')
    parser.add_argument('--additional-calls',type=int,default=0)
    a=parser.parse_args();old=read(a.prior/'STATE.json');plan=read(a.prior/'PLAN.json')
    if old['pending'] is not None or old['status'] in ('running','prepared'):raise ValueError('prior_not_terminal')
    if a.additional_calls<0:raise ValueError('negative_engineering_extension')
    old_ceiling=plan['max_calls']
    plan['max_calls']=max(old_ceiling,old['calls_started']+a.additional_calls)
    source=read(a.prior/'SOURCE.json')
    if a.narrative:
        if not a.target_chapters or not set(a.target_chapters)<={x['index'] for x in source['chapters']}:
            raise ValueError('explicit_valid_target_chapters_required')
        from src.content_factory.novel_adaptation.narrative_render import render
        candidate=read(a.candidate/'CANDIDATE.json');rendered=render(candidate,estimated_timing=a.estimate_timing)
        mapping=[{'scene_id':s['id'],'beat_id':b['id'],'source_ids':b['source_ids']} for s in candidate['scenes'] for b in s['segments']]
        def strings(value):
            if isinstance(value,str):yield value
            elif isinstance(value,dict):
                for x in value.values():yield from strings(x)
            elif isinstance(value,list):
                for x in value:yield from strings(x)
        if not all(value in rendered for value in strings(candidate)):raise ValueError('narrative_review_coverage_missing')
        payload={'complete_chapters':c.indexed_chapters(source),'target_chapters':a.target_chapters,
            'complete_production_text':rendered,'candidate_sha256':digest(candidate),'source_map':mapping,
            'review_scope':'All candidate text including world, design, entry/exit, performance, audio and obligations. Estimated segment durations are not verified speech timestamps. Review all layers; nonperformance metadata must not be confused with spoken or visible content.'}
        if a.estimate_timing:
            from src.content_factory.novel_adaptation.narrative_timing import schedule
            payload['derived_schedule']=schedule(candidate)
            payload['timing_interpretation']='Original text retains authored estimates. Derived schedule extends only needed slots under the explicit planning policy; no prose edits. Evaluate supplied schedule, not a different assumed speed. This is not measured audio. Voiceover can overlap visual action.'
    else:
        payload=compiled_payload(a,source)
    payload={**payload,'field_semantics':RULES}
    a.run.mkdir(exist_ok=False)
    freeze(a.run/'ENGINEERING_EXTENSION.json',{'old_ceiling':old_ceiling,'new_ceiling':plan['max_calls'],
        'net_additional':plan['max_calls']-old_ceiling,'calls_carried':old['calls_started'],
        'scope':'Authorized same-source MiniMax full text review; no replay of previous calls.'})
    for name,value in [('PLAN',plan),('SOURCE',source),('REVIEW_INPUT',payload),('LINEAGE',{'prior':str(a.prior),'candidate':str(a.candidate),'prior_state_sha256':digest(old),'calls_carried':old['calls_started'],'tokens_carried':old['reported_tokens']})]:freeze(a.run/(name+'.json'),value)
    execute_review(a,plan,old,payload,source)


def compiled_payload(a,source):
    packet=read(a.prior/'PACKET.json');candidate=read(a.candidate/'EPISODE.json');views=read(a.candidate/'PRODUCTION_VIEWS_UNAPPROVED.json')
    rendered=episode_markdown(candidate,{'entities':packet['entities']},production_views=views,include_audit=False)
    # Independent exact coverage guard for the reviewer input, not an acceptance test.
    for scene in candidate['scenes']:
        for b in scene['beats']:
            for value in [b['id'],b['action'],b['camera'],b['emotion']]+[x['text'] for x in b['audio']]:
                if value not in rendered:raise ValueError('review_render_coverage_missing')
    mapping=[{'scene_id':s['id'],'beat_id':b['id'],'fact_ids':b['fact_ids'],'source_ids':b['source_ids']} for s in candidate['scenes'] for b in s['beats']]
    payload={'complete_chapters':c.indexed_chapters(source),'target_chapters':candidate['design']['target_chapters'],
        'complete_production_text':rendered,'candidate_sha256':digest(candidate),'source_map':mapping,
        'action_timing_evidence':[row for scene in candidate['scenes'] for row in action_windows(scene)],
        'review_scope':'Every rendered action, camera, expression, speech and timing is included. Audit-only adaptation_detail is not performance. Duplicate runtime arrays are replaced by their actual deterministic rendered text. Source context beyond target chapters is not automatic permission to advance plot.'}
    return payload


def execute_review(a,plan,old,payload,source):
    state={'status':'prepared','calls_started':old['calls_started'],'reported_tokens':old['reported_tokens'],'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens'],'pending':None}
    ledger=StringEnvelopeLedger(a.run,plan,state,StringEnvelopeClient(a.run,plan));ledger.save()
    schema=c.obj(verdict=c.choices(['pass','revise','uncertain']),issues=c.array(c.obj(scene_id=c.TEXT,beat_id=c.TEXT,
        category=c.choices(['source','identity','continuity','visual','timing','information_density']),problem=c.TEXT,
        source_ids=c.refs(c.catalog(source)),severity=c.choices(['must_fix','suggestion','uncertain']))))
    try:
        result=ledger.call('FINAL_RENDERED_REVIEW','writer','''独立审核完整小说改编剧本，不改写。
核对原文事实、说话人与内心归属、条件与否定、时间层及因果；区分明确原文与合理影视补足。
检查实际可见动作、空间/道具连续性、表演能否在给定时长内完成。审查信息密度：是否无信息停留、重复旁白、过长背景铺陈。
动作窗口是音轨结束到本beat结束的共享上界，不是音轨本身时长，也不是各动作独享时长；零窗口需区分瞬间状态落点与需要过程的表演，不能机械认定全部错误。
不要把audit-only注释当实际表演；当前传入的是完整实际输出。完整上下文只帮助理解，target_chapters之外未分配情节不得提前。
每项问题给具体场/beat、依据。只报有证据的问题，不能为审核虚构发生过的事；原文不能证明的判uncertain。合理视觉设计不因原文未逐字记载就判错。'''+semantics_prompt(),payload,schema)
        errors=c.schema_issues(result,schema,'review')
        if errors:raise c.ContractError(errors)
        state['status']='review_awaiting_primary_assessment'
    except Exception as exc:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:5000]})
    finally:ledger.save()


if __name__=='__main__':main()
