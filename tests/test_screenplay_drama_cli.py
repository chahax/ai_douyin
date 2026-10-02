"""Offline entrypoint tests. Synthetic candidates are never production reviews."""
import copy
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from scripts import run_screenplay_drama as stage
from scripts import run_screenplay_stage as existing
from test_script_outline import workflow
from test_script_screenplay import screenplay


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


@pytest.fixture
def case(tmp_path, monkeypatch, workflow):
    root = tmp_path / 'project'
    prompts = root / 'src/trend_intelligence/prompts'
    prompts.mkdir(parents=True)
    for name in ('script_drama.md', 'script_drama_state.md', 'script_drama_revision.md',
                 'script_drama_state_revision.md'):
        (prompts / name).write_bytes((stage.ROOT / 'src/trend_intelligence/prompts' / name).read_bytes())
    monkeypatch.setattr(stage, 'ROOT', root)
    monkeypatch.setattr(existing, 'ROOT', root)
    monkeypatch.setattr(stage, 'settings', SimpleNamespace(SCRIPT_LLM_MODEL='MiniMax-M3', LLM_MODEL='fallback',
        SCRIPT_LLM_THINKING='disabled', SCRIPT_LLM_TIMEOUT_SECONDS=30, SCRIPT_LLM_MAX_TOKENS=24000))
    request = write(root / 'data/pre_video_scripts/_runs/original/request.json', workflow)
    sources = json.loads(workflow[1]['content'])['source_evidence']
    full = write(request.with_name('source_evidence.full.json'), sources)
    feedback = root / 'brief.md'
    feedback.write_text('合成测试不产生审核通过。', encoding='utf-8')
    def story(kind='short'):
        data = screenplay(kind)
        if kind == 'short':
            for shot, seconds in zip(data['version']['shots'], [5, 10, 10, 10, 5, 5]):
                shot['duration_seconds'] = seconds
        data['version']['reference_usage'][0]['source_id'] = sources[0]['source_id']
        return data
    def drama(kind='short'):
        data = story(kind)
        data['schema'] = 'script_drama/v1'
        data['version'].pop('initial_state')
        for shot in data['version']['shots']:
            shot.pop('end_state')
        return data
    def states(kind='short'):
        data = story(kind)
        return {'initial_state': data['version']['initial_state'], 'end_states': [
            {'shot_id': row['shot_id'], **row['end_state']} for row in data['version']['shots']]}
    def companion():
        path = write(root / 'data/qa/companion/screenplay.json', story('long'))
        write(path.with_name('run.json'), {'schema': 'script_screenplay_stage_run/v1', 'stage': 'story',
            'kind': 'long', 'status': 'candidate_pending_independent_review',
            'candidate_sha256': stage.sha(path.read_bytes()), 'workflow_request_sha256': stage.sha(request.read_bytes()),
            'source_evidence_sha256': stage.sha(full.read_bytes())})
        return path
    def argv(*extra, output_name='draft'):
        output = root / 'data/qa' / output_name
        monkeypatch.setattr(stage.sys, 'argv', ['run_screenplay_drama.py', '--stage', 'draft', '--kind', 'short',
            '--workflow-request', str(request), '--editor-feedback-file', str(feedback), '--output-dir', str(output),
            '--reference-source-id', sources[0]['source_id'], *map(str, extra)])
        return output
    output = argv()
    return SimpleNamespace(root=root, request=request, full=full, feedback=feedback, sources=sources,
                           story=story, drama=drama, states=states, companion=companion, argv=argv, output=output)


def client_for(monkeypatch, response):
    calls = []
    class Client:
        provider_name = 'offline_fixture'
        def __init__(self, **kwargs):
            self.provider = SimpleNamespace(last_response_metadata={'synthetic': True})
            calls.append(('init', kwargs))
        def chat_completion_tracked(self, messages, **kwargs):
            calls.append(('call', copy.deepcopy(messages), kwargs))
            if isinstance(response, Exception):
                raise response
            return response
    monkeypatch.setattr(stage, 'LLMClient', Client)
    return calls


