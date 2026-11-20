"""Exclude unusable review prose; keep complete script, R01 and human feedback."""
import json
from src.content_factory.creative_legal_conflict_feedback_v6 import build_wire as prior,validate_current_script
from scripts.creative_resume_dispatch_v3 import digest
def build_wire(*args,**kwargs):
 req=prior(*args,**kwargs);ctx=json.loads(req['messages'][1]['content'])
 if args[4]=='draft':
  ctx['complete_revision_source'].pop('current_complete_review',None)
  ctx['source_diagnosis']=[
   '旧长人事句公文化。直接用短句说明虚构公司要求按主动离开办，不说法律允许。',
   '第一次公司立场、第二次改人事自己的个人劝说；小林接住人际压力但拒绝改写事实。每轮立场或情绪推进。',
   '小林发现个人原因的情绪在正文依次可见，语气变化放在相邻动作，不用数寸逐指或秒数。',
   '原纸路线始终只有递到小林面前一次、最后取回；小林不移纸不碰笔，周姐独自离开。',
   '337服务响应finish_reason=tool_calls却没有tool_calls，只有半截正文，不能当剧本。此新请求须submit_creative_json完整对象，不输出思考或分析开头。']
  req['messages'][0]['content']+='无效旧审查全文已移出本次请求，source_diagnosis是当前实际要求。切勿输出我先核对等分析，准确调用submit_creative_json，一次给出包含title、premise、selected_candidate_id和四拍完整beats的完整工具参数。不能先输出正文再补工具调用。'
 req['messages'][1]['content']=json.dumps(ctx,ensure_ascii=False);req['input_provenance']['source_context_sha256']=digest(ctx)
 req['operator_version']='legal_conflict_feedback_complete_revision/v7_received_failure_isolation'
 return req

