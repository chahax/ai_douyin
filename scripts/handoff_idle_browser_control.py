"""Supervised service upgrade only: stop at a proven queued-only DB boundary.

Never clears active/unknown work. Leaves the service stopped on an unexpected
release failure; starting a replacement is a separate operator action.
"""
import argparse
import ast
from contextlib import ExitStack, nullcontext
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import sys
import time
from datetime import datetime, timezone

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MONITORED_APPROVAL_SHA256 = '1b9e91a9b83cebe7e186fcc7e6c964be1380b89b714104c997adba4639d124bd'
SCOPED_POPUP_APPROVAL_SHA256 = '76bd7054d5d0fc6520755b22bf54ab9ce47e05c186bd08eeeac777ef7b9c21ed'
NATIVE_SCROLL_APPROVAL_SHA256 = '0fb1bf007addbde28256399fad1018d60627ea5a377b2c330d4134f40a94d980'


def closed_worker_children(proc, confirmation, *, now=None):
    """Only user-closed browser's exact idle worker family; no browser remains."""
    now = datetime.now(timezone.utc) if now is None else now
    at = datetime.fromisoformat(confirmation['confirmed_at'])
    if at.tzinfo is None or not -5 <= (now - at).total_seconds() <= 1800:
        raise RuntimeError('Window-close confirmation is not fresh')
    if (confirmation.get('user_statement') != '已关闭项目窗口'
            or confirmation.get('service_pid') != proc.pid
            or confirmation.get('process_create_time') != proc.create_time()):
        raise RuntimeError('Window-close confirmation does not match original service')
    from src.platform_adapter.browser_session import _PW_SCRIPT
    script_sha = hashlib.sha256(_PW_SCRIPT.encode()).hexdigest()
    if confirmation.get('worker_script_sha256') != script_sha:
        raise RuntimeError('Original worker script does not match')
    children = proc.children(recursive=True)
    expected = {r['pid']: r['create_time'] for r in confirmation['observed_children']}
    python_ids, node_ids, console_ids, evidence = set(), set(), set(), []
    for child in children:
        if (child.pid not in expected or child.create_time() != expected[child.pid]
                or child.create_time() < proc.create_time()):
            raise RuntimeError('Unobserved or reused child process')
        command = child.cmdline()
        name = child.name().lower()
        if name in {'pythonw.exe', 'python.exe'}:
            if not worker_command_matches(command, (ROOT / '.venv/Scripts' / name).resolve(), script_sha):
                raise RuntimeError('Child is not the original project browser worker')
            python_ids.add(child.pid)
        elif name == 'node.exe':
            driver = ROOT / '.local_py/site-packages/playwright/driver'
            if (len(command) != 3 or Path(command[0]).resolve() != (driver / 'node.exe').resolve()
                    or Path(command[1]).resolve() != (driver / 'package/cli.js').resolve()
                    or command[2] != 'run-driver'):
                raise RuntimeError('Child is not the project Playwright driver')
            node_ids.add(child.pid)
        elif name == 'conhost.exe':
            if Path(child.exe()).resolve() != (Path(os.environ['SystemRoot']) / 'System32/conhost.exe').resolve():
                raise RuntimeError('Unexpected console child')
            console_ids.add(child.pid)
        else:
            raise RuntimeError('Browser or unrecognized child remains; no stop performed')
        evidence.append({'pid': child.pid, 'ppid': child.ppid(), 'name': name,
                         'create_time': child.create_time()})
    if len(python_ids) > 2 or len(node_ids) > 1 or len(console_ids) > 1:
        raise RuntimeError('Unexpected worker family size')
    by_pid = {r['pid']: r for r in evidence}
    for pid in python_ids:
        if by_pid[pid]['ppid'] not in python_ids | {proc.pid}:
            raise RuntimeError('Worker parent mismatch')
    for pid in node_ids:
        if by_pid[pid]['ppid'] not in python_ids:
            raise RuntimeError('Driver parent mismatch')
    for pid in console_ids:
        if by_pid[pid]['ppid'] not in node_ids:
            raise RuntimeError('Console parent mismatch')
    return children, evidence


def worker_source_evidence(source, expected_script_sha256):
    """Read an original project source as data; never execute a historical worker."""
    path = Path(source).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise RuntimeError('Worker source must be a project evidence file')
    if not re.fullmatch('[0-9a-f]{64}', expected_script_sha256 or ''):
        raise RuntimeError('Explicit original worker SHA256 is required')
    content = path.read_bytes()
    assignments = [n.value.value for n in ast.parse(content.decode('utf-8-sig')).body
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_PW_SCRIPT' for t in n.targets)
        and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)]
    if len(assignments) != 1 or hashlib.sha256(assignments[0].encode()).hexdigest() != expected_script_sha256:
        raise RuntimeError('Original worker source does not match explicit script SHA256')
    return {'path': str(path), 'source_sha256': hashlib.sha256(content).hexdigest(),
            'worker_script_sha256': expected_script_sha256}