def assert_run(output, status, calls, count):
    run = json.loads((output / 'run.json').read_bytes())
    assert run['status'] == status and run['model_calls'] == count
    assert len([x for x in calls if x[0] == 'call']) == count
    assert run['automatic_editorial_approval'] is run['media_generation'] is False
    first, last = [datetime.fromisoformat(run[k]) for k in ('started_at_bjt', 'finished_at_bjt')]
    assert first.utcoffset() == last.utcoffset() == timedelta(hours=8) and last >= first
    if count:
        assert calls[0][1]['max_retries'] == 0
        assert calls[0][1]['preserve_invalid_json'] is True
        assert calls[1][2]['use_cache'] is False
    return run


def test_draft_preserves_twenty_sources_companion_and_raw_response(case, monkeypatch):
    companion = case.companion()
    case.argv('--companion-screenplay', companion)
    original = {p: p.read_bytes() for p in (case.request, case.full, companion, companion.with_name('run.json'))}
    response = json.dumps(case.drama(), ensure_ascii=False)
    calls = client_for(monkeypatch, response)
    stage.main()
    run = assert_run(case.output, 'candidate_pending_independent_review', calls, 1)
    assert run['candidate_sha256'] == stage.sha((case.output / 'drama.json').read_bytes())
    assert run['inputs']['companion_screenplay']['run_sha256'] == stage.sha(companion.with_name('run.json').read_bytes())
    assert all(p.read_bytes() == raw for p, raw in original.items())
    assert (case.output / 'model_output.json').read_text(encoding='utf-8') == response
    assert len(json.loads((case.output / 'source_evidence.full.json').read_bytes())) == 20
    sent = json.loads(calls[1][1][1]['content'])
    assert len(sent['source_overview']) == 20 and len(sent['source_evidence']) == 1
    projected = sent['companion_screenplay']
    assert projected == {'core_message': case.story('long')['core_message'],
        'characters': case.story('long')['characters'],
        'version': {key: case.story('long')['version'][key] for key in
                    ('premise', 'dramatic_question', 'resolution')}, 'long_shot_count': 9}
    assert run['companion_author_context']['shot_actions_dialogue_and_states_sent'] is False
    assert list(sent)[-1] == 'current_editor_feedback'
    assert not (case.output / 'screenplay.json').exists()
    assert 'checks' not in run and 'decision' not in run


def test_state_is_exact_frozen_merge_and_compatible_with_existing_related_story(case, monkeypatch):
    calls = client_for(monkeypatch, json.dumps(case.drama()))
    stage.main()
    assert_run(case.output, 'candidate_pending_independent_review', calls, 1)
    path = case.output / 'drama.json'
    before = {p: p.read_bytes() for p in (path, path.with_name('run.json'))}
    output = case.argv('--stage', 'state', '--drama', path,
        '--drama-run-sha256', stage.sha(before[path.with_name('run.json')]), output_name='states')
    calls = client_for(monkeypatch, json.dumps(case.states(), ensure_ascii=False))
    stage.main()
    run = assert_run(output, 'candidate_pending_independent_review', calls, 1)
    merged = json.loads((output / 'screenplay.json').read_bytes())
    assert merged == case.story()
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert run['inputs']['drama']['run_sha256'] == stage.sha(before[path.with_name('run.json')])
    assert run['frozen_drama_preserved'] is True
    related, identity = existing.read_related_story(output / 'screenplay.json', 'short', 45,
        workflow_sha=stage.sha(case.request.read_bytes()), source_sha=stage.sha(case.full.read_bytes()), sources=case.sources)
    assert related == merged and identity['run_sha256'] == stage.sha((output / 'run.json').read_bytes())
    with pytest.raises(ValueError, match='审核'):
        existing.verify_story_review((output / 'screenplay.json').read_bytes(), run,
            workflow_sha=stage.sha(case.request.read_bytes()), source_sha=stage.sha(case.full.read_bytes()))


