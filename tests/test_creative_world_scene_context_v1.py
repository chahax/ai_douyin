"""Offline contract fixtures, never authored/approved native creative work."""
from copy import deepcopy
import json
from pathlib import Path
import socket

import pytest
from jsonschema import Draft202012Validator, ValidationError

from src.content_factory import creative_world_scene_context_v1 as w
from src.content_factory import creative_goal_evidence_view_v1 as lossless
from tests.test_creative_legal_speech_scope_v2 import synthetic_scope
from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / 'data/production_trials/legal_scoped_text_session_20261015/round_01'


def read(path): return json.loads(path.read_text('utf-8-sig'))
def payload(prepared): return json.loads(prepared['request']['messages'][1]['content'])
def profile(): return read(PROJECT / 'config/creative_fresh_source_session_profile_v2.json')


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError('world/scene contract tests have no network authority')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)


@pytest.fixture
def case():
    """New fields are synthetic test data; original receipts are never changed."""
    goal = deepcopy(read(ROOT / 'call_627_whole_plan_04.json')['output'])
    script = deepcopy(read(ROOT / 'call_634_complete_script_01.json')['output'])
    goal['contract_version'] = w.GOAL_VERSION
    cast = w._ids(goal, 'characters'); scenes = w._ids(goal, 'scenes')
    goal['whole_plan']['world_frame'] = {
        'era_reality': 'OFFLINE合成：当代虚构门店，不是真实事件。',
        'social_context': 'OFFLINE合成：经理与老员工有既有上下级关系。',
        'prehistory': 'OFFLINE合成：谈话前双方已知道本轮人员调整。',
        'relationship_notes': [{'character_ids': cast, 'description': 'OFFLINE合成：双方一起工作过。', 'claim_refs': []}],
        'spatial_connections': [{'from_scene_id': scenes[0], 'to_scene_id': scenes[1],
            'description': 'OFFLINE合成：通道尽头连接值班室。', 'claim_refs': []}], 'claim_refs': []}
    script.update(contract_version=w.SCRIPT_VERSION, native_goal_sha256=w.digest(goal), scene_contexts=[])
    previous = None; last_scene = None
    for i, (beat, planned) in enumerate(zip(script['beats'], goal['whole_plan']['beats'])):
        if planned['scene_id'] != last_scene:
            cid = 'ctx_' + str(i)
            script['scene_contexts'].append({'id': cid, 'scene_id': planned['scene_id'],
                'story_time': {'label': 'OFFLINE合成：同一上午' if previous is None else 'OFFLINE合成：紧接前场',
                    'relation': 'opening' if previous is None else 'continuous'},
                'previous_context_id': previous, 'environment_delta': '', 'present_character_ids': cast[:]})
            previous = cid; last_scene = planned['scene_id']
        actions = [j for j, step in enumerate(beat['steps']) if step['kind'] == 'action']
        assert actions
        beat.update(scene_context_id=cid, ensemble={actor: [{'action_step_indexes': [actions[0]],
            'expression': 'OFFLINE合成神情：安静听着，保持当前姿态。', 'mode': 'holds'}] for actor in cast}, parallel_with=[])
    return goal, script


def review(goal, script):
    fragment = w.review_fragment(goal, script)
    return {'schema': w.REVIEW_VERSION, 'world_scene_context_sha256': w.digest(fragment),
        'world_scene_checks': {key: {'status': 'pass', 'reason': 'OFFLINE synthetic contract result only',
            'evidence': [refs[0]], 'required_revision': ''} for key, refs in fragment['targets'].items()}}


def semantic_base(goal, script):
    p = {'review_part': 'semantic', 'native_goal_document': deepcopy(goal), 'native_script_document': deepcopy(script)}
    schema = w.obj({'schema': {'const': 'OFFLINE_core'}, 'context_sha256': {'const': w.digest(p)},
        'goal_contract_sha256': {'const': w.digest(goal)}, 'script_sha256': {'const': w.digest(script)}})
    return {'request': {'stage': 'full_review', 'model': profile()['director']['model'],
        'parameters': profile()['director']['parameters'], 'structured_schema': schema,
        'messages': [{'role': 'system', 'content': 'OFFLINE core review fixture'},
            {'role': 'user', 'content': json.dumps(p, ensure_ascii=False)}], 'input_provenance': {}}}