def worker_command_matches(command, expected_python, script_sha256):
    """Recognize old inline or exact content-addressed project worker only."""
    if not command or Path(command[0]).resolve() != expected_python:
        return False
    if len(command) == 4 and command[1:3] == ['-S', '-c']:
        return hashlib.sha256(command[3].encode()).hexdigest() == script_sha256
    if len(command) != 3 or command[1] != '-S':
        return False
    from src.platform_adapter.browser_session import _PW_SCRIPT
    if hashlib.sha256(_PW_SCRIPT.encode('utf-8')).hexdigest() != script_sha256:
        return False
    expected = ROOT / 'data/browser_worker_cache' / (script_sha256 + '.py')
    candidate = Path(command[2])
    if (candidate.is_symlink() or expected.parent.is_symlink()
            or candidate.absolute() != expected.absolute()):
        return False
    try:
        return candidate.read_bytes() == _PW_SCRIPT.encode('utf-8')
    except OSError:
        return False


def idle_headless_worker_children(proc, profile_dir, script_sha256):
    """Prove exactly one idle headless project family; never signal its children."""
    profile = Path(profile_dir).resolve()
    if not profile.is_relative_to(ROOT) or profile == ROOT:
        raise RuntimeError('Original browser profile must be inside the project')
    children = proc.children(recursive=True)
    if not 4 <= len(children) <= 40:
        raise RuntimeError('Unexpected idle headless family size')
    expected_python = (ROOT / '.venv/Scripts/pythonw.exe').resolve()
    driver = ROOT / '.local_py/site-packages/playwright/driver'
    expected_chrome = (Path(os.environ['ProgramFiles']) / 'Google/Chrome/Application/chrome.exe').resolve()
    python_ids, node_ids, console_ids, chrome_ids = set(), set(), set(), set()
    evidence, commands = [], {}
    for child in children:
        if child.create_time() < proc.create_time():
            raise RuntimeError('Child predates original service')
        name, command = child.name().lower(), child.cmdline()
        commands[child.pid] = command
        if name == 'pythonw.exe':
            if not worker_command_matches(command, expected_python, script_sha256):
                raise RuntimeError('Not the exact original project pythonw worker')
            python_ids.add(child.pid)
        elif name == 'node.exe':
            if (len(command) != 3 or Path(command[0]).resolve() != (driver/'node.exe').resolve()
                    or Path(command[1]).resolve() != (driver/'package/cli.js').resolve()
                    or command[2] != 'run-driver' or Path(child.exe()).resolve() != (driver/'node.exe').resolve()):
                raise RuntimeError('Not the unique project Playwright driver')
            node_ids.add(child.pid)
        elif name == 'conhost.exe':
            if Path(child.exe()).resolve() != (Path(os.environ['SystemRoot'])/'System32/conhost.exe').resolve():
                raise RuntimeError('Unexpected console child')
            console_ids.add(child.pid)
        elif name == 'chrome.exe':
            if (not command or Path(command[0]).resolve() != expected_chrome
                    or Path(child.exe()).resolve() != expected_chrome):
                raise RuntimeError('Unexpected Chrome executable')
            profiles = [v.split('=', 1)[1] for v in command if v.startswith('--user-data-dir=')]
            if len(profiles) != 1 or Path(profiles[0]).resolve() != profile:
                raise RuntimeError('Chrome is not the original account profile')
            chrome_ids.add(child.pid)
        else:
            raise RuntimeError('Unrecognized or visible child; no stop performed')
        evidence.append({'pid': child.pid, 'ppid': child.ppid(), 'name': name,
                         'create_time': child.create_time()})
    by_pid = {r['pid']: r for r in evidence}
    if (len(by_pid) != len(children) or len(python_ids) not in {1, 2}
            or len(node_ids) != 1 or len(console_ids) > 1 or not chrome_ids):
        raise RuntimeError('Not a single project browser family')
    worker_roots = [pid for pid in python_ids if by_pid[pid]['ppid'] == proc.pid]
    worker_leaves = [pid for pid in python_ids if not any(by_pid[p]['ppid'] == pid for p in python_ids)]
    if len(worker_roots) != 1 or len(worker_leaves) != 1:
        raise RuntimeError('Worker ancestry is not one chain')
    if any(by_pid[p]['ppid'] not in python_ids|{proc.pid} for p in python_ids):
        raise RuntimeError('Worker parent mismatch')
    node_id = next(iter(node_ids))
    if by_pid[node_id]['ppid'] != worker_leaves[0] or any(by_pid[p]['ppid'] != node_id for p in console_ids):
        raise RuntimeError('Driver or console parent mismatch')
    chrome_roots = [p for p in chrome_ids if not any(v.startswith('--type=') for v in commands[p])]
    if len(chrome_roots) != 1 or by_pid[chrome_roots[0]]['ppid'] != node_id:
        raise RuntimeError('Not exactly one Chrome root under the original driver')
    chrome_root = chrome_roots[0]
    command = commands[chrome_root]
    headless = [v for v in command if v == '--headless' or v.startswith('--headless=')]
    if (len(headless) != 1 or headless[0] not in {'--headless', '--headless=new'}
            or '--remote-debugging-pipe' not in command or '--enable-automation' not in command):
        raise RuntimeError('A visible or unproven Chrome context remains')
    for pid in chrome_ids-{chrome_root}:
        types = [v.split('=',1)[1] for v in commands[pid] if v.startswith('--type=')]
        if len(types) != 1 or types[0] not in {'renderer','gpu-process','utility','crashpad-handler','zygote'}:
            raise RuntimeError('Unexpected Chrome child type')
        cursor, visited = pid, set()
        while cursor != chrome_root:
            if cursor in visited or cursor not in chrome_ids:
                raise RuntimeError('Chrome descendant is outside the original root')
            visited.add(cursor)
            cursor = by_pid[cursor]['ppid']
    for item in evidence:
        parent = by_pid.get(item['ppid'])
        if parent and item['create_time'] < parent['create_time']:
            raise RuntimeError('Child identity or ancestry changed')
    return children, evidence


