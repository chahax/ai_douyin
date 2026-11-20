"""Retire one exact backend for an authorized, restricted publication check.

The original outcome_unknown and submission lock remain unchanged. This script
never starts a service, registers a new upload, or resolves the publication.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import handoff_idle_browser_control as browser_proof
from src.operations_accounts.browser_control import BrowserControlStore, _json

AUTHORIZATION_SHA256 = '3933466384fa7d4a2a317d5d506acc7a373de19952202e4b17d8a32fa4227a6c'
RESUME_FAILURE_SHA256 = 'c88cc8fa4eb914e94cfe5212d9ef4ae47acc05f84fa148ed186571929d7b7a63'


def _read_reference(reference):
    if not isinstance(reference, dict) or set(reference) != {'path','sha256'}:
        raise RuntimeError('Exact frozen project reference required')
    path = Path(reference['path']).resolve()
    if (not path.is_relative_to(ROOT) or not path.is_file()
            or not re.fullmatch('[0-9a-f]{64}', reference.get('sha256') or '')):
        raise RuntimeError('Reference is not a frozen project file')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != reference['sha256']:
        raise RuntimeError('Frozen reconciliation evidence changed')
    return data


def read_authorization(path, sha256):
    source = Path(path).resolve()
    reference = {'path':str(source),'sha256':sha256}
    if sha256 != AUTHORIZATION_SHA256:
        raise RuntimeError('Only the exact original reconciliation authorization is allowed')
    value = json.loads(_read_reference(reference))
    expected = {'schema':'publication_reconciliation_repair_authorization/20261019/v1',
        'decision_source':'explicit_user_statement','deployment_authorized':True,
        'utc_day':datetime.now(timezone.utc).date().isoformat(),
        'baseline_daily_runs':33,'max_daily_runs':34,'additional_reconciliation_runs':1,
        'active_control_revision':42,'new_upload_authorized':False,'new_publish_click_authorized':False,
        'preserve_original_unknown_snapshot':True,'retain_submission_lock':True,
        'visible_managed_window_authorized':True,'verify_exact_work_before_comment':True,
        'comment_authorization_is_original_prepared':True,'comment_retry_authorized':False,
        'stop_on_human_required_or_unknown':True}
    if (not isinstance(value,dict) or any(type(value.get(k)) is not type(v) or value[k]!=v for k,v in expected.items())
            or value['utc_day']!='2026-10-19'
            or not all(isinstance(value.get(k),str) and value[k].strip() for k in
                ('account_uuid','account_key','original_command_id','original_owner_id','user_statement','preceding_user_confirmation'))
            or type(value.get('original_generation')) is not int or value['original_generation']<=0
            or type(value.get('original_backend_pid')) is not int or value['original_backend_pid']<=0
            or type(value.get('original_backend_create_time')) not in (float,int)
            or not value['original_owner_id'].startswith(f"backend:{value['original_backend_pid']}:")):
        raise RuntimeError('Reconciliation deployment authorization scope changed')
    original = json.loads(_read_reference(value['original_command']))
    if (not isinstance(original,dict) or original.get('command_id')!=value['original_command_id']
            or original.get('task_id')!=value['original_command_id'] or original.get('account_id')!=value['account_uuid']
            or original.get('kind')!='publish' or original.get('state')!='outcome_unknown'
            or original.get('owner_id')!=value['original_owner_id'] or original.get('generation')!=value['original_generation']):
        raise RuntimeError('Original unknown publication snapshot is not exact')
    for name in ('original_journal','original_submission_lock','prepared'):
        _read_reference(value[name])
    return value, reference, original


def exact_backend(authorization):
    process = psutil.Process(authorization['original_backend_pid'])
    expected_script = str(ROOT/'scripts/run_streamlit_web.py').lower()
    if (not process.is_running() or process.create_time()!=authorization['original_backend_create_time']
            or process.cwd().lower()!=str(ROOT).lower()
            or expected_script not in [s.lower() for s in process.cmdline()]
            or int((ROOT/'data/logs/streamlit_web.pid').read_text())!=process.pid):
        raise RuntimeError('Original backend identity changed; no stop permitted')
    return process


def check_idle(control, browser, authorization, original, profile):
    if not control.in_transaction or not browser.in_transaction:
        raise RuntimeError('Both original writer fences are required')
    owners = [dict(row) for row in browser.execute("SELECT * FROM browser_control_owners WHERE state!='released'")]
    if (len(owners)!=1 or owners[0]['owner_id']!=authorization['original_owner_id']
            or owners[0]['generation']!=authorization['original_generation']
            or owners[0]['account_id']!=authorization['account_uuid'] or owners[0]['state']!='active'
            or owners[0]['binding_version']!=original['binding_version']):
        raise RuntimeError('Original owner generation or binding changed')
    commands = [BrowserControlStore._command(row) for row in browser.execute('SELECT * FROM browser_control_commands')]
    matches = [row for row in commands if row['command_id']==authorization['original_command_id']]
    if len(matches)!=1 or matches[0]!=original:
        raise RuntimeError('Original complete unknown command snapshot changed')
    if any(row['command_id']!=authorization['original_command_id'] and row['state'] not in ('queued','succeeded','failed') for row in commands):
        raise RuntimeError('Another running, paused, unknown or protected command remains')
    rows = control.execute('SELECT account_uuid,account_key,state,revision FROM account_controls WHERE account_uuid=?',
                           (authorization['account_uuid'],)).fetchall()
    if len(rows)!=1 or tuple(rows[0])!=(authorization['account_uuid'],authorization['account_key'],'active',42):
        raise RuntimeError('Original active control changed')
    if control.execute("SELECT 1 FROM account_controls WHERE account_uuid<>? AND state!='paused' LIMIT 1",
                       (authorization['account_uuid'],)).fetchone():
        raise RuntimeError('Another account can dispatch')
    if control.execute("SELECT 1 FROM account_controls WHERE recovery_requested_at IS NOT NULL OR coalesce(recovery_lease_until,0)<>0 OR coalesce(recovery_token,'')<>'' LIMIT 1").fetchone():
        raise RuntimeError('Recovery is pending or unknown')
    for table in ('refresh_accounts','smart_accounts','playback_accounts'):
        if control.execute(f'SELECT 1 FROM {table} WHERE run_id IS NOT NULL OR coalesce(lease_until,0)<>0 LIMIT 1').fetchone():
            raise RuntimeError('Original scheduled run or lease remains')
    for table in ('refresh_runs','smart_runs','playback_runs'):
        if control.execute(f"SELECT 1 FROM {table} WHERE status IN ('running','starting','claimed','outcome_unknown') OR finished_at IS NULL LIMIT 1").fetchone():
            raise RuntimeError('Scheduled work is running or unknown')
    if control.execute("SELECT 1 FROM account_handling_requests WHERE status IN ('requested','probing') LIMIT 1").fetchone():
        raise RuntimeError('Original identity recovery remains')
    with sqlite3.connect((ROOT/'data/douyin.db').as_uri()+'?mode=ro',uri=True) as runtime:
        if runtime.execute("SELECT 1 FROM account_runtime_state WHERE coalesce(lock_owner,'')<>'' OR coalesce(lock_expires_at,'')<>'' LIMIT 1").fetchone():
            raise RuntimeError('Original runtime lease is present or unknown')
        states = runtime.execute('SELECT day_key,daily_runs FROM account_runtime_state WHERE account_uuid=?',
                                 (authorization['account_uuid'],)).fetchall()
        bindings = runtime.execute('SELECT browser_profile_dir FROM account_runtime_bindings WHERE account_uuid=?',
                                   (authorization['account_uuid'],)).fetchall()
    if len(states)!=1 or tuple(states[0])!=(authorization['utc_day'],33):
        raise RuntimeError('Original day or daily33 baseline changed')
    if len(bindings)!=1 or Path(bindings[0][0]).resolve()!=Path(profile).resolve():
        raise RuntimeError('Original account profile binding changed')
    manual_path=ROOT/'data/account_manual_windows.db'
    if manual_path.exists():
        with sqlite3.connect(manual_path.as_uri()+'?mode=ro',uri=True) as manual:
            if manual.execute("SELECT 1 FROM manual_window_jobs WHERE state NOT IN ('closed','failed') LIMIT 1").fetchone():
                raise RuntimeError('Legacy manual window remains active or unknown')
    return owners[0], hashlib.sha256(_json(original).encode('utf8')).hexdigest()


def exclusive_json(path, value):
    with path.open('x',encoding='utf8') as handle:
        handle.write(_json(value));handle.flush();os.fsync(handle.fileno())
    return {'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def preflight_chrome_readability():
    """Prove the final global profile scan is readable before stopping anyone."""
    for process in psutil.process_iter(['name']):
        if (process.info.get('name') or '').lower() != 'chrome.exe':
            continue
        try:
            process.cmdline()
        except psutil.NoSuchProcess:
            continue


def read_resume_failure(path, sha256, authorization, reference, original, worker):
    failure_ref={'path':str(Path(path).resolve()),'sha256':sha256}
    if sha256 != RESUME_FAILURE_SHA256:
        raise RuntimeError('Only the exact stopped reconciliation failure may resume')
    failure=json.loads(_read_reference(failure_ref))
    owner=failure.get('original_owner') or {}
    children=failure.get('observed_children')
    if (failure.get('schema')!='publication_reconciliation_handoff_run/20261019/v1'
            or failure.get('phase')!='stopped_without_handoff' or failure.get('error_type')!='AccessDenied'
            or failure.get('parent_exited') is not True or failure.get('termination_requested') is not True
            or failure.get('handoff_committed') is not False or failure.get('alive_child_ids')!=[]
            or failure.get('authorization')!=reference or failure.get('worker_source')!=worker
            or failure.get('original_command_id')!=original['command_id']
            or failure.get('expected_snapshot_sha256')!=hashlib.sha256(_json(original).encode()).hexdigest()
            or failure.get('browser_writer_fenced') is not True or failure.get('scheduler_writer_fenced') is not True
            or failure.get('original_unknown_preserved') is not True or failure.get('submission_lock_preserved') is not True
            or owner.get('owner_id')!=authorization['original_owner_id'] or owner.get('generation')!=authorization['original_generation']
            or owner.get('account_id')!=authorization['account_uuid'] or owner.get('binding_version')!=original['binding_version']
            or owner.get('state')!='active' or not isinstance(children,list) or not 4<=len(children)<=40):
        raise RuntimeError('Stopped reconciliation evidence does not bind the original handoff')
    if any(not isinstance(c,dict) or set(c)!={'pid','ppid','name','create_time'}
            or type(c['pid']) is not int or c['pid']<=0 or type(c['ppid']) is not int
            or c['name'] not in {'pythonw.exe','node.exe','conhost.exe','chrome.exe'}
            or type(c['create_time']) not in (float,int) or c['create_time']<authorization['original_backend_create_time'] for c in children):
        raise RuntimeError('Stopped child identity evidence is incomplete')
    ids=[c['pid'] for c in children]
    if len(set(ids))!=len(ids) or sorted(failure.get('gone_child_ids',[]))!=sorted(ids):
        raise RuntimeError('Original child retirement set is incomplete')
    check_original_processes_exited(authorization,children)
    return failure, failure_ref


def check_original_processes_exited(authorization, children):
    """Read exact old identities; a reused PID is never signalled or adopted."""
    identities=[(authorization['original_backend_pid'],authorization['original_backend_create_time'])]
    identities.extend((c['pid'],c['create_time']) for c in children)
    checks=[]
    for pid,expected_time in identities:
        item={'pid':pid,'expected_create_time':expected_time}
        try:
            current_time=psutil.Process(pid).create_time()
        except psutil.NoSuchProcess:
            item['status']='not_present'
        else:
            if type(current_time) not in (int,float) or not math.isfinite(current_time) or current_time<=0:
                raise RuntimeError('Original PID identity is unknown; no owner release')
            if current_time==expected_time:
                raise RuntimeError('An original process identity still exists; no owner release')
            item.update(status='pid_reused',current_create_time=current_time)
        checks.append(item)
    return checks


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--authorization-path',required=True)
    parser.add_argument('--authorization-sha256',required=True)
    parser.add_argument('--worker-source',required=True)
    parser.add_argument('--worker-script-sha256',required=True)
    parser.add_argument('--browser-profile',required=True)
    parser.add_argument('--evidence',required=True)
    parser.add_argument('--resume-failure-evidence')
    parser.add_argument('--resume-failure-sha256')
    args=parser.parse_args()
    if bool(args.resume_failure_evidence)!=bool(args.resume_failure_sha256):
        parser.error('Both resume-failure evidence path and SHA256 are required')
    authorization,reference,original=read_authorization(args.authorization_path,args.authorization_sha256)
    target=Path(args.evidence).resolve();retirement=target.with_name(target.stem+'.RETIREMENT.json')
    if not target.is_relative_to(ROOT) or target.exists() or retirement.exists():
        raise RuntimeError('Evidence and retirement must be new project files')
    target.parent.mkdir(parents=True,exist_ok=True)
    worker=browser_proof.worker_source_evidence(args.worker_source,args.worker_script_sha256)
    resumed=None;resumed_ref=None
    if args.resume_failure_evidence:
        resumed,resumed_ref=read_resume_failure(args.resume_failure_evidence,args.resume_failure_sha256,
            authorization,reference,original,worker)
    else:
        exact_backend(authorization)
    store=BrowserControlStore(ROOT/'data/account_browser_control.db')
    record={'schema':'publication_reconciliation_handoff_run/20261019/v1','phase':'checking',
        'authorization':reference,'original_command_id':authorization['original_command_id'],
        'worker_source':worker,'termination_requested':False,'parent_exited':False,
        'descendants_exited':False,'handoff_committed':False,'original_unknown_preserved':True,
        'submission_lock_preserved':True,'requested_at':datetime.now(timezone.utc).isoformat()}
    if resumed:
        record.update(resume_failure_evidence=resumed_ref,resumed_previous_exit=True,parent_exited=True)
    exclusive_json(target,record)
    try:
        with sqlite3.connect((ROOT/'data/account_refresh.db').as_uri()+'?mode=rw',uri=True,timeout=2) as control, \
             sqlite3.connect((ROOT/'data/account_browser_control.db').as_uri()+'?mode=rw',uri=True,timeout=2) as browser:
            control.execute('BEGIN IMMEDIATE');browser.execute('BEGIN IMMEDIATE');browser.row_factory=sqlite3.Row
            owner,digest=check_idle(control,browser,authorization,original,args.browser_profile)
            if resumed:
                latest,latest_ref=read_resume_failure(args.resume_failure_evidence,args.resume_failure_sha256,
                    authorization,reference,original,worker)
                if latest!=resumed or latest_ref!=resumed_ref or owner!=resumed['original_owner']:
                    raise RuntimeError('Stopped original owner or evidence changed')
                observed=resumed['observed_children']
                record.update(original_owner=owner,expected_snapshot_sha256=digest,observed_children=observed,
                    scheduler_writer_fenced=True,browser_writer_fenced=True,
                    gone_child_ids=resumed['gone_child_ids'],alive_child_ids=[])
            else:
                process=exact_backend(authorization)
                children,observed=browser_proof.idle_headless_worker_children(process,args.browser_profile,args.worker_script_sha256)
            current,current_ref,current_original=read_authorization(args.authorization_path,args.authorization_sha256)
            if (current,current_ref,current_original)!=(authorization,reference,original):
                raise RuntimeError('Frozen authorization changed before stop')
            check_idle(control,browser,authorization,original,args.browser_profile)
            if not resumed:
                preflight_chrome_readability()
                process=exact_backend(authorization)
                _,last_observed=browser_proof.idle_headless_worker_children(process,args.browser_profile,args.worker_script_sha256)
                if sorted(observed,key=lambda r:r['pid'])!=sorted(last_observed,key=lambda r:r['pid']):
                    raise RuntimeError('Original browser family changed; no stop performed')
                record.update(phase='termination_requested',termination_requested=True,original_owner=owner,
                    expected_snapshot_sha256=digest,observed_children=observed,scheduler_writer_fenced=True,browser_writer_fenced=True)
                target.write_text(_json(record),encoding='utf8')
                process.terminate()  # Only the exact parent; no child is ever signalled.
                process.wait(timeout=5)
                record.update(phase='parent_exited',parent_exited=True);target.write_text(_json(record),encoding='utf8')
                gone,alive=psutil.wait_procs(children,timeout=30)
                record.update(gone_child_ids=sorted(p.pid for p in gone),alive_child_ids=sorted(p.pid for p in alive))
                if alive:
                    raise RuntimeError('Original descendants have not naturally exited; no owner release')
            browser_proof.assert_profile_exited(args.browser_profile)
            identity_checks=check_original_processes_exited(authorization,observed)
            record.update(phase='descendants_exited',descendants_exited=True,pid_identity_checks=identity_checks)
            retirement_record={'schema':'publication_reconciliation_retirement/20261019/v1',
                'account_uuid':authorization['account_uuid'],'original_command_id':authorization['original_command_id'],
                'owner_id':authorization['original_owner_id'],'generation':authorization['original_generation'],
                'original_backend_pid':authorization['original_backend_pid'],
                'original_backend_create_time':authorization['original_backend_create_time'],
                'parent_exited':True,'descendants_exited':True,'observed_children':observed,
                'gone_child_ids':record['gone_child_ids'],'alive_child_ids':[],
                'pid_identity_checks':identity_checks,
                'finished_at':datetime.now(timezone.utc).timestamp()}
            retirement_reference=exclusive_json(retirement,retirement_record)
            # Core atomically registers restricted reconciliation and releases the
            # retired owner on THIS transaction, preserving the unknown and lock.
            audit=store.handoff_publication_reconciliation(owner_id=authorization['original_owner_id'],
                generation=authorization['original_generation'],authorization=reference,
                expected_snapshot_sha256=digest,retirement_evidence=retirement_reference,connection=browser)
            browser.commit()
            record.update(phase='handoff_committed',handoff_committed=True,
                retirement_evidence=retirement_reference,core_handoff=audit,finished_at=datetime.now(timezone.utc).isoformat())
            target.write_text(_json(record),encoding='utf8')
    except BaseException as exc:
        record.update(phase='handoff_committed_evidence_error' if record['handoff_committed'] else 'stopped_without_handoff' if record['parent_exited'] else 'stop_unconfirmed' if record['termination_requested'] else 'rejected_before_stop',
            error_type=type(exc).__name__,finished_at=datetime.now(timezone.utc).isoformat())
        target.write_text(_json(record),encoding='utf8')
        raise  # No replacement service or compensating mutation.
    print(json.dumps({'handoff_committed':True,'original_unknown_preserved':True,'submission_lock_preserved':True,
        'evidence':str(target)},ensure_ascii=False))


if __name__=='__main__':
    main()
