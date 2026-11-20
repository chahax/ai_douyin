"""Offline grounding audit: synthetic text/media fixtures, no paid API or real approvals."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_script_video as runner
from src.content_factory import ark_opening_frame as opening, compact_execution as compact
from src.content_factory import execution_grounding as grounding, video_campaign as campaign
from src.content_factory.seedance_client import SeedanceClient
from scripts import revise_execution_grounding as cli
from test_ark_opening_frame import prepared
from test_compact_execution import case, staged, review
from test_video_campaign_compact_execution import retry_case
from test_video_campaign import generated_review


VALUE = {'visual_bindings': ['合成首图左侧角色甲，右侧角色乙。'],
         'action_constraints': ['角色甲右手只指纸面，不触碰桌中的笔。']}


@pytest.fixture
def grounding_case(retry_case, request):
    """Register an eighth synthetic failed S01, import its unchanged opening to a new run."""
    item = retry_case
    record = copy.deepcopy(item['record'])
    campaign.reserve(item['folder'], item['manifest'], record)
    report_path = generated_review(item['folder'], record, False)
    report = runner.read(report_path)
    report['checks']['props_and_hands'] = False
    if getattr(request, 'param', None) == 'different_serialization':
        # The submitted bytes are hashed by campaign.review. Current releases
        # preserve them in both copies; recreate the older normalized-copy
        # layout to test compatibility without rewriting the ledger.
        raw = json.dumps(report, ensure_ascii=False, indent=1).replace('\n', '\r\n') + '\r\n'
        report_path.write_bytes(raw.encode('utf-8'))
    else:
        runner.write(report_path, report)
    campaign.review(item['folder'], 'S01', report_path)
    review_digest = runner.sha(report_path)
    if getattr(request, 'param', None) == 'different_serialization':
        quality = item['folder'] / 'S01.quality_review.json'
        history = item['folder'] / 'quality_review_history' / 'S01' / f'{review_digest}.json'
        runner.write(quality, report)
        runner.write(history, report)
    target = item['folder'].parent / 'grounding_target'
    manifest = runner.prepare(target, item['source'], 'Synthetic test only', provider='ark_api')
    campaign.attach(target, item['campaign'])
    imported = opening.import_opening_frame(target, item['folder'], item['image'],
                                            target / 'imported_opening', item['config'])
    return {**item, 'failed_run': item['folder'], 'target': target,
            'target_manifest': runner.read(target / 'production.json'),
            'target_image': Path(imported['image']), 'output': target / 'grounding_v1',
            'submitted_review': report_path, 'submitted_review_sha256': review_digest,
            'history_review': item['folder'] / 'quality_review_history' / 'S01' / f'{review_digest}.json'}


def collect(item):
    return grounding.collect_grounding_source(item['target'], item['target_image'],
                                              item['failed_run'], item['config'])


def args(item, output=None):
    return ['--run-dir', str(item['target']), '--first-frame', str(item['target_image']),
            '--failed-run', str(item['failed_run']), '--output-dir', str(output or item['output'])]


def fake_client(monkeypatch, raw=None, error=None, metadata=None, provider='synthetic'):
    calls = []
    class Client:
        provider_name = provider
        def __init__(self, **kwargs):
            calls.append(('init', kwargs))
            self.provider = SimpleNamespace(last_response_metadata=metadata or {'finish_reason': 'stop'})
        def chat_completion_tracked(self, messages, **kwargs):
            calls.append(('call', copy.deepcopy(messages), kwargs))
            if error:
                raise error('Synthetic provider outcome unknown')
            return raw
    monkeypatch.setattr(cli, 'LLMClient', Client)
    return calls


@pytest.mark.parametrize('value', [None, [], {}, {'visual_bindings': ['x']},
    {'visual_bindings': [], 'action_constraints': ['x']},
    {'visual_bindings': ['x'], 'action_constraints': []},
    {'visual_bindings': ['x'], 'action_constraints': ['']},
    {'visual_bindings': [' '], 'action_constraints': ['x']},
    {'visual_bindings': [1], 'action_constraints': ['x']},
    {'visual_bindings': 'x', 'action_constraints': ['x']},
    {'visual_bindings': ['x'], 'action_constraints': ['x'], 'dialogue': 'invented'},
    {'visual_bindings': ['x'], 'action_constraints': ['x'], 'decision': 'passed'}])
def test_only_two_nonempty_string_arrays_are_accepted(value):
    with pytest.raises((ValueError, TypeError)):
        grounding.validate_model_value(value)


def test_source_preserves_actual_frozen_story_and_bound_failed_evidence(grounding_case):
    item = grounding_case
    before = {p: p.read_bytes() for p in item['target'].parent.rglob('*') if p.is_file()}
    source = collect(item)
    messages = grounding.build_messages(source)
    text = json.dumps(messages, ensure_ascii=False)
    user_input = json.loads(messages[1]['content'])
    assert user_input['model_guide']['sha256'] == source['model_guide']['sha256']
    assert user_input['model_guide']['instruction'] == source['model_guide']['instruction']
    assert user_input['frozen_characters'] == source['frozen_characters']
    for field in ('dialogue', 'start_frame', 'action', 'end_frame'):
        assert item['script']['shots'][0][field] in text
    # Hashes, not just a claim of failure or a mutable file path, must ground repair.
    for path in (item['failed_run'] / 'S01.mp4', item['failed_run'] / 'S01.quality_review.json',
                 item['failed_run'] / 'packet.json', item['failed_run'] / 'observed.txt',
                 item['failed_run'] / 'frame_reviews/S01.json'):
        assert runner.sha(path) in json.dumps(source)
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert campaign.read(item['campaign'])['failed_outputs'] == 8


@pytest.mark.parametrize('changed', ['video', 'evidence', 'review', 'packet', 'image', 'image_review'])
def test_modified_failure_or_first_frame_source_is_rejected(grounding_case, changed):
    item = grounding_case
    paths = {'video': item['failed_run'] / 'S01.mp4', 'evidence': item['failed_run'] / 'observed.txt',
        'review': item['failed_run'] / 'S01.quality_review.json', 'packet': item['failed_run'] / 'packet.json',
        'image': item['target_image'], 'image_review': item['failed_run'] / 'frame_reviews/S01.json'}
    if changed == 'packet':
        # A changed evidence declaration may not discard all observed evidence.
        packet = runner.read(paths[changed]); packet['evidence'] = []
        runner.write(paths[changed], packet)
    elif changed == 'review':
        report = runner.read(paths[changed])
        report['observations'][0]['notes'] = 'Synthetic changed inspection content.'
        runner.write(paths[changed], report)
    else:
        paths[changed].write_bytes(paths[changed].read_bytes() + b'\n')
    with pytest.raises((ValueError, FileNotFoundError)):
        collect(item)


@pytest.mark.parametrize('change', ['unknown', 'unreviewed', 'series', 'ten_failures', 'hold'])
def test_grounding_cannot_clear_existing_campaign_guards(grounding_case, change):
    item = grounding_case
    data = campaign.read(item['campaign'])
    if change in {'unknown', 'unreviewed'}:
        data['attempts'].append({'id': 'synthetic_pending', 'series_id': 'series_001', 'shot': 'S01',
            'status': 'awaiting_generation_or_review' if change == 'unknown' else 'awaiting_review'})
    elif change == 'series':
        data['current_series_id'] = 'series_002'; data['series'].append({'id': 'series_002', 'runs': []})
    elif change == 'ten_failures':
        data['failed_outputs'] = 10
    else:
        data['holds'] = ['Synthetic unresolved prerequisite']
    campaign.write(item['campaign'], data)
    before = item['campaign'].read_bytes()
    with pytest.raises(ValueError):
        collect(item)
    assert item['campaign'].read_bytes() == before


def test_one_model_call_preserves_source_and_requires_final_independent_review(grounding_case, monkeypatch):
    item = grounding_case
    assert grounding.validate_model_value({'visual_bindings': ['图片1的角色甲所持合同对应P1。'],
        'action_constraints': ['保持原动作接触范围。']})
    with pytest.raises(ValueError):
        grounding.validate_model_value({'visual_bindings': ['图片1的角色甲所持合同对应P1。'],
            'action_constraints': ['0.5秒时先停手。']})
    before = {p: p.read_bytes() for p in item['target'].parent.rglob('*') if p.is_file()}
    calls = fake_client(monkeypatch, json.dumps(VALUE, ensure_ascii=False))
    cli.main(args(item))
    assert len([row for row in calls if row[0] == 'call']) == 1
    assert calls[0][1]['model'].lower() == 'minimax-m3' and calls[0][1]['max_retries'] == 0
    assert calls[1][2]['use_cache'] is False
    plan_path = item['output'] / 'grounding_plan.json'
    value, proof = grounding.require_grounding(item['target'], item['target_image'], plan_path, item['config'])
    assert value == VALUE and proof
    assert all(path.read_bytes() == raw for path, raw in before.items())
    output = item['target'] / 'compact_v2/plan.json'
    plan = compact.prepare_compact_execution(item['target'], item['target_image'], output,
                                              item['config'], grounding_plan=plan_path)
    assert plan['profile'] == 'compact_execution/v2'
    assert plan['text_review'] == plan['media_review'] == 'pending'
    assert item['script']['shots'][0]['dialogue'] in plan['prompt']
    assert plan['prompt'].count(item['script']['shots'][0]['dialogue']) == 1
    for group in VALUE.values():
        for line in group:
            assert line in plan['prompt']
    monkeypatch.setattr(SeedanceClient, 'create_task', lambda *a, **kw: pytest.fail('Unreviewed candidate called video API'))
    with pytest.raises(FileNotFoundError):
        runner.submit(item['target'], 'S01', SeedanceClient(item['config']), [], first_frame=item['target_image'],
                      execution_plan=output, execution_review=output.with_name('independent_review.json'))
    # Only the final combined prompt is reviewed. Grounding alone never approves it.
    combined_case = {**item, 'folder': item['target'], 'image': item['target_image'],
        'plan': plan, 'plan_path': output, 'review_path': output.with_name('independent_review.json')}
    review(combined_case)
    prompt, combined_proof = compact.require_compact_execution(item['target'], item['target_image'], output,
        combined_case['review_path'], item['config'])
    assert prompt == plan['prompt'] and combined_proof['profile'] == 'compact_execution/v2'
    run_path = item['output'] / 'run.json'
    run_path.write_bytes(run_path.read_bytes() + b'\n')
    with pytest.raises(ValueError):
        compact.require_compact_execution(item['target'], item['target_image'], output,
            combined_case['review_path'], item['config'])
    assert campaign.read(item['campaign'])['failed_outputs'] == 8
    assert not (item['target'] / 'S01.json').exists()


@pytest.mark.parametrize('raw', ['{invalid', '', 'null', '[]', '{"visual_bindings":["x"],"action_constraints":[]}',
    '{"visual_bindings":["x"],"action_constraints":["x"],"dialogue":"added"}',
    '{"visual_bindings":["x"],"visual_bindings":["y"],"action_constraints":["x"]}'])
def test_invalid_model_response_is_recorded_without_retry_or_candidate(grounding_case, monkeypatch, raw):
    item = grounding_case
    calls = fake_client(monkeypatch, raw)
    with pytest.raises((ValueError, TypeError)):
        cli.main(args(item))
    run = runner.read(item['output'] / 'run.json')
    assert run['status'] == 'failed_model_output' and run['model_calls'] == 1
    assert runner.read(item['output'] / 'model_output.json') == raw
    assert not (item['output'] / 'grounding_plan.json').exists()
    assert len([row for row in calls if row[0] == 'call']) == 1


def test_unknown_call_is_not_replayed_in_same_or_new_output_directory(grounding_case, monkeypatch):
    item = grounding_case
    calls = fake_client(monkeypatch, error=ConnectionError, metadata={'error_type': 'APIConnectionError'})
    with pytest.raises(ConnectionError):
        cli.main(args(item))
    run = runner.read(item['output'] / 'run.json')
    assert run['status'] == 'outcome_unknown' and run['model_calls'] == 1
    assert not (item['output'] / 'grounding_plan.json').exists()
    for output in (item['output'], item['target'] / 'another_grounding_output'):
        with pytest.raises((ValueError, FileExistsError)):
            cli.main(args(item, output))
    # Moving identical input to a second same-source run cannot bypass reservation.
    next_target = item['target'].parent / 'grounding_target_after_unknown'
    runner.prepare(next_target, item['source'], 'Synthetic test only', provider='ark_api')
    campaign.attach(next_target, item['campaign'])
    imported = opening.import_opening_frame(next_target, item['failed_run'], item['image'],
        next_target / 'imported_opening', item['config'])
    next_item = {**item, 'target': next_target, 'target_image': Path(imported['image']),
                 'output': next_target / 'grounding_v1'}
    with pytest.raises((ValueError, FileExistsError)):
        cli.main(args(next_item))
    assert len([row for row in calls if row[0] == 'call']) == 1


@pytest.mark.parametrize('file', ['source.json', 'request.json', 'model_output.json', 'response_metadata.json', 'run.json'])
def test_saved_grounding_trace_bytes_cannot_change_after_candidate(grounding_case, monkeypatch, file):
    item = grounding_case
    fake_client(monkeypatch, json.dumps(VALUE, ensure_ascii=False))
    cli.main(args(item))
    path = item['output'] / file
    if file == 'run.json':
        run = runner.read(path); run['model_calls'] = 0
        runner.write(path, run)
    else:
        path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(ValueError):
        grounding.require_grounding(item['target'], item['target_image'],
                                    item['output'] / 'grounding_plan.json', item['config'])


def test_v1_projection_remains_byte_for_byte_and_does_not_need_grounding(case):
    item = case
    before = item['plan_path'].read_bytes()
    review(item)
    prompt, proof = compact.require_compact_execution(item['folder'], item['image'], item['plan_path'],
                                                       item['review_path'], item['config'])
    assert prompt == item['plan']['prompt'] and proof['profile'] == 'compact_execution/v1'
    # Fixed synthetic v1 request hash captured before the new grounding path is used.
    assert item['plan']['prompt_sha256'] == 'b6766cc827b227457d8b896c06c3f6f6d927550703a99131e2072e9640373aaf'
    assert item['plan_path'].read_bytes() == before


@pytest.mark.parametrize('grounding_case', ['different_serialization'], indirect=True)
def test_original_review_serialization_survives_collection_model_and_replay(grounding_case, monkeypatch):
    item = grounding_case
    quality = item['failed_run'] / 'S01.quality_review.json'
    original, history = item['submitted_review'], item['history_review']
    assert runner.sha(original) != runner.sha(quality)
    assert original.read_bytes().endswith(b'\r\n')
    assert runner.read(original) == runner.read(quality) == runner.read(history)
    assert history.name == item['submitted_review_sha256'] + '.json'
    ledger = campaign.read(item['campaign'])['attempts'][-1]
    assert ledger['review_sha256'] == runner.sha(original)
    before = {p: p.read_bytes() for p in (original, quality, history, item['campaign'])}
    source = collect(item)
    for key, path in (('ledger_bound_review', original), ('review', quality), ('review_history', history)):
        assert source['failure'][key] == {'path': str(path.resolve()), 'sha256': runner.sha(path)}
    calls = fake_client(monkeypatch, json.dumps(VALUE, ensure_ascii=False))
    cli.main(args(item))
    value, proof = grounding.require_grounding(item['target'], item['target_image'],
        item['output'] / 'grounding_plan.json', item['config'])
    assert value == VALUE and proof
    assert len([row for row in calls if row[0] == 'call']) == 1
    assert all(path.read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize('grounding_case', ['different_serialization'], indirect=True)
@pytest.mark.parametrize('changed', ['original_missing', 'original_bytes', 'quality_semantics', 'history_semantics'])
def test_serialization_compatibility_still_requires_original_and_equal_copies(grounding_case, changed):
    item = grounding_case
    original = item['submitted_review']
    if changed == 'original_missing':
        original.unlink()
    elif changed == 'original_bytes':
        original.write_bytes(original.read_bytes() + b'\n')
    else:
        path = (item['history_review'] if changed == 'history_semantics'
                else item['failed_run'] / 'S01.quality_review.json')
        report = runner.read(path)
        report['observations'][0]['notes'] = 'Synthetic altered evidence interpretation.'
        runner.write(path, report)
    with pytest.raises((ValueError, FileNotFoundError)):
        collect(item)


@pytest.mark.parametrize('grounding_case', ['different_serialization'], indirect=True)
def test_quality_bytes_are_frozen_after_grounding_candidate(grounding_case, monkeypatch):
    item = grounding_case
    fake_client(monkeypatch, json.dumps(VALUE, ensure_ascii=False))
    cli.main(args(item))
    quality = item['failed_run'] / 'S01.quality_review.json'
    quality.write_bytes(quality.read_bytes() + b'\n')
    # The copies still agree semantically, but the candidate binds actual bytes.
    assert runner.read(quality) == runner.read(item['submitted_review'])
    with pytest.raises(ValueError, match='source|evidence changed'):
        grounding.require_grounding(item['target'], item['target_image'],
            item['output'] / 'grounding_plan.json', item['config'])


@pytest.mark.parametrize('grounding_case', ['different_serialization'], indirect=True)
def test_reviewed_v2_full_runner_submit_keeps_eight_failures_and_exact_request(grounding_case, monkeypatch):
    item = grounding_case
    fake_client(monkeypatch, json.dumps(VALUE, ensure_ascii=False))
    cli.main(args(item))
    output = item['target'] / 'compact_v2/plan.json'
    plan = compact.prepare_compact_execution(item['target'], item['target_image'], output,
        item['config'], grounding_plan=item['output'] / 'grounding_plan.json')
    combined_case = {**item, 'folder': item['target'], 'image': item['target_image'],
        'plan': plan, 'plan_path': output, 'review_path': output.with_name('independent_review.json')}
    review(combined_case)
    before = campaign.read(item['campaign'])
    video_calls = []
    monkeypatch.setattr(SeedanceClient, 'create_task',
        lambda self, payload: video_calls.append(copy.deepcopy(payload)) or {'id': 'synthetic-grounded-video'})
    runner.submit(item['target'], 'S01', SeedanceClient(item['config']), [],
        first_frame=item['target_image'], execution_plan=output, execution_review=combined_case['review_path'])
    record = runner.read(item['target'] / 'S01.json')
    after = campaign.read(item['campaign'])
    assert len(video_calls) == 1 and video_calls[0] == record['request']
    assert record['request']['content'][0]['text'] == plan['prompt']
    assert record['execution_prompt']['profile'] == 'compact_execution/v2'
    assert record['execution_prompt']['grounding'] == plan['grounding']
    assert record['request']['resolution'] == '480p' and record['request']['duration'] == 7
    assert record['request']['generate_audio'] is True and record['request']['return_last_frame'] is True
    assert after['failed_outputs'] == before['failed_outputs'] == 8
    assert after['attempts'][:-1] == before['attempts']
    assert after['attempts'][-1]['status'] == 'awaiting_generation_or_review'
    assert after['attempts'][-1]['series_id'] == 'series_001'
    assert after['attempts'][-1]['upstream_revision']['previous_failed_attempt_id'] == before['attempts'][-1]['id']


def _reject_parent(item):
    runner.write(item['output'] / 'independent_rejection.json', {
        'schema': 'execution_grounding_rejection/v1', 'decision': 'failed',
        'model_output_sha256': runner.sha(item['output'] / 'model_output.json'),
        'request_sha256': runner.sha(item['output'] / 'request.json'),
        'run_sha256': runner.sha(item['output'] / 'run.json'),
        'notes': 'Synthetic independent rejection: constrain paper identity without restating source action.',
        'reviewed_at': '2026-09-11T09:00:00+08:00'})


def _known_parent_revision(item, monkeypatch, *, candidate=False):
    raw = json.dumps(VALUE, ensure_ascii=False) if candidate else '{"visual_bindings":[],"action_constraints":["x"]}'
    calls = fake_client(monkeypatch, raw)
    if candidate:
        cli.main(args(item))
    else:
        with pytest.raises(ValueError):
            cli.main(args(item))
        assert runner.read(item['output'] / 'run.json')['status'] == 'failed_model_output'
        _reject_parent(item)
    feedback = item['output'] / 'actual_feedback.md'
    feedback.write_text('Synthetic repair feedback: 仅明确角色与合同的对应，不重复原动作。', encoding='utf-8')
    output = item['target'] / 'grounding_revision_v2'
    revision_args = args(item, output) + ['--previous-grounding-run', str(item['output']),
                                         '--feedback-file', str(feedback)]
    return calls, feedback, output, revision_args


def test_a4_is_allowed_only_when_present_in_frozen_source_and_renderer_uses_it(case):
    value = {'visual_bindings': ['图片1中角色甲面前的A4合同是P1。'],
             'action_constraints': ['保持原动作接触范围。']}
    assert grounding.validate_model_value(value, '桌上两份A4合同，角色相对而坐。') == value
    for source in (None, '桌上两份合同。', '型号BA4X不表示纸张规格。'):
        with pytest.raises(ValueError):
            grounding.validate_model_value(value, source)
    shot = copy.deepcopy(case['script']['shots'][0])
    with pytest.raises(ValueError):
        compact.render_compact_prompt(shot, '9:16', value)
    shot['start_frame'] += '纸张均为A4。'
    prompt, _ = compact.render_compact_prompt(shot, '9:16', value)
    assert 'A4合同' in prompt and prompt.count(shot['dialogue']) == 1


@pytest.mark.parametrize('only_flag', ['--previous-grounding-run', '--feedback-file'])
def test_parent_revision_arguments_must_be_given_together(grounding_case, monkeypatch, only_flag):
    item = grounding_case
    calls = fake_client(monkeypatch, json.dumps(VALUE, ensure_ascii=False))
    with pytest.raises((ValueError, SystemExit)):
        cli.main(args(item) + [only_flag, str(item['output'])])
    assert not [row for row in calls if row[0] == 'call']


def test_known_failed_model_output_can_receive_one_bound_feedback_revision(grounding_case, monkeypatch):
    item = grounding_case
    first_calls, feedback, output, revision_args = _known_parent_revision(item, monkeypatch)
    before = {path: path.read_bytes() for path in item['output'].rglob('*') if path.is_file()}
    second_calls = fake_client(monkeypatch, json.dumps(VALUE, ensure_ascii=False))
    cli.main(revision_args)
    plan_path = output / 'grounding_plan.json'
    plan = runner.read(plan_path)
    assert 'parent_revision' in plan['source']
    assert feedback.read_text(encoding='utf-8') in json.dumps(runner.read(output / 'request.json'), ensure_ascii=False)
    assert runner.sha(output / 'request.json') != runner.sha(item['output'] / 'request.json')
    assert grounding.require_grounding(item['target'], item['target_image'], plan_path, item['config'])[0] == VALUE
    assert len([row for row in first_calls + second_calls if row[0] == 'call']) == 2
    assert all(path.read_bytes() == raw for path, raw in before.items())


def test_candidate_parent_requires_exact_bound_independent_rejection(grounding_case, monkeypatch):
    item = grounding_case
    _, _, output, revision_args = _known_parent_revision(item, monkeypatch, candidate=True)
    calls = fake_client(monkeypatch, json.dumps(VALUE, ensure_ascii=False))
    with pytest.raises((ValueError, FileNotFoundError)):
        cli.main(revision_args)
    assert not [row for row in calls if row[0] == 'call']
    _reject_parent(item)
    cli.main(revision_args)
    assert grounding.require_grounding(item['target'], item['target_image'],
        output / 'grounding_plan.json', item['config'])[0] == VALUE
    assert len([row for row in calls if row[0] == 'call']) == 1


def test_unknown_parent_cannot_be_retried_using_feedback(grounding_case, monkeypatch):
    item = grounding_case
    calls = fake_client(monkeypatch, error=ConnectionError, metadata={'error_type': 'APIConnectionError'})
    with pytest.raises(ConnectionError):
        cli.main(args(item))
    feedback = item['output'] / 'actual_feedback.md'
    feedback.write_text('Synthetic feedback cannot resolve a provider outcome.', encoding='utf-8')
    with pytest.raises(ValueError):
        cli.main(args(item, item['target'] / 'invalid_unknown_revision') + [
            '--previous-grounding-run', str(item['output']), '--feedback-file', str(feedback)])
    assert len([row for row in calls if row[0] == 'call']) == 1


def test_parent_feedback_bytes_are_frozen_after_revision_candidate(grounding_case, monkeypatch):
    item = grounding_case
    _, feedback, output, revision_args = _known_parent_revision(item, monkeypatch)
    fake_client(monkeypatch, json.dumps(VALUE, ensure_ascii=False))
    cli.main(revision_args)
    feedback.write_bytes(feedback.read_bytes() + b'\n')
    with pytest.raises(ValueError):
        grounding.require_grounding(item['target'], item['target_image'],
            output / 'grounding_plan.json', item['config'])


def test_parent_model_trace_must_keep_its_original_sha_before_revision(grounding_case, monkeypatch):
    item = grounding_case
    _, _, _, revision_args = _known_parent_revision(item, monkeypatch)
    parent_output = item['output'] / 'model_output.json'
    parent_output.write_bytes(parent_output.read_bytes() + b'\n')
    calls = fake_client(monkeypatch, json.dumps(VALUE, ensure_ascii=False))
    with pytest.raises(ValueError):
        cli.main(revision_args)
    assert not [row for row in calls if row[0] == 'call']