@pytest.mark.parametrize('defect', ['sha', 'stage', 'status', 'workflow', 'source', 'selection', 'run_sha', 'companion'])
def test_state_rejects_changed_draft_or_provenance_before_client(case, monkeypatch, defect):
    companion = case.companion()
    case.argv('--companion-screenplay', companion)
    client_for(monkeypatch, json.dumps(case.drama()))
    stage.main()
    path = case.output / 'drama.json'
    run_path = path.with_name('run.json')
    run = json.loads(run_path.read_bytes())
    fields = {'sha': 'candidate_sha256', 'stage': 'stage', 'status': 'status',
              'workflow': 'workflow_request_sha256', 'source': 'source_evidence_sha256',
              'selection': 'reference_source_ids'}
    if defect in fields:
        run[fields[defect]] = [] if defect == 'selection' else 'invalid'
        write(run_path, run)
    if defect == 'companion':
        companion.with_name('run.json').write_bytes(companion.with_name('run.json').read_bytes() + b'\n')
    extra = ['--drama-run-sha256', '0' * 64] if defect == 'run_sha' else []
    output = case.argv('--stage', 'state', '--drama', path, *extra, output_name='rejected')
    calls = client_for(monkeypatch, json.dumps(case.states()))
    with pytest.raises(ValueError):
        stage.main()
    assert_run(output, 'preflight_rejected', calls, 0)
    assert calls == [] and not (output / 'screenplay.json').exists()


@pytest.mark.parametrize('response', ['{"broken":', '{"schema":"a","schema":"b"}', '{}'])
def test_invalid_model_answer_is_retained_and_never_retried(case, monkeypatch, response):
    calls = client_for(monkeypatch, response)
    with pytest.raises(ValueError):
        stage.main()
    run = assert_run(case.output, 'failed', calls, 1)
    assert (case.output / 'model_output.json').read_text(encoding='utf-8') == response
    assert run['model_output_sha256'] == stage.sha(response.encode())
    assert not (case.output / 'drama.json').exists()


def test_api_exception_keeps_real_attempt_count_and_response_metadata(case, monkeypatch):
    calls = client_for(monkeypatch, RuntimeError('synthetic transport failure'))
    with pytest.raises(RuntimeError, match='synthetic transport'):
        stage.main()
    run = assert_run(case.output, 'failed', calls, 1)
    assert run['response_metadata_sha256'] == stage.sha((case.output / 'response.json').read_bytes())
    assert not (case.output / 'drama.json').exists()


@pytest.mark.parametrize('defect', ['missing_source', 'blocked_source', 'unknown_reference'])
def test_original_twenty_source_gate_remains_before_model(case, monkeypatch, defect):
    request = json.loads(case.request.read_bytes())
    content = json.loads(request[1]['content'])
    if defect == 'missing_source':
        content['source_evidence'].pop()
    elif defect == 'blocked_source':
        content['source_evidence'][0]['expression_analysis']['blocked_for_script_generation'] = True
    else:
        case.argv('--reference-source-id', 'not_a_source')
    request[1]['content'] = json.dumps(content, ensure_ascii=False)
    write(case.request, request)
    calls = client_for(monkeypatch, '{}')
    with pytest.raises(ValueError):
        stage.main()
    assert_run(case.output, 'preflight_rejected', calls, 0)
    assert calls == []


def test_state_cannot_override_drama_and_invalid_state_is_retained(case, monkeypatch):
    client_for(monkeypatch, json.dumps(case.drama()))
    stage.main()
    output = case.argv('--stage', 'state', '--drama', case.output / 'drama.json', output_name='badstate')
    state = case.states()
    state['end_states'][0]['action'] = 'Unrequested rewrite'
    calls = client_for(monkeypatch, json.dumps(state))
    with pytest.raises(ValueError):
        stage.main()
    assert_run(output, 'failed', calls, 1)
    assert json.loads((output / 'states.json').read_bytes()) == state
    assert not (output / 'screenplay.json').exists()


