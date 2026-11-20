import importlib.util
from pathlib import Path
import subprocess
import pytest

PATH = Path(__file__).resolve().parents[1] / 'scripts/run_h3_batch_validation_resume_20261102.py'
spec = importlib.util.spec_from_file_location('h3_validation_resume', PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.fixture
def run(tmp_path, monkeypatch):
    root = tmp_path / 'batch'
    run = root / 'S02'
    run.mkdir(parents=True)
    m.h.durable(run / 'workflow_api.json', {'node': 'graph'})
    service = tmp_path / 'service'
    service.mkdir()
    cache = {key: str(service / 'runtime_cache' / key) for key in ['TEMP', 'TMP', 'CUDA_CACHE_PATH', 'TRITON_CACHE_DIR', 'TORCHINDUCTOR_CACHE_DIR']}
    m.h.durable(service / 'SERVER_STARTED.json', {'cache_env': cache})
    monkeypatch.setattr(m.b, 'SERVICE', service)
    monkeypatch.setattr(m, 'validate_continuation', lambda *a, **kw: dict(wrapper={'path': str(root / 'wrapper.py')}, timeout_seconds=300))
    return run


def test_timeout_streams_preserved_and_owned_cleanup_called(run, monkeypatch):
    cleanup = []
    class Process:
        pid = 123
        def __init__(self, command, **kw):
            kw['stdout'].write(b'initialization started\n')
            kw['stderr'].write(b'import stage traceback\n')
            assert kw['cwd'] == m.COMFY
            assert kw['env']['CUDA_CACHE_PATH'].startswith(str(m.b.SERVICE))
        def wait(self, timeout):
            raise subprocess.TimeoutExpired(['validator'], timeout)
    monkeypatch.setattr(m.subprocess, 'Popen', Process)
    monkeypatch.setattr(m, 'terminate_own_validator', lambda p, wrapper: cleanup.append(p.pid))
    with pytest.raises(subprocess.TimeoutExpired):
        m.native_validate(run)
    assert cleanup == [123]
    assert (run / 'validation.stdout.log').read_bytes() == b'initialization started\n'
    assert (run / 'validation.stderr.log').read_bytes() == b'import stage traceback\n'
    assert m.h.read(run / 'VALIDATION_PROCESS.json')['status'] == 'timeout'
    with pytest.raises(ValueError, match='prior_validator_attempt_preserved'):
        m.native_validate(run)


def test_native_success_uses_shared_cache_and_existing_report_no_restart(run, monkeypatch):
    calls = []
    class Process:
        pid = 456
        def __init__(self, command, **kw):
            calls.append(command)
            m.h.durable(run / 'NATIVE_VALIDATION.json', dict(valid=True, node_errors={}, node_execution_performed=False,
                                                           graph_sha256=m.h.sha(run / 'workflow_api.json')))
        def wait(self, timeout):
            return 0
    monkeypatch.setattr(m.subprocess, 'Popen', Process)
    m.native_validate(run)
    m.native_validate(run)
    assert len(calls) == 1
    assert m.h.read(run / 'VALIDATION_PROCESS.json')['status'] == 'completed'


def test_failed_process_does_not_validate_even_with_report(run, monkeypatch):
    class Process:
        pid = 789
        def __init__(self, command, **kw):
            kw['stderr'].write(b'known failure')
        def wait(self, timeout):
            return 1
    monkeypatch.setattr(m.subprocess, 'Popen', Process)
    with pytest.raises(subprocess.CalledProcessError):
        m.native_validate(run)
    assert m.h.read(run / 'VALIDATION_PROCESS.json')['status'] == 'failed'
    assert (run / 'validation.stderr.log').read_bytes() == b'known failure'
