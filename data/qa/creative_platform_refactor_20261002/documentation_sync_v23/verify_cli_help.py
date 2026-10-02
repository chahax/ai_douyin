from pathlib import Path
import os,sys,socket,runpy,contextlib,io,json
ROOT=Path.cwd();OUT=ROOT/'data/qa/creative_platform_refactor_20261002/documentation_sync_v23'
os.environ['DATABASE_URL']='sqlite:///'+str(OUT/'help_validation.sqlite3').replace(chr(92),'/')
os.environ['LLM_PROVIDER']='mock';sys.path.insert(0,str(ROOT))
def blocked(*args,**kwargs):raise RuntimeError('Documentation checks prohibit network access')
socket.socket.connect=blocked;socket.socket.connect_ex=blocked
expect={
 'scripts/run_creative_workflow.py':['--next-stage','--stop-after-stage','--production-protocol','--review-policy-version'],
 'scripts/debug_creative_workflow.py':['inspect','compare','feedback','stop','resume'],
 'scripts/compile_creative_seedance_segments.py':['run_dir','output','--revised'],
 'scripts/run_creative_seedance_segment.py':['preview','submit','query','--output-dir'],
 'scripts/creative_workbench.py':['prepare-segment','assembly-chain','assemble','prepare-delivery','publish','verify-publish','collect-operations','quality-report'],
 'scripts/review_media_candidate.py':['approved','rejected','--user-statement'],
}
results=[]
for relative,expected in expect.items():
 stream=io.StringIO();sys.argv=[str(ROOT/relative),'--help']
 with contextlib.redirect_stdout(stream),contextlib.redirect_stderr(stream):
  try:runpy.run_path(str(ROOT/relative),run_name='__main__')
  except SystemExit as exc:
   assert exc.code in (None,0),(relative,exc.code)
 value=stream.getvalue();missing=[flag for flag in expected if flag not in value]
 assert not missing,(relative,missing)
 (OUT/(Path(relative).stem+'_help.txt')).write_text(value,encoding='utf-8')
 results.append({'script':relative,'help_ok':True,'expected_flags_or_commands':expected})
# Confirm execute is mandatory on both effectful local assembly and publishing.
from scripts.creative_workbench import parser
for command in ('assemble','publish'):
 sub=next(a for a in parser()._actions if isinstance(a,__import__('argparse')._SubParsersAction)).choices[command]
 flag=next(a for a in sub._actions if '--execute' in a.option_strings)
 assert flag.required
result={'offline':True,'commands':results,'assemble_and_publish_require_execute':True,'generation_or_publish_performed':False}
(OUT/'cli_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'help_entries_verified':len(results),'execute_required':True,'network_disabled':True},ensure_ascii=False))
