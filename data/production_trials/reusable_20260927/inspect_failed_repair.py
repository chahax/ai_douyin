from pathlib import Path
import json
r=Path('data/creative_workflows/reusable_trial_20260927')
for name in ('writer_revise__assistant_02.json','writer_revise__assistant_02__contract_repair.json'):
 d=json.loads((r/name).read_text(encoding='utf-8'));print(name,list(d)); print('output',json.dumps(d.get('output'),ensure_ascii=False));print('text',str(d.get('response',''))[:7500]);print('raw_text',str(d.get('raw_text',''))[:3500]); print('response_metadata',json.dumps(d.get('response_metadata'),ensure_ascii=False))