def test_actual_old_receipts_are_not_silently_filled_or_mutated():
    gp, sp = ROOT / 'call_627_whole_plan_04.json', ROOT / 'call_634_complete_script_01.json'
    before = gp.read_bytes(), sp.read_bytes()
    with pytest.raises(ValidationError): w.validate_goal(read(gp)['output'])
    old_goal = read(gp)['output']
    old_goal['contract_version'] = w.GOAL_VERSION
    with pytest.raises(ValidationError): w.validate_goal(old_goal)
    assert (gp.read_bytes(), sp.read_bytes()) == before


def test_new_native_contract_and_exact_beat_schema_without_fixed_seconds(case):
    goal, script = case
    assert w.validate_script(script, goal)['missing_fields_filled'] is False
    schema = w.build_script_schema(goal)
    beats = schema['properties']['beats']
    assert beats['minItems'] == beats['maxItems'] == len(script['beats'])
    assert beats['items']['properties']['id'] == {'enum': w._ids(goal, 'beats')}
    assert [row['properties']['id']['const'] for row in beats['prefixItems']] == w._ids(goal, 'beats')
    assert 'duration' not in json.dumps(schema) and '150' not in json.dumps(schema)
    with pytest.raises(ValidationError): w.validate_script(read(ROOT / 'call_634_complete_script_01.json')['output'], goal)


@pytest.mark.parametrize('fault', ['actor', 'scene', 'claim', 'duplicate'])
def test_world_references_and_original_identity_are_explicit(case, fault):
    goal, _ = case
    if fault == 'actor': goal['whole_plan']['world_frame']['relationship_notes'][0]['character_ids'] = ['stranger']
    elif fault == 'scene': goal['whole_plan']['world_frame']['spatial_connections'][0]['to_scene_id'] = 'elsewhere'
    elif fault == 'claim': goal['whole_plan']['world_frame']['claim_refs'] = ['missing']
    else: goal['whole_plan']['characters'].append(deepcopy(goal['whole_plan']['characters'][0]))
    with pytest.raises((ValueError, ValidationError)): w.validate_goal(goal)


@pytest.mark.parametrize('fault', ['silent_listener', 'action_ref', 'dialogue_ref', 'wrong_scene', 'previous', 'repeat'])
def test_scene_participation_and_action_bindings_cannot_be_dropped(case, fault):
    goal, script = case; beat = script['beats'][0]
    if fault == 'silent_listener': beat['ensemble'].pop(next(iter(beat['ensemble'])))
    elif fault == 'action_ref': next(iter(beat['ensemble'].values()))[0]['action_step_indexes'] = [1]
    elif fault == 'dialogue_ref': beat['parallel_with'] = [{'action_step_index': 0, 'dialogue_step_index': 0}]
    elif fault == 'wrong_scene': script['scene_contexts'][0]['scene_id'] = goal['whole_plan']['scenes'][1]['id']
    elif fault == 'previous': script['scene_contexts'][1]['previous_context_id'] = None
    else: script['beats'][-1]['scene_context_id'] = script['scene_contexts'][0]['id']
    with pytest.raises((ValueError, ValidationError)): w.validate_script(script, goal)


def test_parallel_is_native_relation_not_document_order_or_added_seconds(case):
    goal, script = case
    script['beats'][0]['parallel_with'] = [{'action_step_index': 0, 'dialogue_step_index': 1}]
    assert not w.validate_script(script, goal)['document_order_is_performance_time']
    assert w.review_fragment(goal, script)['parallel_relations']['B1'] == script['beats'][0]['parallel_with']
    script['beats'][0]['parallel_with'] *= 2
    with pytest.raises((ValueError, ValidationError)): w.validate_script(script, goal)