def assert_profile_exited(profile_dir):
    """Catch a late-born Chrome descendant not present in the pre-stop snapshot."""
    profile = Path(profile_dir).resolve()
    for process in psutil.process_iter(['name']):
        if (process.info.get('name') or '').lower() != 'chrome.exe':
            continue
        try:
            profiles = [v.split('=',1)[1] for v in process.cmdline() if v.startswith('--user-data-dir=')]
        except psutil.NoSuchProcess:
            continue
        if any(Path(v).resolve() == profile for v in profiles):
            raise RuntimeError('Original profile Chrome remains; owner retained, no replacement')


def active_quota_approval(path, sha256, account_id):
    """Frozen one-film user deployment approval; it grants no operation here."""
    source = Path(path).resolve()
    if (not source.is_relative_to(ROOT) or not source.is_file()
            or not re.fullmatch('[0-9a-f]{64}', sha256 or '')):
        raise RuntimeError('Active quota idle mode requires frozen project approval')
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise RuntimeError('Active quota idle approval SHA256 changed')
    value = json.loads(data)
    if isinstance(value, dict) and value.get('schema') == 'publication_native_scroll_retry_user_authorization/20261019/v1':
        if sha256 != NATIVE_SCROLL_APPROVAL_SHA256:
            raise RuntimeError('Native scroll retry requires the exact original user approval')
        from src.operations_accounts import publication_two_run_authorization as quota
        parent_reference = json.loads(quota.REGISTRY_V8.read_bytes())
        parent = quota.validate_authorization(parent_reference)
        approval_reference = {'path': str(source), 'sha256': sha256}
        if (parent.get('schema') != 'publication_native_scroll_retry/20261019/v8'
                or parent.get('user_authorization') != approval_reference
                or value.get('account_uuid') != account_id or parent.get('account_uuid') != account_id
                or parent.get('scope') != 'publish_only' or parent.get('baseline_daily_runs') != 32
                or parent.get('max_daily_runs') != 33 or parent.get('active_control_revision') != 42
                or parent.get('idempotency_keys') != {'publish':'user-native-scroll-publication-retry-20261019:approved-h3-publication'}
                or any(parent.get(k) != value.get(k) for k in ('account_key','utc_day','prepared','video'))):
            raise RuntimeError('Registered native scroll parent does not bind this exact approval and film')
        return value, approval_reference
    if isinstance(value, dict) and value.get('schema') == 'publication_scoped_popup_retry_user_authorization/20261019/v1':
        if sha256 != SCOPED_POPUP_APPROVAL_SHA256:
            raise RuntimeError('Scoped popup retry requires the exact original user approval')
        from src.operations_accounts import publication_two_run_authorization as quota
        parent_reference = json.loads(quota.REGISTRY_V7.read_bytes())
        parent = quota.validate_authorization(parent_reference)
        approval_reference = {'path': str(source), 'sha256': sha256}
        if (parent.get('schema') != 'publication_scoped_popup_retry/20261019/v7'
                or parent.get('user_authorization') != approval_reference
                or value.get('account_uuid') != account_id or parent.get('account_uuid') != account_id
                or parent.get('scope') != 'publish_only' or parent.get('baseline_daily_runs') != 31
                or parent.get('max_daily_runs') != 32 or parent.get('active_control_revision') != 42
                or parent.get('idempotency_keys') != {'publish':'user-scoped-popup-publication-retry-20261019:approved-h3-publication'}
                or any(parent.get(k) != value.get(k) for k in ('account_key','utc_day','prepared','video'))):
            raise RuntimeError('Registered scoped popup parent does not bind this exact approval and film')
        return value, approval_reference
    if isinstance(value, dict) and value.get('schema') == 'publication_monitored_resume_user_authorization/20261019/v1':
        if sha256 != MONITORED_APPROVAL_SHA256:
            raise RuntimeError('Monitored resume requires the exact original user approval')
        from src.operations_accounts import publication_two_run_authorization as quota
        parent_reference = json.loads(quota.REGISTRY_V6.read_bytes())
        parent = quota.validate_authorization(parent_reference)
        approval_reference = {'path': str(source), 'sha256': sha256}
        if (parent.get('schema') != 'publication_monitored_resume/20261019/v6'
                or parent.get('user_authorization') != approval_reference
                or value.get('account_uuid') != account_id or parent.get('account_uuid') != account_id
                or parent.get('scope') != 'publish_only' or parent.get('baseline_daily_runs') != 30
                or parent.get('max_daily_runs') != 31 or parent.get('active_control_revision') != 42
                or parent.get('idempotency_keys') != {'publish':'user-monitored-publication-resume-20261019:approved-h3-publication'}
                or any(parent.get(k) != value.get(k) for k in ('account_key','utc_day','prepared','video'))):
            raise RuntimeError('Registered monitored parent does not bind this exact approval and film')
        return value, approval_reference
    fast = isinstance(value, dict) and value.get('schema') == 'publication_fast_upload_retry_user_authorization/20261019/v1'
    bounded = isinstance(value, dict) and value.get('schema') == 'publication_bounded_retry_user_authorization/20261019/v1'
    expected = {'schema': 'publication_single_retry_user_authorization/20261019/v1',
        'decision_source': 'explicit_user_statement', 'account_uuid': account_id,
        'deployment_authorized': True, 'operator_close_unknown_publication': True,
        'archive_submission_lock': True, 'additional_publication_runs': 1,
        'additional_recovery_runs': 0, 'baseline_daily_runs': 25, 'max_daily_runs': 26,
        'active_control_revision': 42, 'original_outcome_known': False,
        'retain_original_history': True, 'new_media_authorized': False,
        'utc_day': datetime.now(timezone.utc).date().isoformat()}
    if fast or bounded:
        for name in ('operator_close_unknown_publication','archive_submission_lock','original_outcome_known'):
            expected.pop(name)
        expected.update(schema='publication_fast_upload_retry_user_authorization/20261019/v1',
            baseline_daily_runs=26,max_daily_runs=27,user_statement='允许')
        if bounded:
            expected.update(schema='publication_bounded_retry_user_authorization/20261019/v1',
                baseline_daily_runs=27,max_daily_runs=30,additional_publication_runs=3,user_statement='可以',
                only_known_pre_submission_failures=True,stop_on_unknown=True,stop_on_human_required=True)
    if (not isinstance(value, dict) or any(type(value.get(k)) is not type(v) or value[k] != v for k,v in expected.items())
            or value['utc_day'] != '2026-10-19'
            or not all(isinstance(value.get(k), str) and value[k].strip()
                for k in ('account_key','user_statement','approval_question',
                          'previous_command_id' if fast or bounded else 'original_command_id'))):
        raise RuntimeError('Active quota idle approval scope does not match')
    if fast or bounded:
        if any(name in value for name in ('operator_close_unknown_publication','archive_submission_lock','original_outcome_known')):
            raise RuntimeError('Known upload failure approval cannot close or archive unknown work')
        previous = json.loads(frozen_approval_reference(value.get('previous_authorization')))
        if (previous.get('schema') != ('publication_fast_upload_retry/20261019/v4' if bounded else 'publication_single_retry/20261019/v3')
                or previous.get('scope') != 'publish_only' or previous.get('baseline_daily_runs') != (26 if bounded else 25)
                or previous.get('max_daily_runs') != (27 if bounded else 26) or previous.get('active_control_revision') != 42
                or any(previous.get(k) != value.get(k) for k in ('account_uuid','account_key','utc_day','prepared','video'))):
            raise RuntimeError('Publication approval does not continue the same frozen previous film')
        command = json.loads(frozen_approval_reference(value.get('previous_command')))
        if (not isinstance(command, dict) or command.get('command_id') != value['previous_command_id']
                or command.get('account_id') != account_id or command.get('kind') != 'publish'
                or command.get('state') != 'failed' or command.get('result',{}).get('status') != 'upload_failed'):
            raise RuntimeError('Previous publication is not the exact known upload failure')
        for name in ('previous_journal','previous_final_state'):
            frozen_approval_reference(value.get(name))
    return value, {'path': str(source), 'sha256': sha256}


