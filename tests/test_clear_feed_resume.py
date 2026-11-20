import sqlite3
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from src.operations_accounts import clear_feed_resume as resume


def good():
    return {'challenge': {'version':3,'blocking':False,'surface_states':[]},
            'page': {'host':'www.douyin.com','path':'/','ready_state':'complete',
                     'feed_cards':1,'videos':[{'ready_state':2}]}}


@pytest.mark.parametrize('section,change', [
    ('challenge',{'blocking':True}),('challenge',{'blocking':None}),
    ('challenge',{'surface_states':['loading']}),('challenge',{'version':2}),
    ('page',{'host':'other.test'}),('page',{'path':'/user/self'}),
    ('page',{'ready_state':'loading'}),('page',{'feed_cards':0}),
    ('page',{'videos':[]}),('page',{'videos':[{'ready_state':0}]})])
def test_missing_captcha_alone_is_not_enough(section,change):
    evidence=good();evidence[section].update(change)
    assert not resume.clear_loaded_feed(evidence)


def test_loaded_clear_feed_and_reservation_are_bounded(tmp_path):
    assert resume.clear_loaded_feed(good())
    path=tmp_path/'control.db'
    assert resume.reserve('a','first',4,{},path,100000)
    assert not resume.reserve('a','first',4,{},path,200000)
    assert not resume.reserve('a','second',6,{},path,100010)
    assert resume.reserve('b','other-account',1,{},path,100010)
    assert resume.reserve('a','later',8,{},path,200000)


def test_live_observation_is_scoped_expires_and_excludes_frame_content(tmp_path):
    path=tmp_path/'observations.db'
    evidence=good()|{'frames':[{'content':{'text':'PRIVATE'}}]}
    resume.record_observation('a','cmd',4,'feed_not_loaded',path,100,evidence)
    assert resume.latest_observation('a','cmd',path,110)['stage']=='feed_not_loaded'
    assert resume.latest_observation('b','cmd',path,110) is None
    assert resume.latest_observation('a','cmd',path,146)['stage']=='observation_stale'
    with sqlite3.connect(path) as db:
        assert 'PRIVATE' not in db.execute('SELECT evidence_json FROM clear_feed_observations').fetchone()[0]


@pytest.mark.parametrize('blocked,revision_change,retained',[(False,False,False),(True,False,False),(False,True,False),(False,False,True)])
def test_two_live_observations_close_then_request_identity_only(tmp_path,monkeypatch,blocked,revision_change,retained):
    from src.scheduler import account_refresh as backend
    from src.operations_accounts import browser_control_runtime as bridge
    from dataclasses import dataclass
    @dataclass
    class Context:
        profile:object
        binding:object
    path=tmp_path/'control.db';sqlite3.connect(path).close()
    monkeypatch.setattr(backend,'DB',path)
    from src.operations_accounts import retained_feed_session
    monkeypatch.setattr(retained_feed_session,'enabled',lambda *args:retained)
    monkeypatch.setattr(resume,'allowed',lambda *a:True)
    control={'account_uuid':'a','account_key':'key','state':'paused','revision':4,
             'error_code':'verification_ui_unconfirmed','updated_at':1}
    monkeypatch.setattr(resume,'read_control',lambda *a:control)
    monkeypatch.setattr(bridge,'binding_version',lambda ctx:'binding')
    complete=Mock(return_value={'accepted':True,'state':'recovery_requested'})
    monkeypatch.setattr(backend,'complete_account_handling',complete)
    evidence=good()
    page=Mock();page._cmd.side_effect=lambda action:{'evidence':evidence} if action=='inspect_feed_surface' else {'minimized':True}
    session=Mock();session.get_page.return_value=page
    resource=NS(manual_tasks={'cmd':'tab'},console_tasks={},account_uuid='a',account_key='key',
                context=Context(NS(status='active'),object()),runtime=Mock(),session=session,
                shutdown=Mock(),headless=False)
    resource.runtime.profiles.get.return_value=NS(status='active')
    actor=Mock(binding_version='binding',owner_id='owner',generation=2)
    actor.store.get.return_value={'state':'waiting_human','account_id':'a','created_at':2,
                                 'result':{'target':{'source':'recommend_feed'}}}
    monkeypatch.setattr(resume.time,'time',lambda:100000)
    resume.poll(actor,resource)
    complete.assert_not_called();session.close_tab.assert_not_called()
    monkeypatch.setattr(resume.time,'time',lambda:100016)
    if blocked:evidence['challenge']['blocking']=True
    if revision_change:control['revision']=5
    resume.poll(actor,resource)
    if blocked or revision_change:
        complete.assert_not_called();session.close_tab.assert_not_called()
    else:
        session.save_storage_state.assert_called_once()
        if retained:
            session.close_tab.assert_not_called();resource.shutdown.assert_not_called()
            assert resource.retained_feed_tab=='tab' and not resource.headless
        else:
            session.close_tab.assert_called_once_with('tab')
            assert resource.headless
        complete.assert_called_once_with('a','key',handled_by='system:loaded-clear-feed:cmd',
                                         plan_kinds=('playback',),expected_revision=4)
        assert not resource.manual_tasks
