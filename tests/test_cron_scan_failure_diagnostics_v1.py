"""Structural scheduler failures: no secrets and no automatic retry."""
import json

import pytest

from test_account_scheduler_sqlite_recovery import load,fake_cron


def caught(key):
    sensitive_local={'password':'NEVER-SAVE-PASSWORD','token':'NEVER-SAVE-TOKEN'}
    try:raise KeyError(key)
    except KeyError as exc:return exc


def test_structural_keyerror_retains_source_frame_and_known_key_only(tmp_path,monkeypatch):
    cron=load('isolated_structural_cron','src/scheduler/cron.py')
    monkeypatch.setattr(cron,'SCAN_DIAGNOSTIC_DIR',tmp_path/'diag')
    ref=cron._write_scan_failure(caught('account_uuid'),'account_refresh')
    raw=open(ref['path'],encoding='utf8').read();value=json.loads(raw)
    assert value['missing_key']=={'identifier':'account_uuid'}
    assert value['frames'][-1]['function']=='caught' and value['frames'][-1]['line']>0
    assert 'test_cron_scan_failure_diagnostics_v1.py' in value['frames'][-1]['file']
    assert all(x not in raw for x in ('NEVER-SAVE-PASSWORD','NEVER-SAVE-TOKEN','sensitive_local'))
    assert value['exception_message_saved'] is False and value['locals_saved'] is False


def test_unknown_or_sensitive_missing_key_is_hash_only(tmp_path,monkeypatch):
    cron=load('isolated_structural_cron_hash','src/scheduler/cron.py')
    monkeypatch.setattr(cron,'SCAN_DIAGNOSTIC_DIR',tmp_path/'diag')
    key='https://example.invalid/?token=PRIVATE-ARG-VALUE'
    ref=cron._write_scan_failure(caught(key),'account_refresh')
    raw=open(ref['path'],encoding='utf8').read();value=json.loads(raw)
    assert set(value['missing_key'])=={'sha256'} and len(value['missing_key']['sha256'])==64
    assert key not in raw and 'PRIVATE-ARG-VALUE' not in raw


def test_generated_filename_cannot_smuggle_auth_text_into_stack(tmp_path,monkeypatch):
    cron=load('isolated_structural_cron_filename','src/scheduler/cron.py')
    monkeypatch.setattr(cron,'SCAN_DIAGNOSTIC_DIR',tmp_path/'diag')
    try:exec(compile("raise KeyError('seed')",'https://invalid.example/?token=PRIVATE-FILENAME','exec'))
    except KeyError as error:ref=cron._write_scan_failure(error,'account_refresh')
    raw=open(ref['path'],encoding='utf8').read();value=json.loads(raw)
    assert 'PRIVATE-FILENAME' not in raw and value['frames'][-1]['file']=='<external-source>'


def test_scheduler_diagnostic_does_not_unlatch_or_repeat_failed_scan(tmp_path,monkeypatch):
    calls=[];statuses=[]
    def fail(**kwargs):calls.append(kwargs);raise caught('seed')
    jobs=fake_cron(monkeypatch,fail,lambda **kwargs:None,
        lambda component,status,**kwargs:statuses.append((component,status)))
    monkeypatch.setitem(jobs['account_information_refresh'].__globals__,'SCAN_DIAGNOSTIC_DIR',tmp_path/'diag')
    jobs['account_information_refresh']();jobs['account_information_refresh']()
    assert len(calls)==1 and statuses[-1]==('account_refresh','manual_required')
    files=list((tmp_path/'diag').glob('*.json'))
    assert len(files)==1 and json.loads(files[0].read_text())['missing_key']=={'identifier':'seed'}


def test_diagnostic_write_failure_preserves_original_latch_and_status(tmp_path,monkeypatch):
    calls=[];statuses=[]
    def fail(**kwargs):calls.append(kwargs);raise caught('revision')
    jobs=fake_cron(monkeypatch,fail,lambda **kwargs:None,
        lambda component,status,**kwargs:statuses.append((component,status)))
    def unavailable(*a,**kwargs):raise PermissionError('cannot write diagnostic')
    monkeypatch.setitem(jobs['account_information_refresh'].__globals__,'_write_scan_failure',unavailable)
    jobs['account_information_refresh']();jobs['account_information_refresh']()
    assert len(calls)==1 and statuses[-1]==('account_refresh','manual_required')
