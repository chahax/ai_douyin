"""Run one scoped narrative repair, carrying the existing ledger and ceiling."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation.narrative_patch import apply,proposal_schema
from src.content_factory.novel_adaptation.narrative_revision import validate
from src.content_factory.novel_adaptation.narrative_render import render
from src.content_factory.novel_adaptation.protocol_envelope import StringEnvelopeLedger,StringEnvelopeClient
from src.content_factory.novel_adaptation import narrative_span
from src.content_factory.novel_adaptation.narrative_patch import body_schema,bind_body
from src.content_factory.novel_adaptation.performance_patch import RULE,inspect


def main():
    parser=argparse.ArgumentParser()
    for key in ('prior','context','design','run'):parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--candidate-file',default='NARRATIVE_REVISION_ENVELOPE_DECODED.json')
    parser.add_argument('--review-file',type=Path)
    parser.add_argument('--span-targets',type=Path)
    parser.add_argument('--additional-calls',type=int,default=0)
    parser.add_argument('--program-bind',action='store_true')
    parser.add_argument('--direct-tools',action='store_true')
    parser.add_argument('--candidate-from',type=Path)
    a=parser.parse_args();old=read(a.prior/'STATE.json');plan=read(a.prior/'PLAN.json')
    if old['pending'] is not None or old['status'] in ('running','prepared'):raise ValueError('prior_not_terminal')
    if a.additional_calls<0:raise ValueError('negative_engineering_extension')
    old_ceiling=plan['max_calls'];plan['max_calls']=max(old_ceiling,old['calls_started']+a.additional_calls)
    candidate_root=a.candidate_from or a.prior
    if a.candidate_from:
        cs=read(candidate_root/'STATE.json')
        if cs['pending'] is not None or cs['status'] in ('running','prepared') or cs['calls_started']>old['calls_started']:
            raise ValueError('candidate_source_unsettled_or_future')
        if read(candidate_root/'SOURCE.json')!=read(a.prior/'SOURCE.json'):raise ValueError('candidate_source_changed')
    candidate=read(candidate_root/a.candidate_file);review=read(a.review_file or candidate_root/'PRIMARY_REVIEW.json')
    if digest(candidate)!=review['candidate_sha256']:raise ValueError('review_candidate_mismatch')
    source=read(a.prior/'SOURCE.json');packet=read(a.context/'PACKET.json');design=read(a.design/'EPISODE.json')['design']
    paths=list(dict.fromkeys(p for issue in review['findings'] for p in issue['paths']))
    schema=body_schema(candidate,paths) if a.program_bind else proposal_schema(candidate,paths)
    targets=read(a.span_targets) if a.span_targets else []
    if targets:
        if set(paths)&{t['path'] for t in targets}:raise ValueError('field_and_span_scope_overlap')
        schema['properties']['span_edits']=narrative_span.schema(targets)
        schema['required'].append('span_edits')
    payload={'complete_source':c.indexed_chapters(source),'candidate':candidate,'candidate_sha256':digest(candidate),
        'confirmed_issues':review['findings'],'approved_paths':paths,'target_chapters':design['target_chapters']}
    from src.content_factory.novel_adaptation.narrative_timing import repair_feedback
    try:payload['timing_feedback']=repair_feedback(candidate)
    except ValueError as exc:
        payload['timing_feedback']={'status':'unavailable_until_structural_repair','reason':str(exc),'semantic_acceptance':False}
    if targets:payload['approved_spans']=targets
    a.run.mkdir(exist_ok=False)
    for name,value in [('PLAN',plan),('SOURCE',source),('INPUT',payload),('LINEAGE',{
        'prior':str(a.prior),'prior_state_sha256':digest(old),'calls_carried':old['calls_started'],
        'tokens_carried':old['reported_tokens'],'engineering_ceiling':plan['max_calls']})]:freeze(a.run/(name+'.json'),value)
    freeze(a.run/'ENGINEERING_EXTENSION.json',{'old_ceiling':old_ceiling,'new_ceiling':plan['max_calls'],
        'net_additional':plan['max_calls']-old_ceiling,'calls_carried':old['calls_started'],
        'scope':'Authorized same-source MiniMax text repair and subsequent full-candidate verification; no unknown replay.'})
    freeze(a.run/'PROTOCOL_SELECTION.json',{'direct_tools':a.direct_tools,'candidate_from':str(candidate_root),
        'candidate_sha256':digest(candidate),'candidate_source_state_sha256':digest(read(candidate_root/'STATE.json'))})
    state={'status':'prepared','calls_started':old['calls_started'],'reported_tokens':old['reported_tokens'],
        'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens'],'pending':None}
    if a.direct_tools:
        from src.content_factory.novel_adaptation.protocol_direct import DirectLedger,NativeClient
        ledger=DirectLedger(a.run,plan,state,NativeClient(a.run,plan))
    else:ledger=StringEnvelopeLedger(a.run,plan,state,StringEnvelopeClient(a.run,plan))
    ledger.save()
    try:
        proposal=ledger.call('NARRATIVE_PATCH','writer','''只返修已核实的字段，不重写全稿。对approved_paths每个地址恰好返回一次完整字段值，保持字段类型。没有修改必要的授权字段可原样返回。
保持所有未授权字段不变，修复须与保留的相邻动作、镜头、音轨、时间一致。原文事实不能由视觉补足替代；知情不等于听见、镜头外不等于已离场。
若有approved_spans，span_edits只写指定原句跨度的replacement，跨度以外字符不可改。连续性义务必须对应所在segment_id的实际动作与音轨，不能把上一段的义务搬到下一段。镜头说明里的时间省略要通过自然转场表现，不把“时间省略”等制作指令做成字幕。
完整原文供理解，剧情范围严格使用输入target_chapters，不提前引入范围外情节。只输出补丁，不自行声称已验收。
'''+RULE,payload,schema)
        errors=c.schema_issues(proposal,schema,'narrative_patch')
        if errors:raise c.ContractError(errors)
        field_proposal={k:v for k,v in proposal.items() if k!='span_edits'}
        if a.program_bind:
            field_proposal=bind_body(candidate,field_proposal,paths,payload['candidate_sha256'])
            freeze(a.run/'PROGRAM_BOUND_PATCH.json',field_proposal)
        result=apply(candidate,field_proposal,paths,digest(candidate))
        if targets:result=narrative_span.apply_spans(result,targets,proposal['span_edits'])
        freeze(a.run/'CANDIDATE.json',result)
        performance=inspect(result,paths+[t['path'] for t in targets])
        freeze(a.run/'PERFORMANCE_FIELD_CHECK.json',performance)
        if performance['issues']:raise ValueError('repair_process_language_in_performance')
        freeze(a.run/'STRUCTURAL_CHECK.json',validate(result,source,packet,design,240))
        (a.run/'CANDIDATE_UNACCEPTED.md').write_text(render(result),encoding='utf-8')
        state['status']='repaired_candidate_awaiting_independent_review'
    except Exception as exc:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:5000]})
    finally:ledger.save()


if __name__=='__main__':main()
