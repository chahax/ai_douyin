import ast
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest


@pytest.fixture
def setup(tmp_path,monkeypatch):
    from src.shared import database
    from src.memory import MemoryManager
    from src.memory.models import ConversationSession,ConversationMessage
    from src.web import chat_sessions as actions
    from src.web.components import auth
    engine=create_engine('sqlite:///'+str(tmp_path/'chat.db'))
    database.Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    monkeypatch.setattr(database,'SessionLocal',factory)
    monkeypatch.setattr('src.memory.manager.SessionLocal',factory)
    monkeypatch.setattr(auth,'get_current_user',lambda:'alice')
    monkeypatch.setattr(auth,'get_current_role',lambda:'editor')
    with factory() as db:
        for user,status,title in [('alice','active','当前'),('alice','archived','历史'),('bob','archived','不可见')]:
            row=ConversationSession(user_id=user,status=status,title=title)
            db.add(row);db.flush()
            db.add(ConversationMessage(session_id=row.id,role='assistant',content=title+'_消息'))
        db.commit()
    calls=[]
    plan={'plan':{'target_skill':'fixture_only','skill_kwargs':{'account_key':'synthetic','token':'PRIVATE_TEST'}}}
    class Agent:
        def __init__(self,user_id):
            assert user_id=='alice';calls.append('construct')
        def chat_stream(self,text,session_id):
            calls.append('stream')
            with factory() as db:
                row=db.get(ConversationSession,session_id);row.pending_plan=plan
                db.add(ConversationMessage(session_id=session_id,role='user',content=text))
                db.add(ConversationMessage(session_id=session_id,role='assistant',content='隔离计划待确认'))
                db.commit()
            self.last_streaming_response=NS(text='隔离计划待确认',needs_confirmation=True,pending_plan=plan['plan'])
            yield '隔离计划待确认'
        def chat(self,text,session_id):
            calls.append(('execute',text,session_id))
            with factory() as db:
                db.get(ConversationSession,session_id).pending_plan=None
                db.add(ConversationMessage(session_id=session_id,role='assistant',content='已执行合成计划'))
                db.commit()
            return NS(text='已执行合成计划',needs_confirmation=False,pending_plan=None)
    monkeypatch.setitem(sys.modules,'src.agent',NS(Agent=Agent))
    monkeypatch.setitem(sys.modules,'src.platform_adapter.fanqie_batch',NS(read_progress=lambda:None,
        clear_progress=lambda:pytest.fail('view may not clear progress')))
    source=(Path(__file__).parents[1]/'src/web/app.py').read_text(encoding='utf-8-sig')
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='page_chat')
    script=('import streamlit as st\nfrom src.web.components.ui import page_header\n'
            'from src.web.components.auth import get_current_user,get_current_role,has_permission\n'
            'from src.shared.logger import logger\n'+ast.get_source_segment(source,node)+'\npage_chat()\n')
    app=AppTest.from_string(script,default_timeout=30).run()
    yield app,factory,calls,plan
    engine.dispose()


def button(app,label):
    return next(b for b in app.button if b.label==label)


def test_plan_confirmation_survives_rerender_and_executes_once(setup):
    app,factory,calls,plan=setup
    assert not app.exception and not calls
    app.chat_input[0].set_value('生成隔离计划').run()
    assert not app.exception
    app.run()
    assert any(b.label=='✅ 确认执行' for b in app.button)
    assert app.chat_input[0].disabled
    assert 'PRIVATE_TEST' not in str([v.value for v in app.json])
    button(app,'✅ 确认执行').click().run()
    assert not app.exception and len([c for c in calls if isinstance(c,tuple)])==1
    app.run()
    assert not any(b.label=='✅ 确认执行' for b in app.button)


def test_loading_archived_session_is_scoped_and_has_no_name_error(setup):
    app,factory,calls,plan=setup
    button(app,'📄 历史').click().run()
    assert not app.exception and not calls
    from src.memory.models import ConversationSession
    with factory() as db:
        assert db.get(ConversationSession,2).status=='active'
        assert db.get(ConversationSession,3).status=='archived'
    assert any('历史_消息' in v.value for v in app.markdown)


def test_cancel_does_not_construct_agent_or_execute_model(setup):
    app,factory,calls,plan=setup
    from src.memory.models import ConversationSession
    with factory() as db:
        db.get(ConversationSession,1).pending_plan=plan;db.commit()
    app.run()
    button(app,'❌ 取消').click().run()
    assert not app.exception and not calls
    with factory() as db:
        assert db.get(ConversationSession,1).pending_plan is None


def test_session_delete_needs_confirmation_and_preserves_other_user(setup):
    app,factory,calls,plan=setup
    assert app.button(key='del_2').disabled
    next(c for c in app.checkbox if c.key.startswith('delete_session_confirm_2_')).check()
    app.button(key='del_2').click().run()
    assert not app.exception
    from src.memory.models import ConversationSession
    with factory() as db:
        assert db.get(ConversationSession,2) is None and db.get(ConversationSession,3) is not None


