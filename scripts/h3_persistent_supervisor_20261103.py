"""Persistent local supervisor. GET-only inspection; frozen runner owns generation."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import psutil

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=Path(__file__).resolve()
PYTHON=ROOT/'.venv/Scripts/python.exe'
MEDIA=ROOT/'data/video_generation/h3_six_children_full_script_20261102'
HOME=ROOT/'data/h3_supervision/full_script_20261103'
CONFIG=HOME/'SUPERVISOR_PLAN.json'
TERMINAL={'complete','paused','blocked','configuration_changed','restart_exhausted'}
class LockBusyError(RuntimeError):pass


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def bind(path):return dict(path=str(Path(path).resolve()),sha256=sha(path))
def stamp():return datetime.now(timezone.utc).isoformat()
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


@contextmanager
def lock(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as f:
        if not f.tell():f.write(b'1');f.flush()
        f.seek(0)
        try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as error:raise LockBusyError(str(error)) from error
        try:yield
        finally:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)


def event(home,kind,**fields):
    record=dict(at=stamp(),event=kind);record.update(fields)
    with (home/'EVENTS.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps(record,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())


def identity(process):
    return dict(pid=process.pid,create_time=process.create_time(),ppid=process.ppid(),cmdline=process.cmdline(),cwd=process.cwd())


def same_identity(saved,current):
    return saved.get('pid')==current.get('pid') and abs(saved.get('create_time',0)-current.get('create_time',-10))<.01 and saved.get('cmdline')==current.get('cmdline')


def exact_script_process(row,script,arguments):
    command=row.get('cmdline',[])
    if len(command)<2:return False
    position=next((i for i,arg in enumerate(command[1:],1) if not arg.startswith('-')),None)
    if position is None:return False
    path=Path(command[position]);path=path if path.is_absolute() else Path(row.get('cwd',''))/path
    return path.resolve()==Path(script).resolve() and command[position+1:]==arguments


def family_groups(rows):
    by_pid={r['pid']:r for r in rows};groups={}
    for row in rows:
        root=row;visited=set()
        while root['ppid'] in by_pid and root['pid'] not in visited:
            visited.add(root['pid']);root=by_pid[root['ppid']]
        groups.setdefault(root['pid'],[]).append(row)
    return list(groups.values())


def process_rows(script,args):
    rows=[]
    for process in psutil.process_iter(['name']):
        if 'python' not in (process.info['name'] or '').lower():continue
        try:
            row=identity(process)
            if exact_script_process(row,script,args):rows.append(row)
        except (psutil.NoSuchProcess,psutil.AccessDenied):continue
    return rows


def live_identity(row):
    if not row:return False
    try:return same_identity(row,identity(psutil.Process(row['pid'])))
    except (psutil.NoSuchProcess,psutil.AccessDenied):return False


def assert_config(config_path,review=True):
    config=read(config_path)
    for item in config['bindings']:
        if sha(item['path'])!=item['sha256']:raise ValueError('frozen_configuration_changed:'+item['path'])
    if review:
        approval=read(Path(config_path).parent/'PRIMARY_REVIEW.json')
        if approval.get('approved') is not True or approval.get('config_sha256')!=sha(config_path):raise ValueError('supervisor_review_required')
    return config


class LocalService:
    def __init__(self,url):self.url=url;self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(self,path):
        with self.opener.open(self.url+path,timeout=15) as response:return json.load(response)


def queue_ids(queue):
    return {row[1] for key in ('queue_running','queue_pending') for row in queue.get(key,[]) if isinstance(row,list) and len(row)>1}


def recovery_decision(config,service):
    run=Path(config['media_run'])
    if (Path(config['home'])/'PAUSE.json').exists():return dict(action='stop',status='paused',reason='manual_pause')
    state=read(run/'STATE.json')
    if state.get('status') in ('paused','cancelled'):return dict(action='stop',status='paused',reason='runner_paused')
    if state.get('status')=='saved':
        receipt=read(run/'receipt.json');item=receipt['delivery']
        if sha(item['path'])!=item['sha256']:return dict(action='stop',status='blocked',reason='completed_delivery_hash_mismatch')
        return dict(action='stop',status='complete',reason='verified_delivery_saved')
    plan=read(run/'PLAN.json')
    # Find actual first unfinished item; root STATE may lag a saved segment.
    unfinished=None
    for item in plan['segments']:
        folder=run/item['id'];local=read(folder/'STATE.json')
        if local.get('status')!='saved':unfinished=(item,folder,local);break
        receipt=read(folder/'receipt.json')
        if receipt.get('technical_status')!='succeeded' or receipt.get('prompt_id')!=local.get('prompt_id'):
            return dict(action='stop',status='blocked',reason='saved_segment_receipt_identity_mismatch',segment=item['id'])
        for binding in [receipt['delivery'],*receipt['files'].values()]:
            if sha(binding['path'])!=binding['sha256']:return dict(action='stop',status='blocked',reason='saved_segment_hash_mismatch',segment=item['id'])
    if unfinished:
        item,folder,local=unfinished;segment=item['id']
        if local.get('status') in ('failed','request_rejected','cancelled'):
            return dict(action='stop',status='blocked',reason='known_segment_failure',segment=segment)
        prompt_id=local.get('prompt_id')
        if not prompt_id and (folder/'SUBMISSION_RESPONSE.json').exists():
            response=read(folder/'SUBMISSION_RESPONSE.json')
            if response.get('prompt_id') and not response.get('node_errors'):prompt_id=response['prompt_id']
        if not prompt_id and (folder/'SUBMISSION_CLAIM.json').exists():
            return dict(action='stop',status='blocked',reason='unknown_claim_without_id',segment=segment)
        validation=folder/'VALIDATION_PROCESS.json'
        if not prompt_id and validation.exists() and read(validation).get('status') in ('failed','timeout','running'):
            return dict(action='stop',status='blocked',reason='validator_not_known_complete',segment=segment)
    else:segment='assembly';prompt_id=None;folder=None
    stats=service.get('/system_stats');argv=stats['system']['argv']
    if '--offline' not in argv or '--disable-all-custom-nodes' not in argv:
        return dict(action='stop',status='blocked',reason='service_mode_changed')
    for flag,name in [('--input-directory','input'),('--output-directory','output')]:
        if flag not in argv or Path(argv[argv.index(flag)+1]).resolve()!=(Path(config['service_root'])/name).resolve():
            return dict(action='stop',status='blocked',reason='service_identity_changed')
    queue=service.get('/queue');ids=queue_ids(queue)
    if prompt_id:
        history=service.get('/history/'+prompt_id);entry=history.get(prompt_id)
        if entry:
            if entry['prompt'][1]!=prompt_id or entry['prompt'][2]!=read(folder/'workflow_api.json'):
                return dict(action='stop',status='blocked',reason='history_identity_mismatch',segment=segment,prompt_id=prompt_id)
            status=entry['status']
            if status.get('status_str')=='error':return dict(action='stop',status='blocked',reason='known_native_failure',segment=segment,prompt_id=prompt_id)
            if status.get('completed') and status.get('status_str')=='success':
                if ids:return dict(action='wait',status='waiting_gpu',reason='other_queue_busy_after_known_success',segment=segment,prompt_id=prompt_id)
                return dict(action='launch',status='recovering',reason='known_success_collect_original',segment=segment,prompt_id=prompt_id)
        if prompt_id in ids:return dict(action='launch',status='recovering',reason='known_id_running_or_queued',segment=segment,prompt_id=prompt_id)
        return dict(action='stop',status='blocked',reason='known_id_missing_history_and_queue',segment=segment,prompt_id=prompt_id)
    if ids:return dict(action='wait',status='waiting_gpu',reason='queue_busy_no_new_submission',segment=segment)
    return dict(action='launch',status='recovering',reason='unsubmitted_next_or_assembly',segment=segment)


def detached_flags():return getattr(subprocess,'DETACHED_PROCESS',0)|getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0)|getattr(subprocess,'CREATE_NO_WINDOW',0)


def spawn_detached(command,home,label,cwd):
    home.mkdir(parents=True,exist_ok=True)
    with (home/(label+'.stdout.log')).open('ab',buffering=0) as out,(home/(label+'.stderr.log')).open('ab',buffering=0) as err:
        process=subprocess.Popen(command,cwd=cwd,stdin=subprocess.DEVNULL,stdout=out,stderr=err,close_fds=True,creationflags=detached_flags())
    return identity(psutil.Process(process.pid))


def runner_wrapper(config_path,attempt):
    config=assert_config(config_path);folder=Path(config['home'])/'attempts'/attempt;folder.mkdir(parents=True,exist_ok=True)
    command=[config['python'],'-B','-u',config['runner_script'],'execute']
    with (folder/'stdout.log').open('ab',buffering=0) as out,(folder/'stderr.log').open('ab',buffering=0) as err:
        try:
            env=os.environ.copy();env.update(PYTHONUNBUFFERED='1',PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1')
            process=subprocess.Popen(command,cwd=config['workspace'],stdin=subprocess.DEVNULL,stdout=out,stderr=err,env=env,
                                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            save(folder/'PROCESS.json',dict(at=stamp(),command=command,identity=identity(psutil.Process(process.pid))))
            code=process.wait();save(folder/'EXIT.json',dict(at=stamp(),returncode=code,command=command))
            return code
        except Exception as error:
            save(folder/'LAUNCH_ERROR.json',dict(at=stamp(),type=type(error).__name__,error=str(error)));raise


def supervise(config_path,once=False):
    home=Path(config_path).parent;home.mkdir(parents=True,exist_ok=True)
    try:
        with lock(home/'.supervisor.lock'):
            old=read(home/'STATE.json') if (home/'STATE.json').exists() else {}
            if old.get('status') in TERMINAL:return
            try:config=assert_config(config_path)
            except ValueError as error:
                save(home/'STATE.json',dict(status='configuration_changed',reason=str(error),heartbeat_at=stamp(),heartbeat_epoch=time.time()))
                event(home,'configuration_changed',error=str(error));return
            own=identity(psutil.Process());state=dict(old,supervisor=own,started_at=stamp(),status='starting')
            service=LocalService(config['service_url']);last_event=None
            while True:
                try:assert_config(config_path)
                except Exception as error:
                    state.update(status='configuration_changed',reason=str(error));event(home,'configuration_changed',error=str(error));break
                if (home/'PAUSE.json').exists():state.update(status='paused',reason='manual_pause');break
                families=family_groups(process_rows(config['runner_script'],['execute']))
                state.update(heartbeat_at=stamp(),heartbeat_epoch=time.time(),runner_families=families)
                if len(families)>1:state.update(status='blocked',reason='multiple_independent_runner_families');break
                if families:
                    family=families[0]
                    tracked=state.get('runner_identity',[])
                    if tracked and not any(same_identity(a,z) for a in tracked for z in family):
                        event(home,'new_exact_runner_family',previous=tracked,current=family)
                    state.update(status='monitoring',reason='exact_runner_family_alive',runner_identity=family,next_retry_epoch=None,network_failures=0)
                    state.setdefault('adopted_output_availability','existing runner stdout/stderr and exit code unavailable before adoption')
                else:
                    if state.get('runner_identity'):
                        event(home,'runner_family_gone',previous=state['runner_identity'],returncode='unavailable_for_adopted_process')
                    state['runner_identity']=[]
                    if live_identity(state.get('wrapper_identity')):
                        state.update(status='starting',reason='owned_wrapper_alive_wait_for_runner_or_exit')
                        decision=dict(action='wait')
                    elif time.time()<(state.get('next_retry_epoch') or 0):decision=dict(action='wait')
                    else:
                        if state.get('attempt') and state.get('reported_exit_attempt')!=state['attempt']:
                            exit_path=home/'attempts'/state['attempt']/'EXIT.json'
                            result=read(exit_path) if exit_path.exists() else dict(returncode=None,note='wrapper_exit_receipt_unavailable')
                            event(home,'owned_runner_exit',attempt=state['attempt'],result=result);state['reported_exit_attempt']=state['attempt']
                        try:
                            decision=recovery_decision(config,service);state['network_failures']=0
                        except (OSError,TimeoutError,ValueError,KeyError,json.JSONDecodeError) as error:
                            failures=state.get('network_failures',0)+1
                            state.update(status='backoff',reason='service_or_evidence_read_failed',last_error=type(error).__name__+': '+str(error),
                                         network_failures=failures,next_retry_epoch=time.time()+min(300,15*2**min(failures-1,5)))
                            decision=dict(action='wait')
                    if decision['action']=='stop':state.update(decision);break
                    if decision['action']=='wait' and 'status' in decision:state.update(decision)
                    if decision['action']=='launch':
                        progress=(decision.get('segment'),decision.get('prompt_id'))
                        if state.get('progress')!=list(progress):state.update(progress=list(progress),restart_count=0)
                        if state.get('restart_count',0)>=config['max_restarts_without_progress']:
                            state.update(status='restart_exhausted',reason='bounded_restarts_without_progress',decision=decision);break
                        if time.time()>=state.get('next_launch_epoch',0):
                            attempt=uuid.uuid4().hex
                            command=[config['python'],'-B',str(SCRIPT),'runner-wrapper','--config',str(Path(config_path).resolve()),'--attempt',attempt]
                            state.update(restart_count=state.get('restart_count',0)+1,next_launch_epoch=time.time()+config['restart_cooldown_seconds'])
                            try:
                                row=spawn_detached(command,home/'attempts'/attempt,'wrapper',config['workspace'])
                                state.update(decision,attempt=attempt,wrapper_identity=row)
                                event(home,'recovery_wrapper_started',attempt=attempt,identity=row,decision=decision)
                            except Exception as error:
                                state.update(status='backoff',reason='launch_failed',last_error=str(error));event(home,'launch_failed',error=str(error))
                        else:state.update(status='backoff',reason='recovery_cooldown')
                signature=(state.get('status'),state.get('reason'))
                if signature!=last_event:event(home,'state_change',status=signature[0],reason=signature[1]);last_event=signature
                save(home/'STATE.json',state)
                if once:return
                time.sleep(min(30,max(1,config['poll_seconds'])))
            state.update(heartbeat_at=stamp(),heartbeat_epoch=time.time(),stopped_at=stamp())
            save(home/'STATE.json',state);event(home,'supervisor_stopped',status=state['status'],reason=state.get('reason'))
    except LockBusyError as error:
        # An existing exclusive supervisor owns the file; do not start a second.
        event(home,'supervisor_lock_not_acquired',error=str(error))
    except Exception as error:
        fatal=dict(at=stamp(),type=type(error).__name__,error=str(error),pid=os.getpid())
        save(home/'FATAL.json',fatal)
        save(home/'STATE.json',dict(status='crashed',reason='supervisor_exception',last_error=fatal,heartbeat_epoch=time.time(),heartbeat_at=stamp()))
        event(home,'supervisor_exception',**fatal)
        raise


def ensure(config_path):
    home=Path(config_path).parent;home.mkdir(parents=True,exist_ok=True)
    with lock(home/'.ensure.lock'):
        config=assert_config(config_path)
        if (home/'PAUSE.json').exists():return 'paused'
        if (home/'STATE.json').exists() and read(home/'STATE.json').get('status') in TERMINAL:return 'terminal'
        args=['supervise','--config',str(Path(config_path).resolve())]
        rows=process_rows(SCRIPT,args)
        if rows:return 'alive'
        command=[config['python'],'-B',str(SCRIPT),*args]
        row=spawn_detached(command,home,'supervisor',config['workspace']);event(home,'supervisor_started',identity=row)
        return 'started'


def task_xml(config):
    ns='http://schemas.microsoft.com/windows/2004/02/mit/task';ET.register_namespace('',ns)
    def node(parent,name,text=None,**attrs):
        value=ET.SubElement(parent,'{'+ns+'}'+name,attrs);value.text=text;return value
    task=ET.Element('{'+ns+'}Task',version='1.2');triggers=node(task,'Triggers')
    login=node(triggers,'LogonTrigger');node(login,'Enabled','true');node(login,'UserId',config['user'])
    timed=node(triggers,'TimeTrigger');repetition=node(timed,'Repetition');node(repetition,'Interval','PT1M');node(repetition,'StopAtDurationEnd','false')
    node(timed,'StartBoundary',datetime.now().astimezone().replace(microsecond=0).isoformat());node(timed,'Enabled','true')
    principals=node(task,'Principals');principal=node(principals,'Principal',id='Author');node(principal,'UserId',config['user']);node(principal,'LogonType','InteractiveToken');node(principal,'RunLevel','LeastPrivilege')
    settings=node(task,'Settings');node(settings,'MultipleInstancesPolicy','IgnoreNew');node(settings,'DisallowStartIfOnBatteries','false');node(settings,'StopIfGoingOnBatteries','false');node(settings,'StartWhenAvailable','true');node(settings,'Hidden','true');node(settings,'ExecutionTimeLimit','PT0S');node(settings,'Enabled','true')
    actions=node(task,'Actions',Context='Author');command=node(actions,'Exec')
    node(command,'Command',config['ensure_python']);node(command,'Arguments',f'-B "{SCRIPT}" supervise --config "{config["config_path"]}"');node(command,'WorkingDirectory',config['workspace'])
    return ET.tostring(task,encoding='unicode',xml_declaration=True)


def install_script(config):
    def quote(value):return "'"+str(value).replace("'","''")+"'"
    return "\n".join([
      "$ErrorActionPreference = 'Stop'",
      '$taskName = '+quote(config['task_name']),
      '$taskXmlPath = '+quote(Path(config['home'])/'TASK.xml'),
      '$expectedCommand = '+quote(config['ensure_python']),
      '$expectedArguments = '+quote(f'-B "{SCRIPT}" supervise --config "{config["config_path"]}"'),
      '$expectedWorkingDirectory = '+quote(config['workspace']),
      '$expectedUser = '+quote(config['user']),
      'function UserSid($name) { if ($name -match "^S-1-") { return $name }; return ([System.Security.Principal.NTAccount]::new($name)).Translate([System.Security.Principal.SecurityIdentifier]).Value }',
      'function Assert-OwnedTask($task) {',
      '  $actions = @($task.Actions)',
      '  if ($actions.Count -ne 1 -or $actions[0].Execute -ne $expectedCommand -or $actions[0].Arguments -ne $expectedArguments -or $actions[0].WorkingDirectory -ne $expectedWorkingDirectory -or (UserSid $task.Principal.UserId) -ne (UserSid $expectedUser)) { throw "Existing task identity conflicts; preserved without overwrite." }',
      '  [xml]$actualXml = Export-ScheduledTask -TaskName $taskName',
      '  if ($actualXml.Task.Principals.Principal.LogonType -ne "InteractiveToken" -or $actualXml.Task.Triggers.TimeTrigger.Repetition.Interval -ne "PT1M" -or $null -eq $actualXml.Task.Triggers.LogonTrigger -or $actualXml.Task.Settings.ExecutionTimeLimit -ne "PT0S" -or $actualXml.Task.Settings.MultipleInstancesPolicy -ne "IgnoreNew") { throw "Existing task trigger/principal conflicts; preserved without overwrite." }',
      '}',
      '$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue',
      'if ($null -ne $existing) { Assert-OwnedTask $existing } else {',
      '  Register-ScheduledTask -TaskName $taskName -Xml (Get-Content -LiteralPath $taskXmlPath -Raw -Encoding UTF8) | Out-Null',
      '}',
      '$after = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop',
      'Assert-OwnedTask $after',
      '@{verified_at=(Get-Date).ToString("o"); task=$taskName; command=$after.Actions[0].Execute; arguments=$after.Actions[0].Arguments; working_directory=$after.Actions[0].WorkingDirectory; user=$after.Principal.UserId} | ConvertTo-Json | Set-Content -LiteralPath '+quote(Path(config['home'])/'TASK_DEPLOYMENT_VERIFIED.json')+' -Encoding UTF8',
      '' ])


def prepare(config_path=CONFIG):
    home=Path(config_path).parent;home.mkdir(parents=True,exist_ok=True)
    if Path(config_path).exists():raise ValueError('already_prepared')
    manifest=read(MEDIA/'PLAN.json');bindings=[bind(SCRIPT),bind(MEDIA/'PLAN.json'),bind(MEDIA/'PRIMARY_DISPATCH_REVIEW.json')]
    for value in manifest.values():
        if isinstance(value,dict) and 'sha256' in value:bindings.append(value)
    for item in manifest['segments']:bindings.extend([item['graph'],item['prompt']])
    config=dict(schema='h3_supervisor/v1',home=str(home.resolve()),config_path=str(Path(config_path).resolve()),media_run=str(MEDIA),
      service_root=str(ROOT/'data/video_generation/h3_six_children_s01_720p_20261102'),service_url='http://127.0.0.1:8190',
      runner_script=str(ROOT/'scripts/run_h3_full_script_20261102.py'),workspace=str(ROOT),python=str(PYTHON),ensure_python=str(PYTHON.with_name('pythonw.exe')),bindings=bindings,
      poll_seconds=30,max_restarts_without_progress=3,restart_cooldown_seconds=300,task_mode='direct_supervise_ignore_new_no_time_limit',
      user=os.environ.get('USERDOMAIN','')+'\\'+os.environ.get('USERNAME',''),task_name='AI_Douyin_H3_FullScript_Ensure')
    save(config_path,config)
    (home/'TASK.xml').write_text(task_xml(config),encoding='utf-8')
    (home/'INSTALL.ps1').write_text(install_script(config),encoding='utf-8')
    return config


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['prepare','ensure','supervise','runner-wrapper']);parser.add_argument('--config',type=Path,default=CONFIG);parser.add_argument('--attempt');parser.add_argument('--once',action='store_true');args=parser.parse_args()
    if args.command=='runner-wrapper':raise SystemExit(runner_wrapper(args.config,args.attempt))
    elif args.command=='supervise':supervise(args.config,args.once)
    else:print(globals()[args.command](args.config))