def frozen_approval_reference(reference):
    if not isinstance(reference, dict) or set(reference) != {'path','sha256'}:
        raise RuntimeError('Frozen previous publication reference is required')
    path = Path(reference['path']).resolve()
    if (not path.is_relative_to(ROOT) or not path.is_file()
            or not re.fullmatch('[0-9a-f]{64}',reference.get('sha256') or '')):
        raise RuntimeError('Previous publication reference must be a frozen project file')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != reference['sha256']:
        raise RuntimeError('Previous publication evidence changed')
    return data


def continuation_idle_baseline(approval, approval_reference, attempt_index, control, browser_fence):
    """Deployment only: the existing registered slot validator grants no run here."""
    if (type(attempt_index) is not int or attempt_index not in (2,3)
            or approval.get('schema') != 'publication_bounded_retry_user_authorization/20261019/v1'
            or not control.in_transaction or browser_fence is None or not browser_fence.in_transaction):
        raise RuntimeError('Bounded continuation requires both original writer fences')
    from src.operations_accounts import publication_two_run_authorization as quota
    from src.operations_accounts.publication_bounded_retry_authorization import validate_attempt
    parent_reference = json.loads(quota.REGISTRY_V5.read_bytes())
    parent, canonical = quota._load_reference(parent_reference)
    if (parent_reference != canonical or parent.get('user_authorization') != approval_reference
            or any(parent.get(k) != approval.get(k) for k in
                ('account_uuid','account_key','utc_day','prepared','video','active_control_revision'))):
        raise RuntimeError('Registered bounded parent does not bind the original approval')
    limit = validate_attempt(parent_reference,attempt_index)
    if type(limit) is not int or limit != 27+attempt_index:
        raise RuntimeError('Bounded continuation slot limit is not exact')
    return limit-1, parent_reference


