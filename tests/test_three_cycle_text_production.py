from pathlib import Path
from copy import deepcopy
import pytest
import scripts.run_three_cycle_text_production as runner


class NoCalls:
    def call(self, *args, **kwargs):
        raise AssertionError('offline runner gate test must not call provider')


@pytest.fixture
def source(tmp_path):
    parent = tmp_path / 'parent'
    parent.mkdir()
    state = {'calls_started': 30, 'revision_rounds': 6,
             'writer_prompt_binding': {'creative_brief': {'theme': 'fixture'}}}
    runner._write(parent / 'state.json', state)
    runner._write(parent / 'director_brief.json', {'output': {'selected_style_id': 'S1'}})
    screenplay = tmp_path / 'script.json'
    runner._write(screenplay, {'title': 'approved fixture', 'beats': []})
    return parent, screenplay


def test_review_gate_is_resumable_without_resetting_parent(tmp_path, monkeypatch, source):
    parent, screenplay = source
    before = (parent / 'state.json').read_bytes()
    def pending(workflow, *_):
        workflow.state.update(status='script_review_pending', pending_evidence_review={'key': 'test'})
        workflow._save()
        return None
    monkeypatch.setattr(runner, 'generate_reviewed_beats', pending)
    root = tmp_path / 'rounds'
    for _ in range(2):
        state = runner.run_round(root, 1, parent, screenplay, NoCalls())
        assert state['status'] == 'script_review_pending'
        assert state['calls_started'] == 0
    assert (parent / 'state.json').read_bytes() == before
    assert not (root / 'round_01/MEDIA_HANDOFF.json').exists()
    with pytest.raises(RuntimeError, match='上一轮'):
        runner.open_round(root, 2, parent, screenplay, NoCalls())


def test_exception_is_terminal_and_next_cycle_is_explicit(tmp_path, monkeypatch, source):
    parent, screenplay = source
    def broken(*_):
        raise ValueError('fixture production failure')
    monkeypatch.setattr(runner, 'generate_reviewed_beats', broken)
    root = tmp_path / 'rounds'
    state = runner.run_round(root, 1, parent, screenplay, NoCalls())
    assert state['status'] == 'production_exception'
    assert runner.run_round(root, 1, parent, screenplay, NoCalls())['error'] == 'fixture production failure'
    next_workflow, _, _ = runner.open_round(root, 2, parent, screenplay, NoCalls())
    assert next_workflow.state['authorized_round'] == 2
    assert next_workflow.state['same_story'] is True
    runner._write(screenplay, {'title': 'changed'})
    with pytest.raises(RuntimeError, match='已绑定续跑'):
        runner.open_round(root, 2, parent, screenplay, NoCalls())


def test_complete_package_matches_real_downstream_contract(tmp_path, monkeypatch):
    from scripts.compile_creative_seedance_segments import compile_run
    from src.content_factory.creative_calibration import _valid_handoff
    parent = runner.ROOT / 'data/creative_workflows/say_no_reviewed_segments_20260927'
    screenplay = runner.ROOT / 'data/production_trials/say_no_reviewed_segments_20260927/REVIEWED_SCREENPLAY.json'
    if not screenplay.exists():
        pytest.skip('local production receipt fixture unavailable')
    receipts = ['director_shots__beat_01_01', 'director_shots__beat_02_01',
                'director_shots__beat_03_02', 'director_shots__beat_04_00']
    chunks = [runner._read(parent / f'{name}.json')['output'] for name in receipts]
    shots = deepcopy(chunks[0])
    shots['shots'] = [row for chunk in chunks for row in chunk['shots']]
    monkeypatch.setattr(runner, 'generate_reviewed_beats', lambda *_: shots)
    def stage(self, name, role, payload, validator):
        if name.startswith('director_production_design'):
            assert len(payload['asset_catalog']) == 7
            return {'assets': [], 'shots': [], 'issues': []}
        return {'issues': [], 'suggestions': [], 'story_preserved': True}
    monkeypatch.setattr(runner.CreativeWorkflow, '_stage', stage)
    monkeypatch.setattr(runner.CreativeWorkflow, '_verified_review', lambda *_: [])
    root = tmp_path / 'rounds'
    state = runner.run_round(root, 1, parent, screenplay, NoCalls())
    assert state['status'] == 'media_handoff_pending_capability', state.get('error')
    run = root / 'round_01'
    assert _valid_handoff(run, state)['automatic_submit'] is False
    _, receipt = compile_run(run)
    assert receipt['text_gate_status'] == 'assistant_review_pending'
    manifest = runner._read(run / 'CREATIVE_OUTPUT_MANIFEST.json')
    assert runner._hash(manifest) == state['output_manifest_sha256']
    assert len(runner._read(run / 'ASSET_CATALOG_BINDING.json')['asset_catalog']) == 7
    assert state['calls_started'] == 0


