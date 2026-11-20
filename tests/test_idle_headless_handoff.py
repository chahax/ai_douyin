"""Opt-in headless EOF handoff proves one family and never signals children."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys

import pytest

from test_idle_browser_control_handoff import isolated


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('headless_handoff', ROOT/'scripts/handoff_idle_browser_control.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
SCRIPT = 'print("original worker fixture")'
SHA = hashlib.sha256(SCRIPT.encode()).hexdigest()


class Process:
    def __init__(self, pid, ppid, name, cmd=(), *, exe=None):
        self.pid, self.parent, self.label, self.command = pid, ppid, name, list(cmd)
        self.executable = exe or (cmd[0] if cmd else '')
        self.started, self.descendants = 1000+pid, []
    def create_time(self): return self.started
    def ppid(self): return self.parent
    def name(self): return self.label
    def cmdline(self): return self.command
    def exe(self): return self.executable
    def children(self, recursive=True): return self.descendants


def family(root=ROOT):
    service = Process(1, 0, 'pythonw.exe')
    profile = root/'data/original/account/profile'
    py = [str(root/'.venv/Scripts/pythonw.exe'), '-S', '-c', SCRIPT]
    driver = root/'.local_py/site-packages/playwright/driver'
    chrome = str(Path(os.environ['ProgramFiles'])/'Google/Chrome/Application/chrome.exe')
    profile_flag = '--user-data-dir='+str(profile)
    service.descendants = [Process(2,1,'pythonw.exe',py), Process(3,2,'pythonw.exe',py),
        Process(4,3,'node.exe',[str(driver/'node.exe'),str(driver/'package/cli.js'),'run-driver']),
        Process(5,4,'conhost.exe',exe=str(Path(os.environ['SystemRoot'])/'System32/conhost.exe')),
        Process(6,4,'chrome.exe',[chrome,'--headless','--enable-automation','--remote-debugging-pipe',profile_flag]),
        Process(7,6,'chrome.exe',[chrome,'--type=renderer',profile_flag]),
        Process(8,6,'chrome.exe',[chrome,'--type=utility',profile_flag])]
    return service, profile


def test_exact_original_headless_family_is_only_observed_not_signaled():
    service, profile = family()
    children, evidence = module.idle_headless_worker_children(service, profile, SHA)
    assert children == service.descendants
    assert [r['pid'] for r in evidence] == list(range(2,9))


@pytest.mark.parametrize('change', ['visible', 'headless_false', 'wrong_profile', 'wrong_script', 'wrong_python',
    'wrong_driver', 'second_driver', 'second_browser', 'foreign_chrome', 'wrong_console', 'extra_child',
    'wrong_worker_parent', 'wrong_driver_parent', 'foreign_renderer', 'unknown_chrome_type', 'old_child'])
def test_unproven_headless_tree_is_rejected(change):
    service, profile = family(); children=service.descendants
    if change == 'visible': children[4].command.remove('--headless')
    elif change == 'headless_false': children[4].command[1]='--headless=false'
    elif change == 'wrong_profile': children[4].command[-1]='--user-data-dir='+str(ROOT/'other-profile')
    elif change == 'wrong_script': children[0].command[-1]='other script'
    elif change == 'wrong_python': children[0].command[0]='C:/elsewhere/pythonw.exe'
    elif change == 'wrong_driver': children[2].command[-1]='other-driver'
    elif change == 'second_driver': children.append(Process(20,3,'node.exe',children[2].command))
    elif change == 'second_browser': children.append(Process(20,4,'chrome.exe',children[4].command))
    elif change == 'foreign_chrome': children[4].executable='C:/other/chrome.exe'
    elif change == 'wrong_console': children[3].executable=str(ROOT/'conhost.exe')
    elif change == 'extra_child': children.append(Process(20,1,'notepad.exe'))
    elif change == 'wrong_worker_parent': children[1].parent=1
    elif change == 'wrong_driver_parent': children[2].parent=1
    elif change == 'foreign_renderer': children[5].parent=4
    elif change == 'unknown_chrome_type': children[5].command[1]='--type=unknown'
    else: children[4].started=service.create_time()-1
    with pytest.raises(RuntimeError): module.idle_headless_worker_children(service,profile,SHA)


def test_historical_source_is_parsed_as_data_and_bound_to_explicit_script_sha(tmp_path, monkeypatch):
    monkeypatch.setattr(module,'ROOT',tmp_path)
    path=tmp_path/'original.before.py'
    path.write_text('raise RuntimeError("must never execute")\n_PW_SCRIPT='+repr(SCRIPT),encoding='utf8')
    evidence=module.worker_source_evidence(path,SHA)
    assert evidence['worker_script_sha256']==SHA
    assert evidence['source_sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(RuntimeError): module.worker_source_evidence(path,'0'*64)
    monkeypatch.setattr(module,'ROOT',tmp_path/'elsewhere')
    with pytest.raises(RuntimeError): module.worker_source_evidence(path,SHA)


@pytest.mark.parametrize('alive,late_profile', [(False,False),(True,False),(False,True)])
def test_opt_in_main_waits_for_natural_exit_and_retains_owner_on_any_survivor(isolated,monkeypatch,alive,late_profile):
    m,service,store,command,args,root=isolated
    original,profile=family(root)
    service.pid=4321
    original.descendants[0].parent=service.pid
    # The isolated service fixture starts later than our synthetic children.
    source=root/'worker.before.py';source.write_text('_PW_SCRIPT='+repr(SCRIPT),encoding='utf8')
    with sqlite3.connect(root/'data/douyin.db') as db:
        db.execute('CREATE TABLE account_runtime_bindings(account_uuid TEXT,browser_profile_dir TEXT)')
        db.execute('INSERT INTO account_runtime_bindings VALUES(?,?)',('review:A',str(profile)))
    args.extend(['--idle-headless-worker','--worker-source',str(source),'--worker-script-sha256',SHA,'--browser-profile',str(profile)])
    service.children=lambda recursive=True:original.descendants
    waited=[]
    def wait(children,timeout):
        waited.append(timeout)
        return (children[:-1],children[-1:]) if alive else (children,[])
    monkeypatch.setattr(m.psutil,'wait_procs',wait)
    def check_profile(profile):
        if late_profile:raise RuntimeError('late child remains')
    monkeypatch.setattr(m,'assert_profile_exited',check_profile)
    if alive or late_profile:
        with pytest.raises(RuntimeError):m.main()
        assert store.snapshot('review:A')['owner']['state']=='active'
    else:
        m.main()
        assert store.snapshot('review:A')['owner']['state']=='released'
    assert service.terminated==1 and waited==[30]
    assert store.get(command['command_id'])==command
    evidence=json.loads((root/'handoff.json').read_text())
    assert evidence['idle_headless_source']['worker_script_sha256']==SHA
    assert evidence['released'] is not (alive or late_profile)


def test_late_profile_process_prevents_release_but_other_profiles_do_not(monkeypatch):
    process=type('SimpleChrome',(),{})
    obj=process();obj.info={'name':'chrome.exe'}
    obj.cmdline=lambda:['chrome.exe','--user-data-dir='+str(ROOT/'data/original/profile')]
    monkeypatch.setattr(module.psutil,'process_iter',lambda _: [obj])
    module.assert_profile_exited(ROOT/'data/other/profile')
    with pytest.raises(RuntimeError):module.assert_profile_exited(ROOT/'data/original/profile')


def test_final_tree_change_is_rejected_before_termination_requested_is_recorded(isolated,monkeypatch):
    m,service,store,command,args,root=isolated
    source=root/'worker.before.py';source.write_text('_PW_SCRIPT='+repr(SCRIPT),encoding='utf8')
    profile=root/'data/account/profile'
    with sqlite3.connect(root/'data/douyin.db') as db:
        db.execute('CREATE TABLE account_runtime_bindings(account_uuid TEXT,browser_profile_dir TEXT)')
        db.execute('INSERT INTO account_runtime_bindings VALUES(?,?)',('review:A',str(profile)))
    args.extend(['--idle-headless-worker','--worker-source',str(source),'--worker-script-sha256',SHA,'--browser-profile',str(profile)])
    calls=[]
    def changed(*_):
        calls.append(True)
        return [],[{'pid':100,'ppid':4321,'name':'pythonw.exe','create_time':len(calls)}]
    monkeypatch.setattr(m,'idle_headless_worker_children',changed)
    with pytest.raises(RuntimeError,match='changed before stop'):m.main()
    assert len(calls)==2 and service.terminated==0
    assert not(root/'handoff.json').exists()
    assert store.snapshot('review:A')['owner']['state']=='active'
    assert store.get(command['command_id'])==command
