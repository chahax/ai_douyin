"""Behavior and evidence boundaries for the visual capability pages."""
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from src.web.components.flow_graph import validate_selection
from src.web.model_visuals import configured_graph, safe_endpoint, usage_graph
from src.web.production_visuals import build_production_graph
from src.web.skill_dashboard import SKILL_DISPLAY, call_counts
from src.web.workflow_visuals import build_workflow_graph


def test_graph_rejects_unknown_and_malformed_selection():
    nodes, edges = [{'id':'a'}], [{'id':'a:b'}]
    for value in [None, 'a', {'kind':'execute','id':'a'}, {'kind':'node','id':'../secret'}, {'kind':'edge','id':'a'}, {'kind':'node','id':[]}]:
        assert validate_selection(value,nodes,edges) is None
    assert validate_selection({'kind':'node','id':'a','action':'execute'},nodes,edges) == {'kind':'node','id':'a'}
    assert validate_selection({'kind':'edge','id':'a:b'},nodes,edges) == {'kind':'edge','id':'a:b'}


def test_registered_skills_have_chinese_introductions_and_unknown_results_are_not_failures():
    from src.agent.registry import SkillRegistry
    # Full-suite collection imports test_skill_registry, whose three synthetic
    # decorator registrations are not user-facing production skills.
    test_only = {'test_fail_skill', 'test_idempotent_skill', 'test_slow_skill'}
    missing = {s.name for s in SkillRegistry().list_all()} - SKILL_DISPLAY.keys() - test_only
    assert not missing, sorted(missing)
    for name, group, description in SKILL_DISPLAY.values():
        assert any('\u4e00' <= c <= '\u9fff' for c in name)
        assert len(description)>10 and group
    assert call_counts([SimpleNamespace(tool_success=s) for s in (True,False,None)]) == {'成功':1,'失败':1,'未记录结果':1}


def test_workflow_graph_matches_registry_and_disabled_nodes():
    from src.workflow.runtime import get_node_registry, get_selection_store
    from src.web.workflow_dashboard import STAGE_LABELS
    registry=get_node_registry()
    profile=get_selection_store().load().active
    nodes,edges=build_workflow_graph(registry,profile,STAGE_LABELS)
    assert {n['id'] for n in nodes} == set(profile.selections)
    for node in nodes:
        spec=registry.get(node['id'],profile.selections[node['id']])
        assert ['当前实现',spec.label] in node['facts']
        if spec.implementation_id=='disabled_pending_redesign':
            assert node['disabled'] and node['status']=='已停用'
            assert all(e['pending'] for e in edges if node['id'] in (e['source'],e['target']))
    assert all('不声明接口已直接连通' in str(e['facts']) for e in edges)


def test_current_provider_model_not_unrelated_ollama_default():
    settings=SimpleNamespace(SEEDANCE_PROVIDER='dreamina_cli',DREAMINA_MODEL_VERSION='video-current',
                             SEEDANCE_MODEL='unused',TTS_PROVIDER='voice',LLM_TIMEOUT_SECONDS=120)
    client=SimpleNamespace(provider_name='openai_compatible',model_name='actual-current-model')
    nodes,edges=configured_graph(settings,client)
    assert any(n['label']=='actual-current-model' for n in nodes)
    assert not any(n['label']=='unused' for n in nodes)
    assert all(n['status']=='配置示意' for n in nodes)
    assert safe_endpoint('https://user:secret@example.com/v1?api_key=secret#secret')=='https://example.com/v1'
    assert safe_endpoint('not-a-url')=='未配置有效地址'


def test_usage_edge_keeps_cache_and_rate_limit_distinct():
    rows=[SimpleNamespace(caller='agent_chat',model='test-model',calls=5,hits=2,limited=1,cost=.04,in_tok=20,out_tok=30)]
    nodes,edges=usage_graph(rows)
    assert dict(edges[0]['facts'])['请求数']=='5'
    assert dict(edges[0]['facts'])['缓存命中']=='2'
    assert dict(edges[0]['facts'])['被限流']=='1'
    assert len(nodes)==2


def test_production_nodes_keep_stage_status_and_auxiliary_views_separate():
    items=[(name,'待审核' if name=='一致性审核' else '未记录') for name in ['灵感来源','分析依据','剧本内容','分镜与采集','合并成片','一致性审核','本地文件','页面风格']]
    nodes,edges=build_production_graph(items)
    assert next(n for n in nodes if n['id']=='一致性审核')['status']=='待审核'
    assert not any(e['target'] in ('本地文件','页面风格') for e in edges)


def test_skill_filter_selection_and_empty_search_render():
    app=AppTest.from_string('from src.web.skill_dashboard import page_skill_center\npage_skill_center()',default_timeout=20).run()
    assert not app.exception
    app.text_input(key='skill_search').set_value('配音').run()
    assert not app.exception
    assert any(b.key=='skill_card_generate_audio' for b in app.button)
    assert any('文本配音' in s.value for s in app.subheader)
    app.text_input(key='skill_search').set_value('no-such-capability-123').run()
    assert not app.exception
    assert any('没有匹配' in item.value for item in app.info)


def test_system_graph_and_grouped_settings_render_without_model_call(monkeypatch):
    from src.shared.llm_client import llm_client
    def forbidden(*args,**kwargs):
        raise AssertionError('Rendering must not invoke models')
    monkeypatch.setattr(llm_client,'chat_completion',forbidden)
    monkeypatch.setattr(llm_client,'chat_completion_tracked',forbidden)
    app=AppTest.from_string('from src.web.model_visuals import render_system_settings\nrender_system_settings()',default_timeout=20).run()
    assert not app.exception
    assert [t.label for t in app.tabs]==['文本模型设置','配音设置','视频模型设置']
    assert all(t.disabled for t in app.text_input)


def test_navigation_keeps_role_permissions_and_chinese_labels():
    from unittest.mock import patch
    import streamlit as st
    for role in ('viewer', 'editor', 'admin', 'superadmin'):
        def auth(**_kwargs):
            st.set_page_config(layout='wide')
            st.session_state.update(user='ui-test',user_role=role)
            return True
        with patch('src.web.components.auth.render_login_page', auth), patch('streamlit.navigation', wraps=st.navigation) as navigation:
            app=AppTest.from_file('src/web/app.py',default_timeout=30).run()
            assert not app.exception
            titles={page.title for group in navigation.call_args.args[0].values() for page in group}
            assert '模型用量' in titles and '视频用量与余额' in titles
            assert ('技能中心' in titles) == (role != 'viewer')
            assert ('工作流编排' in titles) == (role in ('admin','superadmin'))
            assert ('模型与系统设置' in titles) == (role == 'superadmin')
            assert 'Skill 监控' not in titles and 'LLM 用量' not in titles


def test_navigation_registers_routes_before_cookie_restore_can_stop():
    from unittest.mock import patch
    import streamlit as st
    events = []
    original_navigation = st.navigation

    def navigation(*args, **kwargs):
        events.append(('navigation', kwargs.get('position')))
        return original_navigation(*args, **kwargs)

    def pending_cookie(**kwargs):
        events.append(('auth', kwargs.get('configure_page')))
        return False

    with patch('streamlit.navigation', navigation), patch(
        'src.web.components.auth.render_login_page', pending_cookie
    ):
        app = AppTest.from_file('src/web/app.py', default_timeout=30).run()
    assert not app.exception
    assert events[:2] == [('navigation', 'hidden'), ('auth', False)]
