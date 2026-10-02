from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.evaluate_minimax_scripts import request_once
from scripts.evaluate_minimax_script_events import check,REVIEW_PROMPT,evidence_errors
from src.content_factory.creative_event_script import compile_event_script
from src.content_factory.creative_workflow_contract import parse_json_object,compile_beat_screenplay
from src.content_factory.reusable_production import read,write
sys.stdout.reconfigure(encoding='utf-8')
r=ROOT/'data/model_evaluations/minimax_m27_20260927';r.mkdir(exist_ok=True);cases={c['id']:c for c in read(ROOT/'config/minimax_script_eval_cases_v2_20260927.json')['cases']};samples=[]
write(r/'PLAN.json',{'maximum_remote_calls':4,'writer_model':'MiniMax-M2.7','thinking':'provider_default','max_completion_tokens':16000,'cases':['C03','C06','H03'],'production_model_changed':False,'reason':'同供应商不同模型对照，不是静默回退；沿用M3初稿同一提示词、简报与schema，另改变预算和默认思考配置。'})
for cid in ('C03','C06','H03'):
 d=r/cid;d.mkdir(exist_ok=True);parent=read(ROOT/'data/model_evaluations/minimax_events_v3_20260927/round_00'/cid/'call.json')['request']
 print('M2.7 '+cid,flush=True)
 receipt=request_once(d/'call.json','writer',parent['messages'],parent['schema'],4,r,thinking=None,max_tokens=16000,writer_model='MiniMax-M2.7')
 if receipt['response_metadata'].get('finish_reason')=='length':raise RuntimeError('truncated')
 raw=parse_json_object(receipt['response_text']);write(d/'event_script.json',raw);script=compile_event_script(raw);write(d/'script.json',script);(d/'script.md').write_text(compile_beat_screenplay(script),encoding='utf-8');result=check(script,cases[cid]);write(d/'machine_review.json',result);print(json.dumps({'case':cid,**result},ensure_ascii=False),flush=True);samples.append({'sample_id':cid,'brief':cases[cid]['brief'],'script':script})
d=r/'review';d.mkdir(exist_ok=True);receipt=request_once(d/'call.json','director',[{'role':'system','content':REVIEW_PROMPT},{'role':'user','content':json.dumps({'samples':samples},ensure_ascii=False)}],None,4,r)
review=parse_json_object(receipt['response_text']);write(d/'review.json',review);write(d/'evidence_check.json',{'errors':evidence_errors(review,samples),'automatic_approval':False})
