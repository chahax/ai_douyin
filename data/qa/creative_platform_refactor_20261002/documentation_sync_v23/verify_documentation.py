from pathlib import Path
import json,re,hashlib,subprocess,sys,ast,contextlib,io,socket,os,runpy
from urllib.parse import unquote
ROOT=Path.cwd();OUT=ROOT/'data/qa/creative_platform_refactor_20261002/documentation_sync_v23'
manifest=json.loads((OUT/'implementation_manifest.json').read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
missing=[];links=0;format_errors=[]
for row in manifest['files']:
 p=ROOT/row['path'];s=p.read_text(encoding='utf-8')
 assert sha(p)==row['after_sha256'], 'document changed during validation: '+row['path']
 for target in re.findall(r'\[[^\]\n]+\]\(([^)\n]+)\)',s):
  if target.startswith(('http://','https://','mailto:')):continue
  target=target.strip('<>');base=unquote(target.split('#',1)[0]);links+=1
  resolved=(p.parent/base).resolve() if base else p
  if not resolved.exists():missing.append({'document':row['path'],'target':target})
 for line,text in enumerate(s.splitlines(),1):
  if text.rstrip()!=text:format_errors.append({'document':row['path'],'line':line,'error':'trailing whitespace'})
 if s.count('```')%2:format_errors.append({'document':row['path'],'error':'unbalanced fenced code'})

frozen=[]
for pack in manifest['frozen_packs_before']:
 p=ROOT/pack['pack']
 changed=[name for name,old in pack['files'].items() if sha(p/name)!=old]
 if sha(p/'artifact_manifest.json')!=pack['manifest_sha256']:changed.append('artifact_manifest.json')
 frozen.append({'pack':pack['pack'],'files':len(pack['files']),'changed':changed})
runtime_changes=[name for name,old in manifest['runtime_before'].items() if sha(ROOT/name)!=old]
old_agents=(OUT/'before/AGENTS.md').read_text(encoding='utf-8-sig').replace('\r\n','\n').rstrip()
assert (ROOT/'AGENTS.md').read_text(encoding='utf-8').startswith(old_agents)
for name in ('REUSABLE_VIDEO_WORKFLOW.md','SCRIPT_VIDEO_RUN.md'):
 old=(OUT/'before/docs'/name).read_text(encoding='utf-8-sig');old_body=old.split('\n',1)[1].replace('\r\n','\n').strip()
 assert (ROOT/'docs'/name).read_text(encoding='utf-8').rstrip().endswith(old_body),name

res=subprocess.run(['git','diff','--check','--']+[r['path'] for r in manifest['files']],capture_output=True,text=True,encoding='utf-8')
checks={'schema':'creative_documentation_validation/v1','document_count':len(manifest['files']),'local_links_checked':links,'missing_links':missing,'format_errors':format_errors,'original_AGENTS_policy_preserved':True,'dated_production_record_bodies_preserved':True,'runtime_sources_checked':len(manifest['runtime_before']),'runtime_changes':runtime_changes,'frozen_packs':frozen,'git_diff_check':{'exit_code':res.returncode,'output':res.stdout+res.stderr},'business_tests_rerun':False,'paid_calls':False,'real_media_inspected':False,'published':False}
(OUT/'validation.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in checks.items() if k!='frozen_packs'},ensure_ascii=False))
print(json.dumps({'frozen_pack_count':len(frozen),'changed_packs':[p for p in frozen if p['changed']]},ensure_ascii=False))
assert not missing and not format_errors and not runtime_changes and not any(p['changed'] for p in frozen) and res.returncode==0
