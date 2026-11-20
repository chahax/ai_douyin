import ast
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    from src.shared import database
    from src.memory.models import ConversationSession,ConversationMessage
    from src.memory.error_review_model import ErrorReview
    from src.shared.llm_usage_log_model import LlmUsageLog
    from src.web.components import auth
    engine=create_engine('sqlite:///'+str(tmp_path/'tools.db'))
    database.Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    monkeypatch.setattr(database,'SessionLocal',factory)
    monkeypatch.setattr(auth,'get_current_user',lambda:'alice')
    monkeypatch.setattr(auth,'get_current_role',lambda:'editor')
    with factory() as db:
        for user in ('alice','bob'):
            row=ConversationSession(user_id=user,status='active');db.add(row);db.flush()
            db.add(ConversationMessage(session_id=row.id,role='tool',content='fixture',skill_name='fixture',
                tool_success=False,tool_error=user+'_diagnostic',created_at=datetime.utcnow()))
        db.add(ErrorReview(source='skill_exec',location='skill:fixture',summary='SYSTEM_PRIVATE',
                           last_seen_at=datetime.utcnow(),severity='high',occurrence_count=1))
        db.commit()
    yield factory
    engine.dispose()


def test_skill_runtime_is_owned_for_editor_and_global_only_for_admin(isolated,monkeypatch):
    from src.web.components import auth
    script='from src.web.skill_dashboard import _render_runtime\n_render_runtime([])\n'
    app=AppTest.from_string(script,default_timeout=30).run()
    assert not app.exception
    assert len(app.dataframe)==1
    assert app.dataframe[0].value['错误摘要'].tolist()==['alice_diagnostic']
    monkeypatch.setattr(auth,'get_current_role',lambda:'admin')
    app.run()
    assert not app.exception
    assert set(app.dataframe[0].value['错误摘要'])=={'alice_diagnostic','bob_diagnostic'}
    assert 'SYSTEM_PRIVATE' in app.dataframe[1].value['问题摘要'].tolist()


def test_skill_catalogue_and_failed_history_do_not_expose_raw_errors(isolated,monkeypatch):
    import src.agent.registry as registry
    from src.web.components import auth
    def fail(*a,**kw):raise RuntimeError('PRIVATE_TOKEN')
    monkeypatch.setattr(registry,'SkillRegistry',fail)
    app=AppTest.from_string('from src.web.skill_dashboard import page_skill_center\npage_skill_center()').run()
    assert not app.exception and app.error
    assert all('PRIVATE_TOKEN' not in e.value for e in app.error)
    monkeypatch.setattr(auth,'get_current_role',lambda:'viewer')
    app.run()
    assert not app.error and app.warning


def test_skill_catalogue_filter_and_detail_never_execute_capability(isolated,monkeypatch):
    from src.agent import registry
    skills=[NS(name=name,description='synthetic description',requires_confirmation=True,timeout_s=30,
               retries=0,idempotent=True,params=[],examples=[],retry_on=[]) for name in
               ('rag_search','generate_audio','auto_reply_comments')]
    monkeypatch.setattr(registry,'SkillRegistry',lambda:NS(list_all=lambda:skills))
    app=AppTest.from_string('from src.web.skill_dashboard import page_skill_center\npage_skill_center()',default_timeout=30).run()
    assert not app.exception
    app.text_input(key='skill_search').set_value('配音').run()
    assert not app.exception and any(v.value=='文本配音' for v in app.subheader)
    app.selectbox(key='skill_runtime_filter').set_value('generate_audio').run()
    assert not app.exception and any('暂无调用记录' in v.value for v in app.info)


def test_legacy_history_rejects_outside_paths_and_never_dispatches(tmp_path,monkeypatch):
    from src.web import novel_agent_panel_v9 as page
    monkeypatch.setattr(page,'ROOT',tmp_path)
    run=tmp_path/'data/creative_workflows/original'
    run.mkdir(parents=True)
    (run/'state.json').write_text('{"status":"needs_attention","original_id":"fixture-original"}')
    (run/'SCREENPLAY.md').write_text('synthetic review text')
    outside=tmp_path/'outside';outside.mkdir()
    (outside/'state.json').write_text('{"private":"MUST_NOT_READ"}')
    with pytest.raises(ValueError):page.legacy_creative_records(outside)
    with pytest.raises(ValueError):page.legacy_creative_records(run/'../../../../outside')
    monkeypatch.setattr(page,'_spawn',lambda *a:pytest.fail('history must not dispatch'))
    app=AppTest.from_string('from src.web.novel_agent_panel_v9 import page_legacy_creative_records\npage_legacy_creative_records()',default_timeout=30).run()
    app.text_input(key='creative_v9_history_path').set_value(str(outside)).run()
    assert not app.exception and app.error and not app.json
    app.text_input(key='creative_v9_history_path').set_value(str(run)).run()
    assert not app.exception and not app.error and app.json


def test_local_model_usage_is_readonly_and_counts_all_rows_without_network(isolated):
    from src.shared.llm_usage_log_model import LlmUsageLog
    with isolated() as db:
        db.add_all([LlmUsageLog(model='fixture-model',caller='fixture-caller',prompt_tokens=10,completion_tokens=5,cost_usd=0,cache_hit=True),
                    LlmUsageLog(model='fixture-model',caller='fixture-caller',prompt_tokens=20,completion_tokens=10,cost_usd=0.5,cache_hit=False)])
        db.commit()
    source=(Path(__file__).parents[1]/'src/web/app.py').read_text(encoding='utf-8-sig')
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='page_llm_usage')
    script='import streamlit as st\nfrom src.web.components.ui import page_header\n'+ast.get_source_segment(source,node)+'\npage_llm_usage()\n'
    app=AppTest.from_string(script,default_timeout=30).run()
    assert not app.exception
    values={m.label:m.value for m in app.metric}
    assert values['总调用次数']=='2' and values['累计词元（Token）']=='45' and values['缓存命中率']=='50.0%'
    assert values['已记录成本 (USD)']=='$0.5000'
    app.run()
    with isolated() as db:assert db.query(LlmUsageLog).count()==2
    with isolated() as db:
        db.add(LlmUsageLog(model='unknown',caller='unknown',cost_usd=None));db.commit()
    app.run()
    assert not app.exception and any('费用未记录 1 条' in v.value for v in app.caption)
