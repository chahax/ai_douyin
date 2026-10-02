from pathlib import Path
import json
run=Path('data/creative_workflows/reusable_trial_20260927')
for p in run.glob('writer_analysis*.json'):
 d=json.loads(p.read_text(encoding='utf-8'))
 print(p.name, json.dumps({k:d.get(k) for k in ('status','validation_error','error','contract_error') if k in d},ensure_ascii=False))
 if d.get('output'): print(json.dumps(d['output'],ensure_ascii=False)[:5500])
p=Path('data/video_generation/sequential_workflow_20260908/campaign.json');d=json.loads(p.read_text(encoding='utf-8-sig'))
print('CAMPAIGN',json.dumps({k:d.get(k) for k in ('status','current_series_id','failed_outputs','lifetime_failed_outputs','max_failed_outputs')},ensure_ascii=False))
print('RECENT_ATTEMPTS',json.dumps([{k:a.get(k) for k in ('id','status','shot','run_dir','series_id')} for a in d.get('attempts',[])[-5:]],ensure_ascii=False))
p=Path('data/video_generation/blank_cost_20260925/performance_revision_20260926/photoreal_reference_v3/FULL_VIDEO_PROGRESS.json')
d=json.loads(p.read_text(encoding='utf-8-sig'));print('OTHER_SERIES',json.dumps(d,ensure_ascii=False)[:4800])
