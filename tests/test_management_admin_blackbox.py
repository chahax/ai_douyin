import ast
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest
from streamlit.testing.v1 import AppTest

from src.web.model_visuals import video_configuration


@pytest.mark.parametrize('provider,label,model', [('ark_api','火山方舟 API','ark-model'),
    ('byteplus_api','BytePlus 接口','byte-model'), ('dreamina_cli','即梦网页套餐','cli-model'),
    ('unknown','未识别生成渠道','未配置模型')])
def test_video_settings_preserve_actual_provider(provider,label,model):
    settings=NS(SEEDANCE_PROVIDER=provider, ARK_SEEDANCE_MODEL='ark-model',
                SEEDANCE_MODEL='byte-model', DREAMINA_MODEL_VERSION='cli-model')
    assert video_configuration(settings)==(label,model)


def user_page():
    source=(Path(__file__).parents[1]/'src/web/app.py').read_text(encoding='utf-8-sig')
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='page_users')
    return ('import streamlit as st\nfrom src.web.components.ui import page_header\n'
        'from src.web.components.auth import get_current_role,has_permission\n'
        "role_names={'superadmin':'超级管理员','admin':'运营管理员','editor':'运营编辑','viewer':'查看者'}\n"
        +ast.get_source_segment(source,node)+'\npage_users()\n')


def test_admin_users_page_is_isolated_permissions_and_real_local_feedback(tmp_path,monkeypatch):
    from src.services import database,user_profile_service as service
    from src.web.components import auth
    monkeypatch.setattr(database,'DB_PATH',tmp_path/'users.db')
    monkeypatch.setattr(auth,'get_current_role',lambda:'superadmin')
    app=AppTest.from_string(user_page(),default_timeout=30).run()
    assert not app.exception
    next(b for b in app.button if b.label=='修改角色').click().run()
    assert any('用户昵称' in x.value for x in app.warning)
    app.text_input(key='new_nickname').set_value('fixture-user')
    app.text_input(key='new_pass').set_value('disposable-test-password')
    next(b for b in app.button if b.label=='创建').click().run()
    assert not app.exception and any('创建成功' in x.value for x in app.success)
    assert any(row['user_nickname']=='fixture-user' for row in service.list_users())
    monkeypatch.setattr(service,'set_user_password',lambda *a,**kw:False)
    app.text_input(key='pw_nickname').set_value('fixture-user')
    app.text_input(key='new_password').set_value('another-disposable-test-password')
    next(b for b in app.button if b.label=='设置密码').click().run()
    assert not app.exception and not app.success
    assert any('操作未保存' in x.value for x in app.warning)


def test_users_page_rejects_admin_before_reading(tmp_path,monkeypatch):
    from src.services import database
    from src.web.components import auth
    monkeypatch.setattr(database,'DB_PATH',tmp_path/'not-created.db')
    monkeypatch.setattr(auth,'get_current_role',lambda:'admin')
    app=AppTest.from_string(user_page()).run()
    assert not app.exception and not app.button and not database.DB_PATH.exists()
    assert app.warning


def test_settings_page_is_disabled_readonly_without_model_calls(monkeypatch):
    from src.shared.config import settings
    monkeypatch.setattr(settings,'SEEDANCE_PROVIDER','ark_api')
    monkeypatch.setattr(settings,'ARK_SEEDANCE_MODEL','fixture-ark-model')
    monkeypatch.setitem(sys.modules,'src.shared.llm_client',NS(llm_client=NS(
        provider_name='mock',model_name='fixture')))
    app=AppTest.from_string('from src.web.model_visuals import render_system_settings\nrender_system_settings()').run()
    assert not app.exception and not app.button
    assert all(x.disabled for x in app.text_input)
    assert next(x.value for x in app.text_input if x.label=='生成渠道')=='火山方舟 API'
    assert next(x.value for x in app.text_input if x.label=='生成模型')=='fixture-ark-model'
