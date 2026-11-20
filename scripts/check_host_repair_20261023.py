"""Read-only check of original-ID continuation; writes evidence only."""
import hashlib,json,sqlite3,time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import urllib.request
import psutil

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/account_host_repair/20261023'


def main():
    original=json.loads((OUT/'DEPLOYMENT.json').read_text(encoding='utf-8'))
    patch=OUT/'CLEANUP_GUARD.json'
    if patch.exists():
        proof=json.loads(patch.read_text(encoding='utf-8'))
        assert proof['phase']=='applied'
        key=next(k for k in original['sources'] if Path(k)==Path(proof['source']))
        original['sources'][key]=proof['source_sha256']
    def read(name,q,args=()):
        with sqlite3.connect((ROOT/'data'/name).as_uri()+'?mode=ro',uri=True,timeout=3) as db:
            db.row_factory=sqlite3.Row
            return [dict(r) for r in db.execute(q,args)]
    pid=int((ROOT/'data/logs/streamlit_web.pid').read_text())
    proc=psutil.Process(pid)
    assert str(ROOT/'scripts/run_streamlit_web.py') in proc.cmdline()
    commands=read('account_browser_control.db','SELECT command_id,kind,state,error_code,owner_id,generation,created_at,updated_at,result FROM browser_control_commands WHERE account_id=? AND (created_at>=? OR command_id=?) ORDER BY created_at',
        (original['command']['account_id'],original['at'],original['command']['command_id']))
    for c in commands:
        result=json.loads(c.pop('result') or '{}')
        if c['kind']=='maintenance':
            m=result.get('maintenance_result',{})
            c['summary']={k:m.get(k) for k in ('status','error_code','failure_stage','login_healthy','synced_videos','synced_comments','comment_sync_failures','actual_watch_seconds','log_path')}
        else:c['summary']={k:result.get(k) for k in ('healthy','status','expected_account_uuid')}
    old_run=read('account_refresh.db','SELECT * FROM refresh_runs WHERE run_id=?',(original['run']['run_id'],))[0]
    links=read('account_refresh.db','SELECT run_id,command_id,state,settlement FROM refresh_browser_commands WHERE run_id=?',(original['run']['run_id'],))
    current=read('account_browser_control.db','SELECT request_sha,payload,command_id FROM browser_control_commands WHERE command_id=?',(original['command']['command_id'],))[0]
    out={'at':time.time(),'local_time':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'pid':pid,'created_at':proc.create_time(),
        'http_status':urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health',timeout=5).status,
        'sources_match':all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha for p,sha in original['sources'].items()),
        'original_failed_run_preserved':old_run==original['run'],
        'original_request_preserved':current['request_sha']==original['command']['request_sha'] and json.loads(current['payload'])==original['command']['payload'],
        'commands':commands,'links':links,
        'controls':read('account_refresh.db','SELECT account_key,state,error_code,revision FROM account_controls'),
        'components':read('account_refresh.db','SELECT component,status,error_code,updated_at FROM automation_service'),
        'owners':read('account_browser_control.db','SELECT owner_id,generation,state,heartbeat FROM browser_control_owners')}
    p=OUT/('VERIFY_'+str(time.time_ns())+'.json');p.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(out,ensure_ascii=False))


if __name__=='__main__':main()
