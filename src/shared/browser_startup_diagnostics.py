"""Allowlisted startup facts. Never retain browser messages, argv, URLs or state."""
import re
from pathlib import Path

STAGES = frozenset({'not_started', 'spawning_worker', 'importing_playwright',
    'starting_driver', 'launching_browser', 'restoring_state', 'ready'})
CODES = frozenset({'unknown', 'startup_timeout', 'executable_missing', 'profile_in_use',
    'profile_lock_unavailable', 'permission_denied', 'browser_closed', 'worker_exited', 'invalid_response'})
SOURCES = frozenset({'project_venv', 'optional_local', 'other'})


def runtime_source(path, root=None):
    root = Path(root or Path(__file__).resolve().parents[2]).resolve()
    try:
        candidate = Path(path).resolve()
        if candidate.is_relative_to(root/'.venv'):
            return 'project_venv'
        if candidate.is_relative_to(root/'.local_py'):
            return 'optional_local'
    except (OSError, TypeError, ValueError):
        pass
    return 'other'


def safe_wait_stack(frame):
    """Function locations only; never locals, source lines or full paths."""
    result=[]
    while frame is not None and len(result)<8:
        name=Path(frame.f_code.co_filename).name
        function=frame.f_code.co_name
        if re.fullmatch(r'[\w.<>-]{1,100}',name) and re.fullmatch(r'[\w<>]{1,100}',function):
            result.append({'file':name,'function':function,'line':frame.f_lineno})
        frame=frame.f_back
    return result


def driver_start_watch(executable, entrypoint, *, seconds=15):
    """Worker-local wait observation; no process control or browser commands."""
    from contextlib import contextmanager
    import json
    import sys
    import threading
    @contextmanager
    def watch():
        stop=threading.Event()
        thread_id=threading.get_ident()
        facts={'driver_source':runtime_source(executable),'driver_api_source':runtime_source(entrypoint)}
        def emit(value):
            try:
                sys.stderr.write(json.dumps({'browser_driver_diagnostics':value})+'\n')
                sys.stderr.flush()
            except (OSError, ValueError):
                pass
        emit(facts)
        def observe():
            if not stop.wait(seconds):
                frame=sys._current_frames().get(thread_id)
                emit(dict(facts,driver_wait_stack=safe_wait_stack(frame)))
        threading.Thread(target=observe,name='DriverStartupObservation',daemon=True).start()
        try:
            yield
        finally:
            stop.set()
    return watch()


def child_driver_facts(children, root=None):
    """Only captured descendants of this not-ready worker may be inspected."""
    result={}
    for process in children:
        try:
            if process.name().casefold()=='node.exe':
                return {'driver_present_at_cleanup':True,'driver_pid':process.pid,
                        'driver_source':runtime_source(process.exe(),root)}
        except Exception:
            return {}  # Unknown does not become a claim of process absence.
    result['driver_present_at_cleanup']=False
    return result


def classify(error):
    text = str(error).lower()
    if "executable doesn't exist" in text or 'executable not found' in text:
        code = 'executable_missing'
    elif any(x in text for x in ('access is denied', 'permission denied', 'eacces',
                                 'eperm: operation not permitted', '拒绝访问')):
        code = 'permission_denied'
    elif 'processsingleton' in text:
        code = 'profile_lock_unavailable'
    elif any(x in text for x in ('profile appears to be in use', 'user data directory is already in use')):
        code = 'profile_in_use'
    elif any(x in text for x in ('targetclosederror', 'browser has been closed',
                                 'browser closed', 'target page, context or browser has been closed')):
        code = 'browser_closed'
    else:
        code = 'unknown'
    value = {'code': code, 'error_type': type(error).__name__}
    for name in ('errno', 'winerror'):
        number = getattr(error, name, None)
        if type(number) is int:
            value[name] = number
    match = re.search(r'exitcode[=:]\s*(-?\d{1,11})\b', text)
    if match:
        value['browser_exit_code'] = int(match[1])
    return clean(value)


def clean(value):
    value = value if isinstance(value, dict) else {}
    result = {'code': value.get('code') if isinstance(value.get('code'), str) and value['code'] in CODES else 'unknown'}
    if isinstance(value.get('stage'), str) and value['stage'] in STAGES:
        result['stage'] = value['stage']
    if isinstance(value.get('error_type'), str) and value['error_type'] in {'Error', 'TargetClosedError', 'TimeoutError', 'OSError',
            'FileNotFoundError', 'PermissionError', 'TypeError', 'RuntimeError', 'AttributeError'}:
        result['error_type'] = value['error_type']
    for key in ('worker_pid', 'worker_exit_code', 'browser_exit_code', 'errno', 'winerror', 'driver_pid'):
        number = value.get(key)
        if type(number) is int and -(2**32) <= number <= 2**32:
            result[key] = number
    for key in ('cleanup_verified', 'ready_received', 'driver_present_at_cleanup'):
        if type(value.get(key)) is bool:
            result[key] = value[key]
    for key in ('driver_source','driver_api_source'):
        if isinstance(value.get(key),str) and value[key] in SOURCES:
            result[key]=value[key]
    if isinstance(value.get('driver_wait_stack'),list):
        frames=[]
        for frame in value['driver_wait_stack'][:8]:
            if (isinstance(frame,dict) and isinstance(frame.get('file'),str)
                    and re.fullmatch(r'[\w.<>-]{1,100}',frame['file'])
                    and isinstance(frame.get('function'),str) and re.fullmatch(r'[\w<>]{1,100}',frame['function'])
                    and type(frame.get('line')) is int and 0<frame['line']<1000000):
                frames.append({k:frame[k] for k in ('file','function','line')})
        result['driver_wait_stack']=frames
    return result
