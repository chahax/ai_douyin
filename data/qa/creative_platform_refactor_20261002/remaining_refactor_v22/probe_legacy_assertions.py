"""Hash-exact v21 comparison of pre-existing prompt-only legacy assertions."""
from pathlib import Path
import json, sys, os, hashlib, importlib.util, socket
ROOT=Path(__file__).resolve().parents[4];OUT=Path(__file__).resolve().parent
os.chdir(ROOT);sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
os.environ['LLM_PROVIDER']='mock'
def blocked(*args,**kwargs):raise RuntimeError('No network during baseline comparison')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked
source=OUT/'baseline/src/content_factory/creative_workflow.py'
expected=next(x['sha256'] for x in json.loads((ROOT/'data/creative_governance/20261002_v21_platform_refactor_multi_feedback/runtime_sources.json').read_text())['sources'] if x['path']=='src/content_factory/creative_workflow.py')
assert hashlib.sha256(source.read_bytes()).hexdigest()==expected
spec=importlib.util.spec_from_file_location('src.content_factory.v21_probe',source)
baseline=importlib.util.module_from_spec(spec);sys.modules[spec.name]=baseline;spec.loader.exec_module(baseline)
import test_creative_review_gate as gate
import test_creative_v4_integration as v4
import test_creative_v5_integration as v5
for module in (gate,v4,v5):module.CreativeWorkflow=baseline.CreativeWorkflow
cases=[('review_v1',gate.test_bound_review_version_survives_resume_and_joint_review,('evidence_review_v1',)),
       ('review_v2',gate.test_bound_review_version_survives_resume_and_joint_review,('evidence_review_v2',)),
       ('v4',v4.test_v4_routes_new_workflow_and_keeps_real_review_gate,()),
       ('v5',v5.test_v5_review_routes_deepseek_and_preserves_assistant_gate_and_receipt,()),
       ('v4_in_v5',v5.test_v4_run_cannot_silently_inherit_v5_prompt_or_static_manifest,())]
rows=[]
for name,function,args in cases:
    folder=OUT/'v21_prompt_probe'/name;folder.mkdir(parents=True)
    try:function(folder,*args);error=None
    except Exception as exc:error=type(exc).__name__
    receipt=json.loads(next(folder.rglob('script_review__story_00_00.json')).read_text(encoding='utf-8'))
    rows.append({'case':name,'failure_type':error,'prompt_sha256':receipt['prompt_sha256'],
                 'has_explicit_narrative_layer':'叙事表达优先' in receipt['request']['messages'][0]['content']})
assert all(x['failure_type']=='AssertionError' and x['has_explicit_narrative_layer'] for x in rows)
result={'baseline_matches_frozen_v21':True,'baseline_workflow_sha256':expected,'preexisting_failures':rows,
        'model_calls_are_fixtures':True,'network_disabled':True,'actual_historical_runs_modified':False}
(OUT/'legacy_assertion_baseline.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
