"""Recover the original local ComfyUI server. This guard only probes HTTP with GET."""
import argparse
import errno
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

import psutil

from h3_persistent_supervisor_20261103 import (
    ROOT, MEDIA, LocalService, LockBusyError, assert_config, bind, event, family_groups,
    identity, lock, queue_ids, read, save, sha, stamp, task_xml,
)

SCRIPT = Path(__file__).resolve()
ORIGINAL = MEDIA.parent / 'h3_six_children_s01_720p_20261102'
HOME = ROOT / 'data/h3_supervision/service_8190_20261104'
CONFIG = HOME / 'SERVICE_PLAN.json'
INSTALL = SCRIPT.with_name('install_h3_service_guard_20261104.ps1')
FLAGS = dict(PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8', HF_HUB_OFFLINE='1',
             TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def port_state(host, port):
    with socket.socket() as probe:
        probe.settimeout(8)
        result = probe.connect_ex((host, port))
    if result == 0:
        listeners = psutil.net_connections(kind='tcp4')
        owners = [row.pid for row in listeners if row.status == psutil.CONN_LISTEN
                  and row.laddr.port == port and row.laddr.ip in {host, '0.0.0.0'}]
        return 'open', owners
    if result in {10061, errno.ECONNREFUSED}:
        return 'closed', []
    raise OSError(result, 'listener state uncertain')


def service_processes(command):
    matches = []
    for process in psutil.process_iter(['name']):
        if 'python' not in (process.info['name'] or '').lower():
            continue
        try:
            args = process.cmdline()
            if not args:
                raise RuntimeError(f'python command not inspectable for pid {process.pid}')
            if args[1:] == command[1:]:
                matches.append(identity(process))
        except psutil.NoSuchProcess:
            continue
    return matches


def inspect(config):
    rows = service_processes(config['command'])
    network, owners = port_state('127.0.0.1', 8190)
    result = dict(families=family_groups(rows), port=network, listeners=owners)
    if rows and network == 'closed':
        return dict(result, action='wait', reason='original_process_alive_without_listener')
    if network == 'open':
        if len(result['families']) != 1 or not owners or not set(owners) <= {r['pid'] for r in rows}:
            return dict(result, action='wait', reason='listener_identity_not_proven')
        try:
            stats = LocalService(config['url']).get('/system_stats')
            if stats.get('system', {}).get('argv') == config['command'][2:]:
                return dict(result, action='healthy', reason='verified_listener_and_argv')
        except (OSError, ValueError):
            pass
        return dict(result, action='wait', reason='original_process_http_not_verified')
    return dict(result, action='launch', reason='original_process_absent_and_connection_refused')


def lookup(config):
    service = LocalService(config['url'])
    task = config['incident_id']
    history = service.get('/history/' + task)
    queue = service.get('/queue')
    if not isinstance(history, dict) or not all(isinstance(queue.get(k), list) for k in ('queue_running', 'queue_pending')):
        raise ValueError('unexpected history or queue schema')
    if task in history:
        return dict(prompt_id=task, result='in_history', status=history[task].get('status', {}).get('status_str'))
    return dict(prompt_id=task, result='in_queue' if task in queue_ids(queue) else 'absent_from_history_and_queue')


def stop_reason(config):
    home = Path(config['home'])
    if (home / 'PAUSE.json').exists():
        return 'manual_pause'
    if read(Path(config['media_run']) / 'STATE.json').get('status') == 'saved':
        return 'full_script_saved'
    return None


def retry_decision(attempts, now):
    recent = sorted(t for t in attempts if t > now - 3600)
    if len(recent) >= 3:
        return 'restart_exhausted', None
    if recent:
        next_time = recent[-1] + 60 * 2 ** (len(recent) - 1)
        if now < next_time:
            return 'cooldown', next_time
    return 'launch', None


def record_child(command, cwd, env, folder):
    with (folder / 'server.stdout.log').open('xb', buffering=0) as out, (folder / 'server.stderr.log').open('xb', buffering=0) as err:
        child = subprocess.Popen(command, cwd=cwd, env=env, stdout=out, stderr=err,
                                 stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        try:
            process = psutil.Process(child.pid)
            creation = process.create_time()
        except psutil.NoSuchProcess:
            creation = None
        save(folder / 'PROCESS.json', dict(at=stamp(), pid=child.pid, create_time=creation, command=command,
                                           cwd=str(cwd), stdout=out.name, stderr=err.name))
        code = child.wait()
        save(folder / 'EXIT.json', dict(at=stamp(), pid=child.pid, create_time=creation, returncode=code))
        return code


def serve(config_path, folder):
    config = assert_config(config_path)
    home = Path(config['home'])
    folder = Path(folder).resolve()
    if folder.parent != (home / 'attempts').resolve() or not (folder / 'CLAIM.json').is_file():
        raise ValueError('unbound service attempt')
    # Independent worker retains pipe handles/exit evidence if the monitor is interrupted.
    try:
        with lock(home / '.service_worker.lock'):
            observation = inspect(config)
            if stop_reason(config) or observation['action'] != 'launch' or (folder / 'PROCESS.json').exists():
                save(folder / 'SKIPPED.json', dict(at=stamp(), observation=observation))
                return 0
            env = os.environ.copy()
            env.update(config['cache_env'], **config['runtime_flags'])
            return record_child(config['command'], config['cwd'], env, folder)
    except LockBusyError:
        save(folder / 'SKIPPED.json', dict(at=stamp(), reason='worker_already_owns_service'))
        return 0
    except Exception as error:
        save(folder / 'WORKER_ERROR.json', dict(at=stamp(), error=repr(error)))
        raise


def tick(config, config_path):
    home = Path(config['home'])
    reason = stop_reason(config)
    if reason:
        return dict(status='stopped', reason=reason)
    if (home / 'EXHAUSTED.json').is_file():
        return dict(status='restart_exhausted', reason='three_restarts_within_one_hour')
    observation = inspect(config)
    if observation['action'] == 'healthy':
        if not (home / 'INCIDENT_LOOKUP.json').exists():
            save(home / 'INCIDENT_LOOKUP.json', dict(at=stamp(), **lookup(config)))
        return dict(status='ready', observation=observation)
    if observation['action'] == 'wait':
        return dict(status='retained', reason=observation['reason'], observation=observation)
    # Claim is counted before launching the recorder. Concurrent workers also recheck under a separate lock.
    receipts = [read(p)['epoch'] for p in (home / 'attempts').glob('*/CLAIM.json')]
    now = time.time()
    action, next_time = retry_decision(receipts, now)
    if action == 'restart_exhausted':
        save(home / 'EXHAUSTED.json', dict(at=stamp(), attempts=receipts, observation=observation))
        return dict(status=action)
    if action == 'cooldown':
        return dict(status=action, next_retry_epoch=next_time)
    folder = home / 'attempts' / uuid.uuid4().hex
    save(folder / 'CLAIM.json', dict(at=stamp(), epoch=now, config_sha256=sha(config_path),
                                     source_command=config['command'], observation=observation))
    command = [config['python'], '-B', str(SCRIPT), 'serve', '--config', str(config_path), '--attempt', str(folder)]
    with (folder / 'worker.stdout.log').open('xb') as out, (folder / 'worker.stderr.log').open('xb') as err:
        worker = subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=err, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    event(home, 'service_worker_launched', attempt=folder.name, pid=worker.pid)
    return dict(status='starting', attempt=folder.name, worker=worker.pid)


def supervise(config_path):
    home = config_path.parent
    try:
        with lock(home / '.guard.lock'):
            last = None
            while True:
                try:
                    config = assert_config(config_path)
                except (OSError, ValueError) as error:
                    save(home / 'STATE.json', dict(at=stamp(), status='configuration_blocked', reason=repr(error)))
                    return
                try:
                    state = tick(config, config_path)
                except Exception as error:
                    state = dict(status='observation_or_launch_error', reason=repr(error))
                transition = (state['status'], state.get('reason'))
                if last != transition:
                    event(home, 'guard_transition', **state)
                    last = transition
                save(home / 'STATE.json', dict(heartbeat_at=stamp(), heartbeat_epoch=time.time(),
                                                guard=identity(psutil.Process()), **state))
                if state['status'] in {'restart_exhausted', 'stopped'}:
                    return
                time.sleep(config['poll_seconds'])
    except LockBusyError:
        return


def database_observation(db_path):
    observed = {'at': stamp(), 'database': str(db_path), 'exists': db_path.is_file(), 'tables': []}
    if observed['exists']:
        with sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            observed['tables'] = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return observed


def prepare(config_path):
    home = config_path.parent
    if config_path.exists():
        raise ValueError('service plan already frozen')
    home.mkdir(parents=True, exist_ok=True)
    source = ORIGINAL / 'SERVER_STARTED.json'
    original = read(source)
    command = original['command']
    comfy = Path(command[2]).parent
    config = dict(schema='h3_service_guard/v1', home=str(home), workspace=str(ROOT), config_path=str(config_path),
                  ensure_python=str(ROOT / '.venv/Scripts/pythonw.exe'), python=str(ROOT / '.venv/Scripts/python.exe'),
                  user=os.environ['USERDOMAIN'] + '\\' + os.environ['USERNAME'], task_name='AI_Douyin_H3_Service8190',
                  cwd=str(comfy), command=command, url=original['url'], cache_env=original['cache_env'], runtime_flags=FLAGS,
                  media_run=str(MEDIA), incident_id='5119a505-c86a-4847-b1eb-33259a100e95', poll_seconds=25)
    xml = ET.fromstring(task_xml(config))
    xml.find('.//{*}Arguments').text = f'-B "{SCRIPT}" supervise --config "{config_path}"'
    task_path = home / 'TASK.xml'
    task_path.write_text(ET.tostring(xml, encoding='unicode'), encoding='utf-8')
    config['bindings'] = [bind(p) for p in [SCRIPT, SCRIPT.with_name('h3_persistent_supervisor_20261103.py'), INSTALL,
                                             source, ORIGINAL / 'start_local.py', comfy / 'main.py', task_path]]
    db_path = ORIGINAL / 'user/comfyui.db'
    evidence = database_observation(db_path)
    evidence.update(command_db_url=command[command.index('--database-url')+1], execution_source=bind(comfy / 'execution.py'),
                    prompt_queue_history='PromptQueue initializes self.history = {} and reads results from the same in-memory dictionary',
                    original_segment_state=read(MEDIA / 'F0038/STATE.json'), initial_observation=inspect(config))
    save(home / 'INITIAL_EVIDENCE.json', evidence)
    save(config_path, config)
    print(sha(config_path))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'supervise', 'serve'])
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('--attempt', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.config)
    elif args.command == 'serve':
        sys.exit(serve(args.config, args.attempt))
    else:
        supervise(args.config)


