"""Offline transport integration; fixture outcomes are not production approvals."""
import json
import pytest
from src.content_factory.creative_workflow import CreativeWorkflow, CREATE_REVIEW_PROFILE
from src.content_factory.creative_original_prompt import VERSION as WRITER_VERSION
from src.content_factory.creative_review_v5 import build_review_prompt
from src.content_factory.creative_static_visual_manifest import build_static_manifest_prompt, validate_static_manifest
from src.content_factory.reusable_production import read
from test_creative_model_profile import setup
from test_creative_event_script import as_events
from test_creative_workflow import FakeClients
from test_creative_v4_integration import screenplay_review
from test_creative_static_visual_manifest import manifest


def prepare(tmp_path, version='evidence_review_v5'):
    answers, bundle = setup(tmp_path)
    bundle.metadata['creative_brief']['duration_seconds'] = [20,20]
    clients = FakeClients([answers[0], answers[1], as_events(answers[2]), screenplay_review(answers[2])])
    root = tmp_path / 'run'
    wf = CreativeWorkflow(root, clients=clients, model_profile=CREATE_REVIEW_PROFILE,
                          writer_prompt_version=WRITER_VERSION, review_policy_version=version)
    state = wf.run(bundle)
    return wf, state, clients, root, bundle


def test_v5_review_routes_deepseek_and_preserves_assistant_gate_and_receipt(tmp_path):
    wf, state, clients, root, bundle = prepare(tmp_path)
    assert state['status'] == 'script_review_pending'
    assert state['segmented_director_binding']['version'] == 'reviewed_beat_storyboard_v5'
    receipt_path = root / 'script_review__story_00_00.json'
    receipt = read(receipt_path)
    context = json.loads(receipt['request']['messages'][-1]['content'])
    from src.content_factory.creative_narrative_focus import prompt_for_stage
    assert receipt['request']['messages'][0]['content'] == build_review_prompt(context)+prompt_for_stage(state['narrative_focus_binding'],'script_review__story_00_00')
    assert receipt['context_budget']['provider'] == 'deepseek'
    assert receipt['response_metadata']['transport_config_role'] == 'director'
    assert clients.calls[-1][0] == 'director'
    before = receipt_path.read_bytes()
    resumed = CreativeWorkflow(root, clients=FakeClients([])).run(bundle)
    assert resumed['calls_started'] == state['calls_started']
    assert receipt_path.read_bytes() == before
    assert not (root/'static_visual_manifest.json').exists()
    assert not list(root.glob('director_shots*'))
    assert not (root/'MEDIA_HANDOFF.json').exists()


def test_static_manifest_stage_uses_minimax_and_own_prompt(tmp_path):
    wf, state, _, root, _ = prepare(tmp_path)
    # Exercise the real stage machinery without pretending the prior assistant gate passed.
    answer = manifest()
    clients = FakeClients([answer])
    wf.clients = clients
    actual = wf._stage('static_visual_manifest', 'director', {'creative_brief': {'theme': '离线路由测试'}}, validate_static_manifest)
    assert actual == answer
    assert clients.calls[0][0] == 'writer'
    receipt = read(root/'static_visual_manifest.json')
    assert receipt['request']['messages'][0]['content'] == build_static_manifest_prompt()
    assert receipt['response_metadata']['logical_role'] == 'director'
    assert receipt['response_metadata']['transport_config_role'] == 'writer'
    assert receipt['context_budget']['model'] == 'MiniMax-M3'
    assert 'max_completion_tokens' in receipt['request']['parameters']
    assert not (root/'MEDIA_HANDOFF.json').exists()


def test_v4_run_cannot_silently_inherit_v5_prompt_or_static_manifest(tmp_path):
    _, state, _, root, bundle = prepare(tmp_path, 'evidence_review_v4')
    assert state['segmented_director_binding']['version'] == 'reviewed_beat_storyboard_v3'
    receipt = read(root/'script_review__story_00_00.json')
    context = json.loads(receipt['request']['messages'][-1]['content'])
    from src.content_factory.creative_review_v4 import build_review_prompt as v4_prompt
    from src.content_factory.creative_narrative_focus import prompt_for_stage
    assert receipt['request']['messages'][0]['content'] == v4_prompt(context)+prompt_for_stage(state['narrative_focus_binding'],'script_review__story_00_00')
    assert '固定机位只锁定摄影机' not in receipt['request']['messages'][0]['content']
    with pytest.raises(RuntimeError, match='审核流程版本'):
        CreativeWorkflow(root, review_policy_version='evidence_review_v5')