def test_existing_output_is_not_overwritten(case, monkeypatch):
    sentinel = write(case.output / 'run.json', {'original': True})
    before = sentinel.read_bytes()
    calls = client_for(monkeypatch, '{}')
    with pytest.raises(FileExistsError):
        stage.main()
    assert sentinel.read_bytes() == before and calls == []


def test_exact_revision_retains_all_other_fields_and_can_feed_state(case, monkeypatch):
    companion = case.companion()
    case.argv('--companion-screenplay', companion)
    client_for(monkeypatch, json.dumps(case.drama()))
    stage.main()
    old_path = case.output / 'drama.json'
    before = {path: path.read_bytes() for path in (old_path, old_path.with_name('run.json'))}
    fields = ['/version/shots/1/dialogue', '/characters/1/performance_arc',
              '/version/shots/4/action', '/version/shots/5/action']
    changes = {fields[0]: '当场核对这份。', fields[1]: '由催促到接受核对。',
               fields[2]: '林岚按住眼前纸面。', fields[3]: '林岚抬眼看向陈宁。'}
    extra = [arg for pointer in fields for arg in ('--revise-field', pointer)]
    output = case.argv('--stage', 'revise', '--drama', old_path, *extra, output_name='revision')
    calls = client_for(monkeypatch, json.dumps(changes, ensure_ascii=False))
    stage.main()
    run = assert_run(output, 'candidate_pending_independent_review', calls, 1)
    merged = json.loads((output / 'drama.json').read_bytes())
    expected = case.drama()
    expected['version']['shots'][1]['dialogue'] = changes[fields[0]]
    expected['characters'][1]['performance_arc'] = changes[fields[1]]
    expected['version']['shots'][4]['action'] = changes[fields[2]]
    expected['version']['shots'][5]['action'] = changes[fields[3]]
    assert merged == expected and all(path.read_bytes() == raw for path, raw in before.items())
    assert json.loads((output / 'revision.json').read_bytes()) == changes
    assert run['allowed_revision_fields'] == fields
    assert run['revision_before_sha256'] == stage.sha(before[old_path])
    assert run['revision_after_sha256'] == run['candidate_sha256']
    assert run['inputs']['drama']['run_sha256'] == stage.sha(before[old_path.with_name('run.json')])
    assert run['inputs']['companion_screenplay']['path'] == str(companion)
    sent = json.loads(calls[1][1][1]['content'])
    assert sent['drama'] == case.drama() and sent['allowed_revision_fields'] == fields
    state_output = case.argv('--stage', 'state', '--drama', output / 'drama.json', output_name='revised_state')
    calls = client_for(monkeypatch, json.dumps(case.states()))
    stage.main()
    assert_run(state_output, 'candidate_pending_independent_review', calls, 1)
    actual = json.loads((state_output / 'screenplay.json').read_bytes())
    assert actual['version']['shots'][1]['dialogue'] == changes[fields[0]]
    assert actual['characters'][1]['performance_arc'] == changes[fields[1]]


@pytest.mark.parametrize('pointer', ['/core_message', '/version/shots/0/duration_seconds',
    '/version/shots/0/dialogue_speaker', '/version/shots/01/action', '/version/shots/99/action',
    '/version/reference_usage/0/adaptation', '/characters/0/voice', '/version/props/0/name'])
def test_revision_forbidden_or_fake_path_is_preflight_rejected(case, monkeypatch, pointer):
    client_for(monkeypatch, json.dumps(case.drama()))
    stage.main()
    output = case.argv('--stage', 'revise', '--drama', case.output / 'drama.json',
                       '--revise-field', pointer, output_name='bad_revision')
    calls = client_for(monkeypatch, json.dumps({pointer: 'No change allowed'}))
    with pytest.raises(ValueError, match='revise_field'):
        stage.main()
    assert_run(output, 'preflight_rejected', calls, 0)
    assert calls == []


