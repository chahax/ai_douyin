from pathlib import Path
import json
import os
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import h3_service_guard_20261104 as g


@pytest.fixture
def cfg(tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    run = tmp_path / 'media'
    g.save(run / 'STATE.json', dict(status='stopped', active_segment='F0038'))
    original = g.read(g.ORIGINAL / 'SERVER_STARTED.json')
    return dict(original, home=str(home), media_run=str(run), incident_id='old-prompt')


@pytest.mark.parametrize('groups,port,owners,expected', [
    ([], 'closed', [], 'launch'),
    ([{'pid': 2, 'ppid': 0}], 'closed', [], 'wait'),
    ([], 'open', [3], 'wait'),
    ([{'pid': 2, 'ppid': 0}], 'open', [3], 'wait'),
    ([{'pid': 2, 'ppid': 0}, {'pid': 3, 'ppid': 1}], 'open', [3], 'wait'),
    ([{'pid': 2, 'ppid': 0}, {'pid': 3, 'ppid': 2}], 'open', [3], 'healthy'),
])
def test_process_and_listener_and_original_stats(cfg, monkeypatch, groups, port, owners, expected):
    monkeypatch.setattr(g, 'service_processes', lambda _: groups)
    monkeypatch.setattr(g, 'port_state', lambda *_: (port, owners))
    recorded = g.read(g.ORIGINAL / 'SERVER_STATUS.json')['system_stats']
    monkeypatch.setattr(g.LocalService, 'get', lambda self, _: recorded)
    assert g.inspect(cfg)['action'] == expected


def test_different_argv_retains(cfg, monkeypatch):
    monkeypatch.setattr(g, 'service_processes', lambda _: [{'pid': 2, 'ppid': 1}])
    monkeypatch.setattr(g, 'port_state', lambda *_: ('open', [2]))
    monkeypatch.setattr(g.LocalService, 'get', lambda self, _: {'system': {'argv': ['other']}})
    assert g.inspect(cfg)['action'] == 'wait'


@pytest.mark.parametrize('times,expected', [([], 'launch'), ([999], 'cooldown'),
                          ([800, 999], 'cooldown'), ([700, 800, 900], 'restart_exhausted'),
                          ([-10000, 800, 870], 'launch')])
def test_retry_policy(times, expected):
    assert g.retry_decision(times, 1000)[0] == expected


@pytest.mark.parametrize('history,queue,result', [({}, [], 'absent_from_history_and_queue'),
    ({'old-prompt': {'status': {'status_str':'error'}}}, [], 'in_history'),
    ({}, [[1, 'old-prompt']], 'in_queue')])
def test_incident_lookup_is_get_only(cfg, monkeypatch, history, queue, result):
    paths = []
    def get(self, path):
        paths.append(path)
        return history if path.startswith('/history/') else dict(queue_running=queue, queue_pending=[])
    monkeypatch.setattr(g.LocalService, 'get', get)
    assert g.lookup(cfg)['result'] == result
    assert paths == ['/history/old-prompt', '/queue']


def test_media_complete_or_manual_pause_stops_without_probing(cfg):
    g.save(Path(cfg['media_run']) / 'STATE.json', dict(status='saved'))
    assert g.tick(cfg, None)['reason'] == 'full_script_saved'
    g.save(Path(cfg['home']) / 'PAUSE.json', {})
    assert g.tick(cfg, None)['reason'] == 'manual_pause'


def test_exhaustion_survives_restart(cfg, monkeypatch):
    home = Path(cfg['home'])
    for i in range(3):
        g.save(home / 'attempts' / str(i) / 'CLAIM.json', dict(epoch=g.time.time() - 800))
    monkeypatch.setattr(g, 'inspect', lambda _: {'action':'launch'})
    assert g.tick(cfg, None)['status'] == 'restart_exhausted'
    monkeypatch.setattr(g, 'inspect', lambda _: pytest.fail('terminal latch should precede service access'))
    assert g.tick(cfg, None)['status'] == 'restart_exhausted'


def test_access_denied_or_timeout_never_launch(cfg, monkeypatch):
    monkeypatch.setattr(g, 'service_processes', lambda _: (_ for _ in ()).throw(PermissionError('uninspectable')))
    with pytest.raises(PermissionError):
        g.tick(cfg, None)
    assert not (Path(cfg['home']) / 'attempts').exists()


def test_roundtrip_real_child(tmp_path):
    cmd = [sys.executable, '-B', '-u', '-c',
           'import sys,time; print("ready");print("diagnosis",file=sys.stderr);time.sleep(.15);sys.exit(7)']
    assert g.record_child(cmd, tmp_path, os.environ, tmp_path) == 7
    info = g.read(tmp_path / 'PROCESS.json')
    done = g.read(tmp_path / 'EXIT.json')
    assert info['pid'] == done['pid'] and info['create_time'] == done['create_time'] > 0
    assert done['returncode'] == 7 and info['command'] == cmd
    assert (tmp_path / 'server.stdout.log').read_text().strip() == 'ready'
    assert (tmp_path / 'server.stderr.log').read_text().strip() == 'diagnosis'


def test_sqlite_missing_stays_missing_and_schema_only(tmp_path):
    db = tmp_path / 'sample.db'
    assert g.database_observation(db)['exists'] is False and not db.exists()
    with sqlite3.connect(db) as conn:
        conn.execute('create table sample (data text)')
    assert g.database_observation(db)['tables'] == ['sample']


def test_real_local_stats_http_get(tmp_path):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Thread
    recorded = g.read(g.ORIGINAL / 'SERVER_STATUS.json')['system_stats']
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(recorded).encode())
    with HTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = Thread(target=server.handle_request)
        thread.start()
        try:
            stats = g.LocalService('http://127.0.0.1:' + str(server.server_port)).get('/system_stats')
            assert stats['system']['argv'] == g.read(g.ORIGINAL / 'SERVER_STARTED.json')['command'][2:]
        finally:
            thread.join(10)


def test_prepare_freezes_install_task_and_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(g,'inspect', lambda _:dict(action='launch', port='closed'))
    plan = tmp_path / 'SERVICE_PLAN.json'
    g.prepare(plan)
    config = g.read(plan)
    doc = (tmp_path / 'TASK.xml').read_text()
    xml = ET.fromstring(doc)
    assert not doc.startswith('<?xml') and xml.find('.//{*}ExecutionTimeLimit').text == 'PT0S'
    assert xml.find('.//{*}MultipleInstancesPolicy').text == 'IgnoreNew'
    assert xml.find('.//{*}Command').text.endswith('pythonw.exe')
    assert str(plan) in xml.find('.//{*}Arguments').text
    assert all(g.sha(e['path']) == e['sha256'] for e in config['bindings'])
    install = g.INSTALL.read_text()
    assert 'GetBaseException' in install and '-2147024894' in install and 'RegisterTask($taskName, $taskDocument, 2' in install
    with pytest.raises(ValueError):
        g.prepare(plan)
