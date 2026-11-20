"""Read-only service/task sampling; writes only local monitoring evidence."""
import datetime
import json
from pathlib import Path
import sqlite3
import time
import urllib.request
import sys

import psutil

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/service_startup_monitor'
sys.path.insert(0,str(ROOT))


def read_rows(name,sql):
    with sqlite3.connect((ROOT/'data'/name).as_uri()+'?mode=ro',uri=True,timeout=2)as db:
        db.row_factory=sqlite3.Row
        return [dict(row)for row in db.execute(sql)]


def read_unresolved_commands():
    """Reuse the verified historical settlement rules, with a read-only handle."""
    from src.operations_accounts.browser_control import BrowserControlStore
    from src.operations_accounts.publication_autonomous_reconciliation import unresolved
    columns=('command_id','kind','state','error_code','created_at','updated_at')
    with sqlite3.connect((ROOT/'data/account_browser_control.db').as_uri()+'?mode=ro',
                        uri=True,timeout=2) as db:
        db.row_factory=sqlite3.Row
        accounts=[r[0] for r in db.execute('SELECT DISTINCT account_id FROM browser_control_commands')]
        rows=[]
        for account in accounts:
            # _command is static; do not construct a store or initialize schemas.
            rows.extend(unresolved(BrowserControlStore,db,account,
                ('queued','running','paused','waiting_human','outcome_unknown')))
        return [{k:row[k] for k in columns} for row in rows]


def sample():
    now=time.time();boot=psutil.boot_time()
    report={'schema':'service_startup_monitor/v1','checked_at':now,'boot_time':boot,'startup_grace_seconds':300,
        'backend':{},'components':[],'owners':[],'commands':[],'controls':[],'problems':[]}
    try:
        pid=int((ROOT/'data/logs/streamlit_web.pid').read_text().strip());p=psutil.Process(pid)
        command=p.cmdline();created=p.create_time()
        expected=str(ROOT/'scripts/run_streamlit_web.py').casefold()
        valid=expected in [str(Path(x)).casefold()for x in command[1:]]and created>=boot
        report['backend']={'pid':pid,'created_at':created,'identity_verified':valid}
        if not valid:report['problems'].append('backend_identity_unverified')
    except Exception as exc:report['problems'].append('backend_unavailable:'+type(exc).__name__)
    try:
        report['http_status']=urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health',timeout=5).status
        if report['http_status']!=200:report['problems'].append('web_unhealthy')
    except Exception as exc:report['problems'].append('web_unavailable:'+type(exc).__name__)
    for key,name,sql in (
        ('components','account_refresh.db','SELECT * FROM automation_service'),
        ('owners','account_browser_control.db','SELECT * FROM browser_control_owners'),
        ('controls','account_refresh.db','SELECT account_uuid,account_key,state,reason,error_code,revision FROM account_controls')):
        try:report[key]=read_rows(name,sql)
        except Exception as exc:report['problems'].append(key+'_unknown:'+type(exc).__name__)
    try:report['commands']=read_unresolved_commands()
    except Exception as exc:report['problems'].append('commands_unknown:'+type(exc).__name__)
    for component in report['components']:
        component['age_seconds']=round(now-component['updated_at'],1)
        if now-boot>300 and (component['age_seconds']>180 or component['status']not in('healthy','running')):
            report['problems'].append('component:'+component['component']+':'+component['status'])
    expected={'scheduler','worker','account_refresh','browser_control','playback','playback_schedule','manual_windows'}
    if now-boot>300:
        for name in sorted(expected-{c['component']for c in report['components']}):
            report['problems'].append('component_missing:'+name)
    queued=bool(report['commands'])
    for owner in report['owners']:
        if queued and owner['state']!='released' and owner['heartbeat']<boot-5:
            report['problems'].append('previous_boot_owner_blocks_queue')
        elif queued and owner['state']!='released' and now-owner['heartbeat']>180:
            report['problems'].append('owner_heartbeat_expired')
    for control in report['controls']:
        if control['state']!='active':report['problems'].append('account:'+control['account_key']+':'+control['state'])
    for command in report['commands']:
        if command['state']=='outcome_unknown':report['problems'].append('task_outcome_unknown:'+command['command_id'])
        if command['state']=='waiting_human':report['problems'].append('task_waiting_human:'+command['command_id'])
        if command['state']=='running' and now-command['updated_at']>1800:
            report['problems'].append('task_no_progress_30min:'+command['command_id'])
    report['status']='attention'if report['problems']else'healthy'
    OUT.mkdir(parents=True,exist_ok=True)
    previous={}
    try:previous=json.loads((OUT/'LATEST.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):pass
    report['meaningful_change']=(previous.get('boot_time')!=boot or previous.get('problems')!=report['problems'])
    stamp=datetime.datetime.fromtimestamp(now,datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    (OUT/(stamp+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'LATEST.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    report=sample()
    print(json.dumps({k:report[k]for k in('status','backend','problems','meaningful_change')},ensure_ascii=False))
