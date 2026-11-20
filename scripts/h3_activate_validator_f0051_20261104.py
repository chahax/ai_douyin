"""Stage and activate the approved, independently successful F0051 CPU validation."""
import argparse
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import h3_recover_validator_f0051_20261104 as v
from h3_recover_validator_f0051_20261104 import r, CASE, RUN, TARGET

SCRIPT=Path(__file__).resolve()
BOOTSTRAP=SCRIPT.with_name('h3_supervise_pure_sqlalchemy_20261104.py')
CONFIG=CASE/'RECOVERY_PLAN.json'
STAGE=CASE/'replacement'/'F0051'
ARCHIVE=CASE/'failed_original'/'F0051'
NAMES=('workflow_api.json','PROMPT.txt','STATE.json','FROZEN_INPUT.json')


def tree(path):
    return {p.relative_to(path).as_posix():r.h.sha(p) if p.is_file() else 'directory' for p in sorted(path.rglob('*'))}


def prepare():
    r.require(not CONFIG.exists(),'already_prepared')
    before=r.h.read(CASE/'BEFORE.json')
    r.require(v.inspect()==before,'blocked_scope_changed')
    retry=r.h.read(CASE/'RETRY_RESULT.json')
    for key in ('before','validator_process','validator_report'):
        r.b.bound_ok(retry[key])
    v.verify_report(CASE/'NATIVE_VALIDATION.json',r.h.sha(TARGET/'workflow_api.json'))
    proc=r.h.read(CASE/'VALIDATION_PROCESS.json')
    r.require(proc['status']=='completed' and proc['returncode']==0 and proc['override']=={v.FLAG:'1'},'unsuccessful_retry')
    for n in NAMES:
        r.h.original_copy(TARGET/n,STAGE/n)
    for n in ('NATIVE_VALIDATION.json','VALIDATION_PROCESS.json'):
        r.h.original_copy(CASE/n,STAGE/n)
    r.freeze(STAGE/'VALIDATION_COMMAND.json',proc['command'])
    r.freeze(STAGE/'RECOVERY_PROVENANCE.json',dict(before=r.h.binding(CASE/'BEFORE.json'),result=r.h.binding(CASE/'RETRY_RESULT.json'),
             failed_archive=str(ARCHIVE),original_returncode=v.CODE,validation_logs=[proc['stdout'],proc['stderr']]))
    (STAGE/'deliverables').mkdir(exist_ok=True)
    xml=ET.parse(RUN/'TASK.xml')
    xml.find('.//{*}Arguments').text=f'-B "{BOOTSTRAP}" supervise --run "{RUN}"'
    task=CASE/'TASK.xml'
    task.write_text(ET.tostring(xml.getroot(),encoding='unicode'),encoding='utf8')
    source=r.h.read(RUN/'PLAN.json')
    cfg=dict(task_name='AI_Douyin_H3_FullScript_PureSQL',user=source['user'],bindings=[r.h.binding(p) for p in [
        SCRIPT,BOOTSTRAP,Path(v.__file__),CASE/'INTERRUPTED_ATTEMPT.json',CASE/'BEFORE.json',CASE/'RETRY_RESULT.json',CASE/'VALIDATION_PROCESS.json',
        CASE/'NATIVE_VALIDATION.json',CASE/'validation.stdout.log',CASE/'validation.stderr.log',RUN/'PLAN.json',RUN/'PRIMARY_REVIEW.json',
        r.SCRIPT,r.monitor.SCRIPT,r.guard.INSTALL,task]],old_tree=tree(TARGET),new_tree=tree(STAGE),old_state=before['block'])
    r.freeze(CONFIG,cfg)
    print(r.h.sha(CONFIG),flush=True)


def check_idle():
    command=['powershell.exe','-NoProfile','-NonInteractive','-Command',
             "$ErrorActionPreference='Stop'; (Get-ScheduledTask -TaskName 'AI_Douyin_H3_FullScript_Continuation').State.ToString()"]
    state=subprocess.run(command,capture_output=True,text=True,timeout=30,check=True).stdout.strip()
    r.require(state=='Disabled','previous_scheduler_not_disabled')
    r.require(not r.monitor.process_rows(r.SCRIPT,r.runner_arguments(RUN)) and not r.monitor.process_rows(r.SCRIPT,['supervise','--run',str(RUN)]),'original_runner_or_monitor_alive')
    r.generation()
    r.require(not r.queue_rows(r.h.Client().get('/queue')),'busy_gpu')


def apply():
    cfg=r.monitor.assert_config(CONFIG)
    with r.monitor.lock(RUN/'supervision/.monitor.lock'),r.h.process_lock(RUN/'.execute.lock'),r.h.process_lock(r.OLD/'.full_script.lock'):
        r.require(not (CASE/'APPLIED.json').exists() and not (RUN/'PAUSE.json').exists(), 'already_applied_or_manual_pause')
        check_idle()
        before=cfg['old_state']
        after=dict(before,status='prepared')
        after.pop('error')
        state=r.h.read(RUN/'STATE.json')
        r.require(state==before or (state==after and (CASE/'APPLY_INTENT.json').exists() and ARCHIVE.exists()),'different_block')
        if not ARCHIVE.exists():
            r.require(v.inspect()==r.h.read(CASE/'BEFORE.json') and tree(TARGET)==cfg['old_tree'],'failed_generation_changed')
            r.require(tree(STAGE)==cfg['new_tree'],'new_generation_changed')
            r.freeze(CASE/'APPLY_INTENT.json',dict(before=before,after=after,config=r.h.binding(CONFIG),new_validation=r.h.binding(CASE/'RETRY_RESULT.json')))
            ARCHIVE.parent.mkdir(parents=True,exist_ok=True)
            TARGET.rename(ARCHIVE)
        r.require(tree(ARCHIVE)==cfg['old_tree'],'failed_archive_changed')
        if not TARGET.exists():
            r.require(tree(STAGE)==cfg['new_tree'],'new_generation_changed')
            STAGE.rename(TARGET)
        r.require(tree(TARGET)==cfg['new_tree'],'active_generation_changed')
        r.b.validate_frozen(TARGET)
        v.verify_report(TARGET/'NATIVE_VALIDATION.json',r.h.sha(TARGET/'workflow_api.json'))
        # Reads the completed independent validator and report using the actual frozen consumer.
        r.validate_native(TARGET)
        r.monitor.save(RUN/'STATE.json',after)
        r.freeze(CASE/'APPLIED.json',dict(at=r.h.now(),archive=str(ARCHIVE),new_active=str(TARGET),config=r.h.binding(CONFIG),previous_error=before['error'],media_submissions=0))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['prepare','apply'])
    globals()[parser.parse_args().mode]()

