"""Persistent end-to-end runner, real CLI controls and governed task evidence."""
from pathlib import Path
import os,sys,json,socket,hashlib,subprocess
from copy import deepcopy
ROOT=Path(__file__).resolve().parents[4]
OUT=Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
os.environ['LLM_PROVIDER']='mock'
os.environ['PYTHONIOENCODING']='utf-8'
os.environ['DATABASE_URL']='sqlite:///'+str(OUT/'probe_runtime.sqlite3').replace(chr(92),'/')
def blocked(*args,**kwargs):raise RuntimeError('P1 chain probe prohibits networking')
socket.socket.connect=blocked
socket.socket.connect_ex=blocked
from test_creative_stage_debug import _rebuilt_run,_resume,_read_json
from test_creative_workflow import FakeClients
from src.content_factory.creative_stage_debug import CreativeStageCommandService
from src.content_factory.creative_workflow import CreativeWorkflow, CREATE_REVIEW_PROFILE, _hash
from src.content_factory.creative_workflow_inputs import load_materials
from src.content_factory.creative_governed_runtime import REGISTRY_DIRECTORY

def save(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def cli(run,*args):
    command=[sys.executable,str(ROOT/'scripts/debug_creative_workflow.py'),str(run),*args]
    proc=subprocess.run(command,cwd=ROOT,env=os.environ.copy(),capture_output=True,text=True,encoding='utf-8')
    assert proc.returncode==0,proc.stderr
    return json.loads(proc.stdout)

base=OUT/'chain_case'
base.mkdir()
run,bundle,script,first_feedback=_rebuilt_run(base)
upstream=(run/'writer_analysis.json').read_bytes()
history={str(p.relative_to(run)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (run/'.creative_debug').rglob('*.json') if p.name!='index.json'}
checkpoints=[]
for expected in (6,7):
    before=cli(run,'inspect')
    receipt=_read_json(run/'writer_script.json')
    feedback=cli(run,'feedback','--stage','writer_script','--message',f'FIXTURE CLI feedback round {expected}')
    assert feedback['output_sha256']==receipt['output_sha256']
    script['title']=f'FIXTURE CLI revised version {expected}'
    state,clients=_resume(run,bundle,[deepcopy(script)],single_step=True)
    assert state['status']=='debug_breakpoint' and state['calls_started']==expected and len(clients.calls)==1
    replay,no_calls=_resume(run,bundle,[])
    assert not no_calls.calls and replay['calls_started']==expected
    comparison=cli(run,'compare','--stage','writer_script')
    checkpoints.append({'calls_before':expected-1,'calls_after':expected,'model_calls':len(clients.calls),
        'current_feedback_binding':feedback['output_sha256']==receipt['output_sha256'],
        'breakpoint':state['debug_breakpoint'],'feedback_status':state['debug_feedback_status'],
        'cached_replay_calls':len(no_calls.calls),'comparison':comparison})
    save(f'checkpoint_{expected}.json',state)
snapshot=cli(run,'inspect')
state=_read_json(run/'state.json')
assert all(hashlib.sha256((run/name).read_bytes()).hexdigest()==sha for name,sha in history.items())
archives=list(run.glob('DIRECTOR_FEEDBACK_CANDIDATE_REVISION__history_*.json'))
negotiation=_read_json(run/'DIRECTOR_FEEDBACK_CANDIDATE_REVISION.json')
assert all(p.stem.endswith(_hash(_read_json(p))) for p in archives)
assert negotiation['director_brief_sha256']==_read_json(run/'director_brief.json')['output_sha256']
assert (run/'writer_analysis.json').read_bytes()==upstream
save('chain_probe.json',{'schema':'p1_actual_runner_cli_chain/v1','initial_director_repair_and_rebuild_calls':5,
    'rounds':checkpoints,'final_calls_started':state['calls_started'],
    'reported_total_tokens':sum(row['usage']['total_tokens'] for row in state['stages']),
    'budget':{key:state[key] for key in ['max_calls','max_total_tokens','max_revisions','max_contract_repairs','budget_policy_version']},
    'current_stage_count':len(snapshot['stages']),'history_record_count':len(snapshot['history']),
    'historical_artifacts_and_resolutions_unchanged':True,'original_upstream_unchanged':True,
    'derived_history_hash_names_valid':True,'derived_current_director_binding_valid':True,
    'stage_dependencies':snapshot['stage_dependencies'],'paid_calls':0,'media_review_performed':False})
save('chain_snapshot.json',snapshot)

# Actual new governed task, using retained text response as an offline fixture.
real=ROOT/'data/creative_workflows/say_no_reviewed_segments_20260927'
manifest=_read_json(real/'MATERIALS.json')
original_bundle=load_materials(source_driver=manifest['source_driver'],title=manifest['title'],
    brief_path=Path(manifest['files']['creative_brief']['path']),
    asset_library_path=Path(manifest['files']['asset_library']['path']))
analysis=deepcopy(_read_json(real/'writer_analysis.json')['output'])
governed_run=OUT/'new_governed_original'
params=dict(model_profile=CREATE_REVIEW_PROFILE,writer_prompt_version='original_events_v3',
    review_policy_version='evidence_review_v6',production_protocol='governed_production_v1',
    budget_policy_version='v5_20261001',max_calls=20,max_total_tokens=500000,max_revisions=5,max_contract_repairs=8,
    stop_after_stage='writer_analysis')
clients=FakeClients([analysis])
actual=CreativeWorkflow(governed_run,clients=clients,**params).run(original_bundle)
assert actual['status']=='debug_breakpoint'
assert actual['rule_registry_binding']['registry_dir']==REGISTRY_DIRECTORY
original_feedback=cli(governed_run,'feedback','--stage','writer_analysis','--message','FIXTURE original task analysis repair')
analysis['candidates'][0]['title']+=' FIXTURE revised'
repair=FakeClients([analysis])
revised=CreativeWorkflow(governed_run,clients=repair,**params).run(original_bundle)
assert revised['status']=='debug_breakpoint' and revised['calls_started']==2 and len(repair.calls)==1
cached=FakeClients([])
replayed=CreativeWorkflow(governed_run,clients=cached,**params).run(original_bundle)
assert not cached.calls and replayed['calls_started']==2
save('new_task_binding.json',{'schema':'p1_actual_governed_original_task/v1','rule_registry_binding':actual['rule_registry_binding'],
    'initial_calls_started':1,'repair_calls_started':revised['calls_started'],'cached_replay_model_calls':0,
    'feedback_status':revised['debug_feedback_status'],'feedback_output_sha256':original_feedback['output_sha256'],
    'new_output_sha256':_read_json(governed_run/'writer_analysis.json')['output_sha256'],
    'production_protocol':actual['production_protocol'],'paid_calls':0,'using_retained_text_response_fixture':True})
print(json.dumps({'chain_calls':state['calls_started'],'historical_records':len(snapshot['history']),
    'actual_new_task_registry':actual['rule_registry_binding']['registry_dir'],'new_task_repair_calls':revised['calls_started']},ensure_ascii=False))