@pytest.mark.parametrize('changes', [{}, {'/version/shots/1/dialogue': ''},
    {'/version/shots/1/dialogue': 3}, {'/version/shots/1/dialogue': '可以。', '/core_message': '越权。'}])
def test_invalid_revision_values_are_saved_but_no_merged_candidate(case, monkeypatch, changes):
    client_for(monkeypatch, json.dumps(case.drama()))
    stage.main()
    output = case.argv('--stage', 'revise', '--drama', case.output / 'drama.json',
        '--revise-field', '/version/shots/1/dialogue', output_name='invalid_revision')
    calls = client_for(monkeypatch, json.dumps(changes))
    with pytest.raises(ValueError):
        stage.main()
    assert_run(output, 'failed', calls, 1)
    assert json.loads((output / 'revision.json').read_bytes()) == changes
    assert not (output / 'drama.json').exists()


@pytest.mark.parametrize('defect', ['missing_fields', 'companion_replacement', 'fields_in_state', 'duplicate_fields'])
def test_revision_invocation_is_explicit_and_cannot_swap_companion(case, monkeypatch, defect):
    client_for(monkeypatch, json.dumps(case.drama()))
    stage.main()
    extra = ['--stage', 'revise', '--drama', case.output / 'drama.json']
    if defect == 'companion_replacement':
        extra += ['--companion-screenplay', case.companion(), '--revise-field', '/version/premise']
    elif defect == 'fields_in_state':
        extra += ['--stage', 'state', '--revise-field', '/version/premise']
    elif defect == 'duplicate_fields':
        extra += ['--revise-field', '/version/premise', '--revise-field', '/version/premise']
    output = case.argv(*extra, output_name='bad_flags')
    calls = client_for(monkeypatch, '{}')
    with pytest.raises(ValueError):
        stage.main()
    assert_run(output, 'preflight_rejected', calls, 0)
    assert calls == []


def make_revision(case, monkeypatch, parent=None, *, name='chain_revision', companion=False):
    if parent is None:
        if companion:
            case.argv('--companion-screenplay', case.companion())
        client_for(monkeypatch, json.dumps(case.drama()))
        stage.main()
        parent = case.output / 'drama.json'
    output = case.argv('--stage', 'revise', '--drama', parent,
        '--revise-field', '/version/shots/1/dialogue', output_name=name)
    client_for(monkeypatch, json.dumps({'/version/shots/1/dialogue': '现在核对这张。'}))
    stage.main()
    return output / 'drama.json'


def read_bound(case, path):
    return stage.read_drama(path, 'short', 45, workflow_sha=stage.sha(case.request.read_bytes()),
        source_sha=stage.sha(case.full.read_bytes()), sources=case.sources,
        reference_source_ids=[case.sources[0]['source_id']])


def test_revision_cannot_hide_frozen_field_change_behind_self_reported_hashes(case, monkeypatch):
    path = make_revision(case, monkeypatch)
    data = json.loads(path.read_bytes())
    data['version']['props'][0]['name'] = '伪造的另一种道具定义'
    write(path, data)
    run_path = path.with_name('run.json')
    run = json.loads(run_path.read_bytes())
    run['candidate_sha256'] = run['revision_after_sha256'] = stage.sha(path.read_bytes())
    write(run_path, run)
    with pytest.raises(ValueError, match='replay|父|revision'):
        read_bound(case, path)


def test_two_real_revision_generations_replay_to_original_without_writes(case, monkeypatch):
    first = make_revision(case, monkeypatch, companion=True)
    second = make_revision(case, monkeypatch, first, name='second_revision')
    paths = [p for p in case.root.rglob('*.json')]
    original = {path: path.read_bytes() for path in paths}
    data, identity, companion, companion_identity = read_bound(case, second)
    assert data == json.loads(second.read_bytes())
    assert identity['sha256'] == stage.sha(second.read_bytes())
    assert companion == case.story('long') and companion_identity is not None
    assert all(path.read_bytes() == raw for path, raw in original.items())


