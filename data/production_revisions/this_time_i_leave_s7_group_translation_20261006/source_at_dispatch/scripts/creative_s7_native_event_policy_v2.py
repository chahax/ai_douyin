"""Only original S7 motion kinds; native plans, no output repairs."""
from copy import deepcopy
from scripts.creative_s7_source_event_policy_v1 import restrict_schema as listener_policy
VERSION='s7_original_motion_kinds/v2'

def restrict_schema(schema,inp):
 result=listener_policy(schema,inp)
 allowed={'SH07':['gaze','slide'],'SH09':['gaze'],'SH10':['gaze']}
 if inp['shot_id'] not in allowed:return result
 index=int(inp['shot_id'][2:])-1;b=inp['context']['raw_linear_script']['beats'][index]
 if b['id']!='B'+str(index+1).zfill(2) or len(b['steps'])!=1 or b['steps'][0]['kind']!='action':raise ValueError('original motion source changed')
 for a in result['properties']['actions']['prefixItems']:
  event=a['properties']['events']['items'];options=event['properties']['operation']['anyOf'];kept=[]
  for op in options:
   if op.get('type')=='null':kept.append(op);continue
   if op.get('type')!='object':continue
   v=deepcopy(op);k=v['properties']['kind'];kinds=[x for x in k.get('enum',[]) if x in allowed[inp['shot_id']]]
   if not kinds:continue
   k['enum']=kinds
   if kinds==['slide']:v['properties']['target']={'const':'P06'}
   kept.append(v)
  event['properties']['operation']['anyOf']=kept
 return result

def messages(inp,feedback):
 import json
 from scripts import creative_local_event_performance_v3 as split
 ctx=inp['context'];outline={k:deepcopy(inp['direction'][k]) for k in ('emotional_arc','causal_chain','ending_intent')}
 payload={'read_only_complete_creative_source':{k:deepcopy(ctx[k]) for k in ('raw_linear_script','reference_pack','static_visual_manifest','production_responsibility')},'whole_film_outline':outline,'spatial_contract':deepcopy(inp['direction']['spatial_contract']),'current_direction_and_complete_steps':split.focus(inp),'verified_faults':feedback or {}}
 rule=split.plan_messages(inp)[0]['content']+' 直接调用工具提交actions/events原生字段，不用payload_json或JSON字符串。当前原稿不含的站起、取放、身体移动不可借作写字或手腕动作；原稿已有持笔时不再take。非状态变化的写字、手指、呼吸用null。核对单据必须先看单据再回明细单改，不能倒置因果。'
 return [{'role':'system','content':rule},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}]
