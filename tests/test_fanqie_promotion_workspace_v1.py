"""Public facade/CLI/UI boundaries; no platform, browser or model calls."""
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from src.services.fanqie_promotion_workspace_v1 import PromotionWorkspace


class Accounts:
    def __init__(self,tmp_path):self.db=tmp_path/'browser.db';self.evidence=tmp_path/'evidence';self.calls=[]
    def installed(self):return False
    def latest_command(self,resource):return dict(command_id='old-login',kind='fanqie_login',state='running')
    def queue(self,resource,kind,**kw):self.calls.append(kind);return self.latest_command(resource)


def test_construction_and_status_never_create_missing_database(tmp_path):
    path=tmp_path/'p0.db';accounts=Accounts(tmp_path)
    workspace=PromotionWorkspace(path,accounts=accounts,launcher=lambda *args:pytest.fail('no launch'))
    assert not path.exists() and not accounts.db.exists()
    status=workspace.status()
    assert status['read_only'] and not status['migration_required'] and status['ledger_unavailable']
    assert not path.exists() and not accounts.db.exists()


def test_database_busy_is_unavailable_never_a_migration_request(tmp_path,monkeypatch):
    import sqlite3
    workspace=PromotionWorkspace(tmp_path/'p0.db',accounts=Accounts(tmp_path))
    def busy():raise sqlite3.OperationalError('database is locked')
    monkeypatch.setattr(workspace,'_candidates',busy)
    status=workspace.status()
    assert status['ledger_unavailable'] and not status['migration_required'] and not status['ledger_available']


def test_busy_login_return_is_not_reported_as_new_promotion_queue(tmp_path):
    accounts=Accounts(tmp_path)
    result=PromotionWorkspace(tmp_path/'p0.db',accounts=accounts,launcher=lambda *args:pytest.fail('no launch')).sync('resource')
    assert result['status']=='blocked_existing_command' and result['command_id']=='old-login'
    assert not result['new_request_queued']


def test_public_CLI_status_invokes_read_only_method(monkeypatch,capsys):
    from scripts import run_fanqie_promotion_workspace_v1 as cli
    calls=[]
    monkeypatch.setattr(cli,'PromotionWorkspace',lambda path:NS(status=lambda **kwargs:calls.append(kwargs) or dict(read_only=True)))
    value=cli.main(['status','--resource','resource'])
    assert value==dict(read_only=True) and calls==[dict(resource='resource')]
    assert json.loads(capsys.readouterr().out)['read_only']


def test_cli_outputs_comment_as_valid_json_on_gbk_pipe(monkeypatch,tmp_path):
    import io
    from scripts import run_fanqie_promotion_workspace_v1 as cli
    result={'comment':'想看后续，打开番茄小说搜「小说推广词」。原著是《测试小说》📖'}
    calls=[]
    monkeypatch.setattr(cli,'PromotionWorkspace',
        lambda path:NS(prepare_publish=lambda **params:calls.append(params) or result))
    stream=io.BytesIO()
    output=io.TextIOWrapper(stream,encoding='gbk',write_through=True)
    monkeypatch.setattr(cli.sys,'stdout',output)
    cli.main(['prepare-publish','--ledger',str(tmp_path/'unused')])
    assert json.loads(stream.getvalue().decode('gbk'))==result and calls==[{}]


def test_UI_workspace_mutations_require_admin_before_facade(monkeypatch):
    from src.web import fanqie_accounts_panel as ui
    monkeypatch.setattr(ui,'get_current_user',lambda:None)
    with pytest.raises(PermissionError):ui.mutate(NS(),'workspace_sync',resource='resource')


def test_UI_business_unknown_is_not_shown_as_completed(monkeypatch):
    from src.web import fanqie_accounts_panel as ui
    events=[]
    monkeypatch.setattr(ui.st,'warning',lambda text:events.append('warning'))
    monkeypatch.setattr(ui.st,'success',lambda text:events.append('success'))
    monkeypatch.setattr(ui.st,'info',lambda text:events.append('info'))
    ui._workspace_result(dict(application_status='outcome_unknown',confirmed=False,requires_read_only_sync=True))
    ui._workspace_result(dict(backfill_status='outcome_unknown',confirmed=False,requires_read_only_reconciliation=True))
    assert events==['warning','warning']