@pytest.mark.parametrize('defect', ['parent_run_bytes', 'parent_candidate_bytes', 'parent_path',
    'parent_run_path', 'missing_parent', 'blank_run_sha', 'wrong_parent_source', 'ancestor_revision'])
def test_revision_reopens_and_verifies_complete_parent_chain(case, monkeypatch, defect):
    first = make_revision(case, monkeypatch)
    path = make_revision(case, monkeypatch, first, name='child_revision')
    run = json.loads(path.with_name('run.json').read_bytes())
    parent = json.loads(first.read_bytes())
    if defect == 'parent_run_bytes':
        first.with_name('run.json').write_bytes(first.with_name('run.json').read_bytes() + b'\n')
    elif defect == 'parent_candidate_bytes':
        first.write_bytes(first.read_bytes() + b'\n')
    elif defect == 'parent_path':
        run['inputs']['drama']['path'] = str(case.output / 'drama.json')
    elif defect == 'parent_run_path':
        run['inputs']['drama']['run_path'] = str(case.output / 'run.json')
    elif defect == 'missing_parent':
        run['inputs']['drama']['path'] = str(first.with_name('missing_drama.json'))
    elif defect == 'blank_run_sha':
        run['inputs']['drama']['run_sha256'] = ''
    elif defect == 'wrong_parent_source':
        parent_run = json.loads(first.with_name('run.json').read_bytes())
        parent_run['source_evidence_sha256'] = '0' * 64
        write(first.with_name('run.json'), parent_run)
        run['inputs']['drama']['run_sha256'] = stage.sha(first.with_name('run.json').read_bytes())
    else:
        # Forge a valid-looking ancestor and update the immediate child hashes.
        # The grandparent-to-parent replay must still expose frozen text changes.
        parent['characters'][0]['voice'] = '另一种未获准替换的声线。'
        write(first, parent)
        parent_run = json.loads(first.with_name('run.json').read_bytes())
        parent_run['candidate_sha256'] = parent_run['revision_after_sha256'] = stage.sha(first.read_bytes())
        write(first.with_name('run.json'), parent_run)
        run['inputs']['drama']['sha256'] = run['revision_before_sha256'] = stage.sha(first.read_bytes())
        run['inputs']['drama']['run_sha256'] = stage.sha(first.with_name('run.json').read_bytes())
    write(path.with_name('run.json'), run)
    with pytest.raises((ValueError, FileNotFoundError)):
        read_bound(case, path)


def test_revision_cannot_silently_drop_companion_binding(case, monkeypatch):
    path = make_revision(case, monkeypatch, companion=True)
    run = json.loads(path.with_name('run.json').read_bytes())
    run['inputs'].pop('companion_screenplay')
    write(path.with_name('run.json'), run)
    with pytest.raises(ValueError, match='companion'):
        read_bound(case, path)


def test_revision_cycle_fails_without_unbounded_recursion(case, monkeypatch):
    path = make_revision(case, monkeypatch)
    run = json.loads(path.with_name('run.json').read_bytes())
    run['inputs']['drama'] = {'path': str(path), 'sha256': stage.sha(path.read_bytes()),
        'run_path': str(path.with_name('run.json')), 'run_sha256': '0' * 64}
    run['revision_before_sha256'] = run['inputs']['drama']['sha256']
    write(path.with_name('run.json'), run)
    with pytest.raises(ValueError, match='cycle'):
        read_bound(case, path)


def test_revision_depth_is_bounded_and_boundary_can_pass(case, monkeypatch):
    path = make_revision(case, monkeypatch)
    monkeypatch.setattr(stage, 'MAX_DRAMA_LINEAGE', 2)
    assert read_bound(case, path)[0] == json.loads(path.read_bytes())
    monkeypatch.setattr(stage, 'MAX_DRAMA_LINEAGE', 1)
    with pytest.raises(ValueError, match='bounded depth'):
        read_bound(case, path)


