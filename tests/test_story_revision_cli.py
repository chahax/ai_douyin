"""Offline story revision tests: real saved fixture lineage, no model approval."""
import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scripts import run_screenplay_stage as stage
from test_screenplay_stage_cli import case, workflow, write, client_for


FIELDS = ('/version/shots/3/dialogue', '/version/shots/3/action')
CHANGES = {FIELDS[0]: '先核对这份纸上的内容，再决定当前是否签字。',
           FIELDS[1]: '林岚按住桌面中间的纸面，继续核对当前内容。'}


def create_story(case, monkeypatch):
    prompt = 'script_screenplay_revision.md'
    original = Path(stage.__file__).resolve().parents[1] / 'src/trend_intelligence/prompts' / prompt
    (case.root / 'src/trend_intelligence/prompts' / prompt).write_bytes(original.read_bytes())
    case.argv('--stage', 'story')
    client_for(monkeypatch, json.dumps(case.story(), ensure_ascii=False))
    stage.main()
    return case.output / 'screenplay.json'


def revise_args(case, parent, *, name='revised_story', fields=FIELDS, extra=()):
    output = case.output.parent / name
    field_args = [value for field in fields for value in ('--revise-field', field)]
    case.argv('--stage', 'story-revise', '--previous-screenplay', parent,
              '--output-dir', output, *field_args, *extra)
    return output


def assert_run(output, calls, status, count):
    run = json.loads((output / 'run.json').read_bytes())
    assert run['status'] == status and run['model_calls'] == count
    assert sum(item[0] == 'call' for item in calls) == count
    assert run['media_generation'] is False
    assert not {'passed', 'decision', 'checks', 'approved'} & run.keys()
    start, finish = (datetime.fromisoformat(run[key]) for key in ('started_at_bjt', 'finished_at_bjt'))
    assert start.utcoffset() == finish.utcoffset() == timedelta(hours=8) and finish >= start
    return run


def read_bound(case, path):
    return stage.read_related_story(path, 'short', 45,
        workflow_sha=stage.sha(case.request.read_bytes()), source_sha=stage.sha(case.full.read_bytes()),
        sources=case.sources)


def test_two_leaf_revision_preserves_all_states_and_other_fields(case, monkeypatch):
    parent = create_story(case, monkeypatch)
    originals = {path: path.read_bytes() for path in case.root.rglob('*') if path.is_file()}
    output = revise_args(case, parent)
    calls = client_for(monkeypatch, json.dumps(CHANGES, ensure_ascii=False))
    stage.main()
    run = assert_run(output, calls, 'candidate_pending_independent_review', 1)
    expected = json.loads(originals[parent])
    expected['version']['shots'][3].update(dialogue=CHANGES[FIELDS[0]], action=CHANGES[FIELDS[1]])
    actual, identity = read_bound(case, output / 'screenplay.json')
    assert actual == expected
    assert all(path.read_bytes() == raw for path, raw in originals.items())
    assert json.loads((output / 'story_revision.json').read_bytes()) == CHANGES
    assert run['story_revision_before_sha256'] == stage.sha(originals[parent])
    assert run['story_revision_after_sha256'] == run['candidate_sha256'] == identity['sha256']
    assert run['story_revision_output_sha256'] == stage.sha((output / 'story_revision.json').read_bytes())
    assert run['unchanged_story_fields_preserved'] is True
    assert run['inputs']['previous_screenplay']['run_sha256'] == stage.sha(originals[parent.with_name('run.json')])
    assert run['allowed_revision_fields'] == list(FIELDS)
    assert len(json.loads((output / 'source_evidence.full.json').read_bytes())) == 20
    sent = json.loads(calls[-1][1][1]['content'])
    assert sent['previous_screenplay'] == json.loads(originals[parent])
    assert sent['allowed_revision_fields'] == list(FIELDS)
    assert len(sent['source_evidence']) == 1 and len(sent['source_overview']) == 20
    assert list(sent)[-1] == 'current_editor_feedback'
    assert calls[0][1]['max_retries'] == 0 and calls[-1][2]['use_cache'] is False
    assert not (output / 'compiled_version.json').exists()


@pytest.mark.parametrize('fields', [(), (FIELDS[0], FIELDS[0]), ('/core_message',),
    ('/version/initial_state/props/paper',), ('/version/shots/3/end_state/props/paper',),
    ('/version/shots/3/dialogue_speaker',), ('/version/shots/03/dialogue',),
    ('/version/shots/999/action',), ('/version/shots/3',), ('/version/reference_usage/0/adaptation',)])
