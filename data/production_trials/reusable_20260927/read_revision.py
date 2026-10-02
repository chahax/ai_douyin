from pathlib import Path
import json
r=Path('data/creative_workflows/reusable_trial_20260927');d=json.loads((r/'ASSISTANT_REVISION_DRAFT.json').read_text(encoding='utf-8'))
print(d['script']['screenplay_markdown'])
print('TIMING',[(x['id'],x['duration_seconds']) for x in d['script']['beats']])
for s in d['shots']['shots']: print(json.dumps(s,ensure_ascii=False))
print('DESIGN',json.dumps(d.get('production_design'),ensure_ascii=False))
print('CHECK',json.dumps(d['check'],ensure_ascii=False))
