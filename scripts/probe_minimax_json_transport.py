from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.evaluate_minimax_scripts import request_once
from scripts.evaluate_minimax_script_events import check
from src.content_factory.creative_event_script import compile_event_script
from src.content_factory.creative_workflow_contract import parse_json_object,compile_beat_screenplay
from src.content_factory.reusable_production import read,write
r=ROOT/'data/model_evaluations/minimax_json_transport_20260927';r.mkdir(exist_ok=True)
parent=read(ROOT/'data/model_evaluations/minimax_events_v3_20260927/round_00/C03/call.json')['request'];messages=parent['messages'];messages[0]['content']=messages[0]['content'].replace('用submit_creative_json提交完整稿。','只直接输出完整JSON，不调用工具。')
write(r/'PLAN.json',{'maximum_remote_calls':1,'case':'C03','thinking':'adaptive','max_completion_tokens':12000,'transport':'plain_json_no_tool','reason':'检查结构错误是否受工具参数输出路径影响；仅改变输出方式，不放宽校验。'})
x=request_once(r/'call.json','writer',messages,None,1,r,thinking='adaptive',max_tokens=12000)
if x['response_metadata'].get('finish_reason')=='length':raise RuntimeError('truncated')
raw=parse_json_object(x['response_text']);write(r/'event_script.json',raw);compiled=compile_event_script(raw);write(r/'script.json',compiled);(r/'script.md').write_text(compile_beat_screenplay(compiled),encoding='utf-8')
case=next(c for c in read(ROOT/'config/minimax_script_eval_cases_v2_20260927.json')['cases'] if c['id']=='C03');write(r/'machine_review.json',check(compiled,case))
