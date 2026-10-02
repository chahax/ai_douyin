from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.evaluate_minimax_scripts import request_once
from scripts.evaluate_minimax_script_events import check,REVIEW_PROMPT,evidence_errors
from src.content_factory.creative_script_patches import PATCH_SCHEMA,PATCH_PROMPT,apply_script_patches
from src.content_factory.creative_event_script import compile_event_script
from src.content_factory.creative_workflow_contract import parse_json_object,compile_beat_screenplay
from src.content_factory.reusable_production import read,write
from src.content_factory.creative_workflow_inputs import file_binding
sys.stdout.reconfigure(encoding='utf-8')
r=ROOT/'data/model_evaluations/minimax_targeted_patch_20260927';plan=read(r/'PLAN.json');cases={c['id']:c for c in read(ROOT/'config/minimax_script_eval_cases_v2_20260927.json')['cases']};samples=[]
for entry in plan['cases']:
 cid=entry['id'];d=r/cid;d.mkdir(exist_ok=True);parent=read(Path(entry['parent']))
 payload={'parent':parent,'parent_binding':file_binding(Path(entry['parent'])),'brief':cases[cid]['brief'],'allowed_paths':entry['allowed_paths'],'review_issues':entry['issues']}
 print('PATCH '+cid,flush=True)
 receipt=request_once(d/'call.json','writer',[{'role':'system','content':PATCH_PROMPT},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}],PATCH_SCHEMA,plan['maximum_remote_calls'],r)
 if receipt['response_metadata'].get('finish_reason')=='length':raise RuntimeError('patch truncated')
 patch=parse_json_object(receipt['response_text']);write(d/'patch.json',patch)
 revised=apply_script_patches(parent,patch,entry['allowed_paths']);write(d/'event_script.json',revised);script=compile_event_script(revised);write(d/'script.json',script);(d/'script.md').write_text(compile_beat_screenplay(script),encoding='utf-8');write(d/'machine_review.json',check(script,cases[cid]));samples.append({'sample_id':cid,'brief':cases[cid]['brief'],'script':script})
d=r/'review';d.mkdir(exist_ok=True)
receipt=request_once(d/'call.json','director',[{'role':'system','content':REVIEW_PROMPT},{'role':'user','content':json.dumps({'samples':samples},ensure_ascii=False)}],None,plan['maximum_remote_calls'],r)
review=parse_json_object(receipt['response_text']);write(d/'review.json',review);write(d/'evidence_check.json',{'errors':evidence_errors(review,samples),'automatic_approval':False})
