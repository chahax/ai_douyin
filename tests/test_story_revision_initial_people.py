"""Synthetic story-only initial-person edits; no actual story/media approval."""
import copy
import json

import pytest

from scripts import run_screenplay_stage as stage
from src.trend_intelligence import story_revision, script_drama
from test_script_screenplay import screenplay, sources
from test_story_revision_cli import (case, workflow, write, client_for, create_story,
                                     revise_args, assert_run, read_bound)


INITIAL = '/version/initial_state/people/林岚'
ACTION = '/version/shots/0/action'
FIELDS = (INITIAL, ACTION)
CHANGES = {INITIAL: '坐在桌子北侧，双手搭在桌沿，目光朝向纸面。',
           ACTION: '林岚将右手从桌沿移到纸面，按住当前纸面。'}


def test_mixed_two_leaf_merge_preserves_every_unselected_story_value():
    original = screenplay()
    before = copy.deepcopy(original)
    fields_before, changes_before = list(FIELDS), copy.deepcopy(CHANGES)
    assert story_revision.validate_story_revision_fields(original, fields_before) == FIELDS
    result = story_revision.apply_story_revision(original, CHANGES, fields_before, 'short', 45,
                                                 sources(), ('douyin:1',))
    expected = copy.deepcopy(before)
    expected['version']['initial_state']['people']['林岚'] = CHANGES[INITIAL]
    expected['version']['shots'][0]['action'] = CHANGES[ACTION]
    assert result == expected and original == before
    assert CHANGES == changes_before and fields_before == list(FIELDS)
    assert result['version']['shots'][0]['end_state'] == before['version']['shots'][0]['end_state']
    assert not {'passed', 'decision', 'approved'} & result.keys()


@pytest.mark.parametrize('field', [
    '/version/initial_state/people/未知角色', '/version/initial_state/props/paper',
    '/version/shots/0/end_state/people/林岚', '/version/shots/0/end_state/props/paper',
    '/version/initial_state/people', '/version/initial_state', '/version/shots/0/end_state',
    '/initial_state/people/林岚', '/version/initial_state/people/林岚/extra',
])
def test_initial_person_scope_does_not_open_other_states_or_objects(field):
    with pytest.raises(ValueError):
        story_revision.validate_story_revision_fields(screenplay(), [field])


@pytest.mark.parametrize('value', ['', '  ', None, {'state': '对象替换'}])
def test_selected_initial_person_must_stay_nonempty_text(value):
    with pytest.raises(ValueError):
        story_revision.apply_story_revision(screenplay(), {INITIAL: value}, [INITIAL], 'short', 45,
                                             sources(), ('douyin:1',))


def test_new_story_field_does_not_expand_drama_revision_whitelist():
    story = screenplay()
    with pytest.raises(ValueError):
        script_drama.validate_revision_fields(story, [INITIAL])
    drama = copy.deepcopy(story)
    drama['schema'] = script_drama.SCHEMA
    drama['version'].pop('initial_state')
    for shot in drama['version']['shots']:
        shot.pop('end_state')
    with pytest.raises(ValueError):
        script_drama.validate_revision_fields(drama, [INITIAL])


def test_cli_mixed_revision_replays_parent_and_remains_pending(case, monkeypatch):
    parent = create_story(case, monkeypatch)
    originals = {path: path.read_bytes() for path in case.root.rglob('*') if path.is_file()}
    output = revise_args(case, parent, fields=FIELDS)
    calls = client_for(monkeypatch, json.dumps(CHANGES, ensure_ascii=False))
    stage.main()
    run = assert_run(output, calls, 'candidate_pending_independent_review', 1)
    actual, _ = read_bound(case, output / 'screenplay.json')
    expected = json.loads(originals[parent])
    expected['version']['initial_state']['people']['林岚'] = CHANGES[INITIAL]
    expected['version']['shots'][0]['action'] = CHANGES[ACTION]
    assert actual == expected
    assert run['allowed_revision_fields'] == list(FIELDS)
    assert all(path.read_bytes() == raw for path, raw in originals.items())
    sent = json.loads(calls[-1][1][1]['content'])
    assert sent['allowed_revision_fields'] == list(FIELDS)
    assert len(sent['source_overview']) == 20 and len(sent['source_evidence']) == 1


@pytest.mark.parametrize('field', ['/version/initial_state/people/未知角色',
    '/version/initial_state/props/paper', '/version/shots/0/end_state/people/林岚',
    '/version/initial_state/people'])
def test_cli_scope_rejection_precedes_model(case, monkeypatch, field):
    parent = create_story(case, monkeypatch)
    output = revise_args(case, parent, fields=(field,))
    calls = client_for(monkeypatch, '{}')
    with pytest.raises(ValueError):
        stage.main()
    assert_run(output, calls, 'preflight_rejected', 0)
    assert calls == [] and not (output / 'screenplay.json').exists()


def test_replay_detects_unselected_initial_person_change_despite_rehashed_candidate(case, monkeypatch):
    parent = create_story(case, monkeypatch)
    output = revise_args(case, parent, fields=FIELDS)
    client_for(monkeypatch, json.dumps(CHANGES, ensure_ascii=False))
    stage.main()
    current = output / 'screenplay.json'
    forged = json.loads(current.read_bytes())
    forged['version']['initial_state']['people']['陈宁'] = '未经开放却改变另一人物初态。'
    write(current, forged)
    run = json.loads((output / 'run.json').read_bytes())
    run['candidate_sha256'] = run['story_revision_after_sha256'] = stage.sha(current.read_bytes())
    write(output / 'run.json', run)
    with pytest.raises(ValueError):
        read_bound(case, current)


def test_two_revision_ancestry_replays_initial_person_then_rejects_changed_origin(case, monkeypatch):
    parent = create_story(case, monkeypatch)
    first = revise_args(case, parent, name='initial_revision', fields=FIELDS)
    client_for(monkeypatch, json.dumps(CHANGES, ensure_ascii=False))
    stage.main()
    second = revise_args(case, first / 'screenplay.json', name='second_revision', fields=(ACTION,))
    next_action = {ACTION: '林岚把右手移到当前纸面，停稳后开始核对。'}
    client_for(monkeypatch, json.dumps(next_action, ensure_ascii=False))
    stage.main()
    current = second / 'screenplay.json'
    replayed, _ = read_bound(case, current)
    assert replayed['version']['initial_state']['people']['林岚'] == CHANGES[INITIAL]
    assert replayed['version']['shots'][0]['action'] == next_action[ACTION]
    raw_path = parent.with_name('model_output.json')
    raw_path.write_bytes(raw_path.read_bytes() + b'\n')
    with pytest.raises(ValueError):
        read_bound(case, current)
