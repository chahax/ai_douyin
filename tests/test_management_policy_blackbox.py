"""Actual page functions + actual service SQLite, all disposable test data."""
import ast
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    from src.services import database
    from src.web.components import auth
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'policies.db')
    monkeypatch.setattr(auth, 'get_current_role', lambda: 'admin')
    return database


def app_for(name):
    # Load the exact registered page functions without running app navigation,
    # authentication cookie machinery, scheduler startup or production services.
    source = (Path(__file__).parents[1] / 'src/web/app.py').read_text(encoding='utf-8-sig')
    tree = ast.parse(source)
    functions = '\n\n'.join(ast.get_source_segment(source, node) for node in tree.body
                            if isinstance(node, ast.FunctionDef)
                            and node.name in {name, '_valid_rule_regex'})
    script = ('import streamlit as st\n'
              'from src.web.components.ui import page_header\n'
              'from src.web.components.auth import get_current_role, has_permission\n'
              + functions + '\n' + name + '()\n')
    return AppTest.from_string(script, default_timeout=30).run()


def item(elements, label):
    return next(e for e in elements if e.label == label)


def test_rule_empty_regex_and_model_validation_before_storage(isolated):
    from src.services.reply_rules_service import get_rules
    app = app_for('page_rules')
    item(app.button, '添加规则').click().run()
    assert any('空格' in w.value for w in app.warning) and get_rules() == []
    item(app.text_input, '触发关键词').set_value('[')
    item(app.text_input, '回复模板').set_value('回复')
    item(app.selectbox, '匹配方式').set_value('regex')
    item(app.button, '添加规则').click().run()
    assert any('正则表达式无效' in w.value for w in app.warning) and get_rules() == []
    item(app.selectbox, '匹配方式').set_value('contains')
    item(app.selectbox, '回复类型').set_value('llm')
    item(app.text_input, '大模型').set_value('  ')
    item(app.button, '添加规则').click().run()
    assert any('模型名称' in w.value for w in app.warning) and get_rules() == []


def test_rule_add_disable_missing_id_and_confirmed_delete(isolated):
    from src.services.reply_rules_service import get_rules
    app = app_for('page_rules')
    item(app.text_input, '触发关键词').set_value('  合同  ')
    item(app.text_input, '回复模板').set_value('  已收到  ')
    item(app.button, '添加规则').click().run()
    assert not app.exception and any('添加成功' in x.value for x in app.success)
    rule = get_rules()[0]
    assert rule.keyword == '合同' and rule.reply_template == '已收到'
    item(app.selectbox, '操作').set_value('禁用')
    item(app.button, '执行操作').click().run()
    assert not get_rules()[0].enabled and any('禁用' in x.value for x in app.success)
    item(app.number_input, '规则 ID').set_value(999)
    item(app.button, '执行操作').click().run()
    assert any('找不到' in x.value for x in app.warning)
    item(app.number_input, '规则 ID').set_value(rule.id)
    item(app.selectbox, '操作').set_value('删除').run()
    assert item(app.button, '执行操作').disabled
    item(app.checkbox, '确认删除此规则').check()
    item(app.button, '执行操作').click().run()
    assert get_rules() == [] and any('已删除' in x.value for x in app.success)


def test_words_empty_duplicate_and_empty_batch_have_visible_feedback(isolated):
    from src.services.blocked_words_service import get_blocked_words
    app = app_for('page_blocked_words')
    initial = len(get_blocked_words())
    item(app.text_input, '违禁词').set_value('   ')
    item(app.button, '添加').click().run()
    assert app.warning and len(get_blocked_words()) == initial
    item(app.button, '批量导入').click().run()
    assert any('有效词条' in x.value for x in app.warning)
    item(app.text_input, '违禁词').set_value('测试词')
    item(app.button, '添加').click().run()
    assert any('已添加' in x.value for x in app.success)
    item(app.button, '添加').click().run()
    assert any('已存在' in x.value for x in app.info)
    assert len(get_blocked_words()) == initial + 1
    item(app.number_input, '删除违禁词 ID').set_value(999).run()
    assert item(app.button, '🗑️ 删除').disabled
    item(app.checkbox, '确认删除此词条').check()
    item(app.button, '🗑️ 删除').click().run()
    assert any('找不到' in x.value for x in app.warning)


def test_deleted_all_words_do_not_reappear_on_read_or_refresh(isolated):
    from src.services.blocked_words_service import get_blocked_words, remove_blocked_word
    initial = get_blocked_words()
    assert initial  # Brand-new installation still receives defaults once.
    for row in initial:
        assert remove_blocked_word(row['id'])
    assert get_blocked_words() == []
    app = app_for('page_blocked_words')
    app.run()
    assert not app.exception and get_blocked_words() == []
    assert any('暂无违禁词' in x.value for x in app.info)


@pytest.mark.parametrize('page', ['page_rules', 'page_blocked_words'])
def test_policy_pages_reject_nonadmin_before_reading(isolated, monkeypatch, page):
    from src.web.components import auth
    monkeypatch.setattr(auth, 'get_current_role', lambda: 'editor')
    app = app_for(page)
    assert not app.exception and not app.button and not app.text_input
    assert any('需要管理员' in x.value for x in app.warning)
    assert not isolated.DB_PATH.exists()


def test_rule_storage_failure_never_claims_success_or_leaks_error(isolated, monkeypatch):
    from src.services import reply_rules_service as service
    def fail(*a, **kw):
        raise RuntimeError('PRIVATE_TOKEN_VALUE')
    monkeypatch.setattr(service, 'add_rule', fail)
    app = app_for('page_rules')
    item(app.text_input, '触发关键词').set_value('test')
    item(app.text_input, '回复模板').set_value('reply')
    item(app.button, '添加规则').click().run()
    assert not app.exception and app.error and not app.success
    assert 'PRIVATE_TOKEN_VALUE' not in str(app.error)