def make_state(case, monkeypatch):
    case.argv('--companion-screenplay', case.companion())
    client_for(monkeypatch, json.dumps(case.drama()))
    stage.main()
    output = case.argv('--stage', 'state', '--drama', case.output / 'drama.json', output_name='full_state')
    client_for(monkeypatch, json.dumps(case.states()))
    stage.main()
    return output / 'screenplay.json'


def read_bound_state(case, path):
    return stage.read_state_screenplay(path, 'short', 45,
        workflow_sha=stage.sha(case.request.read_bytes()), source_sha=stage.sha(case.full.read_bytes()),
        sources=case.sources, reference_source_ids=[case.sources[0]['source_id']])


def make_state_revision(case, monkeypatch, parent=None, name='state_revision'):
    parent = parent or make_state(case, monkeypatch)
    pointer = '/version/shots/1/end_state/props/paper'
    output = case.argv('--stage', 'state-revise', '--screenplay', parent,
        '--revise-field', pointer, output_name=name)
    calls = client_for(monkeypatch, json.dumps({pointer: '桌面中央，正面向上，未签署。'}))
    stage.main()
    return output / 'screenplay.json', calls


def test_state_revision_changes_only_requested_leaf_and_replays_into_existing_story_flow(case, monkeypatch):
    parent = make_state(case, monkeypatch)
    originals = {p: p.read_bytes() for p in case.root.rglob('*.json')}
    path, calls = make_state_revision(case, monkeypatch, parent)
    run = assert_run(path.parent, 'candidate_pending_independent_review', calls, 1)
    expected = case.story()
    expected['version']['shots'][1]['end_state']['props']['paper'] = '桌面中央，正面向上，未签署。'
    actual, identity, drama, drama_identity, companion, _ = read_bound_state(case, path)
    assert actual == expected and drama == case.drama() and companion == case.story('long')
    assert all(p.read_bytes() == raw for p, raw in originals.items())
    assert run['state_revision_before_sha256'] == stage.sha(parent.read_bytes())
    assert run['state_revision_after_sha256'] == identity['sha256']
    assert run['frozen_drama_sha256'] == drama_identity['sha256']
    assert run['state_revision_output_sha256'] == stage.sha(path.with_name('state_revision.json').read_bytes())
    assert 'checks' not in run and run['non_state_fields_preserved'] is True
    related, _ = existing.read_related_story(path, 'short', 45,
        workflow_sha=stage.sha(case.request.read_bytes()), source_sha=stage.sha(case.full.read_bytes()), sources=case.sources)
    assert related == expected
    with pytest.raises(ValueError, match='审核'):
        existing.verify_story_review(path.read_bytes(), run,
            workflow_sha=stage.sha(case.request.read_bytes()), source_sha=stage.sha(case.full.read_bytes()))


@pytest.mark.parametrize('pointer', ['/version/shots/1/action', '/version/shots/1/end_state',
    '/initial_state/props/paper', '/version/initial_state/props/not_defined', '/version/shots/01/end_state/props/paper'])
def test_state_revision_forbidden_or_fake_path_has_zero_calls(case, monkeypatch, pointer):
    parent = make_state(case, monkeypatch)
    output = case.argv('--stage', 'state-revise', '--screenplay', parent,
        '--revise-field', pointer, output_name='invalid_state_revision')
    calls = client_for(monkeypatch, '{}')
    with pytest.raises(ValueError):
        stage.main()
    assert_run(output, 'preflight_rejected', calls, 0)
    assert calls == []


@pytest.mark.parametrize('replacement', [{}, {'/version/initial_state/props/paper': ''},
    {'/version/initial_state/props/paper': {}}, {'/version/initial_state/props/paper': '桌面。', '/version/shots/0/action': '改写'}])
