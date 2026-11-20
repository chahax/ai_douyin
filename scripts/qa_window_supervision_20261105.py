"""Native, two-profile local-only supervision acceptance on the interactive desktop."""
from pathlib import Path
import ctypes
import json
import os
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace as NS

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/qa/window_supervision_20261105/native'
sys.path.insert(0,str(ROOT))


def main():
    OUT.mkdir(parents=True,exist_ok=False)
    log=(OUT/'QA.log').open('a',encoding='utf8',buffering=1)
    sys.stdout=sys.stderr=log
    os.environ['DISABLE_SQLALCHEMY_CEXT_RUNTIME']='1'
    os.environ['AI_DOUYIN_WINDOW_SUPERVISION']='1'
    from src.platform_adapter.browser_session import BrowserSession
    from src.platform_adapter.models import BrowserSessionConfig
    from src.operations_accounts import window_supervision as windows, browser_control_runtime as bridge
    from src.operations_accounts.browser_control import BrowserControlActor,BrowserControlStore,BrowserControlDeferred
    from src.operations_accounts.interactive_desktop import current_desktop_name
    from src.scheduler import account_refresh as backend
    import psutil
    assert current_desktop_name()=='Default'
    windows.DB=OUT/'windows.db';bridge.DB=OUT/'owners.db';backend.DB=OUT/'controls.db'
    with sqlite3.connect(backend.DB) as db:
        db.execute('CREATE TABLE account_controls(account_uuid TEXT PRIMARY KEY,account_key TEXT,state TEXT)')
        db.executemany('INSERT INTO account_controls VALUES(?,?,?)',[('qa-alpha','QA alpha','active'),('qa-beta','QA beta','active')])
    class Local(BaseHTTPRequestHandler):
        def do_GET(self):
            title='QA supervision alpha' if self.path.startswith('/alpha') else 'QA independent beta'
            body=('<!doctype html><meta charset="utf-8"><title>'+title+'</title><h1>'+title+'</h1><p>Local synthetic test. No account, login or production data.</p><textarea aria-label="Independent input" rows="8" cols="65"></textarea><div id="counter">0</div>').encode()
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(body)
        def log_message(self,*_):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Local)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base='http://127.0.0.1:'+str(server.server_port)
    store=BrowserControlStore(bridge.DB)
    sessions=[];actors=[];records=[];families=[]
    before=int(ctypes.windll.user32.GetForegroundWindow())
    result={'started_at':time.time(),'production_profiles_used':False,'production_tasks_dispatched':False,'local_url':base,'checks':{}}
    def write(): (OUT/'RESULT.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    def admission(ctx,phase):
        with sqlite3.connect(backend.DB) as db:
            state=db.execute('SELECT state FROM account_controls WHERE account_uuid=?',(ctx.account_id,)).fetchone()[0]
        if state!='active':raise BrowserControlDeferred('human_required','QA pause')
    try:
        for account,name in [('qa-alpha','alpha'),('qa-beta','beta')]:
            windows.save(account,'QA '+name,True,'background',actor='QA admin',expected_revision=0,control_path=backend.DB)
            session=BrowserSession(BrowserSessionConfig(base_url=base,home_url=base+'/'+name,
                user_data_dir=str(OUT/(name+'_profile')),storage_state_path=str(OUT/(name+'_no_auth.json')),
                headless=False,mute_audio=True,start_minimized=True,browser_channel='chrome',chromium_sandbox=True,timeout_ms=10000))
            sessions.append(session)
            res=NS(account_uuid=account,account_key='QA '+name,headless=False,session=session,ensure_session=lambda s=session:s)
            def handler(ctx,payload,res=res,name=name):
                token=bridge._active.set(ctx)
                try:
                    borrowed=bridge.BorrowedSession(res,'maintenance')
                    borrowed.open_page(base+'/'+name)
                    borrowed.get_page().evaluate('document.querySelector("#counter").textContent="1"')
                    tab=borrowed.tab_id
                    borrowed.stop()
                    return {'tab_id':tab}
                finally:bridge._active.reset(token)
            actor=BrowserControlActor(store,account,'QA-binding-'+name,'QA-owner-'+name,{'maintenance':handler},admission=admission,context=res)
            actors.append(actor)
            original=store.submit(account,actor.binding_version,'maintenance','first',{})
            receipt=actor.run_next();assert receipt['state']=='succeeded'
            records.append((res,actor,receipt['result']['tab_id']))
            families.extend(psutil.Process(session._proc.pid).children(recursive=True))
        result['checks']['startup_kept_existing_foreground']=int(ctypes.windll.user32.GetForegroundWindow())==before
        result['checks']['two_distinct_worker_processes']=sessions[0]._proc.pid!=sessions[1]._proc.pid
        result['phase']='ready_for_observation';write()
        res,actor,tab=records[0]
        original_pid=sessions[0]._proc.pid
        previous=windows.runtime_snapshot(res.account_uuid)
        windows.save(res.account_uuid,res.account_key,True,'watch',actor='QA admin',expected_revision=previous['applied_revision'],target=previous,control_path=backend.DB)
        res._supervision_next=0;windows.synchronize(res,actor)
        result['checks']['display_did_not_steal_foreground']=int(ctypes.windll.user32.GetForegroundWindow())==before
        # Navigate/reuse the same task tab while the native window is expanded.
        store.submit(res.account_uuid,actor.binding_version,'maintenance','second',{})
        second=actor.run_next();assert second['state']=='succeeded'
        result['checks']['same_original_tab_reused']=second['result']['tab_id']==tab
        mode=sessions[0].get_page(tab)._cmd('supervision_window_state')
        result['checks']['expanded_window_remains_normal']=mode['window_state']=='normal'
        # Independent page contents must survive alpha's navigation and display.
        beta=sessions[1].get_page(records[1][2])
        beta.evaluate('document.querySelector("textarea").value="QA independent input unchanged"')
        beta_url=beta.url
        for i in range(8):
            store.submit(res.account_uuid,actor.binding_version,'maintenance','navigation-'+str(i),{})
            assert actor.run_next()['state']=='succeeded'
        result['checks']['other_profile_content_untouched']=beta.evaluate('document.querySelector("textarea").value')=='QA independent input unchanged' and beta.url==beta_url
        result['checks']['background_navigation_kept_foreground']=int(ctypes.windll.user32.GetForegroundWindow())==before
        with sqlite3.connect(backend.DB) as db:db.execute("UPDATE account_controls SET state='paused' WHERE account_uuid='qa-alpha'")
        pending=store.submit(res.account_uuid,actor.binding_version,'maintenance','paused-original',{})
        refused=actor.run_next()
        result['checks']['pause_blocks_handler']=refused['state']=='queued' and store.get(pending['command_id'])['state']=='queued'
        # Real time exceeding the production 120 second idle threshold.
        idle_start=time.monotonic();result['phase']='idle_persistence';write()
        while time.monotonic()-idle_start<125:
            for resource,owner,_ in records:
                owner._check_owner(renew=True)
                resource._supervision_next=0;windows.synchronize(resource,owner)
                assert windows.keep_idle_window(resource)
            time.sleep(2)
        result['checks']['idle_over_120_seconds_same_worker']=sessions[0]._proc.pid==original_pid and sessions[0]._proc.poll() is None
        result['checks']['idle_same_tab_still_open']=any(r['tab_id']==tab and not r['closed'] for r in sessions[0].list_tabs())
        # Explicit display-close is not an identity or recovery acknowledgement.
        result['checks']['no_recovery_or_publish_requests']=not any(c['kind']!='maintenance' for a in ('qa-alpha','qa-beta') for c in store.snapshot(a)['commands'])
        result['phase']='completed'
        result['status']='passed' if all(result['checks'].values()) else 'failed'
    except Exception as exc:
        result.update(status='failed',error_type=type(exc).__name__,local_qa_error=str(exc).splitlines()[0][:300])
    finally:
        for actor in actors:actor.stop_heartbeat()
        codes=[]
        for session in sessions:
            process=session._proc
            session.stop()
            codes.append(process.poll() if process else None)
        _,alive=psutil.wait_procs(families,timeout=6)
        result['normal_exit_codes']=codes;result['qa_family_stopped']=not alive
        result['finished_at']=time.time();write();server.shutdown()
    return 0 if result.get('status')=='passed' and not alive and all(code==0 for code in codes) else 1


if __name__=='__main__':raise SystemExit(main())