def test_exact_plan_receipt_rejects_duplicate_unknown_and_foreign_user(setup):
    app,factory,calls,plan=setup
    from src.web import chat_sessions as actions
    from src.memory.models import ConversationSession
    with factory() as db:
        db.get(ConversationSession,1).pending_plan=plan;db.commit()
    sha=actions.digest(plan)
    for user,sid,token in [('bob',1,sha),('alice',3,sha),('alice',1,'wrong')]:
        with pytest.raises(ValueError):actions.resolve(user,sid,token,'confirm',lambda _:pytest.fail('foreign call'))
    def unknown(_):raise RuntimeError('PRIVATE_DIAGNOSTIC')
    with pytest.raises(RuntimeError):actions.resolve('alice',1,sha,'confirm',unknown)
    with pytest.raises(ValueError):actions.resolve('alice',1,sha,'confirm',lambda _:pytest.fail('replay'))
    with factory() as db:
        assert db.query(actions.ChatActionReceipt).one().status=='outcome_unknown'


def test_session_actions_are_owned_and_empty_title_is_not_success(setup):
    app,factory,calls,plan=setup
    from src.web import chat_sessions as actions
    assert not actions.rename('alice',1,'   ')
    assert not actions.rename('alice',3,'wrong')
    assert not actions.activate('alice',3)
    from src.memory.models import ConversationSession
    with factory() as db: foreign_token=actions.session_token(db.get(ConversationSession,3))
    assert not actions.delete('alice',3,confirmed=True,expected_token=foreign_token)
    assert not actions.new('alice',expected_active=999)
    assert actions.rename('alice',1,'新标题')


def test_viewer_can_read_but_cannot_call_model_or_mutate_sessions(setup,monkeypatch):
    app,factory,calls,plan=setup
    from src.web.components import auth
    monkeypatch.setattr(auth,'get_current_role',lambda:'viewer')
    app.run()
    assert not app.exception and app.chat_input[0].disabled and not calls
    assert app.button(key='new_session').disabled and app.button(key='archive_active').disabled


def test_page_read_does_not_create_confirmation_schema_and_bad_progress_is_safe(setup,monkeypatch):
    app,factory,calls,plan=setup
    from src.web import chat_sessions as actions
    from src.memory.models import ConversationSession
    batch=sys.modules['src.platform_adapter.fanqie_batch']
    with factory() as db:
        bind=db.get_bind()
        actions.ChatActionReceipt.__table__.drop(bind,checkfirst=True)
        before=db.query(ConversationSession).count()
    monkeypatch.setattr(batch,'read_progress',lambda:{'running':True,'total':10,'current':-1,'updated_at':'invalid'})
    app.run()
    assert not app.exception and not calls
    with factory() as db:
        assert db.query(ConversationSession).count()==before
        assert not inspect(db.get_bind()).has_table(actions.ChatActionReceipt.__tablename__)


def test_unresolved_plan_cannot_be_deleted_even_after_archiving(setup):
    app,factory,calls,plan=setup
    from src.web import chat_sessions as actions
    from src.memory.models import ConversationSession
    with factory() as db:
        db.get(ConversationSession,2).pending_plan=plan;db.commit()
    app.run()
    assert app.button(key='del_2').disabled
    assert any('当前不能删除' in v.value for v in app.caption)
    token=actions.view('alice')['archived'][0]['token']
    assert not actions.delete('alice',2,confirmed=True,expected_token=token)
    assert actions.activate('alice',2)


def test_delete_token_is_bound_to_observed_session_version(setup):
    app,factory,calls,plan=setup
    from src.web import chat_sessions as actions
    row=actions.view('alice')['archived'][0]
    assert actions.rename('alice',row['id'],'已变化')
    assert not actions.delete('alice',row['id'],confirmed=True,expected_token=row['token'])


def test_missing_confirmation_response_is_unknown_and_not_replayed(setup):
    app,factory,calls,plan=setup
    from src.web import chat_sessions as actions
    from src.memory.models import ConversationSession
    with factory() as db:
        db.get(ConversationSession,1).pending_plan=plan;db.commit()
    with pytest.raises(RuntimeError):actions.resolve('alice',1,actions.digest(plan),'confirm',lambda _:None)
    assert actions.view('alice')['active']['receipt']=='outcome_unknown'


def test_unknown_receipt_remains_visible_when_agent_already_cleared_pending_plan(setup):
    app,factory,calls,plan=setup
    from src.web import chat_sessions as actions
    from src.memory.models import ConversationSession
    with factory() as db:
        db.get(ConversationSession,1).pending_plan=plan;db.commit()
    def fail_after_claim(_):
        with factory() as db:
            db.get(ConversationSession,1).pending_plan=None;db.commit()
        raise RuntimeError('synthetic lost response')
    with pytest.raises(RuntimeError):actions.resolve('alice',1,actions.digest(plan),'confirm',fail_after_claim)
    app.run()
    assert not app.exception and any('尚未结清的计划受理记录' in v.value for v in app.warning)
    assert not any(b.label=='✅ 确认执行' for b in app.button) and not calls


def test_viewer_forged_disabled_button_event_still_cannot_write(setup,monkeypatch):
    app,factory,calls,plan=setup
    from src.web import chat_dashboard as page
    from src.web.components import auth
    from src.memory.models import ConversationSession
    monkeypatch.setattr(auth,'get_current_role',lambda:'viewer')
    real_button=page.st.button
    def forged(label,*args,**kwargs):
        pressed=real_button(label,*args,**kwargs)
        return True if kwargs.get('key')=='new_session' else pressed
    monkeypatch.setattr(page.st,'button',forged)
    app.run()
    assert not app.exception and not calls
    with factory() as db:assert db.query(ConversationSession).count()==3
