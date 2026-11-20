"""Reclaim only idle ownership that provably predates this host boot."""
import math
import os
from pathlib import Path
import re

from .browser_control import _json


def _boot_evidence():
    import psutil
    process=psutil.Process(os.getpid())
    root=Path(__file__).resolve().parents[2]
    if str(root/'scripts/run_streamlit_web.py').casefold() not in [str(Path(x)).casefold() for x in process.cmdline()[1:]]:
        return None
    return {'boot_time':psutil.boot_time(),'backend_pid':process.pid,'backend_create_time':process.create_time()}


def read_owner(store,account_id):
    with store._db() as db:
        row=db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',(account_id,)).fetchone()
        return dict(row) if row else None


def release_previous_boot_owner(store,account_id,expected_owner):
    """Resume only durably proven pre-handler work from a previous host boot."""
    evidence=_boot_evidence()
    if not evidence:return False
    boot=evidence['boot_time'];created=evidence['backend_create_time'];now=store.clock()
    if (any(type(v) not in (int,float) or not math.isfinite(v) for v in (boot,created,now))
            or not 0<boot<=created<=now or not expected_owner
            or not re.fullmatch(r'backend:[1-9][0-9]*:[a-f0-9]+',expected_owner['owner_id'])):return False
    if (expected_owner['state']=='released' or expected_owner['heartbeat']>=boot-5
            or expected_owner['updated_at']>=boot-5):return False
    with store._db(write=True) as db:
        row=db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',(account_id,)).fetchone()
        if not row or dict(row)!=expected_owner:return False
        from .publication_autonomous_reconciliation import unresolved
        pending = unresolved(store,db,account_id,('running','paused','waiting_human','outcome_unknown'))
        from . import browser_execution_journal as execution
        safe = []
        blocked = []
        for command in pending:
            stage = db.execute('SELECT * FROM browser_control_execution WHERE command_id=?', (command['command_id'],)).fetchone() if execution.exists(db) else None
            proven = (command['state'] == 'running' and stage is not None
                and stage['phase'] == 'admission_pending' and stage['handler_entered'] == 0
                and command['owner_id'] == stage['owner_id'] == expected_owner['owner_id']
                and command['generation'] == stage['generation'] == expected_owner['generation']
                and command['binding_version'] == expected_owner['binding_version']
                and command['request_sha'] == stage['request_sha']
                and 0 < stage['updated_at'] < boot-5 and 0 < command['updated_at'] < boot-5)
            (safe if proven else blocked).append(command)
        db.execute('''CREATE TABLE IF NOT EXISTS browser_control_boot_checks(
            account_id TEXT NOT NULL,boot_time REAL NOT NULL, evidence TEXT NOT NULL,
            checked_at REAL NOT NULL,PRIMARY KEY(account_id,boot_time))''')
        diagnostic = _json({'owner_id':expected_owner['owner_id'],'generation':expected_owner['generation'],
            'status':'blocked_execution_unknown' if blocked else 'recovered',
            'blocked':[{'command_id':c['command_id'],'state':c['state'],'kind':c['kind']} for c in blocked],
            'pre_handler_ids':[c['command_id'] for c in safe]})
        prior = db.execute('SELECT evidence FROM browser_control_boot_checks WHERE account_id=? AND boot_time=?',(account_id,boot)).fetchone()
        if not prior or prior[0] != diagnostic:
            db.execute('INSERT OR REPLACE INTO browser_control_boot_checks VALUES(?,?,?,?)',(account_id,boot,diagnostic,now))
        if blocked:return False
        db.execute('''CREATE TABLE IF NOT EXISTS browser_control_boot_recoveries(
            recovery_id INTEGER PRIMARY KEY,account_id TEXT NOT NULL,original_owner TEXT NOT NULL,
            boot_evidence TEXT NOT NULL,recovered_at REAL NOT NULL)''')
        db.execute('INSERT INTO browser_control_boot_recoveries(account_id,original_owner,boot_evidence,recovered_at) VALUES(?,?,?,?)',
            (account_id,_json(expected_owner),_json(dict(evidence,unexecuted_commands=safe)),now))
        for command in safe:
            execution.record(db,command,'recovered_before_handler',now)
            db.execute("""UPDATE browser_control_commands SET state='queued',owner_id=NULL,generation=NULL,
                error_code='recovered_before_handler',updated_at=? WHERE command_id=?""",(now,command['command_id']))
        db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=?",(now,account_id))
        return True
