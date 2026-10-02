from pathlib import Path
import json
base=Path('data/production_trials/reusable_20260927')
p=base/'brief.json'
if p.exists():
 raise SystemExit('Existing trial brief; inspect before resuming')
b=json.loads(Path('config/creative_brief.example.json').read_text(encoding='utf-8-sig'))
b['title']='还记得'
p.write_text(json.dumps(b,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(base/'TRIAL_SCOPE.json').write_text(json.dumps({'schema':'reusable_production_trial/v1','authorization':'你操作审核一下','story_selection':'assistant_selected_from_editable_example_for_first_production_trial','brief':str(p.resolve()),'workflow_run':str(Path('data/creative_workflows/reusable_trial_20260927').resolve()),'scope':'one pilot story with actual editorial and media review; no publication','text_budget':{'max_calls':20,'max_total_tokens':500000,'max_revisions':2,'max_contract_repairs':8},'video_failure_limit_per_script':10,'actual_quality_passed':False,'remote_media_submitted':False},ensure_ascii=False,indent=2),encoding='utf-8')
