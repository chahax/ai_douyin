from pathlib import Path
import os,sys,json,hashlib,ast,subprocess
ROOT=Path(__file__).resolve().parents[4];OUT=Path(__file__).resolve().parent
os.chdir(ROOT);sys.path.insert(0,str(ROOT))
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
from src.content_factory.creative_governed_runtime import REGISTRY_DIRECTORY,bind_new_task
from src.content_factory.creative_rule_registry import validate_registry_binding
packs={}
for name,relative in [('v20',REGISTRY_DIRECTORY),('v19','data/creative_governance/20261002_v19_platform_refactor_p1_recovery'),('v18','data/creative_governance/20261002_v18_platform_refactor')]:
 directory=ROOT/relative;manifest=read(directory/'artifact_manifest.json')
 failures=[row['path'] for row in manifest['artifacts'] if sha(directory/row['path'])!=row['sha256']]
 packs[name]={'directory':relative,'artifact_count':len(manifest['artifacts']),'artifact_mismatches':failures,'manifest_sha256':sha(directory/'artifact_manifest.json'),'runtime_manifest_sha256':sha(directory/'runtime_sources.json')}
 if name=='v20':
  runtime=read(directory/'runtime_sources.json')
  packs[name].update(runtime_source_count=len(runtime['sources']),runtime_mismatches=[row['path'] for row in runtime['sources'] if sha(ROOT/row['path'])!=row['sha256']])
receipt=read(ROOT/REGISTRY_DIRECTORY/'runtime_upgrade_receipt.json')
packs['v19']['manifest_matches_v20_frozen_base']=packs['v19']['manifest_sha256']==receipt['base_artifact_manifest_sha256']
packs['v19']['runtime_manifest_matches_v20_frozen_base']=packs['v19']['runtime_manifest_sha256']==receipt['base_runtime_sources_sha256']
prior=read(OUT.parent/'v19_confirmation'/'integrity_checks.json')
for old in ('v18','v19'):
 packs[old]['manifest_unchanged_from_prior_confirmation']=packs[old]['manifest_sha256']==prior['packs'][old]['manifest_sha256']
 packs[old]['runtime_manifest_unchanged_from_prior_confirmation']=packs[old]['runtime_manifest_sha256']==prior['packs'][old]['runtime_manifest_sha256']
binding=bind_new_task()
checks=validate_registry_binding(binding,ROOT,stage='review',features=['gaze','cut','seat','state','dialogue','timing','source','handoff'])
sources=[]
for row in read(ROOT/REGISTRY_DIRECTORY/'runtime_sources.json')['sources']:
 path=ROOT/row['path'];syntax_valid=None
 if path.suffix=='.py':ast.parse(path.read_text(encoding='utf-8-sig'));syntax_valid=True
 sources.append({'path':row['path'],'sha256':sha(path),'syntax_valid':syntax_valid})
scoped=['src/content_factory/creative_workflow.py','src/content_factory/creative_stage_debug.py','src/content_factory/creative_governed_runtime.py','src/content_factory/media_review_policy.py','src/scheduler/queue.py','tests/test_creative_stage_debug.py']
diffs={}
for name,args in [('scoped',['--']+scoped),('global',[])]:
 proc=subprocess.run(['git','-c','core.safecrlf=false','diff','--check']+args,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
 (OUT/(name+'_diff_check.log')).write_text(proc.stdout+proc.stderr,encoding='utf-8')
 diffs[name]={'exit_code':proc.returncode,'errors':[line for line in (proc.stdout+proc.stderr).splitlines() if 'new blank line' in line or 'trailing whitespace' in line or 'space before tab' in line]}
result={'packs':packs,'new_task_binding':binding,'governance_validation':checks,'source_checks':sources,'diff_checks':diffs,'migration_document_sha256':sha(ROOT/REGISTRY_DIRECTORY/'MIGRATION.md')}
(OUT/'integrity_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'packs':packs,'runtime_verification':checks['validation']['runtime_sources'],'semantic_limit_exceeded':checks['activation']['requires_split_or_merge'],'syntax_source_count':sum(row['syntax_valid'] is True for row in sources),'diff_checks':diffs},ensure_ascii=False))


