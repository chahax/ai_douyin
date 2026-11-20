import importlib.util
import json
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET
import pytest

PATH=Path(__file__).resolve().parents[1]/'scripts/h3_persistent_supervisor_20261103.py'
spec=importlib.util.spec_from_file_location('h3_supervisor_test',PATH)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


@pytest.fixture
def config(tmp_path):
    home=tmp_path/'monitor';home.mkdir()
    run=tmp_path/'media';segment=run/'F0001';segment.mkdir(parents=True)
    m.save(run/'PLAN.json',dict(segments=[dict(id='F0001')]))
    m.save(run/'STATE.json',dict(status='running',active_segment='F0001'))
    m.save(segment/'STATE.json',dict(status='submitted',prompt_id='original-id'))
    m.save(segment/'workflow_api.json',{'a':dict(class_type='stub')})
    return dict(home=str(home),media_run=str(run),service_root=str(tmp_path/'service'),service_url='http://127.0.0.1:1',
                workspace=str(tmp_path),python=str(m.PYTHON),ensure_python=str(m.PYTHON.with_name('pythonw.exe')),
                runner_script=str(tmp_path/'dummy.py'),bindings=[],poll_seconds=1,max_restarts_without_progress=3,
                restart_cooldown_seconds=300,user='TEST\\user',task_name='AI_Douyin_H3_FullScript_Ensure',
                config_path=str(home/'SUPERVISOR_PLAN.json'))


class Service:
    def __init__(self,config,status='success',queued=False,missing=False,other=False):
        self.config=config;self.status=status;self.queued=queued;self.missing=missing;self.other=other
    def get(self,path):
        if path=='/system_stats':return dict(system=dict(argv=['main.py','--input-directory',str(Path(self.config['service_root'])/'input'),
                                                              '--output-directory',str(Path(self.config['service_root'])/'output'),'--offline','--disable-all-custom-nodes']))
        if path=='/queue':return dict(queue_running=[[1,'original-id']] if self.queued else [[2,'other']] if self.other else [],queue_pending=[])
        if path=='/history/original-id':
            if self.missing:return {}
            return {'original-id':dict(prompt=[0,'original-id',m.read(Path(self.config['media_run'])/'F0001/workflow_api.json')],
                                       status=dict(status_str=self.status,completed=self.status=='success'))}
        raise AssertionError(path)


@pytest.mark.parametrize('native_status,queued,missing,expected',[
    ('success',False,False,'known_success_collect_original'),
    ('running',True,True,'known_id_running_or_queued'),
    ('error',False,False,'known_native_failure'),
    ('running',False,True,'known_id_missing_history_and_queue')])
def test_original_id_decisions(config,native_status,queued,missing,expected):
    result=m.recovery_decision(config,Service(config,native_status,queued,missing))
    assert result['reason']==expected
    assert result['action']==('launch' if expected.startswith(('known_success','known_id_running')) else 'stop')


def test_unknown_claim_without_id_blocks_before_network(config):
    folder=Path(config['media_run'])/'F0001'
    m.save(folder/'STATE.json',dict(status='submit_outcome_unknown',prompt_id=None))
    m.save(folder/'SUBMISSION_CLAIM.json',dict(claim='retained'))
    assert m.recovery_decision(config,None)['reason']=='unknown_claim_without_id'


def test_known_response_id_recovery(config):
    folder=Path(config['media_run'])/'F0001'
    m.save(folder/'STATE.json',dict(status='submit_outcome_unknown',prompt_id=None))
    m.save(folder/'SUBMISSION_CLAIM.json',{})
    m.save(folder/'SUBMISSION_RESPONSE.json',dict(prompt_id='original-id',node_errors={}))
    assert m.recovery_decision(config,Service(config))['action']=='launch'


def test_busy_gpu_never_launches_unsubmitted_next(config):
    m.save(Path(config['media_run'])/'F0001/STATE.json',dict(status='prepared'))
    assert m.recovery_decision(config,Service(config,other=True))['action']=='wait'


def test_manual_pause_is_terminal(config):
    m.save(Path(config['home'])/'PAUSE.json',dict(user_request=True))
    assert m.recovery_decision(config,None)['status']=='paused'


def test_pid_reuse_and_launcher_family():
    a=dict(pid=10,ppid=1,create_time=100,cmdline=['python','script'],cwd='D:/IT/ai_douyin')
    child=dict(a,pid=11,ppid=10,create_time=100.01)
    assert len(m.family_groups([child,a]))==1
    assert m.same_identity(a,dict(a))
    assert not m.same_identity(a,dict(a,create_time=200))
    assert len(m.family_groups([a,dict(child,ppid=99)]))==2


def test_duplicate_supervisor_lock_is_distinct_from_io_error(tmp_path):
    with m.lock(tmp_path/'one.lock'):
        with pytest.raises(m.LockBusyError):
            with m.lock(tmp_path/'one.lock'):pass
    with pytest.raises(FileExistsError):
        with m.lock(tmp_path/'one.lock'/'invalid'):pass


def authorize(config):
    path=Path(config['config_path']);m.save(path,config)
    m.save(path.parent/'PRIMARY_REVIEW.json',dict(approved=True,config_sha256=m.sha(path)))
    return path