def test_new_series_binds_prior_assets_and_requires_real_analysis(tmp_path, monkeypatch, source):
    parent, screenplay = source
    runner._write(parent / 'director_brief.json', {
        'output': {'selected_style_id': 'S1'},
        'request': {'messages': [{'content': __import__('json').dumps({'asset_catalog': [{'reuse_key': 'existing-room'}]})}]},
    })
    prior = tmp_path / 'prior'
    prior.mkdir()
    runner._write(prior / 'THREE_CYCLE_LEDGER.json', {'rounds': {'3': {'status': 'production_exception'}}, 'new_calls_started': 11})
    before = (prior / 'THREE_CYCLE_LEDGER.json').read_bytes()
    real_workflow = runner.CreativeWorkflow
    def workflow(*args, **kwargs):
        assert kwargs['review_policy_version'] == 'evidence_review_v6'
        kwargs['review_policy_version'] = 'evidence_review_v5'
        return real_workflow(*args, **kwargs)
    monkeypatch.setattr(runner, 'CreativeWorkflow', workflow)
    def binding(**kwargs):
        assert kwargs['state_plan'] is True
        assert kwargs['state_plan_version'] == 'whole_film_state_plan_v3'
        return {'version': 'reviewed_beat_storyboard_v6'}
    monkeypatch.setattr(runner, 'bind_segmented_director', binding)
    def broken(*_):
        raise ValueError('actual stage failure')
    monkeypatch.setattr(runner, 'generate_reviewed_beats', broken)
    root = tmp_path / 'new'
    state = runner.run_round(root, 1, parent, screenplay, NoCalls(), series=runner.NEW_SERIES, prior_root=prior)
    assert state['status'] == 'production_exception'
    ledger = runner._read(root / 'THREE_CYCLE_LEDGER.json')
    assert ledger['series'] == runner.NEW_SERIES
    assert ledger['rounds']['1']['source_at_start']
    assert ledger['rounds']['1']['source_at_latest_run']
    assert runner._read(root / 'CONTINUATION_INPUTS.json')['asset_catalog'][0]['reuse_key'] == 'existing-room'
    with pytest.raises(RuntimeError, match='真实分析'):
        runner.open_round(root, 2, parent, screenplay, NoCalls(), series=runner.NEW_SERIES, prior_root=prior)
    runner._write(root / 'round_01/ROUND_ANALYSIS.json', {'analysis_complete': True, 'finding': 'actual stage failure'})
    next_workflow, _, _ = runner.open_round(root, 2, parent, screenplay, NoCalls(), series=runner.NEW_SERIES, prior_root=prior)
    assert next_workflow.state['authorized_round'] == 2
    assert (prior / 'THREE_CYCLE_LEDGER.json').read_bytes() == before


def test_new_series_refuses_missing_asset_context(tmp_path, source):
    parent, screenplay = source
    with pytest.raises(RuntimeError, match='真实资产目录'):
        runner.bind_inputs(parent, screenplay, series=runner.NEW_SERIES)


