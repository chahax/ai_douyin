"""Hash-exact frozen pack, history and current-runtime acceptance."""
from pathlib import Path
from copy import deepcopy
import os,sys,json,hashlib,ast,shutil
ROOT=Path(__file__).resolve().parents[4]
OUT=Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
from src.content_factory.creative_governed_runtime import REGISTRY_DIRECTORY,bind_new_task,verify_rules
from src.content_factory.creative_rule_registry import validate_registry_binding
previous=read(OUT.parent/'p1_closure_v21/integrity_checks.json')['packs']
packs={}
for name,relative in [('v22',REGISTRY_DIRECTORY),('v21','data/creative_governance/20261002_v21_platform_refactor_multi_feedback'),
                      ('v20','data/creative_governance/20261002_v20_platform_refactor_repair_resume'),
                      ('v19','data/creative_governance/20261002_v19_platform_refactor_p1_recovery'),
                      ('v18','data/creative_governance/20261002_v18_platform_refactor')]:
    directory=ROOT/relative
    manifest=read(directory/'artifact_manifest.json')
    mismatches=[x['path'] for x in manifest['artifacts'] if sha(directory/x['path'])!=x['sha256']]
    row={'directory':relative,'artifact_count':len(manifest['artifacts']),'artifact_mismatches':mismatches,
         'manifest_sha256':sha(directory/'artifact_manifest.json'),'runtime_manifest_sha256':sha(directory/'runtime_sources.json')}
    assert not mismatches,(name,mismatches)
    if name!='v22':
        row['manifest_unchanged_from_v21_acceptance']=row['manifest_sha256']==previous[name]['manifest_sha256']
        row['runtime_manifest_unchanged_from_v21_acceptance']=row['runtime_manifest_sha256']==previous[name]['runtime_manifest_sha256']
        assert row['manifest_unchanged_from_v21_acceptance'] and row['runtime_manifest_unchanged_from_v21_acceptance']
    else:
        expected={x['path'] for x in manifest['artifacts']}|{'artifact_manifest.json'}
        actual={str(p.relative_to(directory)).replace(chr(92),'/') for p in directory.rglob('*') if p.is_file()}
        assert expected==actual,(expected^actual)
    packs[name]=row
runtime=read(ROOT/REGISTRY_DIRECTORY/'runtime_sources.json')
candidate=read(OUT/'candidate_pack_03/runtime_sources.json')
assert runtime['sources']==candidate['sources'],'candidate tested runtime differs from released runtime'
sources=[]
for row in runtime['sources']:
    path=ROOT/row['path']; assert sha(path)==row['sha256'],row['path']
    if path.suffix=='.py':ast.parse(path.read_text(encoding='utf-8-sig'))
    dest=OUT/'source_snapshot'/row['path'];dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists():assert sha(dest)==sha(path)
    else:shutil.copyfile(path,dest)
    sources.append({**row,'syntax_valid':True if path.suffix=='.py' else None})
binding=bind_new_task()
checks=validate_registry_binding(binding,ROOT,stage='review',features=['gaze','cut','seat','state','dialogue','timing','source','handoff'])
from test_creative_governed_protocol import workflow
old_checks=[]
for old in ('v20','v21'):
    folder=OUT/('old_'+old+'_binding_probe');folder.mkdir(exist_ok=False)
    w,clients=workflow(folder,[])
    relative=packs[old]['directory']
    prior={**deepcopy(binding),'registry_dir':relative,'artifact_manifest_sha256':packs[old]['manifest_sha256'],'rules_sha256':sha(ROOT/relative/'rules.json')}
    w.state['rule_registry_binding']=prior;w._save();before=(folder/'state.json').read_bytes()
    try:verify_rules(w,'director_brief')
    except ValueError as exc:
        assert 'RUNTIME_SOURCE_CHANGED' in str(exc)
        error=str(exc)
    else:raise AssertionError('old task silently accepted new runtime')
    assert before==(folder/'state.json').read_bytes() and not clients.calls and w.state['rule_registry_binding']==prior
    old_checks.append({'version':old,'error':error,'state_unchanged':True,'calls':0})
upgrade=read(ROOT/REGISTRY_DIRECTORY/'runtime_upgrade_receipt.json')
assert upgrade['base_artifact_manifest_sha256']==packs['v21']['manifest_sha256']
assert upgrade['base_runtime_sources_sha256']==packs['v21']['runtime_manifest_sha256']
result={'schema':'creative_v22_integrity/v1','packs':packs,'source_checks':sources,'candidate_equals_released_runtime':True,
        'new_task_binding':binding,'governance_validation':checks,'old_binding_rejections':old_checks,
        'same_intent_migration_performed':False,'historical_tasks_modified':False}
(OUT/'integrity_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'runtime_sources':len(sources),'python_sources':sum(x['syntax_valid'] is True for x in sources),'packs_unchanged':list(previous),'old_bindings_rejected':len(old_checks)}))