def test_third_silent_actor_is_supported_without_fixed_two_person_cast(case):
    goal, script = case
    listener = deepcopy(goal['whole_plan']['characters'][0]); listener.update(id='c_offline_listener', name='OFFLINE观察者')
    goal['whole_plan']['characters'].append(listener)
    script['native_goal_sha256'] = w.digest(goal)
    for context in script['scene_contexts']: context['present_character_ids'].append(listener['id'])
    for beat in script['beats']:
        beat['ensemble'][listener['id']] = [{'action_step_indexes': [next(i for i, s in enumerate(beat['steps']) if s['kind'] == 'action')],
            'expression': 'OFFLINE合同样例：保持安静。', 'mode': 'holds'}]
    assert w.validate_script(script, goal)['valid']
    assert listener['name'] in w.render_script(script, goal)
    # A native performance instruction is not proof the scene was performed.
    assert not w.validate_script(script, goal)['semantic_quality_approved']


def test_one_actor_one_scene_is_not_rejected_by_specialized_prototype_limits(case):
    goal, script = case
    actor = goal['whole_plan']['characters'][0]; scene = goal['whole_plan']['scenes'][0]
    goal['whole_plan']['characters'] = [actor]; goal['whole_plan']['scenes'] = [scene]
    for beat in goal['whole_plan']['beats']: beat.update(actor_id=actor['id'], scene_id=scene['id'])
    frame = goal['whole_plan']['world_frame']; frame.update(relationship_notes=[], spatial_connections=[])
    context = script['scene_contexts'][0]; context['present_character_ids'] = [actor['id']]
    script['scene_contexts'] = [context]; script['native_goal_sha256'] = w.digest(goal)
    for beat in script['beats']:
        beat.update(scene_context_id=context['id'], steps=[{'kind': 'action', 'speaker': '', 'text': 'OFFLINE单人合同夹具：保持坐姿。'},
            {'kind': 'dialogue', 'speaker': actor['id'], 'text': 'OFFLINE合成句，仅测试单人在场。'}], ensemble={actor['id']: [
                {'action_step_indexes': [0], 'expression': 'OFFLINE保持平静。', 'mode': 'holds'}]})
    assert w.validate_script(script, goal)['valid']
    assert not w.validate_script(script, goal)['semantic_quality_approved']


def test_evidence_preserves_step_refs_and_includes_new_world_scene_ensemble(case):
    goal, script = case; catalog = w.build_evidence_catalog(goal, script)
    old = w.text_contract.evidence_catalog(w.legacy_script_checking_projection(script))
    assert all(catalog[k]['quote'] == v['quote'] and catalog[k]['role'] == 'actual_step' for k, v in old.items())
    assert any(v['document_path'].startswith('whole_plan.world_frame.') for v in catalog.values())
    assert any(k.startswith('H:') and v['role'] == 'scene_context_not_performed_event' for k, v in catalog.items())
    assert any(k.startswith('P:') and v['role'] == 'native_performance_instruction' for k, v in catalog.items())
    assert not w.review_fragment(goal, script)['background_is_actual_event']


def test_scope_and_source_actual_payloads_reconstruct_all_new_world_text(case):
    goal, _ = case
    scope_request = w.prepare_scope_request(profile(), goal)
    assert lossless.reconstruct_goal(payload(scope_request)['native_goal_evidence_view']) == goal
    old_payload = json.loads(read(ROOT / 'call_629_source_audit_04.json')['request']['messages'][1]['content'])
    source_context = {key: old_payload[key] for key in w.source_review.SOURCE_KEYS}
    source_request = w.prepare_source_request(profile(), goal, synthetic_scope(goal), source_context)
    assert lossless.reconstruct_goal(payload(source_request)['native_goal_evidence_view']) == goal
    for request in (scope_request, source_request):
        assert request['wire'] == expected_wire_request(request['request'])
        assert request['manifest']['world_in_complete_source_frame'] and not request['production_dispatch_eligible']


