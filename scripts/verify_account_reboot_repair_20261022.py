"""Read-only production verification, writing only this repair's evidence."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/account_reboot_repair/20261022'


def main():
    import psutil
    before=json.loads((OUT/'DEPLOY_STOP.json').read_text(encoding='utf-8'))
    expected_sources=dict(before['sources'])
    guard_path=OUT/'GUARD_PATCH.json'
    if guard_path.exists():
        guard=json.loads(guard_path.read_text(encoding='utf-8'))
        assert guard['phase']=='applied' and guard['pid']==int((ROOT/'data/logs/streamlit_web.pid').read_text())
        expected_sources['src/operations_accounts/browser_control.py']=guard['source_sha256']
    def read(name,query,args=()):
        with closing(sqlite3.connect((ROOT/'data'/name).as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
            db.row_factory=sqlite3.Row
            return [dict(r) for r in db.execute(query,args)]
    account=before['original_owners'][0]['account_id']
    pid=int((ROOT/'data/logs/streamlit_web.pid').read_text())
    process=psutil.Process(pid)
    assert str(ROOT/'scripts/run_streamlit_web.py') in process.cmdline()
    controls=read('account_refresh.db','SELECT account_uuid,account_key,state,error_code,revision FROM account_controls')
    commands=read('account_browser_control.db', '''SELECT command_id,kind,state,error_code,owner_id,generation,created_at,updated_at
        FROM browser_control_commands WHERE account_id=? AND created_at>=? ORDER BY created_at''',(account,before['at']))
    checks=read('account_browser_control.db',"SELECT command_id,result FROM browser_control_commands WHERE account_id=? AND kind='recovery' AND created_at>=?",(account,before['at']))
    proof=[]
    for check in checks:
        result=json.loads(check['result']) if check['result'] else {}
        proof.append({'command_id':check['command_id'],**{k:result.get(k) for k in ('healthy','status','expected_account_uuid')}})
    old=read('account_browser_control.db','SELECT original_command FROM browser_control_operator_disposals WHERE command_id=?',
             (before['original_commands'][0]['command_id'],))[0]
    stages=read('account_browser_control.db', '''SELECT e.command_id,e.phase,e.handler_entered,e.generation,e.updated_at
        FROM browser_control_execution e JOIN browser_control_commands c ON c.command_id=e.command_id
        WHERE c.account_id=? AND c.created_at>=?''',(account,before['at']))
    report={'at':time.time(),'pid':pid,'created_at':process.create_time(),
        'http_status':urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health',timeout=5).status,
        'source_hashes_match_deployment':all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha for name,sha in expected_sources.items()),
        'original_manual_snapshot_preserved':json.loads(old['original_command'])==before['original_commands'][0],
        'controls':controls,'identity_probes':proof,'commands_since_deploy':commands,'execution_stages':stages,
        'components':read('account_refresh.db','SELECT component,status,error_code,updated_at FROM automation_service'),
        'owners':read('account_browser_control.db','SELECT account_id,owner_id,generation,state,heartbeat FROM browser_control_owners')}
    target=OUT/f'PRODUCTION_VERIFY_{int(report["at"])}.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