def test_v6_real_stage_and_review_repair_reaches_assistant_gate(tmp_path, monkeypatch):
    """Only transport is faked: real prompt dispatch, compilation, validators and gate."""
    import json
    from src.content_factory.creative_workflow_roles import RoleResult
    from tests.test_creative_state_plan_v6 import sample
    from tests.test_creative_review_v6 import prepared
    plan, script, manifest = sample()
    original_binding = runner.bind_segmented_director
    def v1_fixture_binding(**kwargs):
        kwargs.pop('state_plan_version', None)
        kwargs.pop('state_plan_guidance_version', None)
        return original_binding(**kwargs)
    monkeypatch.setattr(runner, 'bind_segmented_director', v1_fixture_binding)
    manifest['schema'] = 'static_visual_manifest_v2'
    parent = tmp_path / 'parent'
    parent.mkdir()
    runner._write(parent / 'state.json', {'calls_started': 30, 'revision_rounds': 6,
        'writer_prompt_binding': {'creative_brief': {'theme': '关系变化'}}})
    runner._write(parent / 'director_brief.json', {'output': {'selected_style_id': 'S01'},
        'request': {'messages': [{'content': json.dumps({'asset_catalog': [{'reuse_key': 'fixture-room'}]})}]}})
    screenplay = tmp_path / 'screenplay.json'
    runner._write(screenplay, script)
    prior = tmp_path / 'prior'
    prior.mkdir()
    runner._write(prior / 'THREE_CYCLE_LEDGER.json', {'new_calls_started': 11})
    class Transport:
        def __init__(self): self.calls = []; self.review = None
        def call(self, role, messages, **kwargs):
            self.calls.append((role, deepcopy(messages)))
            payload = json.loads(messages[-1]['content'])
            if len(self.calls) == 1: value = manifest
            elif len(self.calls) == 2: value = plan
            elif len(self.calls) == 3:
                context = payload
                _, value = prepared()
                value['story_preserved'] = True
                value['issues'] = []
                value['suggestions'] = []
                def leaves(obj, path=''):
                    if isinstance(obj, dict):
                        return [r for k,v in obj.items() for r in leaves(v, path+'.'+str(k) if path else str(k))]
                    if isinstance(obj, list):
                        return [r for i,v in enumerate(obj) for r in leaves(v, path+'.'+str(i))]
                    return [{'path': path, 'quote': obj}] if isinstance(obj,str) and obj else []
                refs = leaves(context)
                template = deepcopy(value['coverage'][0])
                value['coverage'] = []
                for shot in context['shots']['shots']:
                    row = deepcopy(template); row['id'] = shot['id']
                    for check in row['checks'].values():
                        check.update(status='pass', issue_ids=[], reason='离线传输fixture，仅验证审核契约与门禁，非实际质量认证。', evidence_refs=deepcopy(refs))
                    value['coverage'].append(row)
                self.review = deepcopy(value)
                value['coverage'][0]['checks']['timing']['evidence_refs'] = []
            elif len(self.calls) == 4:
                assert payload['review_context']['state_plan'] == plan
                assert payload['invalid_review']['coverage'][0]['checks']['timing']['evidence_refs'] == []
                assert payload['target_contract']
                value = self.review
            else: raise AssertionError('Must stop at real assistant review gate')
            return RoleResult(json.dumps(value, ensure_ascii=False), {'role':role,'requested_model':'fixture','total_tokens':1})
    transport = Transport()
    root = tmp_path / 'rounds'
    state = runner.run_round(root, 1, parent, screenplay, transport, series=runner.NEW_SERIES, prior_root=prior)
    assert state['status'] == 'script_review_pending', state.get('error')
    assert state['calls_started'] == 4
    assert state['pending_evidence_review']
    assert len(transport.calls) == 4
    assert not (root / 'round_01/MEDIA_HANDOFF.json').exists()
    assert (root / 'round_01/writer_check__state_plan_00__contract_repair.json').exists()