def test_writer_keeps_actual_raw_ownership_r01_and_existing_author_rule(case):
    goal, script = case; inputs = read(ROOT / 'INPUTS.json')
    old_setup = read(ROOT / 'call_633_opening_setup_02.json')['output']
    with pytest.raises(ValueError): w.prepare_writer_request(inputs, profile(), goal, opening_setup=old_setup)
    setup = deepcopy(old_setup); setup['goal_sha256'] = w.digest(goal)  # OFFLINE identity fixture; no native approval.
    prepared = w.prepare_writer_request(inputs, profile(), goal, opening_setup=setup)
    p = payload(prepared); raw = w.ownership.original_user_goal_contract(inputs)
    assert sum(len(raw[key]) for key in ('constraints', 'audience_goals')) == 10
    assert sum(len(p['user_goal_contract'][key]) for key in ('constraints', 'audience_goals')) == 8
    assert p['reference_fulltext'] == inputs['reference_fulltext'] and prepared['manifest']['reference_occurrences'] == 1
    assert p['native_goal_document'] == goal and 'world_frame' in p['native_goal_document']['whole_plan']
    assert w.ownership.AUTHOR_RULE in prepared['wire']['messages'][0]['content']
    assert p['coordinator_output_contract']['not_character_dialogue_requirement']
    assert prepared['manifest']['four_native_audits_not_validated_by_this_adapter']
    Draft202012Validator(prepared['request']['structured_schema']).validate(script)
    assert prepared['wire'] == expected_wire_request(prepared['request'])


def test_writer_preserves_whole_revision_evidence_once_without_reinterpreting_it(case):
    goal, _ = case; inputs = read(ROOT / 'INPUTS.json')
    previous = {'title': 'OFFLINE previous complete document', 'body': 'OFFLINE immutable whole evidence'}
    diagnostics = {'schema': 'OFFLINE diagnosis fixture', 'findings': ['OFFLINE only']}
    inputs.update(previous_complete_document=previous, revision_diagnostics=diagnostics)
    setup = {'goal_sha256': w.digest(goal)}
    prepared = w.prepare_writer_request(inputs, profile(), goal, opening_setup=setup)
    p = payload(prepared)
    assert p['previous_complete_document'] == previous and p['revision_diagnostics'] == diagnostics
    assert prepared['manifest']['preserved_feedback_identity'] == {
        'previous_complete_document_sha256': w.digest(previous), 'revision_diagnostics_sha256': w.digest(diagnostics)}
    assert json.dumps(p).count(previous['body']) == 1


def test_compilation_preserves_native_new_fields_and_labels_distinct_identity(case):
    goal, script = case; before = deepcopy(script)
    compiled = w.compile_script(script, goal)
    assert compiled['script'] == {**script, 'selected_candidate_id': 'native_goal:' + w.digest(goal)}
    assert compiled['manifest']['native_script_sha256'] == w.digest(script)
    assert compiled['manifest']['compiled_script_sha256'] != w.digest(script)
    assert not compiled['manifest']['invented_world_actions_or_expression']
    assert script == before
    wrong_brief = w._brief(goal); wrong_brief['selected_candidate_id'] = 'native_goal:' + w.digest(w.legacy_goal_checking_projection(goal))
    with pytest.raises(ValueError): w.compile_script(script, goal, wrong_brief)


def test_semantic_request_requires_full_native_objects_and_visible_extension_schema(case):
    goal, script = case; prepared = semantic_base(goal, script)
    new = w.augment_semantic_request(prepared, goal, script)
    p = payload(new)
    assert p['native_script_document'] == script and p['native_goal_document'] == goal
    assert p['world_scene_review_context'] == w.review_fragment(goal, script)
    assert not new['manifest']['physical_parallel_order_adapter_connected']
    assert new['request']['structured_schema']['properties']['context_sha256'] == {'const': w.digest(p)}
    assert 'world_scene_checks' in new['wire']['tools'][0]['function']['parameters']['required']
    core = payload(prepared); core['native_script_document'] = w.legacy_script_checking_projection(script)
    prepared['request']['messages'][1]['content'] = json.dumps(core)
    with pytest.raises(ValueError): w.augment_semantic_request(prepared, goal, script)


