"""Normal original-owner shutdown after the user reports handling finished.

Deployment-only, one shot. Never verifies identity, resumes plans, solves a
challenge, terminates processes, or infers closure merely from a user statement.
"""
import json
from pathlib import Path
import time


def close_original_environment(actor,resource,config,checkpoint):
    if config.get('user_statement')!='已关闭' or not config.get('close_original_environment'):
        return False
    checkpoint=Path(checkpoint)
    started=checkpoint/'ORIGINAL_ENVIRONMENT_CLOSE_STARTED.json'
    if started.exists():return False  # Unknown IPC outcome is never replayed.
    actor._assert_thread();actor._check_owner()
    if actor._stack or getattr(resource,'console_tasks',{}) or set(resource.manual_tasks)!={config['manual_id']}:
        return False
    command=actor.store.get(config['manual_id'])
    tab_id=resource.manual_tasks[config['manual_id']]
    if (not command or command['kind']!='manual' or command['state']!='waiting_human'
            or command['owner_id']!=actor.owner_id or command['generation']!=actor.generation
            or (command.get('result')or{}).get('tab_id')!=tab_id):
        return False
    with actor.store._db()as db:
        if db.execute("SELECT 1 FROM browser_control_commands WHERE account_id=? AND command_id!=? AND state IN ('running','paused','waiting_human','outcome_unknown') LIMIT 1",
                (actor.account_id,config['manual_id'])).fetchone():
            return False
    session=resource.session
    status=session.window_status()
    if any(not r.get('closed') and r.get('role') in {'manual','official_console'} and r.get('tab_id')!=tab_id for r in status.get('tabs',[])):
        return False
    from src.platform_adapter.douyin_challenge import confirmed_douyin_challenge
    current=confirmed_douyin_challenge(session.get_page(tab_id))
    if current.get('blocking') is not False or current.get('surface_state')!='clear':
        (checkpoint/'ORIGINAL_ENVIRONMENT_CLOSE_BLOCKED.json').write_text(json.dumps(
            {'reason':'current_verification_not_clear','blocking':current.get('blocking'),'surface_state':current.get('surface_state')}),encoding='utf8')
        return False
    # Native save-state acknowledgement precedes the normal stop message. No
    # authentication snapshot is read or copied by this deployment helper.
    saved=session._send({'action':'save_state','path':session.config.storage_state_path})
    if saved.get('state_saved') is not True:
        return False
    import psutil
    process=session._proc
    descendants=psutil.Process(process.pid).children(recursive=True)
    observed=[{'pid':p.pid,'create_time':p.create_time()}for p in descendants]
    proof={'manual_id':config['manual_id'],'owner_id':actor.owner_id,'generation':actor.generation,
           'worker_pid':process.pid,'observed_children':observed,'state_saved':True,'at':time.time()}
    with started.open('x',encoding='utf8')as handle:json.dump(proof,handle,indent=2)
    # The project's stop protocol deliberately has no response line: it closes
    # the context/driver and exits. Wait for that real exit, without any kill.
    process.stdin.write(b'{"action":"stop"}\n');process.stdin.flush()
    code=process.wait(timeout=15)
    if code!=0 or any(p.is_running() for p in descendants):
        raise RuntimeError('Original environment exit not confirmed')
    actor._check_owner()
    actor.store.complete_waiting(config['manual_id'],actor.owner_id,actor.generation,
        result={'window_closed':True,'identity_verified':False,'account_pause_changed':False,
                'close_source':'original_owner_graceful_environment_exit','state_saved':True})
    resource.manual_tasks.pop(config['manual_id'])
    resource.shutdown()  # Process already exited; no termination fallback is needed.
    resource.headless=True
    proof.update(exit_code=code,worker_exited=True,descendants_exited=True,finished_at=time.time())
    (checkpoint/'ORIGINAL_ENVIRONMENT_CLOSE_COMPLETED.json').write_text(json.dumps(proof,indent=2),encoding='utf8')
    return True
