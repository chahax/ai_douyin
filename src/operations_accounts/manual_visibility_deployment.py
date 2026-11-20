"""One explicit display-repair deployment on the original live owner thread."""
import json
import os
from pathlib import Path
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT = ROOT / 'data/development_checkpoints/manual_window_visibility_20261103'
ARM = CHECKPOINT / 'ARM.json'


def close_for_upgrade(actor, resource, config, checkpoint):
    """Save and normally exit the invisible original; never acknowledge handling."""
    checkpoint = Path(checkpoint)
    started = checkpoint / 'CLOSE_STARTED.json'
    if started.exists():
        return False
    if (config.get('purpose') != 'repair_invisible_manual_window'
            or config.get('user_statement') != '看不到 Chrome 处理窗口'):
        return False
    actor._assert_thread()
    actor._check_owner()
    manual_id = config['manual_id']
    if (actor.account_id != config['account_id'] or actor.owner_id != config['owner_id']
            or actor.generation != config['generation'] or actor._stack
            or set(resource.manual_tasks) != {manual_id} or resource.console_tasks):
        return False
    command = actor.store.get(manual_id)
    tab_id = resource.manual_tasks[manual_id]
    if (not command or command['kind'] != 'manual' or command['state'] != 'waiting_human'
            or command['owner_id'] != actor.owner_id or command['generation'] != actor.generation
            or (command.get('result') or {}).get('tab_id') != tab_id):
        return False
    with actor.store._db() as db:
        if db.execute("SELECT 1 FROM browser_control_commands WHERE account_id=? AND command_id!=? AND state IN ('running','paused','waiting_human','outcome_unknown') LIMIT 1",
                      (actor.account_id, manual_id)).fetchone():
            return False
    session = resource.session
    if session is None or getattr(session, '_proc', None) is None:
        return False
    status = session.window_status()
    tabs = status.get('tabs', [])
    if not any(r.get('tab_id') == tab_id and r.get('role') == 'manual' and r.get('closed') is False for r in tabs):
        return False
    if any(r.get('closed') is not True and r.get('tab_id') != tab_id
           and not (r.get('role') == 'default' and r.get('url') == 'about:blank') for r in tabs):
        return False
    saved = session._send({'action': 'save_state', 'path': session.config.storage_state_path})
    if saved.get('state_saved') is not True:
        return False
    import psutil
    process = session._proc
    descendants = psutil.Process(process.pid).children(recursive=True)
    proof = {'manual_id': manual_id, 'owner_id': actor.owner_id, 'generation': actor.generation,
        'worker_pid': process.pid, 'worker_create_time': psutil.Process(process.pid).create_time(),
        'children': [{'pid': p.pid, 'create_time': p.create_time()} for p in descendants],
        'state_saved': True, 'at': time.time()}
    with started.open('x', encoding='utf-8') as handle:
        json.dump(proof, handle, indent=2)
    process.stdin.write(b'{"action":"stop"}\n')
    process.stdin.flush()
    code = process.wait(timeout=15)
    if code != 0 or any(p.is_running() for p in descendants):
        raise RuntimeError('Original manual environment exit is unconfirmed')
    actor._check_owner()
    actor.store.complete_waiting(manual_id, actor.owner_id, actor.generation, result={
        'window_closed': True, 'identity_verified': False, 'account_pause_changed': False,
        'close_source': 'manual_window_visibility_upgrade', 'state_saved': True,
        'original_window_receipt': command['result']})
    resource.manual_tasks.pop(manual_id)
    resource.shutdown()
    resource.headless = True
    proof.update(exit_code=code, worker_exited=True, descendants_exited=True, finished_at=time.time())
    (checkpoint / 'CLOSE_COMPLETED.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
    return True


def install_if_armed():
    if not ARM.exists():
        return
    config = json.loads(ARM.read_text(encoding='utf-8'))
    if os.getpid() != config['backend_pid']:
        return
    import psutil
    if psutil.Process().create_time() != config['backend_create_time']:
        return
    for thread in threading.enumerate():
        target = getattr(thread, '_target', None)
        if (thread.name != 'AccountBrowser-' + config['account_key'] or not thread.is_alive()
                or getattr(target, '__name__', '') != '_host'
                or Path(target.__code__.co_filename).resolve() != ROOT / 'src/operations_accounts/browser_control_runtime.py'
                or getattr(thread, '_args', ()) != (config['account_key'],)):
            continue
        namespace = target.__globals__
        previous = namespace['_poll_manual_windows']
        if getattr(previous, '_manual_visibility_deployment', False):
            return
        def poll(actor, resource):
            if close_for_upgrade(actor, resource, config, CHECKPOINT):
                return
            return previous(actor, resource)
        poll._manual_visibility_deployment = True
        namespace['_poll_manual_windows'] = poll
        (CHECKPOINT / 'INSTALLED.json').write_text(json.dumps({'backend_pid': os.getpid(),
            'owner_id': config['owner_id'], 'generation': config['generation'],
            'thread_name': thread.name, 'at': time.time()}, indent=2), encoding='utf-8')
        return
