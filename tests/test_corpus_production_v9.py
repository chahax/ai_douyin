"""New-task MiniMax defaults, effective options and no-replay/source gates."""
from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from src.content_factory import corpus_production_v9 as p
from src.content_factory.corpus_scope_v9 import record_cloud_authorization
from src.content_factory.minimax_production_client_v1 import MiniMaxProductionClient, MODEL, REQUEST_POLICY
from tests.test_corpus_production_v6 import source, put, Classifier


@pytest.fixture
def configured(monkeypatch):
    routes = {'writer': {'provider': 'minimax', 'model': 'MiniMax-M3', 'base_url': 'https://fixture.invalid'},
              'director': {'provider': 'deepseek', 'model': 'deepseek-flash', 'base_url': 'https://fixture.invalid'}}
    monkeypatch.setattr(p, '_legacy_cloud_routes', lambda: deepcopy(routes))
    monkeypatch.setattr(p, 'preflight', lambda route: {**route, 'digest': 'fixture-digest'})
    return routes


def prepared(tmp_path, approve=True, **kwargs):
    manifest, history = source(tmp_path)
    run = tmp_path / 'run'
    plan = p.prepare(manifest, run, user_statement='Synthetic offline acceptance', previous_status=history, workers=1, **kwargs)
    if approve:
        record_cloud_authorization(run, 'Explicit synthetic fixture scope',
            approved_source_sha256=plan['source_sha256'], approved_destinations=plan['cloud_models'])
    return run, plan


def test_persistent_new_default_classifies_with_m31_and_preserves_legacy_env(tmp_path, configured):
    run, plan = prepared(tmp_path)
    assert configured['writer']['model'] == 'MiniMax-M3'
    assert plan['cloud_models']['writer']['model'] == MODEL
    assert plan['stage_routes']['chapter_materials'] == 'writer'
    assert plan['stage_routes']['material_review'] == 'local'
    assert plan['minimax_request_policy'] == REQUEST_POLICY
    c = Classifier()
    state = p.execute_materials(run, c)
    assert state['status'] == 'materials_ready' and state['pending'] is None
    assert len(c.requests) == 3 and all(role == 'writer' for role, _ in c.requests)
    assert p.read(run / 'materials/PLAN.json')['analysis_route']['model'] == MODEL
    assert not (run / 'local').exists()
    assert p.execute_local(run, c) == state and len(c.requests) == 3


def test_cloud_approval_required_before_initial_classifier(tmp_path, configured):
    run, plan = prepared(tmp_path, approve=False)
    c = Classifier()
    with pytest.raises(ValueError, match='authorization'):
        p.execute_materials(run, c)
    assert not c.requests and p.read(run / 'materials/STATE.json')['calls_started'] == 0


def test_unknown_initial_classifier_never_replayed(tmp_path, configured):
    run, plan = prepared(tmp_path)
    c = Classifier(unknown=True)
    with pytest.raises(Exception, match='incomplete'):
        p.execute_materials(run, c)
    assert p.read(run / 'STATE.json')['pending']
    p.execute_materials(run, c)
    assert len(c.requests) == 1


@pytest.mark.parametrize('role', ['writer', 'director', 'local'])
def test_stage_clients_bind_exact_roles_and_local_review(configured, role):
    seen = []
    spy = SimpleNamespace(call=lambda role, messages, **kwargs: seen.append((role, kwargs)))
    routes = p._cloud_routes()
    clients = p.StageClients({'max_tokens': 8192}, routes, local_client=spy, cloud_client=spy, minimax_client=spy)
    clients.call(role, [], response_format={'type':'json_object'}, max_tokens=16384, thinking='disabled')
    assert seen[0][0] == ('director' if role == 'local' else role)
    assert seen[0][1]['max_tokens'] == (8192 if role == 'local' else 16384)


def test_permanent_client_translates_legacy_disabled_and_json_options():
    seen = []
    original = {'native': 'preserved'}
    def call(role, messages, **kwargs):
        seen.append((role, messages, kwargs))
        return SimpleNamespace(text='{}', metadata={'response_model': MODEL}, response_payload=original)
    client = MiniMaxProductionClient(SimpleNamespace(call=call))
    result = client.call('writer', [{'role':'user','content':'test'}], max_tokens=16384,
                         temperature=.2, thinking='disabled', response_format={'type':'json_object'})
    assert seen[0][2] == {'max_tokens':16384, 'thinking':'adaptive'}
    assert result.response_payload is original
    assert result.metadata['effective_request_policy'] == REQUEST_POLICY
    assert result.metadata['effective_max_completion_tokens'] == 16384


@pytest.mark.parametrize('version', [3,4,5,6,7,8,9])
def test_cli_and_fanqie_keep_frozen_version(tmp_path, version):
    import importlib
    from scripts.run_corpus_production import coordinator, current
    from scripts.run_fanqie_corpus_workflow import TEXT_ROUTES, addressed_materials
    module = importlib.import_module(f'src.content_factory.corpus_production_v{version}')
    put(tmp_path / 'PLAN.json', {'version':module.VERSION})
    assert coordinator(tmp_path) is module and TEXT_ROUTES[module.VERSION] is module
    from src.content_factory import corpus_production_v9 as latest
    assert current is latest and addressed_materials is latest


@pytest.mark.parametrize('file,key,value', [('PLAN.json','cloud_models',{}), ('SOURCE.json','chapters',[]),
    ('materials/PLAN.json','new_call_limit',999), ('AUTHORIZATION.json','destinations',{})])
def test_frozen_scope_tamper_rejected_before_call(tmp_path, configured, file, key, value):
    run, plan = prepared(tmp_path)
    data=p.read(run / file); data[key]=value; put(run / file,data)
    c=Classifier()
    with pytest.raises(ValueError,match='changed'):
        p.execute_materials(run,c)
    assert not c.requests


def test_provider_change_never_falls_back(configured):
    routes=p._cloud_routes()
    configured['writer']['base_url']='https://changed.invalid'
    clients=p.StageClients({'max_tokens':8192},routes)
    with pytest.raises(p.LocalInputRejected, match='changed'):
        clients.call('writer',[],max_tokens=16384)
