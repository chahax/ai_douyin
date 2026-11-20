"""Explicit continuation after CPU-validator timeout; old batch stays unchanged."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time
import psutil

BASE_FILE = Path(__file__).with_name('run_h3_six_children_batch_20261102.py')
spec = importlib.util.spec_from_file_location('h3_batch_base', BASE_FILE)
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
h = b.h
OLD = b.BATCH
RUN = OLD.with_name(OLD.name + '_validation_resume')
COMFY = Path('D:/IT/AI_vido/ComfyUI')


def prepare(run=RUN):
    if any((OLD / segment / 'SUBMISSION_CLAIM.json').exists() for segment in b.IDS):
        raise ValueError('old_batch_has_submission_claim')
    b.prepare(run)
    wrapper = run / 'native_validation_traced.py'
    wrapper.write_text("import faulthandler,runpy\nfaulthandler.enable()\nfaulthandler.dump_traceback_later(45,repeat=True)\nrunpy.run_path(" + repr(str(b.VALIDATOR)) + ",run_name='__main__')\n", encoding='utf-8')
    continuation = dict(reason='old S02 CPU validation timed out before any POST; preserve old stopped state',
                        old_plan=h.binding(OLD / 'PLAN.json'), old_state=h.binding(OLD / 'STATE.json'),
                        old_validation_command=h.binding(OLD / 'S02/VALIDATION_COMMAND.json'),
                        plan=h.binding(run / 'PLAN.json'), code=h.binding(__file__), base_code=h.binding(BASE_FILE),
                        wrapper=h.binding(wrapper), service_environment=h.binding(b.SERVICE / 'SERVER_STARTED.json'),
                        successful_diagnostic=h.binding(h.ROOT / 'data/qa/h3_validation_timeout_20261102/NATIVE_VALIDATION.json'),
                        timeout_seconds=300, validation_cwd=str(COMFY), shared_cache=True)
    h.durable(run / 'CONTINUATION.json', continuation, immutable=True)
    return continuation


def validate_continuation(run, require_review=True):
    record = h.read(run / 'CONTINUATION.json')
    for item in record.values():
        if isinstance(item, dict) and 'sha256' in item:
            b.bound_ok(item)
    if any((OLD / segment / 'SUBMISSION_CLAIM.json').exists() for segment in b.IDS):
        raise ValueError('old_batch_submitted_since_continuation')
    if require_review:
        review = h.read(run / 'PRIMARY_DISPATCH_REVIEW.json')
        if review.get('continuation_sha256') != h.sha(run / 'CONTINUATION.json'):
            raise ValueError('continuation_review_required')
    return record


def terminate_own_validator(process, wrapper):
    """Only the exact launched validator tree; never the existing ComfyUI server."""
    try:
        descendants = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        descendants = []
    for child in reversed(descendants):
        try:
            if str(wrapper) in child.cmdline():
                child.kill()
        except psutil.NoSuchProcess:
            pass
    process.kill()
    process.wait(timeout=15)


def native_validate(run):
    batch = run.parent
    record = validate_continuation(batch, require_review=False)
    report = run / 'NATIVE_VALIDATION.json'
    attempt = run / 'VALIDATION_PROCESS.json'
    if not report.exists():
        if attempt.exists():
            raise ValueError('prior_validator_attempt_preserved_review_required')
        service = h.read(b.SERVICE / 'SERVER_STARTED.json')
        env = os.environ.copy()
        for key, value in service['cache_env'].items():
            if not Path(value).resolve().is_relative_to((b.SERVICE / 'runtime_cache').resolve()):
                raise ValueError('cache_path_outside_existing_D_run')
            env[key] = value
        env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1', HF_HUB_OFFLINE='1',
                   TRANSFORMERS_OFFLINE='1', PYTHONIOENCODING='utf-8')
        wrapper = Path(record['wrapper']['path'])
        command = [str(b.PYTHON), '-B', '-u', str(wrapper), '--graph', str(run / 'workflow_api.json'),
                   '--report', str(report), '--input-root', str(b.SERVICE / 'input')]
        h.durable(run / 'VALIDATION_COMMAND.json', command, immutable=True)
        started = time.monotonic()
        with (run / 'validation.stdout.log').open('wb') as out, (run / 'validation.stderr.log').open('wb') as err:
            process = subprocess.Popen(command, stdout=out, stderr=err, cwd=COMFY, env=env,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            result = dict(pid=process.pid, command=command, cwd=str(COMFY), at=h.now(), status='running',
                          cache_env=service['cache_env'], stdout=str(run / 'validation.stdout.log'), stderr=str(run / 'validation.stderr.log'))
            h.durable(attempt, result)
            try:
                code = process.wait(timeout=record['timeout_seconds'])
            except subprocess.TimeoutExpired:
                result.update(status='timeout', elapsed=time.monotonic()-started)
                h.durable(attempt, result)
                terminate_own_validator(process, wrapper)
                raise
        result.update(status='completed' if code == 0 else 'failed', returncode=code, elapsed=time.monotonic()-started)
        h.durable(attempt, result)
        if code != 0:
            raise subprocess.CalledProcessError(code, command)
    if attempt.exists() and h.read(attempt).get('status') != 'completed':
        raise ValueError('validator_completion_not_confirmed')
    value = h.read(report)
    if not value.get('valid') or value.get('node_errors') or value.get('node_execution_performed') is not False or value.get('graph_sha256') != h.sha(run / 'workflow_api.json'):
        raise ValueError('native_validation_failed')


def execute(run=RUN):
    validate_continuation(run)
    return b.execute(run, validate_fn=native_validate)


def validate_first(run=RUN):
    validate_continuation(run, require_review=False)
    b.freeze_predecessor(run, run / 'S02', b.SERVICE, h.Client())
    native_validate(run / 'S02')
    print(json.dumps(h.read(run / 'S02/NATIVE_VALIDATION.json')), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'execute', 'validate_first', 'status'])
    parser.add_argument('--run', type=Path, default=RUN)
    args = parser.parse_args()
    (b.status if args.command == 'status' else globals()[args.command])(args.run)
