"""Offline production-revision provenance and exact-field boundary checks."""
import json

import pytest

from scripts import run_screenplay_stage as stage
from test_screenplay_stage_cli import case, workflow, write, client_for
from test_script_screenplay import production_v2


DELIVERY = ('触发：对方递出合同；情绪：迟疑后稳定；语速：略慢；'
            '语气：克制；重音：合同；停顿：回答前一拍；余波：目光回到对方。')


def create_production(case, monkeypatch):
    story = case.related()
    review = case.review(story)
    case.argv('--stage', 'production', '--screenplay', story, '--story-review', review)
    production = production_v2(case.story())
    for shot in production['shots']:
        shot['emotion_and_performance'] = DELIVERY
    client_for(monkeypatch, json.dumps(production, ensure_ascii=False))
    stage.main()
    return case.output / 'production.json', story, review


def revise_args(case, production, story, review, *, name='revised_production', fields=('/scene_design/camera_angle',)):
    output = case.output.parent / name
    args = [arg for pointer in fields for arg in ('--revise-field', pointer)]
    case.argv('--stage', 'production-revise', '--screenplay', story, '--story-review', review,
              '--previous-production', production, '--output-dir', output, *args)
    return output


def read_bound(case, production, story, review):
    return stage.read_previous_production(production, 'short', story=json.loads(story.read_bytes()),
        screenplay_identity={'path': str(story), 'sha256': stage.sha(story.read_bytes())},
        review_identity={'path': str(review), 'sha256': stage.sha(review.read_bytes())},
        workflow_sha=stage.sha(case.request.read_bytes()), source_sha=stage.sha(case.full.read_bytes()),
        reference_source_ids=[case.sources[0]['source_id']])


def assert_run(output, calls, count, status):
    run = json.loads((output / 'run.json').read_bytes())
    assert run['status'] == status and run['model_calls'] == count
    assert run['media_generation'] is False and 'decision' not in run and 'checks' not in run
    assert sum(row[0] == 'call' for row in calls) == count
    return run


def test_production_revision_exact_patch_preserves_story_and_other_production_fields(case, monkeypatch):
    original, story, review = create_production(case, monkeypatch)
    before = {p: p.read_bytes() for p in case.root.rglob('*.json')}
    changes = {'/scene_design/camera_angle': '同一桌轴一侧，平视二人面部。',
               '/shots/1/emotion_and_performance': DELIVERY.replace('回答前一拍', '回答前两拍')}
    output = revise_args(case, original, story, review, fields=tuple(changes))
    calls = client_for(monkeypatch, json.dumps(changes, ensure_ascii=False))
    stage.main()
    run = assert_run(output, calls, 1, 'candidate_pending_independent_review')
    parent = json.loads(original.read_bytes())
    parent['scene_design']['camera_angle'] = changes['/scene_design/camera_angle']
    parent['shots'][1]['emotion_and_performance'] = changes['/shots/1/emotion_and_performance']
    actual, identity = read_bound(case, output / 'production.json', story, review)
    assert actual == parent and all(p.read_bytes() == raw for p, raw in before.items())
    assert run['production_revision_before_sha256'] == stage.sha(before[original])
    assert run['production_revision_after_sha256'] == identity['sha256']
    assert run['inputs']['previous_production']['run_sha256'] == stage.sha(before[original.with_name('run.json')])
    assert json.loads((output / 'production_revision.json').read_bytes()) == changes
    compiled = json.loads((output / 'compiled_version.json').read_bytes())
    for raw, shot in zip(case.story()['version']['shots'], compiled['shots']):
        assert raw['action'] == shot['action'] and raw['dialogue'] == shot['dialogue']
    assert calls[0][1]['max_retries'] == 0 and calls[1][2]['use_cache'] is False


@pytest.mark.parametrize('pointer', ['/schema', '/shots/0/shot_id', '/shots/0/participants',
    '/shots/0/action', '/scene_design/blocking', '/shots/01/composition', '/shots/999/composition',
    '/shots/0/camera_angle', '/scene_design'])
def test_production_revision_forbidden_or_missing_pointer_is_zero_call(case, monkeypatch, pointer):
    original, story, review = create_production(case, monkeypatch)
    output = revise_args(case, original, story, review, fields=(pointer,))
    calls = client_for(monkeypatch, '{}')
    with pytest.raises(ValueError):
        stage.main()
    assert_run(output, calls, 0, 'preflight_rejected')
    assert calls == []


@pytest.mark.parametrize('changes', [{}, {'/scene_design/camera_angle': ''},
    {'/scene_design/camera_angle': {}}, {'/scene_design/camera_angle': '平视。', '/shots/0/shot_id': 'S99'}])
