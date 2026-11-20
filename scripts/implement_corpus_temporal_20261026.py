"""One-shot versioned prompt-policy wiring, without executing model tasks."""
from pathlib import Path
import hashlib
import json

root=Path(__file__).resolve().parents[1]
base=root/'src/content_factory'
qa=root/'data/qa/corpus_temporal_20261026'
qa.mkdir(parents=True,exist_ok=True)
paths=[base/name for name in ('corpus_production_v7.py','corpus_scope_v7.py',
    'corpus_chapter_materials_v6.py','corpus_episode_state_v6.py','corpus_production_contract_v6.py',
    'minimax_production_client_v1.py')]
paths += [p for p in (root/'data/corpus_production_trials/20261026_v7_minimax_default').rglob('*')
          if p.is_file() and '__pycache__' not in p.parts]
with (qa/'OLD_FILES.json').open('x',encoding='utf-8') as f:
    json.dump({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},f,indent=2)
s=(base/'corpus_production_v7.py').read_text(encoding='utf-8')
s=s.replace('corpus_scope_v7','corpus_scope_v8')
s=s.replace('corpus_production/v7-minimax-materials-episode-state','corpus_production/v8-temporal-subject')
s=s.replace('from .visual_storytelling_v1 import profile', 'from .visual_storytelling_v1 import profile\nfrom . import corpus_temporal_policy_v1 as temporal')
s=s.replace('chapters_api.EXTRACT_PROMPT,','temporal.extraction_prompt(chapters_api.EXTRACT_PROMPT),')
s=s.replace("chapters_api.chapter_schema(chapter_plan, payload)}, materials_route)", "temporal.extraction_schema(chapters_api.chapter_schema(chapter_plan, payload))}, materials_route)")
s=s.replace("'minimax_request_policy': deepcopy(REQUEST_POLICY), 'target_seconds'", "'minimax_request_policy': deepcopy(REQUEST_POLICY),\n            'temporal_policy_version': temporal.VERSION, 'temporal_policy_sha256': digest(temporal.RULES), 'target_seconds'")
s=s.replace("'writer', api.EXTRACT_PROMPT,", "'writer', temporal.extraction_prompt(api.EXTRACT_PROMPT),")
s=s.replace('payload, api.chapter_schema(chapter_plan, payload),', 'payload, temporal.extraction_schema(api.chapter_schema(chapter_plan, payload)),')
s=s.replace('payload, api.chapter_schema(cp, payload),', 'payload, temporal.extraction_schema(api.chapter_schema(cp, payload)),')
s=s.replace("'corpus_production_v7.py', 'corpus_scope_v8.py'", "'corpus_production_v8.py', 'corpus_scope_v8.py', 'corpus_temporal_policy_v1.py'")
s=s.replace("                role = STAGES['material_review']", "                role = STAGES['material_review']\n            if not name.startswith('MATERIALS_REPAIR_'):\n                prompt = temporal.review_prompt(prompt) if role in ('local', 'director') else temporal.extraction_prompt(prompt)")
s=s.replace("            or plan['stage_routes'] != STAGES):", "            or plan['stage_routes'] != STAGES\n            or plan.get('temporal_policy_version') != temporal.VERSION\n            or plan.get('temporal_policy_sha256') != digest(temporal.RULES)):")
s=s.replace("v7's frozen materials route", "v8's frozen materials route")
with (base/'corpus_production_v8.py').open('x',encoding='utf-8') as f:f.write(s)
s=(base/'corpus_scope_v7.py').read_text(encoding='utf-8')
s=s.replace('corpus_scope/v7-minimax-default','corpus_scope/v8-temporal-subject')
s=s.replace('corpus_production/v7-minimax-materials-episode-state','corpus_production/v8-temporal-subject')
s=s.replace('corpus_scope_v7.py','corpus_scope_v8.py').replace('corpus_production_v7.py','corpus_production_v8.py')
s=s.replace('    "minimax_production_client_v1.py",', '    "corpus_temporal_policy_v1.py", "minimax_production_client_v1.py",')
s=s.replace('whole_v7_production_implementation','whole_v8_production_implementation').replace('v7 implementation','v8 implementation')
with (base/'corpus_scope_v8.py').open('x',encoding='utf-8') as f:f.write(s)
print('Created v8 temporal policy wiring; old files preserved.')
