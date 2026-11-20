"""Private owner DB + public CLI protocol; platform reader is an explicit edge."""
import json
from pathlib import Path
import sys

import pytest

from src.platform_adapter import fanqie_filled_details_controls_v2 as adapter

BOOK='7302660145530539062';NAME='你敢惹我？我有六个反派儿子';ALIAS='从旧饭桌开始改命'


def test_private_owner_strict_read_result_and_native_fatal_are_separate(tmp_path,monkeypatch):
    from test_fanqie_managed_promotion_v1 import accounts,Session
    from src.operations_accounts.fanqie_account_control import run_owner
    from src.operations_accounts.fanqie_readonly_startup_recovery_v1 import READONLY_KINDS
    from src.platform_adapter.browser_session import BrowserWorkerUnavailable
    a,env=accounts.__wrapped__(tmp_path);calls=[];mode=['ordinary']
    def reader(page,*,book_id,book_name,alias,guard,checkpoint):
        guard();assert (book_id,book_name,alias)==(BOOK,NAME,ALIAS)
        assert page is Session.instances[-1] and page.url.startswith('https://kol.fanqieopen.com/page/promotion-list')
        calls.append(mode[0]);checkpoint('exact_row_controls',dict(target=alias))
        if mode[0]=='typed':raise adapter.DetailsControlsNotConfirmed('exact_filled_alias_row_not_unique')
        if mode[0]=='fatal':raise BrowserWorkerUnavailable('synthetic existing worker response lost')
        return dict(schema='fanqie_filled_details_controls_observation/v2',status='view_result_unconfirmed',
            append_capability_verified=False,view_clicks=1,uploaded=False,submitted=False,deleted=False,old_ledger_changed=False)
    monkeypatch.setattr(adapter,'inspect_filled_details_controls',reader)
    kind='fanqie_filled_details_controls';target=dict(book_id=BOOK,book_name=NAME,lookup_alias=ALIAS)
    for extra in [dict(promotion_request={}),dict(lookup_request={}),dict(observer_request={}),dict(locate=True),
                  dict(chapters=1),dict(snapshot_version='v2'),dict(binding_uuid='wrong'),dict(manifest_sha256='wrong')]:
        with pytest.raises(ValueError):a.queue(env['resource_id'],kind,**target,**extra)
    assert kind in READONLY_KINDS
    cmd=a.queue(env['resource_id'],kind,**target);assert cmd['payload']==dict(environment_key=env['environment_key'],**target)
    result=run_owner(env['resource_id'],a,session_factory=Session)
    assert result['state']=='succeeded' and result['result']['read_observation_status']=='view_result_unconfirmed'
    evidence=json.loads(Path(result['result']['filled_details_controls']['path']).read_text(encoding='utf8'))
    assert evidence['managed_subject']['task_id']==cmd['command_id'] and evidence['managed_subject']['platform_identity_key']=='uid:12345'
    assert evidence['managed_subject']['owner_id']==result['owner_id']
    assert evidence['checkpoint_refs'] and result['result']['automatic_retry'] is False
    mode[0]='typed';a.queue(env['resource_id'],kind,**target);result=run_owner(env['resource_id'],a,session_factory=Session)
    assert result['state']=='succeeded' and result['result']['read_observation_status']=='read_observation_not_confirmed'
    mode[0]='fatal';a.queue(env['resource_id'],kind,**target);result=run_owner(env['resource_id'],a,session_factory=Session)
    assert result['state']=='outcome_unknown' and len(calls)==3 and Session.submit_count==0


def test_public_cli_routes_only_exact_read_target_and_rejects_write_flags(monkeypatch,capsys):
    from scripts import run_fanqie_account as cli
    calls=[]
    class Accounts:
        def queue(self,*args,**kw):calls.append((args,kw));return dict(command_id='private-cid')
    monkeypatch.setattr(cli,'FanqieAccounts',lambda *args,**kw:Accounts())
    monkeypatch.setattr(cli,'launch_worker',lambda *args,**kw:dict(launched=False,fixture=True))
    argv=['prog','filled-details-controls','--resource','private-resource','--book-id',BOOK,'--book-name',NAME,'--lookup-alias',ALIAS]
    monkeypatch.setattr(sys,'argv',argv);cli.main()
    assert calls==[(('private-resource','fanqie_filled_details_controls'),dict(book_name=NAME,chapters=0,book_id=BOOK,lookup_alias=ALIAS))]
    for extra in [['--request','unused.json'],['--lookup-request','unused.json'],['--observer-request','unused.json'],
                  ['--locate'],['--chapters','1'],['--snapshot-version','v2'],['--binding-uuid','wrong'],['--identity','wrong']]:
        monkeypatch.setattr(sys,'argv',argv+extra)
        with pytest.raises(SystemExit) as error:cli.main()
        assert error.value.code==2
    assert len(calls)==1
