"""Explicit flat atomic event lines, strict decode; no semantic repair or fallback."""
from copy import deepcopy
import json,re
from scripts.creative_evidenced_role_clients_v1 import EvidencedRoleClients,EvidenceCallError
from scripts.creative_dialogue_prose_transport_v1 import ProseOrToolClients
from src.content_factory.creative_workflow_roles import RoleResult
VERSION='atomic_event_group_lines/v2'
KINDS={'hold','gaze','face','move','stand','sit','take','place','pass','slide'}

def lines(text):
 if not isinstance(text,str) or not text.strip() or any(s in text for s in ('```','{','}','<','>')):raise ValueError('only complete flat event lines required')
 rows=text.splitlines()
 if not 1<=len(rows)<=40 or any(len(row.split('|'))!=7 for row in rows):raise ValueError('each line requires exactly seven pipe separated columns')
 return [row.split('|') for row in rows]

def decode(text,inp):
 from scripts import creative_local_event_performance_v3 as split
 source_refs=[s['source_step_ref'] for s in split.focus(inp)['ordered_complete_current_steps'] if s['kind']=='action'];actions=[{'source_step_ref':r,'events':[]} for r in source_refs];chars={c['id'] for c in inp['context']['static_visual_manifest']['characters']}
 previous=(-1,-1)
 for raw in lines(text):
  slot,subject,kind,target,value,satisfies=[s.strip() for s in raw[:6]];intent=raw[6]
  if len(slot)!=1 or not 'A'<=slot<='Z' or subject not in chars or kind not in KINDS or not intent.strip():raise ValueError('invalid group/subject/kind/intent')
  ai=ord(slot)-ord('A');ei=len(actions[ai]['events']) if ai<len(actions) else 0
  if ai>=len(actions) or ai<previous[0] or ai>previous[0]+1:raise ValueError('complete ordered original action groups required')
  if kind=='hold':
   if target!='-' or value!='-':raise ValueError('hold cannot hide target or state change')
   operation=None
  else:operation={'kind':kind,'actor':subject,'target':'' if target=='-' else target,'value':value}
  ids=[] if satisfies=='-' else satisfies.split(',')
  actions[ai]['events'].append({'intent':intent,'subject':subject,'operation':operation,'satisfies':ids});previous=(ai,ei)
 if not actions or any(not a['events'] for a in actions):raise ValueError('all complete original action groups required')
 return {'actions':actions}

class GroupLinesProseOrTools(ProseOrToolClients):
 def call(self,role,messages,**kwargs):
  if kwargs.get('structured_schema') is not None or not messages[0]['content'].startswith(VERSION):return super().call(role,messages,**kwargs)
  result=EvidencedRoleClients.call(self,role,messages,**kwargs)
  try:lines(result.text)
  except ValueError:raise EvidenceCallError('EVENT_LINES_PROTOCOL_INVALID',started=True,received=True,outcome_known=True,metadata=result.metadata,payload=result.response_payload,text=result.text) from None
  metadata=deepcopy(result.metadata);metadata['local_projection']=VERSION;metadata['original_model_event_lines_preserved']=True
  kwargs['evidence'].record('event_lines_received',{'contract':VERSION,'exact_original_lines':True,'no_content_fallback':True})
  return RoleResult(text=json.dumps({'event_lines':result.text},ensure_ascii=False),metadata=metadata,response_payload=result.response_payload)

def messages(inp,feedback):
 from scripts.creative_s7_native_event_policy_v2 import messages as focused
 result=focused(inp,feedback)
 from scripts import creative_local_event_performance_v3 as split
 refs=[s for s in split.focus(inp)['ordered_complete_current_steps'] if s['kind']=='action']
 payload=json.loads(result[1]['content']);payload['original_action_groups']=[{'action_index':i,'source_step_ref':s['source_step_ref'],'complete_original_text':s['text']} for i,s in enumerate(refs)]
 result[0]['content']=VERSION+'。只返回完整事件行，不用工具、JSON、数组、Markdown表格、围栏或解释。每行恰七列以|分隔：slot|subject|kind|target|value|satisfies|intent。slot是A0E0等，A是下列原action编号，E从0连续，动作组按原顺序齐全；subject人物ID且为实际操作者。kind只能hold/gaze/face/move/stand/sit/take/place/pass/slide；hold仅写非状态表演，两列target/value均为-。gaze/face/move等无道具操作target为-，value完整目标或人物位置；道具操作target为ID，value真实位置如surface:E02:beside_P05。无窗口satisfies为-，有要求填当前窗口ID。intent一句原事件自然意图，不含|；不同状态变化分别一行。写字、呼吸、手腕小动作hold，不站起/重拿笔；核对先看P06再回P05改，不偷演下一镜。原演员、动作及因果全部完整，不补原文没有的剧情。'
 result[1]['content']=json.dumps(payload,ensure_ascii=False,separators=(',',':'));return result
