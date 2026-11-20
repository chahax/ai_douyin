"""Explicit new editorial experiment; never resumes or overwrites a previous run."""
import argparse,sys
from pathlib import Path
from copy import deepcopy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation.narrative_revision import schema,validate
from src.content_factory.novel_adaptation.protocol_envelope import StringEnvelopeLedger,StringEnvelopeClient


def main():
    p=argparse.ArgumentParser()
    for name in ('prior','candidate','context','run'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--additional-calls',type=int,default=3)
    p.add_argument('--maximum-seconds',type=float,default=240)
    p.add_argument('--failed-receipt',action='store_true',help='Use the prior known rejected native draft as repair input only.')
    p.add_argument('--reuse-feedback',action='store_true',help='Carry prior source-bound repair input; never consume its truncated output.')
    p.add_argument('--writer-effort',choices=['medium','high','xhigh'])
    a=p.parse_args();old=read(a.prior/'STATE.json')
    if old['pending'] is not None or old['status'] in ('running','prepared'):raise ValueError('prior_not_terminal')
    source=read(a.prior/'SOURCE.json');packet=read(a.context/'PACKET.json')
    candidate=read(a.candidate/'EPISODE.json');design=candidate['design']
    plan=deepcopy(read(a.prior/'PLAN.json'));old_ceiling=plan['max_calls']
    previous_effort=plan['inference']['writer_effort']
    if a.writer_effort:plan['inference']['writer_effort']=a.writer_effort
    if a.failed_receipt and a.reuse_feedback:raise ValueError('conflicting_feedback_modes')
    if a.additional_calls<0 or a.maximum_seconds<=0:raise ValueError('invalid_authoring_limits')
    plan.update(max_calls=max(old_ceiling,old['calls_started']+a.additional_calls),baseline_calls=old['calls_started'],baseline_tokens=old['reported_tokens'])
    payload={'complete_source':c.indexed_chapters(source),'target_chapters':design['target_chapters'],
        'identities':packet['entities'],'places':design['places'],
        'scene_order':[{'id':s['id'],'place':s['place']} for s in design['scenes']],
        'scene_objectives':design['scenes'],
        'editorial_brief':{'maximum_seconds':a.maximum_seconds,'target':'信息紧凑、人物主动行动、情绪与关系可见；上限不是凑满目标'},
        'previous_candidate_sha256':digest(candidate)}
    if a.failed_receipt:
        from src.content_factory.novel_adaptation.author_feedback import rejected_feedback
        payload['repair_feedback']=rejected_feedback(
            read(a.prior/f"RESPONSE_{old['calls_started']:03}.json"),old,plan,source,packet,design,a.maximum_seconds)
    if a.reuse_feedback:
        from src.content_factory.novel_adaptation.author_feedback import reuse_feedback
        payload['repair_feedback']=reuse_feedback(read(a.prior/'INPUT.json'),payload)
    a.run.mkdir(exist_ok=False)
    for name,value in [('PLAN',plan),('SOURCE',source),('INPUT',payload),('INFERENCE_CHANGE',{
        'previous_writer_effort':previous_effort,'writer_effort':plan['inference']['writer_effort'],
        'feedback_input_reused':a.reuse_feedback,'prior_input_sha256':digest(read(a.prior/'INPUT.json')) if a.reuse_feedback else None}),('ENGINEERING_EXTENSION',{
        'previous_ceiling':old_ceiling,'new_ceiling':plan['max_calls'],'net_additional':plan['max_calls']-old_ceiling,
        'prior':str(a.prior),'prior_state_sha256':digest(old),'reason':'Authorized MiniMax text iteration: narrative compression plus bounded verification; no replay of ended calls.'})]:freeze(a.run/(name+'.json'),value)
    state={'status':'prepared','calls_started':old['calls_started'],'reported_tokens':old['reported_tokens'],
        'baseline_calls':old['calls_started'],'baseline_tokens':old['reported_tokens'],'pending':None}
    ledger=StringEnvelopeLedger(a.run,plan,state,StringEnvelopeClient(a.run,plan));ledger.save()
    try:
        result=ledger.call('NARRATIVE_REVISION','writer','''依据完整原文，为target_chapters写完整可拍剧本。其他章只供理解，情节止于目标章节范围。
保留既定场次地点与顺序，依scene_objectives组织本集。先简述世界、人物关系和环境画风，然后每场写动作、神情、镜头、实际音轨与时长、场间承接。
这是剧情表演层，不输出锅碗配方或物品库存操作。涉及因果的进出、谁在场、关键物品交接、知情变化写入continuity_obligations；普通备菜用有明确时间省略的短镜头表现，不逐个器具讲解。
保留目标章节核心冲突、转折及因果，不增加原文没有的死亡、行为动机、肯定结局；条件、否定、猜测保持限定。集体心理优先通过可见行为呈现，不随意分配原文未指明的个人内心。
遵守editorial_brief.maximum_seconds，不必凑满。对白和动作应能自然并行完成；长过程用明确剪辑省略但保留关键结果与状态承接。避免长段无信息停留与重复内心解释。人物站坐、重要物品放下/拿起、食材处理后形态与位置都要前后相符。
若提供repair_feedback，这是此前未通过的原生稿及全部结构诊断，按完整原文重新核对并修复，不能继承其正确性。先分配各场时间，所有段seconds总和须在上限内；中文音轨按每秒约4字核算，不能只压数字不压内容。停顿写动作神情，不写成纯标点音轨；表演提示放动作字段，不让角色读出括号说明。
每段source_ids为实际原文依据，visual_additions单列合理影视补足；来源并不自动证明内容正确。保留有意压缩的说明，不伪称逐字改编。NARRATOR仅音轨叙述者，不是出场人物。''',payload,schema(source,packet,design))
        freeze(a.run/'CANDIDATE.json',result)
        freeze(a.run/'STRUCTURAL_CHECK.json',validate(result,source,packet,design,a.maximum_seconds))
        state['status']='candidate_awaiting_semantic_and_continuity_review'
    except Exception as exc:
        state['status']='outcome_unknown' if state['pending'] is not None else 'needs_attention'
        freeze(a.run/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:5000]})
    finally:ledger.save()


if __name__=='__main__':main()
