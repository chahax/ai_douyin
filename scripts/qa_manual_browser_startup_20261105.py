"""One-shot native QA, clean local profile only. Never imports account runtime."""
from pathlib import Path
import json
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.local_py/site-packages'))
OUT = ROOT / 'data/qa/manual_browser_startup_20261105'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    case = ('headed' if '--headed' in sys.argv else 'headless') + '_' + uuid.uuid4().hex
    directory = OUT / case
    directory.mkdir()
    if '--private-profile' in sys.argv:
        # New QA directory only; no ACL edits to any original profile.
        (directory/'profile').mkdir(mode=0o700)
    # Match the production pythonw entry: log sinks need real streams.
    log = (directory/'QA.log').open('a', encoding='utf-8', buffering=1)
    sys.stdout = sys.stderr = log
    if '--native-pytest' in sys.argv:
        import pytest
        code = pytest.main([str(ROOT/'tests/test_fanqie_account_control.py') +
            '::test_real_worker_identity_rpc_is_fail_closed_on_local_page', '-q',
            '--basetemp=' + str(directory/'pytest'), '--junitxml=' + str(directory/'native.xml')])
        (directory/'RESULT.json').write_text(json.dumps({'status':'passed' if code == 0 else 'failed',
            'mode':'original_native_pytest', 'pytest_code':int(code), 'production_profile_used':False,
            'finished_at':time.time()}), encoding='utf-8')
        return int(code)
    if '--venv-driver' in sys.argv:
        import os
        import hashlib
        primary = ROOT/'.venv/Lib/site-packages/playwright/driver/node.exe'
        fallback = ROOT/'.local_py/site-packages/playwright/driver/node.exe'
        assert hashlib.sha256(primary.read_bytes()).digest() == hashlib.sha256(fallback.read_bytes()).digest()
        os.environ['PLAYWRIGHT_NODEJS_PATH'] = str(primary)
    # Do not use production profile, auth snapshot or platform URL.
    from src.platform_adapter.browser_session import BrowserSession
    from src.platform_adapter.models import BrowserSessionConfig
    if '--diagnose-local' in sys.argv:
        # QA-only worker: its profile is new, unauthenticated and about:blank.
        # Capture only the first launch error line, never the launch call-log.
        from src.platform_adapter import browser_session as module
        module._PW_SCRIPT = module._PW_SCRIPT.replace(
            'evidence = dict(classify(exc), stage=_last_stage)',
            "sys.stderr.write(json.dumps({'qa_local_error_line': str(exc).splitlines()[0][:500], 'qa_local_stderr': [line[:700] for line in str(exc).splitlines() if '[err]' in line][:12]}) + '\\n'); sys.stderr.flush()\n        evidence = dict(classify(exc), stage=_last_stage)")
        def read_stages(self, process):
            # Filter exclusively the tagged QA first line; all other raw stderr
            # stays discarded. No full traceback/argv/auth is persisted.
            import re
            for line in process.stderr:
                try: event = json.loads(line)
                except (ValueError, UnicodeError): continue
                if 'qa_local_error_line' in event:
                    message = re.sub(r'https?://\S+', '<url>', event['qa_local_error_line'])
                    (directory/'LOCAL_LAUNCH_ERROR.json').write_text(json.dumps({'first_line':message,
                        'local_test_only_browser_errors': event.get('qa_local_stderr', [])}), encoding='utf-8')
                elif event.get('browser_worker_stage') in {'importing_playwright','starting_driver','launching_browser','restoring_state'}:
                    self._worker_stage = event['browser_worker_stage']
        module.BrowserSession._read_worker_stages = read_stages
    from src.operations_accounts.interactive_desktop import current_desktop_name
    import psutil
    import threading
    trace_stop = threading.Event()
    trace = []
    def trace_family():
        from qa_browser_token_metadata_20261105 import metadata
        seen = set()
        while not trace_stop.wait(.02):
            try:
                processes = [psutil.Process()] + psutil.Process().children(recursive=True)
                for process in processes:
                    if process.pid not in seen:
                        seen.add(process.pid)
                        trace.append({'pid':process.pid, 'name':process.name(), 'token':metadata(process.pid)})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    monitor = None
    if '--trace-process' in sys.argv:
        monitor = threading.Thread(target=trace_family, daemon=True)
        monitor.start()
    result = {'case': case, 'started_at': time.time(), 'desktop': current_desktop_name(),
              'status': 'started', 'production_profile_used': False,
              'chromium_sandbox': '--sandbox-on' in sys.argv,
              'driver_source':'same_sha_project_venv' if '--venv-driver' in sys.argv else 'existing_default'}
    session = BrowserSession(BrowserSessionConfig(base_url='about:blank', home_url='about:blank',
        user_data_dir=str(directory/'profile'), storage_state_path=str(directory/'never_authenticated.json'),
        headless=not case.startswith('headed_'), mute_audio=True, timeout_ms=10000,
        chromium_sandbox='--sandbox-on' in sys.argv))
    family = []
    try:
        if result['desktop'] != 'Default':
            raise RuntimeError('QA requires original interactive desktop')
        page = session.get_page()
        family = psutil.Process(session._proc.pid).children(recursive=True)
        result['ready'] = True
        result['rpc_identity'] = page._cmd('fanqie_identity', reset=True)['evidence']['verified'] is False
        result['rpc_window_open'] = session.window_status()['open'] is True
        result['status'] = 'passed' if result['rpc_identity'] and result['rpc_window_open'] else 'failed'
    except Exception as exc:
        result.update(status='failed', error_type=type(exc).__name__,
            startup_evidence=getattr(exc, 'startup_evidence', {}))
    finally:
        session.stop()
        trace_stop.set()
        if monitor:
            monitor.join(timeout=2)
            (directory/'PROCESS_FLAGS.json').write_text(json.dumps(trace, indent=2), encoding='utf-8')
        try:
            _, alive = psutil.wait_procs(family, timeout=5)
            result['observed_family_stopped'] = (not alive if result.get('ready') else
                result.get('startup_evidence', {}).get('cleanup_verified') is True)
        except Exception:
            result['observed_family_stopped'] = False
        result['finished_at'] = time.time()
        (directory/'RESULT.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        (OUT/('LAST_HEADED.json' if case.startswith('headed_') else 'LAST_HEADLESS.json')).write_text(
            json.dumps(result, indent=2), encoding='utf-8')
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    try:
        code = main()
    except Exception as exc:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT/'BOOTSTRAP_FAILURE.json').write_text(json.dumps({
            'status': 'failed', 'stage': 'qa_bootstrap', 'error_type': type(exc).__name__,
            'captured_at': time.time()}), encoding='utf-8')
        code = 2
    raise SystemExit(code)