@pytest.mark.parametrize('version,thinking', [('whole_film_state_plan_v1','disabled'), ('whole_film_state_plan_v2','adaptive'), ('whole_film_state_plan_v2','disabled'), ('whole_film_state_plan_v3','disabled')])
def test_state_plan_transport_thinking_and_schema_are_version_bound(tmp_path, monkeypatch, source, version, thinking):
    import json
    import src.content_factory.creative_state_plan_v6 as plan_module
    from src.content_factory.creative_workflow_roles import RoleResult
    from src.content_factory.creative_workflow_contract import CreativeContractError
    marker = {'type':'object','properties':{'valid':{'type':'boolean'}},'required':['valid'],'additionalProperties':False}
    schema_payloads = []
    def schema(payload):
        schema_payloads.append(deepcopy(payload))
        return marker
    monkeypatch.setattr(plan_module, 'build_state_plan_schema', schema, raising=False)
    class Transport:
        def __init__(self): self.calls=[]
        def call(self, role, messages, **kwargs):
            self.calls.append((role, deepcopy(messages), deepcopy(kwargs)))
            return RoleResult(json.dumps({'valid':len(self.calls)>1}),
                {'role':role,'requested_model':'fixture','total_tokens':1,'thinking':kwargs['thinking']})
    transport = Transport()
    parent, screenplay = source
    workflow, _, _ = runner.open_round(tmp_path / version, 1, parent, screenplay, transport)
    payload = {'state_plan_version':version,'script':{'beats':[]},'static_visual_manifest':{},'issues':[]}
    if version in ('whole_film_state_plan_v2','whole_film_state_plan_v3') and thinking == 'disabled':
        payload['plan_thinking_mode'] = 'disabled'
    def validate(value):
        if value.get('valid') is not True: raise CreativeContractError('fixture invalid plan')
    value = workflow._stage('director_state_plan__00','director',payload,validate)
    assert value == {'valid':True}
    assert len(transport.calls) == 2
    for role,messages,kwargs in transport.calls:
        assert role == 'writer'  # production role mapping routes creation to MiniMax
        assert kwargs['thinking'] == thinking
        assert kwargs.get('structured_schema') == (marker if version in ('whole_film_state_plan_v2','whole_film_state_plan_v3') else None)
    original = runner._read(workflow.run_dir / 'director_state_plan__00.json')
    assert original['request']['parameters']['thinking'] == thinking
    assert original['request']['tool_schema_sha256'] == (runner._hash(marker) if version in ('whole_film_state_plan_v2','whole_film_state_plan_v3') else None)
    repair = runner._read(workflow.run_dir / 'director_state_plan__00__contract_repair.json')
    assert repair['response_metadata']['thinking'] == thinking
    if version in ('whole_film_state_plan_v2','whole_film_state_plan_v3'):
        assert repair['request_parameters']['thinking'] == thinking
        assert repair['request_parameters']['max_completion_tokens'] == 12000
        assert repair['request_parameters']['temperature'] == 0.0
        assert repair['tool_schema_sha256'] == runner._hash(marker)
        assert schema_payloads == [payload,payload]
        assert 'submit_creative_json' in transport.calls[1][1][0]['content']
    else:
        assert schema_payloads == []
        assert 'request_parameters' not in repair


def test_two_cycle_series_has_hard_authorization_cap_and_history(tmp_path, source):
    import json
    parent, screenplay = source
    runner._write(parent / 'director_brief.json', {'output': {'selected_style_id':'S01'},
        'request': {'messages':[{'content':json.dumps({'asset_catalog':[{'reuse_key':'fixture'}]})}]}})
    prior = tmp_path / 'prior'; prior.mkdir()
    runner._write(prior / 'THREE_CYCLE_LEDGER.json', {'max_rounds':3,'rounds':{'3':{'status':'production_exception'}}})
    previous=(prior/'THREE_CYCLE_LEDGER.json').read_bytes()
    root=tmp_path/'two'
    with pytest.raises(ValueError,match='2个'):
        runner.open_round(root,3,parent,screenplay,NoCalls(),series=runner.TWO_SERIES,prior_root=prior)
    assert not root.exists()
    workflow,inputs,ledger=runner.open_round(root,1,parent,screenplay,NoCalls(),series=runner.TWO_SERIES,prior_root=prior)
    assert ledger['max_rounds']==2
    assert workflow.state['segmented_director_binding']['state_plan_version']=='whole_film_state_plan_v3'
    assert workflow.state['segmented_director_binding']['plan_thinking_mode']=='disabled'
    assert workflow.state['max_contract_repairs']==2 and workflow.state['max_calls']==24
    history=runner._read(root/'HISTORICAL_RECEIPT_HASHES.json')
    assert runner._hash(history)==ledger['historical_receipt_hashes_sha256']
    assert str((prior/'THREE_CYCLE_LEDGER.json').resolve()) in history
    assert (prior/'THREE_CYCLE_LEDGER.json').read_bytes()==previous
    sources=ledger['rounds']['1']['source_at_start']
    assert 'src/content_factory/creative_state_plan_v3.py' in sources
    assert 'src/content_factory/creative_workflow_roles.py' in sources
    with pytest.raises(RuntimeError,match='上一轮'):
        runner.open_round(root,2,parent,screenplay,NoCalls(),series=runner.TWO_SERIES,prior_root=prior)
