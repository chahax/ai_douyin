"""Load an idempotent completion-only job into the existing running scheduler."""
import inspect
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
import types
from datetime import datetime

JOB_ID='account_human_completion'
ACTIVATION_PATH=Path(__file__).resolve().parents[2]/'data/development_checkpoints/handling_latency_20261105/ACTIVATION.json'
_install_lock=threading.Lock()
_legacy_scan_lock=threading.Lock()
_last_error=None


def pending_controls(path):
    target=Path(path).resolve()
    if not target.exists():return []
    with sqlite3.connect(target.as_uri()+'?mode=ro',uri=True,timeout=2) as db:
        db.row_factory=sqlite3.Row
        return [dict(r) for r in db.execute("""SELECT c.* FROM account_controls c
            WHERE c.state='recovery_requested' AND EXISTS(SELECT 1 FROM account_handling_requests r
            WHERE r.account_uuid=c.account_uuid AND r.account_key=c.account_key AND r.status='requested')""")]


def probe_controls(controls, *, path, claim, finish, exception_code):
    from src.operations_accounts.runtime import AccountRuntimeService
    for control in controls:
        token=claim(control['account_uuid'],control['account_key'],path=path)
        if token is None:continue
        try:
            result=AccountRuntimeService().probe_recovery(control['account_key'],headless=True)
            expected=getattr(result,'expected',None)
            same=(getattr(expected,'account_uuid',None)==control['account_uuid']
                  and getattr(expected,'account_key',None)==control['account_key'])
            finish(control['account_uuid'],control['account_key'],token,
                   healthy=bool(result.healthy and same),status=result.status if same else 'account_uuid_mismatch',path=path)
        except Exception as exc:
            finish(control['account_uuid'],control['account_key'],token,healthy=False,status=exception_code(exc),
                   diagnostic=f'{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else "未提供详情"}',path=path)


def run_registered_requests():
    global _last_error
    from src.scheduler import account_refresh as refresh
    try:
        processor=refresh.recover_requested_accounts
        parameters=inspect.signature(processor).parameters
        if 'requested_only' in parameters:
            processor(path=refresh.DB,requested_only=True)
        elif any(p.kind==p.VAR_KEYWORD for p in parameters.values()):
            processor(requested_only=True)
        elif _legacy_scan_lock.acquire(blocking=False):
            try:
                # The existing transaction/CAS claim is the authority. Do not
                # reload or patch its module, owners, handlers or running tasks.
                probe_controls(pending_controls(refresh.DB),path=refresh.DB,
                    claim=refresh._claim_recovery,finish=refresh._finish_recovery,exception_code=refresh._exception_code)
            finally:_legacy_scan_lock.release()
        _last_error=None
    except Exception as exc:
        _last_error=type(exc).__name__
        logging.getLogger(__name__).error('Completion scan deferred (%s)',_last_error)


def _normalized_code(code):
    constants=tuple(_normalized_code(v) if isinstance(v,types.CodeType) else v for v in code.co_consts)
    return (code.co_code,code.co_names,code.co_varnames,constants,code.co_argcount,code.co_kwonlyargcount,
            code.co_posonlyargcount,code.co_flags,code.co_exceptiontable,code.co_freevars,code.co_cellvars)


def verify_original_claims(refresh):
    source=Path(__file__).with_name('account_refresh.py')
    # Compile the complete module but do not execute it. Python 3.14 optimizes
    # imported-module attribute calls differently from an isolated function.
    compiled=compile(source.read_text(encoding='utf8'),str(source),'exec')
    codes={code.co_name:code for code in compiled.co_consts if isinstance(code,types.CodeType)}
    for name in ('_claim_recovery','_finish_recovery','_exception_code'):
        current=getattr(refresh,name)
        if _normalized_code(current.__code__)!=_normalized_code(codes[name]):
            raise RuntimeError('Loaded recovery validation differs from reviewed source')


def install_from_web():
    from src.web.components.auth import get_current_user,get_current_role,has_permission
    user=get_current_user()
    if not user or not has_permission(get_current_role(),'admin'):
        raise PermissionError('Signed-in administrator required')
    from src.scheduler import runner,account_refresh
    with _install_lock:
        instance=runner.scheduler_instance
        scheduler=getattr(instance,'_scheduler',None)
        if scheduler is None or not scheduler.running:
            raise RuntimeError('Original scheduler is not running; no service was started')
        verify_original_claims(account_refresh)
        job=scheduler.get_job(JOB_ID)
        reused=job is not None
        if job is not None:
            if (job.func is not run_registered_requests or job.trigger.interval.total_seconds()!=2
                    or job.max_instances!=1):
                raise RuntimeError('Existing job identity is different; it was not replaced')
        else:
            scheduler.add_job(run_registered_requests,'interval',seconds=2,id=JOB_ID,
                coalesce=True,max_instances=1,misfire_grace_time=2,next_run_time=datetime.now())
        # UI-only code can reload without touching background/browser modules.
        import importlib
        from src.web import account_exception_notice
        importlib.reload(account_exception_notice)
        record={'version':1,'backend_pid':os.getpid(),'job_id':JOB_ID,'interval_seconds':2,
                'max_instances':1,'reused':reused,'actor':str(user),'activated_at':time.time(),
                'backend_restarted':False,'browser_operations':False,'business_requests_created':False}
        target=Path(ACTIVATION_PATH)
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_suffix('.tmp')
        temporary.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
        temporary.replace(target)
        return record


def latest_receipt(account,key,*,after):
    from src.scheduler.account_refresh import DB
    with sqlite3.connect(Path(DB).resolve().as_uri()+'?mode=ro',uri=True,timeout=2) as db:
        row=db.execute('SELECT request_id FROM account_handling_requests WHERE account_uuid=? AND account_key=? AND requested_at>=? ORDER BY requested_at DESC LIMIT 1',(account,key,after)).fetchone()
    return row[0] if row else None