@pytest.mark.parametrize('fault', ['unknown', 'fail', 'cross_script', 'wrong_ref', 'cross_context'])
def test_new_review_context_is_source_bound_and_never_substitutes_complete_review(case, fault):
    goal, script = case; document = review(goal, script); row = document['world_scene_checks']['world']
    if fault in ('unknown', 'fail'):
        row['status'] = fault; row['required_revision'] = 'OFFLINE full native revision guidance' if fault == 'fail' else ''
        result = w.validate_review_extension(document, goal, script)
        assert not result['extension_accepted'] and not result['text_ready_for_director']
    else:
        if fault == 'cross_script': script['beats'][0]['ensemble'][next(iter(script['beats'][0]['ensemble']))][0]['expression'] += ' changed'
        elif fault == 'wrong_ref': row['evidence'] = ['not_a_ref']
        else: document['world_scene_context_sha256'] = '0' * 64
        with pytest.raises((ValueError, ValidationError)): w.validate_review_extension(document, goal, script)


def test_review_schema_conditions_match_local_extension_not_full_semantic_truth(case):
    goal, script = case; doc = review(goal, script)
    assert w.validate_review_extension(doc, goal, script)['extension_accepted']
    assert not w.validate_review_extension(doc, goal, script)['complete_same_source_review']
    doc['world_scene_checks']['world']['evidence'] = [next(k for k in w.build_evidence_catalog(goal, script) if k.startswith('E'))]
    with pytest.raises(ValidationError): Draft202012Validator(w.build_review_extension_schema(goal, script)).validate(doc)


def test_segment_requires_external_qualification_and_does_not_execute_metadata(case):
    goal, script = case; snapshot = {'OFFLINE': 'accepted state fixture only'}
    args = {'snapshot_kind': 'accepted_local_performance_end', 'expected_snapshot_sha256': w.digest(snapshot)}
    with pytest.raises(ValueError): w.build_segment_context(goal, script, 'B2', snapshot, **args)
    with pytest.raises(ValueError): w.build_segment_context(goal, script, 'B2', snapshot, snapshot_qualifier=lambda *a, **k: {'verified': False}, **args)
    def qualifier(s, **kw): return {'verified': True, **kw, 'OFFLINE': True}
    result = w.build_segment_context(goal, script, 'B2', snapshot, snapshot_qualifier=qualifier, **args)
    assert result['world_frame'] == goal['whole_plan']['world_frame'] and result['previous_script_event']['beat_id'] == 'B1'
    assert not result['previous_script_event_is_verified_executed']
    assert result['upcoming_locked_event']['beat_id'] == 'B3' and not result['upcoming_event_is_already_executed']
    assert not result['actual_media_request_connected'] and not result['snapshot_qualification_proven_by_this_function']
    def cross_goal(s, **kw): return {**qualifier(s, **kw), 'native_goal_sha256': '0' * 64}
    with pytest.raises(ValueError): w.build_segment_context(goal, script, 'B2', snapshot, snapshot_qualifier=cross_goal, **args)
    with pytest.raises(ValueError): w.build_segment_context(goal, script, 'B2', {'changed': True}, snapshot_qualifier=qualifier, **args)


def test_renderer_uses_native_framework_headers_each_participant_without_fixed_names(case):
    goal, script = case
    text = w.render_script(script, goal)
    assert script['premise'] in text and goal['whole_plan']['world_frame']['era_reality'] in text
    for context in script['scene_contexts']: assert context['story_time']['label'] in text
    for beat in script['beats']:
        for performances in beat['ensemble'].values():
            for p in performances: assert p['expression'] in text
    assert '150–180' not in text
    assert text.count('当拍情境：') == len(script['beats'])
