"""Run production boundaries with offline fixtures and retain inspectable receipts."""
from pathlib import Path
import os, sys, socket, json, hashlib
ROOT=Path(__file__).resolve().parents[4]
OUT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
os.chdir(ROOT)
os.environ['DATABASE_URL']='sqlite:///'+str(OUT/'probe.sqlite3').replace(chr(92),'/')
os.environ['LLM_PROVIDER']='mock'
def blocked(*args,**kwargs):raise RuntimeError('offline fixture probe prohibits network')
socket.socket.connect=blocked
socket.socket.connect_ex=blocked
import src.content_factory.creative_governed_runtime as governed
if len(sys.argv)>1:governed.REGISTRY_DIRECTORY=str((OUT/sys.argv[1]).relative_to(ROOT)).replace(chr(92),'/')
import test_creative_remaining_refactor as t
from src.content_factory.creative_quality_evidence import quality_report
from src.content_factory.creative_stage_debug import CreativeStageCommandService
from scripts.creative_workbench import main as workbench_cli
from pytest import MonkeyPatch
probe=OUT/'execution_chain'
probe.mkdir(exist_ok=False)
cases={}
for label,function in [('stop_resume',t.test_stop_inflight_saves_result_and_resume_preserves_budget),
                       ('field_dependency',t.test_actual_field_projection_reuses_unchanged_consumed_request),
                       ('media_chain',t.test_full_preview_segment_human_tail_cut_assembly_delivery_chain),
                       ('unknown_dispatch',t.test_changing_output_directory_cannot_resubmit_unknown_or_unreviewed_segment),
                       ('same_script_budget',t.test_same_script_media_failure_budget_is_preserved_before_paid_dispatch)]:
    folder=probe/label;folder.mkdir()
    function(folder)
    cases[label]={'assertions_passed':True,'directory':str(folder.relative_to(ROOT)).replace(chr(92),'/')}
folder=probe/'browser_publish';folder.mkdir()
with MonkeyPatch.context() as patch:
    t.test_delivery_uses_actual_browser_workflow_lock_and_independent_verification(folder,patch,False)
cases['browser_publish']={'assertions_passed':True,'real_publish':False,'browser_page':'fixture; existing PublishWorkflow executed'}
run=probe/'field_dependency/run'
compared=CreativeStageCommandService(run).compare('director_brief')
cost=quality_report(run)
workbench_cli([str(probe/'media_chain/media_run'),'inspect-media'])
summary={
  'schema':'creative_v22_execution_probe/v1','cases':cases,
  'network_blocked':True,'paid_calls':0,'media_content_review_performed':False,
  'human_decisions':'explicitly marked test fixtures only; no real user approval claimed',
  'ffmpeg':'injected fixture runner; native-audio argument wiring checked; no real film quality claim',
  'stop_resume':t.read(probe/'stop_resume/run/state.json'),
  'field_compare':{k:compared[k] for k in ('base_sha256','target_sha256','base_input_sha256','target_input_sha256','output_identical','input_snapshots_available','input_diff')},
  'quality':cost,
  'budget':t.read(probe/'same_script_budget/media_run/.creative_debug/media/submissions/budget.json'),
  'budget_rejected_before_provider':t.read(probe/'same_script_budget/media_run/second/receipt.json'),
  'unknown_original':t.read(probe/'unknown_dispatch/media_run/unknown-original/receipt.json'),
  'changed_directory_blocked':t.read(probe/'unknown_dispatch/media_run/renamed-output/receipt.json'),
  'files':[{'path':str(p.relative_to(OUT)).replace(chr(92),'/'),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
           for p in sorted(probe.rglob('*')) if p.is_file()]
}
(OUT/'execution_chain_probe.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'probe_cases':len(cases),'files':len(summary['files']),'paid_calls':0,'quality_improvement_verified':False}))
