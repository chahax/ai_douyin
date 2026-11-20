"""Test current public API on main/worker threads, blank profiles only."""
from pathlib import Path
import hashlib
import json
import sys
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/qa/browser_history_compare_20261105'
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'.local_py/site-packages'))


def main():
    run=OUT/('api_'+uuid.uuid4().hex)
    run.mkdir(parents=True)
    log=(run/'QA.log').open('a',encoding='utf-8',buffering=1)
    sys.stdout=sys.stderr=log
    from src.platform_adapter.browser_session import BrowserSession
    from src.platform_adapter.models import BrowserSessionConfig
    from src.operations_accounts.interactive_desktop import current_desktop_name
    from qa_browser_token_metadata_20261105 import metadata
    import psutil
    assert current_desktop_name()=='Default'
    results=[]
    for in_thread,plain_reader in [(False,False),(True,False),(True,True),(True,False)]:
        case=run/str(len(results)+1)
        case.mkdir()
        session=BrowserSession(BrowserSessionConfig(base_url='about:blank',home_url='about:blank',
            user_data_dir=str(case/'profile'),storage_state_path=str(case/'no_auth.json'),
            headless=True,mute_audio=True,browser_channel='chrome',timeout_ms=30000))
        record={'threaded':in_thread,'plain_stderr_reader':plain_reader,'started_at':time.time(),
            'source_sha256':hashlib.sha256((ROOT/'src/platform_adapter/browser_session.py').read_bytes()).hexdigest(),
            'production_profile_used':False}
        stages=[]
        frames=[]
        if plain_reader:
            # QA diagnostic variant to distinguish logging/pipe timing. No
            # replacement of the production module or original backend objects.
            def reader(process):
                for line in process.stderr:
                    try:
                        event=json.loads(line)
                        if event.get('browser_worker_stage') in {'importing_playwright','starting_driver',
                                'launching_browser','restoring_state','ready'}:
                            session._worker_stage=event['browser_worker_stage']
                            stages.append({'stage':session._worker_stage,'at':time.time()})
                    except (ValueError,AttributeError):pass
            session._read_worker_stages=reader
        stop=threading.Event()
        def monitor():
            seen=set()
            while not stop.wait(.1):
                try:
                    proc=session._proc
                    if proc:
                        for child in psutil.Process(proc.pid).children(recursive=True):
                            if child.pid in seen:continue
                            seen.add(child.pid)
                            name=child.name()
                            if name.lower()=='node.exe':
                                exe=Path(child.exe())
                                frames.append({'pid':child.pid,'name':name,'token_flags':metadata(child.pid),
                                    'venv_driver':exe==ROOT/'.venv/Lib/site-packages/playwright/driver/node.exe'})
                except (psutil.NoSuchProcess,psutil.AccessDenied):pass
        watcher=threading.Thread(target=monitor,daemon=True);watcher.start()
        def exercise():
            try:
                start=time.monotonic()
                page=session.new_tab('manual')
                page.goto('about:blank')
                record.update(ready=True,local_rpc=page.url=='about:blank',ready_seconds=round(time.monotonic()-start,3))
                proc=session._proc
                family=psutil.Process(proc.pid).children(recursive=True)
                session.stop()
                code=proc.poll()
                _,alive=psutil.wait_procs(family,timeout=5)
                record.update(status='passed' if record['local_rpc'] and code==0 and not alive else 'failed',
                    normal_exit_code=code,known_family_stopped=not alive)
            except Exception as exc:
                record.update(status='failed',error_type=type(exc).__name__,
                    startup_evidence=getattr(exc,'startup_evidence',{}))
        if in_thread:
            worker=threading.Thread(target=exercise,name='AccountBrowser-QA-only')
            worker.start();worker.join(timeout=75)
            if worker.is_alive():
                record.update(status='failed',outer_timeout=True)
                if session._proc:session._discard_starting_worker()
                worker.join(timeout=8)
                if worker.is_alive():
                    raise RuntimeError('QA caller still active; do not continue with next case')
        else:exercise()
        stop.set();watcher.join(timeout=2)
        record.update(finished_at=time.time(),driver_process_flags=frames,stages=stages)
        (case/'RESULT.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        results.append(record)
        (OUT/'API_LATEST.json').write_text(json.dumps({'run':str(run.relative_to(ROOT)),'results':results},indent=2),encoding='utf-8')
    return 0 if all(r['status']=='passed' for r in results) else 1


if __name__=='__main__':raise SystemExit(main())