def test_config_hash_change_blocks(config):
    file=Path(config['home'])/'frozen';file.write_text('old')
    config['bindings']=[m.bind(file)];path=authorize(config);file.write_text('new')
    with pytest.raises(ValueError,match='frozen_configuration_changed'):m.assert_config(path)
    m.supervise(path,once=True)
    assert m.read(path.parent/'STATE.json')['status']=='configuration_changed'


def test_duplicate_ensure_does_not_spawn(config,monkeypatch):
    path=authorize(config)
    monkeypatch.setattr(m,'process_rows',lambda *a:[dict(pid=1)])
    monkeypatch.setattr(m,'spawn_detached',lambda *a:pytest.fail('must reuse live supervisor'))
    assert m.ensure(path)=='alive'


def test_network_failure_backoff_writes_fresh_heartbeat(config,monkeypatch):
    path=authorize(config)
    monkeypatch.setattr(m,'process_rows',lambda *a:[])
    class Unavailable:
        def get(self,path):raise OSError('service offline')
    monkeypatch.setattr(m,'LocalService',lambda *a:Unavailable())
    monkeypatch.setattr(m,'spawn_detached',lambda *a:pytest.fail('network failure is not launch permission'))
    m.supervise(path,once=True)
    state=m.read(path.parent/'STATE.json')
    assert state['status']=='backoff' and state['next_retry_epoch']>state['heartbeat_epoch']


def test_hidden_task_absolute_paths_and_no_destructive_overwrite(config):
    xml=ET.fromstring(m.task_xml(config));ns={'t':'http://schemas.microsoft.com/windows/2004/02/mit/task'}
    command=xml.find('t:Actions/t:Exec/t:Command',ns).text
    assert Path(command).is_absolute() and command.endswith('pythonw.exe')
    assert str(m.SCRIPT) in xml.find('t:Actions/t:Exec/t:Arguments',ns).text
    assert ' supervise --config ' in xml.find('t:Actions/t:Exec/t:Arguments',ns).text
    assert xml.find('t:Settings/t:ExecutionTimeLimit',ns).text=='PT0S'
    assert xml.find('t:Settings/t:MultipleInstancesPolicy',ns).text=='IgnoreNew'
    assert xml.find('t:Actions/t:Exec/t:WorkingDirectory',ns).text==config['workspace']
    script=m.install_script(config)
    assert '-Force' not in script
    assert 'Assert-OwnedTask $existing' in script and 'Assert-OwnedTask $after' in script
    assert 'preserved without overwrite' in script


def test_crash_known_success_launches_wrapper_once(config,monkeypatch):
    path=authorize(config);launches=[]
    monkeypatch.setattr(m,'process_rows',lambda *a:[])
    monkeypatch.setattr(m,'LocalService',lambda *a:Service(config))
    monkeypatch.setattr(m,'spawn_detached',lambda command,*a:launches.append(command) or dict(pid=123,create_time=1,cmdline=command))
    m.supervise(path,once=True)
    assert len(launches)==1 and 'runner-wrapper' in launches[0]
    state=m.read(path.parent/'STATE.json')
    assert state['reason']=='known_success_collect_original' and state['restart_count']==1


def test_repeated_same_position_has_bounded_restart(config,monkeypatch):
    path=authorize(config)
    m.save(path.parent/'STATE.json',dict(status='backoff',progress=['F0001','original-id'],restart_count=3))
    monkeypatch.setattr(m,'process_rows',lambda *a:[])
    monkeypatch.setattr(m,'LocalService',lambda *a:Service(config))
    monkeypatch.setattr(m,'spawn_detached',lambda *a:pytest.fail('restart limit must stop'))
    m.supervise(path,once=True)
    assert m.read(path.parent/'STATE.json')['status']=='restart_exhausted'


def test_io_exception_is_fatal_not_lock_contention(config,monkeypatch):
    path=authorize(config)
    monkeypatch.setattr(m,'process_rows',lambda *a:(_ for _ in ()).throw(OSError('simulated IO error')))
    with pytest.raises(OSError):m.supervise(path,once=True)
    assert m.read(path.parent/'FATAL.json')['type']=='OSError'
    assert m.read(path.parent/'STATE.json')['status']=='crashed'


def test_real_local_supervisor_adopts_dummy_without_media(config):
    script=Path(config['runner_script'])
    script.write_text('import time\ntime.sleep(4)\n',encoding='utf-8')
    path=authorize(config)
    process=subprocess.Popen([str(m.PYTHON),'-B',str(script),'execute'],cwd=config['workspace'],
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        subprocess.run([str(m.PYTHON),'-B',str(PATH),'supervise','--config',str(path),'--once'],cwd=m.ROOT,
                       capture_output=True,text=True,check=True,timeout=15)
        state=m.read(path.parent/'STATE.json')
        assert state['status']=='monitoring' and len(state['runner_families'])==1
        assert state['reason']=='exact_runner_family_alive'
    finally:process.wait(timeout=10)


def test_real_wrapper_keeps_stdout_stderr_and_exit_code(config):
    script=Path(config['runner_script'])
    script.write_text("import sys\nprint('stdout evidence',flush=True)\nprint('stderr evidence',file=sys.stderr,flush=True)\nraise SystemExit(7)\n",encoding='utf-8')
    path=authorize(config)
    assert m.runner_wrapper(path,'smoke')==7
    folder=path.parent/'attempts/smoke'
    assert m.read(folder/'EXIT.json')['returncode']==7
    assert b'stdout evidence' in (folder/'stdout.log').read_bytes()
    assert b'stderr evidence' in (folder/'stderr.log').read_bytes()
