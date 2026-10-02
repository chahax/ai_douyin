from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.evaluate_minimax_scripts import request_once
from scripts.evaluate_minimax_script_events import check
from src.content_factory.creative_event_script import compile_event_script
from src.content_factory.creative_workflow_contract import parse_json_object,compile_beat_screenplay
from src.content_factory.reusable_production import read,write
r=ROOT/'data/model_evaluations/minimax_temperature_20260927';r.mkdir(exist_ok=True)
req=read(ROOT/'data/model_evaluations/minimax_events_v3_20260927/round_00/C03/call.json')['request']
write(r/'PLAN.json',{'maximum_remote_calls':1,'temperature':1.0,'thinking':'disabled','model':'MiniMax-M3','case':'C03','reason':'单独测试官方推荐温度，同一原始提示词、schema与6000输出上限。'})
receipt=request_once(r/'call.json','writer',req['messages'],req['schema'],1,r,temperature=1.0)
raw=parse_json_object(receipt['response_text']);write(r/'event_script.json',raw);script=compile_event_script(raw);write(r/'script.json',script);(r/'script.md').write_text(compile_beat_screenplay(script),encoding='utf-8')
case=next(c for c in read(ROOT/'config/minimax_script_eval_cases_v2_20260927.json')['cases'] if c['id']=='C03');write(r/'machine_review.json',check(script,case))
