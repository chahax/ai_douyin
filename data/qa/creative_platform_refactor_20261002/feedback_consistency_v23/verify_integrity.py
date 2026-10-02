"""Verify v23 release, original review evidence and frozen history without migration."""
from pathlib import Path
import json,hashlib,ast,sys,os,shutil
ROOT=Path(__file__).resolve().parents[4];OUT=Path(__file__).resolve().parent
os.chdir(ROOT);sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
from src.content_factory.creative_governed_runtime import REGISTRY_DIRECTORY,bind_new_task,verify_rules
from src.content_factory.creative_rule_registry import validate_registry_binding
prior=read(OUT.parent/'remaining_refactor_v22/integrity_checks.json')['packs']
packs={}
for name,relative in [('v23',REGISTRY_DIRECTORY)]+[(k,v['directory']) for k,v in prior.items()]:
    directory=ROOT/relative;manifest=read(directory/'artifact_manifest.json')
    mismatches=[x['path'] for x in manifest['artifacts'] if sha(directory/x['path'])!=x['sha256']]
    assert not mismatches,(name,mismatches)
    row={'directory':relative,'artifact_count':len(manifest['artifacts']),'artifact_mismatches':mismatches,
         'manifest_sha256':sha(directory/'artifact_manifest.json'),'runtime_manifest_sha256':sha(directory/'runtime_sources.json')}
    if name!='v23':
        assert row['manifest_sha256']==prior[name]['manifest_sha256']
        assert row['runtime_manifest_sha256']==prior[name]['runtime_manifest_sha256']
        row['unchanged_from_v22_acceptance']=True
    else:
        expected={x['path'] for x in manifest['artifacts']}|{'artifact_manifest.json'}
        assert expected=={p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    packs[name]=row
runtime=read(ROOT/REGISTRY_DIRECTORY/'runtime_sources.json')
assert runtime['sources']==read(OUT/'candidate_pack_07/runtime_sources.json')['sources']
sources=[]
for item in runtime['sources']:
    path=ROOT/item['path'];assert sha(path)==item['sha256'],item['path']
    if path.suffix=='.py':ast.parse(path.read_text(encoding='utf-8-sig'))
    dest=OUT/'source_snapshot'/item['path'];dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists():assert sha(dest)==sha(path)
    else:shutil.copyfile(path,dest)
    sources.append({**item,'syntax_valid':path.suffix=='.py'})
pack=ROOT/REGISTRY_DIRECTORY
old=ROOT/prior['v22']['directory']
assert sha(pack/'rules.json')==sha(old/'rules.json')
assert sha(pack/'dataset_manifest.json')==sha(old/'dataset_manifest.json')
upgrade=read(pack/'runtime_upgrade_receipt.json')
assert upgrade['base_artifact_manifest_sha256']==prior['v22']['manifest_sha256']
assert upgrade['base_runtime_sources_sha256']==prior['v22']['runtime_manifest_sha256']
binding=bind_new_task();checks=validate_registry_binding(binding,ROOT,stage='review',features=['gaze','cut','seat','state','dialogue','timing','source','handoff'])
from copy import deepcopy
from test_creative_governed_protocol import workflow
folder=OUT/'old_v22_binding_probe';folder.mkdir(exist_ok=False)
w,clients=workflow(folder,[])
old_binding={**deepcopy(binding),'registry_dir':prior['v22']['directory'],'artifact_manifest_sha256':prior['v22']['manifest_sha256'],'rules_sha256':sha(old/'rules.json')}
w.state['rule_registry_binding']=old_binding;w._save();before=(folder/'state.json').read_bytes()
try:verify_rules(w,'director_brief')
except ValueError as exc:
    assert 'RUNTIME_SOURCE_CHANGED' in str(exc);rejection=str(exc)
else:raise AssertionError('Old task silently accepted v23')
assert before==(folder/'state.json').read_bytes() and not clients.calls
review=OUT.parent/'implementation_review_v22/review_report.html'
assert sha(review)==read(pack/'platform_refactor_contract.json')['implementation_review_sha256']
result={'schema':'creative_v23_integrity/v1','packs':packs,'source_checks':sources,'candidate_equals_released_runtime':True,
        'rules_unchanged':True,'dataset_unchanged':True,'original_implementation_review_sha256':sha(review),
        'new_task_binding':binding,'governance_validation':checks,
        'old_v22_rejection':{'error':rejection,'state_and_binding_unchanged':True,'provider_calls':0},
        'production_tasks_migrated':False}
(OUT/'integrity_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'runtime_sources':len(sources),'python_sources':sum(x['syntax_valid'] for x in sources),'history_packs_unchanged':list(prior),'rules_dataset_unchanged':True}))
