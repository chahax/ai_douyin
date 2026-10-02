"""Verify frozen history, default runtime binding and all current sources."""
from pathlib import Path
import os,sys,json,hashlib,ast,subprocess
ROOT=Path(__file__).resolve().parents[4]
OUT=Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
from src.content_factory.creative_governed_runtime import REGISTRY_DIRECTORY,bind_new_task,verify_rules
from src.content_factory.creative_rule_registry import validate_registry_binding
prior=read(OUT.parent/'v20_confirmation/integrity_checks.json')
packs={}
for name,relative in [('v21',REGISTRY_DIRECTORY),('v20','data/creative_governance/20261002_v20_platform_refactor_repair_resume'),
                      ('v19','data/creative_governance/20261002_v19_platform_refactor_p1_recovery'),
                      ('v18','data/creative_governance/20261002_v18_platform_refactor')]:
    directory=ROOT/relative
    manifest=read(directory/'artifact_manifest.json')
    failures=[row['path'] for row in manifest['artifacts'] if sha(directory/row['path'])!=row['sha256']]
    row={'directory':relative,'artifact_count':len(manifest['artifacts']),'artifact_mismatches':failures,
         'manifest_sha256':sha(directory/'artifact_manifest.json'),'runtime_manifest_sha256':sha(directory/'runtime_sources.json')}
    assert not failures
    if name=='v21':
        runtime=read(directory/'runtime_sources.json')
        row.update(runtime_source_count=len(runtime['sources']),runtime_mismatches=[item['path'] for item in runtime['sources'] if sha(ROOT/item['path'])!=item['sha256']])
        assert not row['runtime_mismatches']
    else:
        row['manifest_unchanged_from_v20_confirmation']=row['manifest_sha256']==prior['packs'][name]['manifest_sha256']
        row['runtime_manifest_unchanged_from_v20_confirmation']=row['runtime_manifest_sha256']==prior['packs'][name]['runtime_manifest_sha256']
        assert row['manifest_unchanged_from_v20_confirmation'] and row['runtime_manifest_unchanged_from_v20_confirmation']
    packs[name]=row
upgrade=read(ROOT/REGISTRY_DIRECTORY/'runtime_upgrade_receipt.json')
assert upgrade['base_artifact_manifest_sha256']==packs['v20']['manifest_sha256']
assert upgrade['base_runtime_sources_sha256']==packs['v20']['runtime_manifest_sha256']
binding=bind_new_task()
checks=validate_registry_binding(binding,ROOT,stage='review',features=['gaze','cut','seat','state','dialogue','timing','source','handoff'])
assert read(OUT/'new_task_binding.json')['rule_registry_binding']==binding
sources=[]
for row in read(ROOT/REGISTRY_DIRECTORY/'runtime_sources.json')['sources']:
    path=ROOT/row['path']
    valid=None
    if path.suffix=='.py':
        ast.parse(path.read_text(encoding='utf-8-sig'))
        valid=True
    sources.append({'path':row['path'],'sha256':sha(path),'syntax_valid':valid})
# Verify old v20 governance cannot silently switch to v21.
from test_creative_governed_protocol import workflow
from copy import deepcopy
from tempfile import mkdtemp
old_probe=Path(mkdtemp(prefix='old_v20_binding_',dir=OUT))
w,clients=workflow(old_probe,[])
old_dir=packs['v20']['directory']
old_binding={**deepcopy(binding),'registry_dir':old_dir,'artifact_manifest_sha256':packs['v20']['manifest_sha256'],
             'rules_sha256':sha(ROOT/old_dir/'rules.json')}
w.state['rule_registry_binding']=old_binding
w._save()
before=(old_probe/'state.json').read_bytes()
try:
    verify_rules(w,'director_brief')
    raise AssertionError('Old v20 task silently accepted changed runtime')
except ValueError as exc:
    assert 'RUNTIME_SOURCE_CHANGED' in str(exc)
    rejection=str(exc)
assert (old_probe/'state.json').read_bytes()==before and w.state['rule_registry_binding']==old_binding
assert not clients.calls
scoped=['src/content_factory/creative_workflow.py','src/content_factory/creative_stage_debug.py',
        'src/content_factory/creative_governed_runtime.py','src/web/creative_workflow_dashboard.py',
        'scripts/version_creative_governance_runtime.py','tests/test_creative_stage_debug.py',
        'tests/test_creative_workflow_ui.py','docs/CREATIVE_STAGE_DEBUGGING.md','docs/CREATIVE_WORKFLOW_IMPLEMENTATION.md']
proc=subprocess.run(['git','-c','core.safecrlf=false','diff','--check','--',*scoped],capture_output=True,text=True,encoding='utf-8')
(OUT/'scoped_diff_check.log').write_text(proc.stdout+proc.stderr,encoding='utf-8')
assert proc.returncode==0
# These files are largely untracked in this workspace, so explicitly inspect text too.
text_checks=[]
for relative in scoped:
    text=(ROOT/relative).read_text(encoding='utf-8-sig')
    trailing=[i for i,line in enumerate(text.splitlines(),1) if line.rstrip()!=line]
    assert not trailing,(relative,trailing)
    if relative.endswith('.py'):ast.parse(text)
    text_checks.append({'path':relative,'sha256':sha(ROOT/relative),'trailing_whitespace_lines':trailing})
result={'schema':'p1_v21_integrity/v1','packs':packs,'new_task_binding':binding,'actual_new_task_binding_matches':True,
        'governance_validation':checks,'source_checks':sources,'changed_file_checks':text_checks,
        'old_v20_rejection':{'error':rejection,'binding_unchanged':True,'state_file_unchanged':True,'model_calls':0},
        'scoped_diff_exit_code':proc.returncode,'migration_provenance_correct':'archived 20261002_v20_platform_refactor_repair_resume run' in (ROOT/REGISTRY_DIRECTORY/'MIGRATION.md').read_text(encoding='utf-8'),
        'prior_confirmation_sha256':sha(OUT.parent/'v20_confirmation/confirmation.json')}
assert result['migration_provenance_correct']
(OUT/'integrity_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'packs':packs,'runtime_source_count':len(sources),'old_v20_rejected_without_rebinding':True,'syntax_source_count':sum(row['syntax_valid'] is True for row in sources)},ensure_ascii=False))