def check_active_quota_idle(control, approval, *, attempt_index=1, approval_reference=None, browser_fence=None):
    """Caller holds account_refresh BEGIN IMMEDIATE through parent and child exit."""
    if not control.in_transaction:
        raise RuntimeError('Active quota idle scheduler writer fence is missing')
    if type(attempt_index) is not int or attempt_index not in (1,2,3):
        raise RuntimeError('Invalid deployment quota attempt index')
    continuation_parent = None
    baseline = approval['baseline_daily_runs']
    if attempt_index != 1:
        baseline, continuation_parent = continuation_idle_baseline(
            approval,approval_reference,attempt_index,control,browser_fence)
    rows = control.execute('SELECT account_uuid,account_key,state,revision FROM account_controls WHERE account_uuid=?',
                           (approval['account_uuid'],)).fetchall()
    if len(rows) != 1 or tuple(rows[0]) != (approval['account_uuid'],approval['account_key'],'active',42):
        raise RuntimeError('Original active account or control revision changed')
    if control.execute("SELECT 1 FROM account_controls WHERE account_uuid<>? AND state!='paused' LIMIT 1",
                       (approval['account_uuid'],)).fetchone():
        raise RuntimeError('Another account can dispatch; no process stopped')
    if control.execute("SELECT 1 FROM account_controls WHERE recovery_requested_at IS NOT NULL OR coalesce(recovery_lease_until,0)<>0 OR coalesce(recovery_token,'')<>'' LIMIT 1").fetchone():
        raise RuntimeError('Recovery pending or unknown; no process stopped')
    with sqlite3.connect((ROOT/'data/douyin.db').as_uri()+'?mode=ro',uri=True) as runtime:
        if runtime.execute("SELECT 1 FROM account_runtime_state WHERE coalesce(lock_owner,'')<>'' LIMIT 1").fetchone():
            raise RuntimeError('Business lease present; no process stopped')
        state = runtime.execute('SELECT day_key,daily_runs FROM account_runtime_state WHERE account_uuid=?',
                                (approval['account_uuid'],)).fetchall()
    if len(state) != 1 or tuple(state[0]) != (approval['utc_day'],baseline):
        raise RuntimeError('Original UTC day or daily quota baseline changed')
    snapshot = {'account_uuid':approval['account_uuid'],'account_key':approval['account_key'],
            'state':'active','revision':42,'day_key':approval['utc_day'],'daily_runs':baseline,
            'normal_daily_limit':20,'scheduler_writer_fenced':True}
    if continuation_parent is not None:
        snapshot.update(quota_attempt_index=attempt_index,registered_parent=continuation_parent)
    return snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pid', required=True, type=int)
    parser.add_argument('--process-create-time', required=True, type=float)
    parser.add_argument('--owner-id', required=True)
    parser.add_argument('--generation', required=True, type=int)
    parser.add_argument('--account-id', required=True)
    parser.add_argument('--closed-window-confirmation')
    parser.add_argument('--idle-headless-worker', action='store_true')
    parser.add_argument('--worker-source')
    parser.add_argument('--worker-script-sha256')
    parser.add_argument('--browser-profile')
    parser.add_argument('--active-quota-idle', action='store_true')
    parser.add_argument('--approval-path')
    parser.add_argument('--approval-sha256')
    parser.add_argument('--quota-attempt-index', type=int, choices=(1,2,3), default=1)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    worker_evidence = None
    if args.idle_headless_worker:
        if args.closed_window_confirmation or not all((args.worker_source, args.worker_script_sha256, args.browser_profile)):
            raise RuntimeError('Headless mode requires exact source, script SHA and original profile; no close confirmation')
        worker_evidence = worker_source_evidence(args.worker_source, args.worker_script_sha256)
    elif any((args.worker_source, args.worker_script_sha256, args.browser_profile)):
        raise RuntimeError('Worker options require explicit idle-headless-worker mode')
    approval = approval_ref = None
    if args.active_quota_idle:
        if not args.idle_headless_worker or not args.approval_path or not args.approval_sha256:
            raise RuntimeError('Active quota idle mode requires explicit headless mode and frozen approval')
        approval, approval_ref = active_quota_approval(args.approval_path,args.approval_sha256,args.account_id)
    elif args.approval_path or args.approval_sha256:
        raise RuntimeError('Approval options require explicit active-quota-idle mode')
    if args.quota_attempt_index != 1 and (not args.active_quota_idle or approval.get('schema') !=
            'publication_bounded_retry_user_authorization/20261019/v1'):
        raise RuntimeError('Only the original bounded approval supports continuation deployment')
    target = Path(args.evidence).resolve()
    if not target.is_relative_to(ROOT) or target.exists():
        raise RuntimeError('Evidence must be a new project file')
    proc = psutil.Process(args.pid)
    expected_start = args.process_create_time
    expected_script = str(ROOT / 'scripts/run_streamlit_web.py').lower()
    if (proc.create_time() != expected_start or not proc.is_running()
            or proc.cwd().lower() != str(ROOT).lower()
            or expected_script not in [s.lower() for s in proc.cmdline()]):
        raise RuntimeError('Process is not the exact project service')
    if int((ROOT / 'data/logs/streamlit_web.pid').read_text()) != args.pid:
        raise RuntimeError('Service PID changed')
    confirmation = None
    confirmation_sha = None
    if args.closed_window_confirmation:
        source = Path(args.closed_window_confirmation).resolve()
        if not source.is_relative_to(ROOT):
            raise RuntimeError('Confirmation must be a project evidence file')
        confirmation_bytes = source.read_bytes()
        confirmation = json.loads(confirmation_bytes.decode('utf-8'))
        confirmation_sha = hashlib.sha256(confirmation_bytes).hexdigest()
    record = {'schema': 'known_idle_owner_handoff/v1',
              'requested_at': datetime.now(timezone.utc).isoformat(),
              'pid': args.pid, 'process_create_time': expected_start,
              'expected_owner_id': args.owner_id, 'expected_generation': args.generation,
              'expected_account_id': args.account_id, 'phase': 'checking',
              'termination_requested': False, 'stop_outcome': 'not_attempted',
              'stopped': False, 'released': False, 'attempts': []}
    db_path = ROOT / 'data/account_browser_control.db'
    for _ in range(20):
        # Writer reservation fences claim_next before inspecting queued state.
        with ExitStack() as fences, sqlite3.connect(db_path, timeout=2) as db:
            active_control = None
            if args.active_quota_idle:
                active_control = fences.enter_context(sqlite3.connect(
                    (ROOT/'data/account_refresh.db').as_uri()+'?mode=rw',uri=True,timeout=2))
                active_control.execute('BEGIN IMMEDIATE')
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            owners = [dict(r) for r in db.execute(
                "SELECT * FROM browser_control_owners WHERE state!='released'")]
            commands = [dict(r) for r in db.execute(
                'SELECT command_id,account_id,state,error_code FROM browser_control_commands')]
            if (len(owners) != 1 or owners[0]['owner_id'] != args.owner_id
                    or owners[0]['generation'] != args.generation
                    or owners[0]['account_id'] != args.account_id
                    or not args.owner_id.startswith(f'backend:{args.pid}:')
                    or owners[0]['state'] != 'active'):
                raise RuntimeError('Unexpected owner; no process stopped')
            if any(r['state'] not in {'queued', 'succeeded', 'failed'} for r in commands):
                record['attempts'].append('not_idle')
                db.rollback()
            else:
                with sqlite3.connect((ROOT / 'data/douyin.db').as_uri() + '?mode=ro', uri=True) as old:
                    if old.execute("SELECT 1 FROM account_runtime_state WHERE coalesce(lock_owner,'')<>'' LIMIT 1").fetchone():
                        raise RuntimeError('Business lease present; no process stopped')
                    if args.idle_headless_worker:
                        profiles = old.execute('SELECT browser_profile_dir FROM account_runtime_bindings WHERE account_uuid=?',
                                               (args.account_id,)).fetchall()
                        if (len(profiles) != 1 or Path(profiles[0][0]).resolve() != Path(args.browser_profile).resolve()):
                            raise RuntimeError('Browser profile does not match original account binding')
                with (nullcontext(active_control) if args.active_quota_idle else sqlite3.connect(
                        (ROOT / 'data/account_refresh.db').as_uri() + '?mode=ro', uri=True)) as control:
                    if control.execute('SELECT COUNT(*) FROM account_controls WHERE account_uuid=?',
                                       (args.account_id,)).fetchone()[0] != 1:
                        raise RuntimeError('Original account control missing; no process stopped')
                    active_snapshot = check_active_quota_idle(control,approval,attempt_index=args.quota_attempt_index,
                        approval_reference=approval_ref,browser_fence=db) if args.active_quota_idle else None
                    if not args.active_quota_idle and control.execute("SELECT 1 FROM account_controls WHERE state!='paused' LIMIT 1").fetchone():
                        raise RuntimeError('Account can dispatch; no process stopped')
                    for table in ('refresh_accounts', 'smart_accounts', 'playback_accounts'):
                        if control.execute(f'SELECT 1 FROM {table} WHERE run_id IS NOT NULL OR coalesce(lease_until,0)<>0 LIMIT 1').fetchone():
                            raise RuntimeError('Business owner or unknown original run present; no process stopped')
                    for table in ('refresh_runs', 'smart_runs', 'playback_runs'):
                        if control.execute(f"SELECT 1 FROM {table} WHERE status IN ('running','starting','claimed','outcome_unknown') OR finished_at IS NULL LIMIT 1").fetchone():
                            raise RuntimeError('Business inflight; no process stopped')
                    if control.execute("SELECT 1 FROM account_handling_requests WHERE status IN ('requested','probing') LIMIT 1").fetchone():
                        raise RuntimeError('Recovery inflight; no process stopped')
                manual_path = ROOT / 'data/account_manual_windows.db'
                if manual_path.exists():
                    with sqlite3.connect(manual_path.as_uri() + '?mode=ro', uri=True) as manual:
                        if manual.execute("SELECT 1 FROM manual_window_jobs WHERE state NOT IN ('closed','failed') LIMIT 1").fetchone():
                            raise RuntimeError('Legacy manual window active or unknown; no process stopped')
                # A new Process object avoids trusting a cached create_time on
                # the original psutil object if the PID was reused meanwhile.
                current = psutil.Process(args.pid)
                if (not current.is_running() or current.create_time() != expected_start
                        or current.cwd().lower() != str(ROOT).lower()
                        or expected_script not in [s.lower() for s in current.cmdline()]
                        or int((ROOT / 'data/logs/streamlit_web.pid').read_text()) != args.pid):
                    raise RuntimeError('Process changed; no process stopped')
                children, child_evidence = [], []
                if args.idle_headless_worker:
                    children, child_evidence = idle_headless_worker_children(current, args.browser_profile, args.worker_script_sha256)
                elif confirmation is None:
                    if current.children(recursive=True):
                        raise RuntimeError('Child exists; no process stopped')
                else:
                    if (confirmation.get('owner_id') != args.owner_id
                            or confirmation.get('generation') != args.generation):
                        raise RuntimeError('Window-close owner mismatch')
                    children, child_evidence = closed_worker_children(current, confirmation)
                proc = current
                record.update(owner_before=owners[0], commands_before=commands,
                              queued_claim_fenced=True, browser_children=[],
                              closed_worker_children=child_evidence,
                              closed_window_confirmation=args.closed_window_confirmation,
                              closed_window_confirmation_sha256=confirmation_sha,
                              idle_headless_worker=args.idle_headless_worker,
                              idle_headless_source=worker_evidence,
                              idle_headless_profile=str(Path(args.browser_profile).resolve()) if args.idle_headless_worker else None,
                              active_quota_idle=args.active_quota_idle,
                              active_quota_idle_approval=approval_ref,
                              active_quota_idle_snapshot=active_snapshot,
                              reason='all nonterminal commands queued, pre-dispatch; known service upgrade')
                if args.idle_headless_worker:
                    _, final_children = idle_headless_worker_children(current, args.browser_profile, args.worker_script_sha256)
                    if sorted(child_evidence, key=lambda r:r['pid']) != sorted(final_children, key=lambda r:r['pid']):
                        raise RuntimeError('Browser family changed before stop; no stop performed')
                if args.active_quota_idle:
                    active_quota_approval(args.approval_path,args.approval_sha256,args.account_id)
                    check_active_quota_idle(active_control,approval,attempt_index=args.quota_attempt_index,
                        approval_reference=approval_ref,browser_fence=db)
                record.update(phase='termination_requested', termination_requested=True,
                              stop_outcome='unknown')
                target.write_text(json.dumps(record, indent=2), encoding='utf-8')
                try:
                    proc.terminate()
                    record['phase'] = 'waiting_for_exit'
                    target.write_text(json.dumps(record, indent=2), encoding='utf-8')
                    proc.wait(timeout=5)
                except BaseException as exc:
                    record.update(phase='termination_unconfirmed', stop_outcome='unknown',
                                  error_type=type(exc).__name__,
                                  finished_at=datetime.now(timezone.utc).isoformat())
                    target.write_text(json.dumps(record, indent=2), encoding='utf-8')
                    raise  # No owner release and no replacement process.
                record.update(stopped=True, phase='process_exit_confirmed', stop_outcome='confirmed_dead')
                if children:
                    try:
                        gone, alive = psutil.wait_procs(children, timeout=30 if args.idle_headless_worker else 5)
                    except BaseException as exc:
                        record.update(phase='closed_worker_exit_unconfirmed', error_type=type(exc).__name__,
                                      finished_at=datetime.now(timezone.utc).isoformat())
                        target.write_text(json.dumps(record, indent=2), encoding='utf-8')
                        raise
                    record['closed_worker_exits'] = {'gone': [p.pid for p in gone], 'alive': [p.pid for p in alive]}
                    if alive:
                        record.update(phase='closed_worker_exit_unconfirmed',
                                      finished_at=datetime.now(timezone.utc).isoformat())
                        target.write_text(json.dumps(record, indent=2), encoding='utf-8')
                        raise RuntimeError('Closed worker exit unconfirmed; owner retained, no replacement')
                if args.idle_headless_worker:
                    try:
                        assert_profile_exited(args.browser_profile)
                    except BaseException as exc:
                        record.update(phase='headless_profile_exit_unconfirmed', error_type=type(exc).__name__,
                                      finished_at=datetime.now(timezone.utc).isoformat())
                        target.write_text(json.dumps(record, indent=2), encoding='utf-8')
                        raise
                db.commit()
                target.write_text(json.dumps(record, indent=2), encoding='utf-8')
                from src.operations_accounts.browser_control import BrowserControlStore
                owner = owners[0]
                # Public API rechecks the exact generation and rejects unresolved work.
                try:
                    store = BrowserControlStore(db_path)
                    store.release_owner(owner['account_id'], owner['owner_id'], owner['generation'])
                except BaseException as exc:
                    record.update(phase='owner_release_failed', error_type=type(exc).__name__,
                                  finished_at=datetime.now(timezone.utc).isoformat())
                    target.write_text(json.dumps(record, indent=2), encoding='utf-8')
                    raise
                record['released'] = True
                record['phase'] = 'owner_released'
                record['owner_after'] = store.snapshot(owner['account_id'])['owner']
                record['finished_at'] = datetime.now(timezone.utc).isoformat()
                target.write_text(json.dumps(record, indent=2), encoding='utf-8')
                print(json.dumps({'stopped': True, 'released': True, 'evidence': str(target)}))
                return
        time.sleep(0.25)
    target.write_text(json.dumps(record, indent=2), encoding='utf-8')
    raise RuntimeError('No idle queued-only boundary observed; no stop performed')


if __name__ == '__main__':
    main()
