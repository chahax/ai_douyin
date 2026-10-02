"""Controlled adaptive-thinking probe: unchanged writer prompt/schema on known cases."""
from pathlib import Path
import sys,json
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.evaluate_minimax_scripts import request_once
from scripts.evaluate_minimax_script_events import check,REVIEW_PROMPT,evidence_errors
from src.content_factory.creative_event_script import EVENT_SCHEMA,compile_event_script
from src.content_factory.creative_workflow_contract import parse_json_object,compile_beat_screenplay
from src.content_factory.creative_writer_prompt_pack import build_writer_prompt
from src.content_factory.reusable_production import read,write
from src.content_factory.creative_workflow_inputs import file_binding
sys.stdout.reconfigure(encoding='utf-8')
r=ROOT/'data/model_evaluations/minimax_adaptive_20260927';r.mkdir(exist_ok=True)
base=read(ROOT/'config/minimax_script_eval_cases_v2_20260927.json')['cases'];cases=[c for c in base if c['id'] in ('C03','C06','H03')]
for cid,theme,rel,turn,end in [('H04','收到批评后认真倾听','温南、贺羽，两名成年同事，在桌旁','温南停止为自己辩解，把一直朝向自己的作品纸转向贺羽','温南请求对方指出最需要修改的一处，贺羽用手指指出，温南点头'),('H05','笨拙但体贴的合作','许风、陈雨，两名成年朋友，在家中书桌前','陈雨发现许风不是嫌画丑而是看不清反光，调整自己的观看位置','许风把画纸轻轻转向无反光的一侧，两人一起看')]:
 cases.append({'id':cid,'label':theme,'beat_count':3,'required_beat_ids':['B01','B02','B03'],'prompt_modules':['emotion'],'split':'fresh_holdout','brief':{'schema':'creative_brief/v1','theme':theme,'duration_seconds':[30,40],'relationships':rel,'turn':turn,'ending':end,'visual_style':'自然写实','constraints':['只出现两个人、一张纸和桌椅；不新增笔、手机、杯子','结尾最多10秒'],'avoid':['说教旁白','没有前因的突然认错']},'max_ending_seconds':10})
plan={'schema':'adaptive_probe/v1','maximum_remote_calls':7,'writer_calls':5,'review_calls':2,'thinking':'adaptive','max_completion_tokens':12000,'cases':cases,'pack':file_binding(ROOT/'config/prompts/creative_writer_modules_v3.json'),'note':'已见难例3个+全新需求2个；相较v3关闭思考，输出预算改为12000容纳思考，是两项配置变化，不作纯单因素因果结论。无返修。'}
if (r/'PLAN.json').exists() and read(r/'PLAN.json')!=plan:raise RuntimeError('plan changed')
write(r/'PLAN.json',plan);samples=[]
for case in cases:
 cid=case['id'];d=r/cid;d.mkdir(exist_ok=True)
 # Reuse exact frozen first-round messages/schema for the three known cases.
 parent=ROOT/'data/model_evaluations/minimax_events_v3_20260927/round_00'/cid/'call.json'
 if parent.exists():req=read(parent)['request'];messages=req['messages'];schema=req['schema']
 else:
  prompt=build_writer_prompt(case['prompt_modules'],pack_path=ROOT/'config/prompts/creative_writer_modules_v3.json')+'\n用submit_creative_json提交完整稿。'
  payload={'brief':case['brief'],'required_beat_ids':case['required_beat_ids'],'candidate_lock':{'id':'C01','title':case['label']}}
  schema=deepcopy(EVENT_SCHEMA);schema['properties']['selected_candidate_id']['enum']=['C01'];bs=schema['properties']['beats'];bs.update(minItems=case['beat_count'],maxItems=case['beat_count']);bs['items']['properties']['id']['enum']=case['required_beat_ids']
  messages=[{'role':'system','content':prompt},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
 print('ADAPTIVE '+cid,flush=True)
 try:receipt=request_once(d/'call.json','writer',messages,schema,7,r,thinking='adaptive',max_tokens=12000)
 except RuntimeError as exc:
  print('FAILED '+cid+': '+str(exc),flush=True)
  write(d/'machine_review.json',{'response_error':str(exc),'structural_errors':['no_usable_response']})
  continue
 if receipt['response_metadata'].get('finish_reason')=='length':raise RuntimeError('adaptive truncated')
 raw=parse_json_object(receipt['response_text']);write(d/'event_script.json',raw)
 try:script=compile_event_script(raw);write(d/'script.json',script);(d/'script.md').write_text(compile_beat_screenplay(script),encoding='utf-8');result=check(script,case);samples.append({'sample_id':cid,'brief':case['brief'],'script':script})
 except ValueError as e:result={'structural_errors':[str(e)]}
 write(d/'machine_review.json',result);print(json.dumps({'case':cid,**result},ensure_ascii=False),flush=True)
for i in range(0,len(samples),3):
 group=samples[i:i+3];d=r/f'review_{i//3+1}';d.mkdir(exist_ok=True)
 receipt=request_once(d/'call.json','director',[{'role':'system','content':REVIEW_PROMPT},{'role':'user','content':json.dumps({'samples':group},ensure_ascii=False)}],None,7,r)
 review=parse_json_object(receipt['response_text']);write(d/'review.json',review);write(d/'evidence_check.json',{'errors':evidence_errors(review,group),'automatic_approval':False})
