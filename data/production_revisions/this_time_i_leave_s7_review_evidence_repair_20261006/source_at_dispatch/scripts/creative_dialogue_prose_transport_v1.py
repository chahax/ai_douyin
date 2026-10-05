"""Explicit plain response only for zero-action dialogue performance. No fallback."""
from copy import deepcopy
import json,re
from scripts.creative_evidenced_role_clients_v1 import EvidencedRoleClients, EvidenceCallError
from src.content_factory.creative_workflow_roles import RoleResult
VERSION='dialogue_prose/v1'

def project(text):
 if not isinstance(text,str) or not 15<=len(text)<=1800 or any(x in text for x in ('{','}','[',']','```','<','>','dialogue_performance','slot_id','payload_json','seconds')):
  raise ValueError('complete natural prose required, no embedded structure')
 if re.search(r'\d+(?:\.\d+)?\s*秒',text):raise ValueError('programme owns full original dialogue timing')
 return {'dialogue_performance':text}

class ProseOrToolClients(EvidencedRoleClients):
 def call(self,role,messages,**kwargs):
  if kwargs.get('structured_schema') is not None:return super().call(role,messages,**kwargs)
  if role!='writer' or not messages or VERSION not in messages[0]['content']:raise EvidenceCallError('PROSE_CONTRACT_NOT_DECLARED',started=False,outcome_known=True)
  result=super().call(role,messages,**kwargs)
  try:doc=project(result.text)
  except ValueError as exc:raise EvidenceCallError('PROSE_CONTRACT_INVALID',started=True,received=True,outcome_known=True,metadata=result.metadata,payload=result.response_payload,text=result.text) from None
  metadata=deepcopy(result.metadata);metadata['local_projection']=VERSION;metadata['original_model_prose_preserved']=True
  kwargs['evidence'].record('prose_projected',{'contract':VERSION,'exact_original_string':True,'no_content_fallback':True})
  return RoleResult(text=json.dumps(doc,ensure_ascii=False),metadata=metadata,response_payload=result.response_payload)

def prose_messages(inp,feedback):
 from scripts import creative_local_event_performance_v3 as split
 ctx=inp['context'];payload={'read_only_complete_creative_source':{k:deepcopy(ctx[k]) for k in ('raw_linear_script','reference_pack','static_visual_manifest','production_responsibility')},'whole_film_outline':{k:deepcopy(inp['direction'][k]) for k in ('emotional_arc','causal_chain','ending_intent')},'current_direction_and_complete_steps':split.focus(inp),'verified_prior_faults':feedback or {}}
 system=VERSION+'：你是MiniMax表演导演。只提交一段自然中文表演正文，不使用工具、不输出JSON、字段名、编号、秒数、标签或代码。当前镜只有方澄两句完整原话，没有动作事件。原话和对白时长由程序插入；你只写语气、唇部、眼神与呼吸。保持上一镜已看林屿的视线，第一句平稳坚定，自然换气，第二句轻而明确；不新增抬眼、手势、拿票、转身、赔笑、道歉或补偿。整片原文和R01供理解，不复制输入。'
 return [{'role':'system','content':system},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}]
