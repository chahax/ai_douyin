from pathlib import Path
import json
r=Path('data/creative_workflows/reusable_trial_20260927')
for name in ('writer_revise__assistant_02.json','writer_revise__assistant_02__contract_repair.json'):
 d=json.loads((r/name).read_text(encoding='utf-8'));print(name);print(d['response_text'])
