import ast
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest


def test_personal_memory_queries_and_page_are_scoped_and_readonly(tmp_path, monkeypatch):
    from src.shared import database
    from src.memory import humane_recorder, MemoryManager
    from src.memory.models import ConversationSession, ConversationMessage
    from src.memory.problem_memory import MemoryLayerManager, ProblemMemory
    from src.web.components import auth
    engine = create_engine('sqlite:///' + str(tmp_path / 'memory.db'))
    database.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(database, 'SessionLocal', factory)
    monkeypatch.setattr(humane_recorder, 'SessionLocal', factory)
    monkeypatch.setattr(auth, 'get_current_user', lambda: 'alice')
    monkeypatch.setattr(MemoryManager, 'get_or_create_active_session',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError('view must not create a session')))
    with factory() as db:
        for user in ('alice', 'bob'):
            session = ConversationSession(user_id=user, title=user, status='archived')
            db.add(session)
            db.flush()
            db.add(ConversationMessage(session_id=session.id, role='user', content=user + '_text',
                humane_summary=user + '_followup', needs_followup=True, topics=['fixture-topic']))
            db.add(ProblemMemory(user_id=user, problem_text=user + '_problem', status='unresolved'))
        db.commit()
        with MemoryLayerManager(db) as manager:
            assert [r['problem_text'] for r in manager.get_unresolved_problems(user_id='alice')] == ['alice_problem']
        before = db.query(ConversationSession).count()
    assert [r['humane_summary'] for r in humane_recorder.get_followup_reminders('alice')] == ['alice_followup']
    assert [r['content'] for r in humane_recorder.get_messages_by_topic('alice', 'fixture-topic')] == ['alice_text']
    source = (Path(__file__).parents[1] / 'src/web/app.py').read_text(encoding='utf-8-sig')
    function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'page_memory')
    script = ('import streamlit as st\nfrom src.web.components.ui import page_header\n'
              'from src.web.components.auth import get_current_user\n'
              + ast.get_source_segment(source, function) + '\npage_memory()\n')
    app = AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception
    visible = '\n'.join(x.value for x in app.markdown)
    assert 'alice_problem' in visible and 'alice_followup' in visible and 'bob_' not in visible
    app.run()
    with factory() as db:
        assert db.query(ConversationSession).count() == before
    engine.dispose()
