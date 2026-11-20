import sqlite3
from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_admin_panel_saves_only_on_submit_and_does_not_create_business(tmp_path,monkeypatch):
    monkeypatch.setenv('AI_DOUYIN_WINDOW_SUPERVISION','1')
    from src.operations_accounts import window_supervision as windows
    from src.scheduler import account_refresh
    from src.web.components import auth
    controls=tmp_path/'controls.db';prefs=tmp_path/'supervision.db'
    with sqlite3.connect(controls) as db:
        db.execute('CREATE TABLE account_controls(account_uuid TEXT PRIMARY KEY,account_key TEXT,state TEXT)')
        db.execute("INSERT INTO account_controls VALUES('a','alpha','active')")
    monkeypatch.setattr(windows,'DB',prefs)
    monkeypatch.setattr(account_refresh,'DB',controls)
    monkeypatch.setattr(auth,'get_current_user',lambda:'qa-admin')
    monkeypatch.setattr(auth,'get_current_role',lambda:'admin')
    monkeypatch.setattr(auth,'has_permission',lambda *args:True)
    app=AppTest.from_string("from src.web.account_window_supervision import render_window_supervision\nrender_window_supervision('a','alpha')").run(timeout=30)
    assert not app.exception and not prefs.exists()
    app.checkbox[0].check().run()
    assert not prefs.exists()
    app.button[0].click().run()
    assert not app.exception
    assert windows.preference('a')['enabled']==1
    assert not any(b.label=='查看原运行窗口' for b in app.button)
    with sqlite3.connect(controls) as db:
        assert db.execute("SELECT state FROM account_controls WHERE account_uuid='a'").fetchone()[0]=='active'
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]==1


def test_viewer_panel_has_no_enabled_write_controls(tmp_path,monkeypatch):
    monkeypatch.setenv('AI_DOUYIN_WINDOW_SUPERVISION','1')
    from src.operations_accounts import window_supervision as windows
    from src.web.components import auth
    monkeypatch.setattr(windows,'DB',tmp_path/'no-viewer-writes.db')
    monkeypatch.setattr(auth,'get_current_user',lambda:'qa-viewer')
    monkeypatch.setattr(auth,'get_current_role',lambda:'viewer')
    monkeypatch.setattr(auth,'has_permission',lambda *args:False)
    app=AppTest.from_string("from src.web.account_window_supervision import render_window_supervision\nrender_window_supervision('a','alpha')").run(timeout=30)
    assert not app.exception and all(b.disabled for b in app.button)
    assert all(c.disabled for c in app.checkbox)
    assert not windows.DB.exists()
