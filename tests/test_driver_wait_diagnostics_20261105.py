import io
import json
import sys
import threading
from types import SimpleNamespace as NS

from src.shared.browser_startup_diagnostics import (runtime_source, clean,
    driver_start_watch, child_driver_facts)


def test_runtime_source_does_not_emit_paths(tmp_path):
    assert runtime_source(tmp_path/'.venv/driver/node.exe',tmp_path)=='project_venv'
    assert runtime_source(tmp_path/'.local_py/private/node.exe',tmp_path)=='optional_local'
    assert runtime_source(tmp_path/'secret/path',tmp_path)=='other'
    assert runtime_source(tmp_path/'.venv/../../outside',tmp_path)=='other'


def test_driver_wait_snapshot_excludes_local_values_and_full_paths(tmp_path,monkeypatch):
    output=io.StringIO()
    monkeypatch.setattr(sys,'stderr',output)
    secret='credentials-and-cookie-value'
    with driver_start_watch(tmp_path/'secret_node.exe',tmp_path/'secret_cli.js',seconds=.01):
        threading.Event().wait(.08)
    events=[json.loads(line)['browser_driver_diagnostics'] for line in output.getvalue().splitlines()]
    assert len(events)==2 and events[1]['driver_wait_stack']
    assert all('driver_source' in event for event in events)
    text=json.dumps(events)
    assert secret not in text and str(tmp_path) not in text and 'secret_node' not in text
    assert all(set(frame)=={'file','function','line'} for frame in events[1]['driver_wait_stack'])


def test_cleanup_observation_only_covers_captured_children(tmp_path):
    node=NS(pid=123,name=lambda:'node.exe',exe=lambda:str(tmp_path/'.venv/node.exe'))
    assert child_driver_facts([node],tmp_path)=={'driver_present_at_cleanup':True,
        'driver_pid':123,'driver_source':'project_venv'}
    assert child_driver_facts([],tmp_path)=={'driver_present_at_cleanup':False}
    def unavailable():raise PermissionError('private')
    assert child_driver_facts([NS(name=unavailable)],tmp_path)=={}


def test_parent_accepts_only_safe_driver_diagnostics(tmp_path):
    from src.platform_adapter.browser_session import BrowserSession
    from src.platform_adapter.models import BrowserSessionConfig
    session=BrowserSession(BrowserSessionConfig(base_url='about:blank',home_url='about:blank',
        user_data_dir=str(tmp_path/'profile'),storage_state_path=str(tmp_path/'no_auth.json')))
    event={'browser_driver_diagnostics':{'driver_source':'project_venv',
        'driver_api_source':'optional_local','cookie':'private','argv':'private',
        'driver_wait_stack':[{'file':'_transport.py','function':'connect','line':120,'locals':'private'},
            {'file':'C:/private/path.py','function':'read','line':1}]}}
    session._startup_evidence={'code':'startup_timeout'}
    process=NS(stderr=io.BytesIO((json.dumps(event)+'\n').encode()))
    session._read_worker_stages(process)
    assert session._startup_evidence=={'code':'startup_timeout','driver_source':'project_venv',
        'driver_api_source':'optional_local',
        'driver_wait_stack':[{'file':'_transport.py','function':'connect','line':120}]}
    assert 'private' not in json.dumps(clean(session._startup_evidence))