def test_state_revision_invalid_values_saved_without_candidate(case, monkeypatch, replacement):
    parent = make_state(case, monkeypatch)
    output = case.argv('--stage', 'state-revise', '--screenplay', parent,
        '--revise-field', '/version/initial_state/props/paper', output_name='bad_state_values')
    calls = client_for(monkeypatch, json.dumps(replacement))
    with pytest.raises(ValueError):
        stage.main()
    assert_run(output, 'failed', calls, 1)
    assert json.loads((output / 'state_revision.json').read_bytes()) == replacement
    assert not (output / 'screenplay.json').exists()


@pytest.mark.parametrize('defect', ['run_sha', 'states', 'frozen_story', 'original_drama', 'status'])
def test_state_revision_rejects_fake_original_parent_before_model(case, monkeypatch, defect):
    parent = make_state(case, monkeypatch)
    run_path = parent.with_name('run.json')
    run = json.loads(run_path.read_bytes())
    if defect == 'run_sha':
        run['candidate_sha256'] = '0' * 64
    elif defect == 'states':
        parent.with_name('states.json').write_bytes(parent.with_name('states.json').read_bytes() + b'\n')
    elif defect == 'frozen_story':
        data = json.loads(parent.read_bytes())
        data['version']['shots'][0]['action'] = '未经允许的新动作。'
        write(parent, data)
        run['candidate_sha256'] = stage.sha(parent.read_bytes())
    elif defect == 'original_drama':
        run['inputs']['drama']['run_sha256'] = '0' * 64
    else:
        run['status'] = 'failed'
    write(run_path, run)
    output = case.argv('--stage', 'state-revise', '--screenplay', parent,
        '--revise-field', '/version/initial_state/props/paper', output_name='fake_parent')
    calls = client_for(monkeypatch, '{}')
    with pytest.raises(ValueError):
        stage.main()
    assert_run(output, 'preflight_rejected', calls, 0)
    assert calls == []


def test_state_revision_parent_chain_detects_frozen_forgery_cycles_and_depth(case, monkeypatch):
    first, _ = make_state_revision(case, monkeypatch)
    second, _ = make_state_revision(case, monkeypatch, first, name='second_state_revision')
    original = second.read_bytes()
    original_run = second.with_name('run.json').read_bytes()
    assert read_bound_state(case, second)[0] == json.loads(original)
    data = json.loads(original)
    data['version']['shots'][0]['dialogue'] = '未被授权替换的对白。'
    write(second, data)
    run = json.loads(original_run)
    run['candidate_sha256'] = run['state_revision_after_sha256'] = stage.sha(second.read_bytes())
    write(second.with_name('run.json'), run)
    with pytest.raises(ValueError, match='replay'):
        read_bound_state(case, second)
    second.write_bytes(original)
    run = json.loads(original_run)
    run['inputs']['screenplay'] = {'path': str(second), 'sha256': stage.sha(original),
        'run_path': str(second.with_name('run.json')), 'run_sha256': '0' * 64}
    run['state_revision_before_sha256'] = stage.sha(original)
    write(second.with_name('run.json'), run)
    with pytest.raises(ValueError, match='cycle'):
        read_bound_state(case, second)
    second.with_name('run.json').write_bytes(original_run)
    monkeypatch.setattr(stage, 'MAX_DRAMA_LINEAGE', 2)
    with pytest.raises(ValueError, match='bounded depth'):
        read_bound_state(case, second)


def test_flat_new_draft_is_retained_as_raw_failure_without_retry(case, monkeypatch):
    draft = case.drama()
    for shot, seconds in zip(draft['version']['shots'], [7, 8, 7, 8, 8, 7]):
        shot['duration_seconds'] = seconds
    calls = client_for(monkeypatch, json.dumps(draft, ensure_ascii=False))
    with pytest.raises(ValueError, match='dramatic pacing'):
        stage.main()
    assert not (case.output / 'drama.json').exists()
    assert (case.output / 'model_output.json').exists()
    assert len([call for call in calls if call[0] == 'call']) == 1