def test_UI_dispatch_requires_displayed_metadata_and_same_task_match_frozen_request():
    from src.web.fanqie_accounts_panel import prepared_metadata_matches
    metadata=dict(title='已确认标题',description='说明',hashtags=['小说推文'],ai_generated=True,fictional_story=True)
    candidate=dict(prepared_publication=dict(request=metadata,promotion=dict(row=dict(platform_task_id='task'))))
    assert prepared_metadata_matches(candidate,metadata,'task')
    assert not prepared_metadata_matches(candidate,dict(metadata,title='临时改标题'),'task')
    assert not prepared_metadata_matches(candidate,metadata,'other-task')
    candidate['prepared_publication']['comment']='本书推广评论'
    assert prepared_metadata_matches(candidate,dict(metadata,comment='本书推广评论'),'task')
    assert not prepared_metadata_matches(candidate,dict(metadata,comment='另一部作品的评论'),'task')
    assert not prepared_metadata_matches(candidate,metadata,'task')


def test_workspace_page_previews_copy_and_scopes_approval_to_the_displayed_alias(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    candidate=dict(candidate_id='candidate1',book_id='book1',book_name='门后的信',
        media={'path':str(tmp_path/'missing.mp4')},prepared_publication=None)
    options=[dict(key=k,alias=a,label=a,book_id=b) for k,a,b in [
        ('first','第一封信','book1'),('second','另一封信','book1'),('different','其他小说','book2')]]
    state=dict(candidates=[candidate],promotion_options=options,douyin_status={'available':True,'publication_ready':True})
    monkeypatch.setattr(PromotionWorkspace,'status',lambda *args:state)
    app=AppTest.from_string(
        "from types import SimpleNamespace as NS\nfrom src.web.fanqie_accounts_panel import render_workspace\n"
        "render_workspace(NS(get=lambda _: {},check_association=lambda _: {'account_key':'novel'}),'resource',admin=True)"
    ).run(timeout=30)
    assert not app.exception
    task=app.selectbox(key='fanqie_workspace_task')
    assert task.options==['第一封信','另一封信']
    task.select('first')
    app.text_input(key='fanqie_workspace_title_candidate1').set_value('门后藏着谁的信？').run(timeout=30)
    assert not app.exception
    caption,comment=[item.value for item in app.text]
    assert '门后藏着谁的信？' in caption and '第一封信' not in caption
    assert '「第一封信」' in comment and '《门后的信》' in comment
    checkbox=lambda:next(item for item in app.checkbox if '发送作者评论' in item.label)
    checkbox().check().run(timeout=30)
    assert checkbox().value
    app.selectbox(key='fanqie_workspace_task').select('second').run(timeout=30)
    assert not app.exception and not checkbox().value
    assert '「另一封信」' in app.text[-1].value


def _status_workspace(tmp_path,monkeypatch,*,controls=True):
    import sqlite3
    accounts=Accounts(tmp_path);accounts.control_db=tmp_path/'account_refresh.db'
    accounts.get=lambda resource:dict(resource_id=resource,douyin_account_uuid='douyin-user')
    accounts.check_association=lambda env:dict(account_uuid='douyin-user',account_key='novel')
    accounts.latest_command=lambda resource:None
    if controls:
        with sqlite3.connect(accounts.control_db) as db:
            db.execute('CREATE TABLE account_controls(account_uuid,state,reason,error_code,updated_at)')
            db.execute("INSERT INTO account_controls VALUES('douyin-user','paused','manual check','identity_pending',1)")
    from src.operations_accounts.browser_control import BrowserControlStore
    store=BrowserControlStore(accounts.db)
    with sqlite3.connect(accounts.db) as db:
        for cid,kind,state,error,at in [('manual-original','manual','waiting_human','',1),('publish-original','publish','failed','platform_guard',2)]:
            db.execute('INSERT INTO browser_control_commands(command_id,account_id,binding_version,kind,idempotency_key,payload,request_sha,priority,state,error_code,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (cid,'douyin-user','binding',kind,cid,'{}','fixture',0,state,error,at,at))
    workspace=PromotionWorkspace(tmp_path/'p0.db',accounts=accounts)
    frozen=json.dumps(dict(book_id='book',book_name='书名',media={},account=dict(account_uuid='douyin-user',binding_version='binding')))
    candidate=dict(candidate_id='c',frozen_json=frozen,task_id=1,video_job_id=1,publish_id=None,
        command_id='publish-original',dispatch_state='queued',review_json=None,prepared_json=None)
    monkeypatch.setattr(workspace,'_candidates',lambda:NS(list_candidates=lambda:[candidate]))
    monkeypatch.setattr(workspace,'latest_snapshot',lambda resource:None)
    return workspace,accounts


def test_linked_pause_original_manual_and_real_publish_state_are_read_only_projected(tmp_path,monkeypatch):
    workspace,accounts=_status_workspace(tmp_path,monkeypatch)
    before=accounts.control_db.read_bytes(),accounts.db.read_bytes()
    status=workspace.status('fanqie-resource');linked=status['douyin_status']
    assert linked['available'] and linked['control_state']=='paused' and not linked['publication_ready']
    assert linked['waiting_original_manual_window'] and linked['waiting_original_identity_check']
    assert status['candidates'][0]['publication_command_state']=='failed'
    assert status['candidates'][0]['publication_command_error']=='platform_guard'
    assert before==(accounts.control_db.read_bytes(),accounts.db.read_bytes())


def test_missing_linked_control_store_is_unavailable_not_active_and_not_created(tmp_path,monkeypatch):
    workspace,accounts=_status_workspace(tmp_path,monkeypatch,controls=False)
    status=workspace.status('fanqie-resource')['douyin_status']
    assert not status['available'] and not status['publication_ready'] and status['control_state']=='unavailable'
    assert not accounts.control_db.exists()


def test_verified_settled_history_not_a_blocker_but_new_unknown_is(tmp_path,monkeypatch):
    import sqlite3
    from src.operations_accounts import publication_autonomous_reconciliation as reconciliation
    from src.operations_accounts.browser_control import BrowserControlStore,_json
    workspace,accounts=_status_workspace(tmp_path,monkeypatch)
    # Reuse the shared exact snapshot settlement projection, without reading
    # this machine's unrelated historical registry in the synthetic fixture.
    monkeypatch.setattr(reconciliation,'_completed_resolution',lambda db,uid:None)
    with sqlite3.connect(accounts.control_db) as db:
        db.execute("UPDATE account_controls SET state='active'")
    with sqlite3.connect(accounts.db) as db:
        db.row_factory=sqlite3.Row
        db.execute("UPDATE browser_control_commands SET state='outcome_unknown' WHERE command_id='manual-original'")
        settled=BrowserControlStore._command(db.execute("SELECT * FROM browser_control_commands WHERE command_id='manual-original'").fetchone())
        db.execute(f'CREATE TABLE {reconciliation.TABLE}(account_id,resolution)')
        db.execute(f'INSERT INTO {reconciliation.TABLE} VALUES(?,?)',('douyin-user',_json(dict(settled_readonly_snapshots=[settled]))))
    state=workspace._douyin_status('fanqie-resource')
    assert state['available'] and state['publication_ready'] and not state['active_commands']
    with sqlite3.connect(accounts.db) as db:
        db.execute("UPDATE browser_control_commands SET state='outcome_unknown' WHERE command_id='publish-original'")
    state=workspace._douyin_status('fanqie-resource')
    assert state['available'] and not state['publication_ready']
    assert [c['command_id'] for c in state['active_commands']]==['publish-original']
    with sqlite3.connect(accounts.db) as db:
        db.execute(f'UPDATE {reconciliation.TABLE} SET resolution=?',('malformed-json',))
    state=workspace._douyin_status('fanqie-resource')
    assert not state['available'] and state['control_state']=='unavailable'


def test_display_limit_does_not_hide_older_unresolved_blocker(tmp_path,monkeypatch):
    import sqlite3
    workspace,accounts=_status_workspace(tmp_path,monkeypatch)
    with sqlite3.connect(accounts.control_db) as db:db.execute("UPDATE account_controls SET state='active'")
    with sqlite3.connect(accounts.db) as db:
        db.execute("UPDATE browser_control_commands SET kind='recovery',state='outcome_unknown' WHERE command_id='manual-original'")
        for n in range(21):
            db.execute('INSERT INTO browser_control_commands(command_id,account_id,binding_version,kind,idempotency_key,payload,request_sha,priority,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (f'queued-{n}','douyin-user','binding','collect',f'key-{n}','{}','fixture',0,'queued',n+10,n+10))
    state=workspace._douyin_status('fanqie-resource')
    assert state['available'] and len(state['active_commands'])==20
    assert all(c['state']=='queued' for c in state['active_commands']) and not state['publication_ready']