def test_forbidden_missing_or_duplicate_fields_reject_before_model(case, monkeypatch, fields):
    parent = create_story(case, monkeypatch)
    output = revise_args(case, parent, fields=fields)
    calls = client_for(monkeypatch, '{}')
    with pytest.raises(ValueError):
        stage.main()
    assert_run(output, calls, 'preflight_rejected', 0)
    assert calls == [] and not (output / 'screenplay.json').exists()


@pytest.mark.parametrize('changes', [{}, {FIELDS[0]: CHANGES[FIELDS[0]]},
    {**CHANGES, '/core_message': '未经授权改变共同核心。'},
    {**CHANGES, FIELDS[0]: ''}, {**CHANGES, FIELDS[0]: '  '},
    {**CHANGES, FIELDS[1]: {}}, {**CHANGES, FIELDS[1]: None}])
def test_nonexact_or_nonstring_patch_keeps_raw_without_candidate(case, monkeypatch, changes):
    parent = create_story(case, monkeypatch)
    parent_raw = parent.read_bytes()
    output = revise_args(case, parent)
    raw = json.dumps(changes, ensure_ascii=False)
    calls = client_for(monkeypatch, raw)
    with pytest.raises(ValueError):
        stage.main()
    assert_run(output, calls, 'failed', 1)
    assert (output / 'model_output.json').read_text(encoding='utf-8') == raw
    assert not (output / 'screenplay.json').exists() and parent.read_bytes() == parent_raw


def test_duplicate_model_patch_key_is_preserved_and_never_last_value_wins(case, monkeypatch):
    parent = create_story(case, monkeypatch)
    output = revise_args(case, parent)
    raw = '{' + json.dumps(FIELDS[0]) + ': "earlier contradictory dialogue", ' + json.dumps(CHANGES, ensure_ascii=False)[1:]
    calls = client_for(monkeypatch, raw)
    with pytest.raises(ValueError, match='duplicate JSON key'):
        stage.main()
    assert_run(output, calls, 'failed', 1)
    assert (output / 'model_output.json').read_text(encoding='utf-8') == raw
    assert not (output / 'screenplay.json').exists()


@pytest.mark.parametrize('defect', ['candidate_sha256', 'workflow_request_sha256',
    'source_evidence_sha256', 'status', 'request.json', 'model_output.json'])
def test_changed_parent_run_or_original_model_trace_is_zero_call(case, monkeypatch, defect):
    parent = create_story(case, monkeypatch)
    run_path = parent.with_name('run.json')
    run = json.loads(run_path.read_bytes())
    if defect.endswith('.json'):
        path = parent.with_name(defect)
        path.write_bytes(path.read_bytes() + b'\n')
    else:
        run[defect] = 'failed' if defect == 'status' else '0' * 64
        write(run_path, run)
    output = revise_args(case, parent)
    calls = client_for(monkeypatch, '{}')
    with pytest.raises(ValueError):
        stage.main()
    assert_run(output, calls, 'preflight_rejected', 0)
    assert calls == [] and not (output / 'screenplay.json').exists()


def test_related_revision_replays_parent_chain_instead_of_trusting_unchanged_flag(case, monkeypatch):
    parent = create_story(case, monkeypatch)
    output = revise_args(case, parent)
    client_for(monkeypatch, json.dumps(CHANGES, ensure_ascii=False))
    stage.main()
    current = output / 'screenplay.json'
    original = json.loads(current.read_bytes())
    assert read_bound(case, current)[0] == original
    forged = copy.deepcopy(original)
    forged['version']['shots'][0]['end_state']['props']['paper'] = '未经允许变为已签字。'
    write(current, forged)
    run = json.loads((output / 'run.json').read_bytes())
    run['candidate_sha256'] = run['story_revision_after_sha256'] = stage.sha(current.read_bytes())
    write(output / 'run.json', run)
    with pytest.raises(ValueError):
        read_bound(case, current)


def test_second_revision_replays_both_models_and_rejects_changed_ancestor(case, monkeypatch):
    parent = create_story(case, monkeypatch)
    first = revise_args(case, parent, name='story_revision_1')
    client_for(monkeypatch, json.dumps(CHANGES, ensure_ascii=False))
    stage.main()
    second_changes = {FIELDS[0]: '目前这份内容仍未共同确认，先停止当前签署。'}
    second = revise_args(case, first / 'screenplay.json', name='story_revision_2', fields=(FIELDS[0],))
    client_for(monkeypatch, json.dumps(second_changes, ensure_ascii=False))
    stage.main()
    result, _ = read_bound(case, second / 'screenplay.json')
    assert result['version']['shots'][3]['dialogue'] == second_changes[FIELDS[0]]
    assert result['version']['shots'][3]['action'] == CHANGES[FIELDS[1]]
    parent.with_name('model_output.json').write_bytes(parent.with_name('model_output.json').read_bytes() + b'\n')
    with pytest.raises(ValueError):
        read_bound(case, second / 'screenplay.json')
