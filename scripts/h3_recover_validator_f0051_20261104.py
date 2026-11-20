"""One audited CPU-only validation after a pre-dispatch access violation."""
import argparse
import os
from pathlib import Path
import subprocess
import time

import h3_restart_continuation_20261104 as r

RUN=r.RUN
TARGET=RUN/'A0/F0051'
INTERRUPTED=RUN/'validator_recovery/F0051_access_violation'
CASE=RUN/'validator_recovery/F0051_access_violation_resume'
CODE=0xC0000005
FILES=('workflow_api.json','PROMPT.txt','STATE.json','FROZEN_INPUT.json','VALIDATION_PROCESS.json','VALIDATION_COMMAND.json',
       'validation.stderr.log','validation.stdout.log')
FLAG='DISABLE_SQLALCHEMY_CEXT_RUNTIME'


def eligible(run,folder):
    state=r.h.read(run/'STATE.json')
    attempt=r.h.read(folder/'VALIDATION_PROCESS.json')
    command=r.h.read(folder/'VALIDATION_COMMAND.json')
    error=str(subprocess.CalledProcessError(CODE,command))
    r.require(state.get('status')=='blocked' and state.get('active_segment')=='F0051' and state.get('completed')==50
              and state.get('error')==error and not (run/'PAUSE.json').exists(),'different_block_or_paused')
    r.require(attempt.get('status')=='failed' and attempt.get('returncode')==CODE and attempt.get('command')==command,
              'wrong_failed_validation')
    r.require(r.h.read(folder/'STATE.json')==dict(status='prepared',prompt_id=None,submissions=0),'not_pre_submit')
    forbidden=('SUBMISSION_CLAIM.json','SUBMISSION_RESPONSE.json','REQUEST.actual.json','job_ids.txt','receipt.json','NATIVE_VALIDATION.json')
    r.require(not any((folder/name).exists() for name in forbidden) and not (run/'A1/F0051').exists(),'possible_prior_submission')
    return state


def inspect():
    plan=r.check_scope(RUN)
    state=eligible(RUN,TARGET)
    item=next(s for s in plan['segments'] if s['id']=='F0051')
    r.require(r.output_graph(item,0)==r.h.read(TARGET/'workflow_api.json'),'workflow_differs')
    r.b.bound_ok(item['prompt'])
    r.require(r.h.sha(TARGET/'PROMPT.txt')==item['prompt']['sha256'],'prompt_differs')
    r.b.validate_frozen(TARGET)
    r.source_receipt(RUN/'A0/F0050')
    r.require(not r.inventory(TARGET,r.h.read(TARGET/'workflow_api.json'))[0],'original_outputs_exist')
    return dict(block=state,inputs=r.h.read(TARGET/'FROZEN_INPUT.json'),files={n:r.h.binding(TARGET/n) for n in FILES},
                original_plan=r.h.binding(RUN/'PLAN.json'),runner=r.h.binding(r.SCRIPT))


def verify_report(report,expected):
    result=r.h.read(report)
    r.require(result.get('valid') is True and result.get('node_errors')=={} and result.get('node_execution_performed') is False
              and result.get('graph_sha256')==expected,'invalid_cpu_report')


def retry():
    before=inspect()
    prior=r.h.read(INTERRUPTED/'VALIDATION_PROCESS.json')
    r.require(not r.psutil.pid_exists(prior['pid']) and not (INTERRUPTED/'NATIVE_VALIDATION.json').exists() and not (INTERRUPTED/'RETRY_RESULT.json').exists(), 'prior_validator_still_live_or_result_exists')
    CASE.mkdir(parents=True,exist_ok=True)
    with (CASE/'RETRY_CLAIM').open('x') as claim:
        claim.write(r.h.now())
        claim.flush()
        os.fsync(claim.fileno())
    r.freeze(CASE/'INTERRUPTED_ATTEMPT.json',dict(original=r.h.binding(INTERRUPTED/'VALIDATION_PROCESS.json'),stderr=r.h.binding(INTERRUPTED/'validation.stderr.log'),result='no_report_returncode_unavailable',media_submissions=0))
    r.freeze(CASE/'BEFORE.json',before)
    old=r.h.read(TARGET/'VALIDATION_PROCESS.json')
    command=list(old['command'])
    expected=[str(r.b.PYTHON),'-B','-u',str(r.OLD/'native_validation_traced.py'),'--graph',str(TARGET/'workflow_api.json'),
              '--report',str(TARGET/'NATIVE_VALIDATION.json'),'--input-root',str(r.b.SERVICE/'input')]
    r.require(command==expected and Path(old['cwd']).resolve()==r.full.c.COMFY.resolve(),'unexpected_validator')
    command[command.index('--report')+1]=str(CASE/'NATIVE_VALIDATION.json')
    cache=r.h.read(r.b.SERVICE/'SERVER_STARTED.json')['cache_env']
    r.require(old['cache_env']==cache,'unexpected_cache')
    env=os.environ.copy()
    env.update(cache)
    env.update(r.guard.FLAGS, PYTHONUNBUFFERED='1')
    env[FLAG]='1'
    with (CASE/'validation.stdout.log').open('xb') as out, (CASE/'validation.stderr.log').open('xb') as err:
        proc=subprocess.Popen(command,cwd=old['cwd'],env=env,stdout=out,stderr=err,stdin=subprocess.DEVNULL,creationflags=r.guard.NO_WINDOW)
        attempt=dict(at=r.h.now(),pid=proc.pid,command=command,cwd=old['cwd'],cache_env=cache,override={FLAG:'1'},
                     status='running',stdout=out.name,stderr=err.name)
        file=CASE/'VALIDATION_PROCESS.json'
        r.monitor.save(file,attempt)
        try:
            code=proc.wait(timeout=900)
        except subprocess.TimeoutExpired:
            r.full.c.terminate_own_validator(proc,Path(command[3]))
            r.monitor.save(file,dict(attempt,status='timeout',returncode=proc.returncode))
            raise
    r.monitor.save(file,dict(attempt,status='completed' if code==0 else 'failed',returncode=code))
    if code:
        raise subprocess.CalledProcessError(code,command)
    verify_report(CASE/'NATIVE_VALIDATION.json',r.h.sha(TARGET/'workflow_api.json'))
    r.require(inspect()==before,'failure_evidence_changed')
    r.freeze(CASE/'RETRY_RESULT.json',dict(at=r.h.now(),before=r.h.binding(CASE/'BEFORE.json'),
             validator_process=r.h.binding(file),validator_report=r.h.binding(CASE/'NATIVE_VALIDATION.json'),media_submissions=0))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['inspect','retry'])
    args=parser.parse_args()
    globals()[args.mode]()

