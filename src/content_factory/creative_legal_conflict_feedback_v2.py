"""Rebuild review contracts after changing the emotional brief; preserve failed v1."""
from copy import deepcopy
import json
from scripts.creative_resume_dispatch_v3 import digest
from src.content_factory.creative_legal_conflict_feedback_v1 import build_wire as prior,validate_exact_wording
from src.content_factory.creative_complete_review_ids_v1 import schema as review_schema
VERSION='legal_conflict_feedback_complete_revision/v2'
def build_wire(*args,**kwargs):
 req=prior(*args,**kwargs);ctx=json.loads(req['messages'][1]['content'])
 ctx['revision_contract']['company_position']='人事直接回答为何写个人原因：可用统一模板、要向公司交回签好的单子等虚构工作立场；不把签字与工资社保手续资格绑定，不把公司要求当法律义务。不能只换成另一句往下办。'
 ctx['revision_contract']['emotion']='正文实际写出发现字样后的吃惊或不信、抬眼质问，以及人事回应后小林的情绪变化；不能只在premise或event宣称情绪而正文只有机械念词。小林不触笔不移纸，用人脸、呼吸和有来有回对白完成。'
 ctx['revision_contract']['ending']='周姐取回纸笔后拿起文件夹、明确站起再走门；小林留坐，门关后一次短暂呼气放松，不逐指慢镜，不新增人事工牌。'
 ctx['revision_contract']['review_qualification']='人手不碰纸、纸不动的可见性由当前源状态和后续表演共同承担，不强制每拍另加动作。门关紧接放松是连续因果，不强制再加多套释放姿势。旧无效331仅作问题线索，不继承为有效审查或硬分拍模板。'
 stage=args[4]
 if stage=='draft':
  req['messages'][0]['content']+='本次完整返修特别删除工资手续不好接等新威胁；周姐具体回应为什么统一模板写个人原因及她的工作立场，不以泛泛往下办替代。小林情绪要在steps可见而非只概述。小林不移纸不拿笔；只有他保留原工牌。周姐拿夹站起后才出门。收束门关后一次短呼气，不逐指松开。旧331审查未通过本地哈希合同，只作线索，真矛盾修复，可选导演细化不机械堆动作。'
 else:
  req['messages'][0]['content']+='company_position和review_qualification优先：工资手续不与签字绑定，公司解释直接回答为什么写个人原因；不因每拍缺重复纸状态或重复放松动作而强加新操作。情绪递进须在当前steps兑现，不能仅premise写吃惊委屈、正文未表达。'
  req['structured_schema']=review_schema(kwargs['script'],ctx['emotional_brief'])
 req['messages'][1]['content']=json.dumps(ctx,ensure_ascii=False)
 req['input_provenance'].update(source_context_sha256=digest(ctx),revision_contract_sha256=digest(ctx['revision_contract']),active_emotional_brief_sha256=digest(ctx['emotional_brief']))
 req['operator_version']=VERSION
 return req
def validate_current_script(script):
 check=validate_exact_wording(script)
 for b in script['beats']:
  for s in b['steps']:
   if s['kind']=='dialogue' and s['speaker'].startswith('周姐') and any(w in s['text'] for w in ('工资','社保')):raise ValueError('new company reply introduces wage/social-insurance pressure outside current revision scope')
 return {**check,'new_wage_social_insurance_pressure_absent':True}

