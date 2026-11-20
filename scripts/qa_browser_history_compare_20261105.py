"""Bounded historical worker A/B test: blank page, fresh profile, no accounts.

Only extracts the historical _PW_SCRIPT literal, never imports the old module.
All variants use the same installed project driver and a 45-second outer bound.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'data/qa/browser_history_compare_20261105'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'.local_py/site-packages'))


def extract(path):
    source=path.read_text(encoding='utf-8-sig')
    tree=ast.parse(source)
    for item in tree.body:
        if isinstance(item,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_PW_SCRIPT' for t in item.targets):
            return ast.literal_eval(item.value)
    raise ValueError('Historical worker literal not found')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    run=OUT/uuid.uuid4().hex
    run.mkdir()
    log=(run/'QA.log').open('a',encoding='utf-8',buffering=1)
    sys.stdout=sys.stderr=log
    from src.platform_adapter.browser_session import BrowserSession
    from src.platform_adapter.models import BrowserSessionConfig
    from src.operations_accounts.interactive_desktop import current_desktop_name
    import psutil
    assert current_desktop_name()=='Default'
    variants=[('current',ROOT/'src/platform_adapter/browser_session.py',True),
        ('nov3_backup_not_exact_success_sha',ROOT/'data/development_checkpoints/manual_window_visibility_20261103/before/src/platform_adapter/browser_session.py',True),
        ('git_sep10',ROOT/'data/development_checkpoints/browser_history_compare_20261105/GIT_3251b13_browser_session.py',False)]
    results=[]
    for repetition in range(2):
        for name,path,skip_site in variants:
            case=run/(str(repetition+1)+'_'+name)
            case.mkdir()
            assert case.resolve().is_relative_to(OUT.resolve())
            worker=extract(path)
            # QA-only timing around the same real driver call, without browser
            # content/argv tracing. Historical source remains unchanged on disk.
            mark="def _history_mark(name):\n    sys.stderr.write(json.dumps({'history_stage':name})+'\\n'); sys.stderr.flush()\n"
            pattern=r'^(\s*)pw = sync_playwright\(\)\.start\(\)$'
            matches=list(re.finditer(pattern,worker,re.MULTILINE))
            assert len(matches)==1
            match=matches[0]
            indent=match.group(1)
            # Preserve indentation if a newer worker wraps driver start in a
            # diagnostics context. The original version bytes stay unchanged.
            replacement=indent+"_history_mark('driver_begin')\n"+match.group(0)+"\n"+indent+"_history_mark('driver_ready')"
            worker=worker[:match.start()]+replacement+worker[match.end():]
            worker=mark+worker
            config=BrowserSessionConfig(base_url='about:blank',home_url='about:blank',
                user_data_dir=str(case/'profile'),storage_state_path=str(case/'no_auth.json'),
                headless=True,mute_audio=True,browser_channel='chrome',chromium_sandbox=True,timeout_ms=10000)
            session=BrowserSession(config)
            session._ensure_runtime_paths()
            env=session._build_child_env()
            node=ROOT/'.venv/Lib/site-packages/playwright/driver/node.exe'
            assert Path(env['PLAYWRIGHT_NODEJS_PATH']).resolve()==node.resolve()
            record={'variant':name,'repetition':repetition+1,'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'source':str(path.relative_to(ROOT)),'worker_original_sha256':hashlib.sha256(extract(path).encode()).hexdigest(),
                'skip_site':skip_site,'node_sha256':hashlib.sha256(node.read_bytes()).hexdigest(),
                'headless':True,'chromium_sandbox':True,'production_profile_used':False,'started_at':time.time()}
            stages=[]
            safe_stack=[]
            output=queue.Queue()
            def read_stderr(process):
                for line in process.stderr:
                    try:
                        item=json.loads(line)
                        stage=item.get('history_stage') or item.get('browser_worker_stage')
                        if stage in {'driver_begin','driver_ready','importing_playwright','starting_driver','launching_browser','restoring_state','ready'}:
                            stages.append({'stage':stage,'at':time.time()})
                    except (ValueError,AttributeError,UnicodeError):
                        # Preserve only stack function/line names, not raw logs.
                        match=re.search(r'File "([^\"]+)", line (\d+), in ([\w<>]+)',line.decode(errors='replace') if isinstance(line,bytes) else line)
                        if match:safe_stack.append({'file':Path(match[1]).name,'line':int(match[2]),'function':match[3]})
            args=[sys.executable]+(['-S'] if skip_site else [])+['-c',worker]
            process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                env=env,cwd=ROOT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            session._proc=process
            thread=threading.Thread(target=read_stderr,args=(process,),daemon=True);thread.start()
            threading.Thread(target=lambda:output.put(process.stdout.readline()),daemon=True).start()
            start=time.monotonic()
            try:
                init={'user_data_dir':config.user_data_dir,'storage_state_path':config.storage_state_path,
                    'headless':True,'mute_audio':True,'channel':'chrome','chromium_sandbox':True,
                    'timeout_ms':10000,'python_paths':session._child_python_paths()}
                process.stdin.write(json.dumps(init).encode()+b'\n');process.stdin.flush()
                line=output.get(timeout=45)
                response=json.loads(line or b'{}')
                record['ready']=response.get('status')=='ready'
                if record['ready']:
                    process.stdin.write(b'{"action":"current_url"}\n');process.stdin.flush()
                    q=queue.Queue()
                    threading.Thread(target=lambda:q.put(process.stdout.readline()),daemon=True).start()
                    rpc=json.loads(q.get(timeout=10) or b'{}')
                    record['rpc_local_page']=rpc.get('url')=='about:blank'
                    process.stdin.write(b'{"action":"stop"}\n');process.stdin.flush()
                    family=psutil.Process(process.pid).children(recursive=True)
                    code=process.wait(timeout=12)
                    _,alive=psutil.wait_procs(family,timeout=5)
                    record.update(status='passed' if record['rpc_local_page'] and code==0 and not alive else 'failed',
                                  normal_exit_code=code,known_family_stopped=not alive)
                else:
                    record.update(status='failed',startup_evidence=response.get('startup_evidence',{}))
            except Exception as exc:
                record.update(status='failed',error_type=type(exc).__name__)
            finally:
                if process.poll() is None:
                    session._discard_starting_worker()  # only this disposable QA family
                    record['forced_qa_cleanup_verified']=session._startup_cleanup_verified
                else:
                    session._proc=None
                thread.join(timeout=1)
                record.update(elapsed_seconds=round(time.monotonic()-start,3),stages=stages,
                              safe_stack=safe_stack,finished_at=time.time())
                (case/'RESULT.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
                results.append(record)
                (run/'PROGRESS.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
                (OUT/'LATEST.json').write_text(json.dumps({'run':str(run.relative_to(ROOT)),
                    'finished_cases':len(results),'results':results},indent=2),encoding='utf-8')
    return 0 if all(r['status']=='passed' for r in results) else 1


if __name__=='__main__':
    raise SystemExit(main())