def test_production_revision_invalid_mapping_is_retained_without_candidate(case, monkeypatch, changes):
    original, story, review = create_production(case, monkeypatch)
    output = revise_args(case, original, story, review)
    calls = client_for(monkeypatch, json.dumps(changes))
    with pytest.raises(ValueError):
        stage.main()
    assert_run(output, calls, 1, 'failed')
    assert json.loads((output / 'production_revision.json').read_bytes()) == changes
    assert not (output / 'production.json').exists() and not (output / 'compiled_version.json').exists()


@pytest.mark.parametrize('defect', ['story', 'review', 'source', 'status', 'model_output', 'request', 'compiled'])
def test_production_revision_rejects_changed_parent_bindings_before_model(case, monkeypatch, defect):
    original, story, review = create_production(case, monkeypatch)
    path = original.with_name('run.json')
    run = json.loads(path.read_bytes())
    if defect in ('story', 'review'):
        key = 'screenplay' if defect == 'story' else 'story_review'
        run['inputs'][key]['sha256'] = '0' * 64
    elif defect == 'source':
        run['source_evidence_sha256'] = '0' * 64
    elif defect == 'status':
        run['status'] = 'failed'
    else:
        filename = {'model_output': 'model_output.json', 'request': 'request.json', 'compiled': 'compiled_version.json'}[defect]
        target = original.with_name(filename)
        target.write_bytes(target.read_bytes() + b'\n')
    write(path, run)
    output = revise_args(case, original, story, review)
    calls = client_for(monkeypatch, '{}')
    with pytest.raises(ValueError):
        stage.main()
    assert_run(output, calls, 0, 'preflight_rejected')
    assert calls == []


def test_production_revision_detects_forged_unchanged_fields_and_parent_cycle(case, monkeypatch):
    parent, story, review = create_production(case, monkeypatch)
    output = revise_args(case, parent, story, review)
    client_for(monkeypatch, json.dumps({'/scene_design/camera_angle': '同轴一侧平视。'}))
    stage.main()
    path = output / 'production.json'
    original_bytes = path.read_bytes()
    original_run = path.with_name('run.json').read_bytes()
    assert read_bound(case, path, story, review)[0] == json.loads(original_bytes)
    data = json.loads(original_bytes)
    data['shots'][0]['composition'] = '未经允许改写另一镜构图。'
    write(path, data)
    run = json.loads(original_run)
    run['production_sha256'] = run['production_revision_after_sha256'] = stage.sha(path.read_bytes())
    write(path.with_name('run.json'), run)
    with pytest.raises(ValueError, match='replay'):
        read_bound(case, path, story, review)
    path.write_bytes(original_bytes)
    run = json.loads(original_run)
    run['inputs']['previous_production'] = {'path': str(path), 'sha256': stage.sha(original_bytes),
        'run_path': str(path.with_name('run.json')), 'run_sha256': '0' * 64}
    run['production_revision_before_sha256'] = stage.sha(original_bytes)
    write(path.with_name('run.json'), run)
    with pytest.raises(ValueError, match='cycle'):
        read_bound(case, path, story, review)


def test_production_revision_parent_chain_and_depth_boundary(case, monkeypatch):
    parent, story, review = create_production(case, monkeypatch)
    first = revise_args(case, parent, story, review, name='revision_1')
    client_for(monkeypatch, json.dumps({'/scene_design/camera_angle': '同轴一侧平视。'}))
    stage.main()
    second = revise_args(case, first / 'production.json', story, review, name='revision_2')
    client_for(monkeypatch, json.dumps({'/scene_design/camera_angle': '桌轴一侧平视面部。'}))
    stage.main()
    assert read_bound(case, second / 'production.json', story, review)[0]['scene_design']['camera_angle'] == '桌轴一侧平视面部。'
    monkeypatch.setattr(stage, 'MAX_PRODUCTION_LINEAGE', 2)
    with pytest.raises(ValueError, match='bounded depth'):
        read_bound(case, second / 'production.json', story, review)


def test_production_revision_requires_real_passed_story_review(case, monkeypatch):
    original, story, review = create_production(case, monkeypatch)
    bad = json.loads(review.read_bytes())
    bad['decision'] = 'failed'
    write(review, bad)
    output = revise_args(case, original, story, review)
    calls = client_for(monkeypatch, '{}')
    with pytest.raises(ValueError, match='审核'):
        stage.main()
    assert_run(output, calls, 0, 'preflight_rejected')
    assert calls == []
