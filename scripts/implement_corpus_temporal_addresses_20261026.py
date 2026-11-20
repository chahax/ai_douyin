"""Preserve the failed v8 experiment; new v9 adds an explicit source address view."""
from pathlib import Path
import hashlib
import json

root=Path(__file__).resolve().parents[1];base=root/'src/content_factory'
qa=root/'data/qa/corpus_temporal_20261026'
paths=[base/name for name in ('corpus_production_v8.py','corpus_scope_v8.py','corpus_temporal_policy_v1.py')]
paths += [p for p in (root/'data/corpus_production_trials/20261026_v8_temporal').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
with (qa/'V8_BASELINE.json').open('x',encoding='utf-8') as f:
 json.dump({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},f,indent=2)
s=(base/'corpus_production_v8.py').read_text(encoding='utf-8')
s=s.replace('corpus_scope_v8','corpus_scope_v9').replace('corpus_production/v8-temporal-subject','corpus_production/v9-temporal-source-addresses')
s=s.replace('from . import corpus_temporal_policy_v1 as temporal','from . import corpus_temporal_policy_v1 as temporal\nfrom . import corpus_reference_view_v1 as references')
s=s.replace('chapters_api.chapter_payload(', 'references.chapter_payload(').replace('api.chapter_payload(', 'references.chapter_payload(')
s=s.replace('lambda value: api.validate(', 'lambda value: references.validate(').replace('lambda raw: api.validate(', 'lambda raw: references.validate(')
s=s.replace("'corpus_production_v8.py', 'corpus_scope_v9.py'", "'corpus_production_v9.py', 'corpus_scope_v9.py', 'corpus_reference_view_v1.py'")
s=s.replace("'temporal_policy_version': temporal.VERSION,", "'reference_view_version': references.VERSION, 'temporal_policy_version': temporal.VERSION,")
s=s.replace("            or plan.get('temporal_policy_version')", "            or plan.get('reference_view_version') != references.VERSION\n            or plan.get('temporal_policy_version')")
s=s.replace("v8's frozen", "v9's frozen")
with (base/'corpus_production_v9.py').open('x',encoding='utf-8') as f:f.write(s)
s=(base/'corpus_scope_v8.py').read_text(encoding='utf-8').replace('corpus_scope/v8-temporal-subject','corpus_scope/v9-temporal-source-addresses').replace('corpus_production/v8-temporal-subject','corpus_production/v9-temporal-source-addresses')
s=s.replace('corpus_scope_v8.py','corpus_scope_v9.py').replace('corpus_production_v8.py','corpus_production_v9.py')
s=s.replace('    "corpus_temporal_policy_v1.py",','    "corpus_reference_view_v1.py", "corpus_temporal_policy_v1.py",')
s=s.replace('whole_v8_production_implementation','whole_v9_production_implementation').replace('v8 implementation','v9 implementation')
with (base/'corpus_scope_v9.py').open('x',encoding='utf-8') as f:f.write(s)
print('Created v9; v8 evidence preserved.')
