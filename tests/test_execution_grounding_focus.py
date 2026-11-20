"""Offline terminal-attention regressions; all model/video calls are synthetic mocks."""
import copy
import json
from pathlib import Path

import pytest

from scripts import run_script_video as runner, revise_execution_grounding as cli
from src.content_factory import ark_opening_frame as opening, compact_execution as compact
from src.content_factory import execution_grounding as grounding, video_campaign as campaign
from src.content_factory.seedance_client import SeedanceClient
from test_execution_grounding import (grounding_case, prepared, case, staged, retry_case,
    fake_client, args, VALUE, review, generated_review, _reject_parent)


TERMINAL_VALUE = {'visual_bindings': copy.deepcopy(VALUE['visual_bindings']),
    'action_constraints': ['片尾角色乙看角色甲所持合同，角色甲保持指向自己的合同。']}


@pytest.fixture
def terminal_case(grounding_case, monkeypatch):
    """Submit an actually bound synthetic v2, record failure nine, then import to a fresh run."""
    item = grounding_case
    fake_client(monkeypatch, json.dumps(VALUE, ensure_ascii=False))
    cli.main(args(item))
    execution_path = item['target'] / 'compact_v2/plan.json'
    execution = compact.prepare_compact_execution(item['target'], item['target_image'], execution_path,
        item['config'], grounding_plan=item['output'] / 'grounding_plan.json')
    combined = {**item, 'folder': item['target'], 'image': item['target_image'],
        'plan': execution, 'plan_path': execution_path,
        'review_path': execution_path.with_name('independent_review.json')}
    review(combined)
    video_calls = []
    monkeypatch.setattr(SeedanceClient, 'create_task',
        lambda self, payload: video_calls.append(copy.deepcopy(payload)) or {'id': 'synthetic-before-terminal-focus'})
    runner.submit(item['target'], 'S01', SeedanceClient(item['config']), [], first_frame=item['target_image'],
        execution_plan=execution_path, execution_review=combined['review_path'])
    record = runner.read(item['target'] / 'S01.json')
    report_path = generated_review(item['target'], record, False)
    report = runner.read(report_path)
    report['checks'].update(props_and_hands=True, cut_continuity=False,
        speaker_voice=None, lip_sync=None, dialogue_pace=None)
    report['observations'] = [row for row in report['observations'] if report['checks'][row['check']] is not None]
    for row in report['observations']:
        if row['check'] == 'cut_continuity':
            row.update(time_seconds=5.9, notes='Synthetic terminal mismatch: 角色乙片尾未看角色甲的合同。')
    runner.write(report_path, report)
    assert campaign.review(item['target'], 'S01', report_path)['failed_outputs'] == 9
    assert len(video_calls) == 1
    target = item['target'].parent / 'terminal_focus_target'
    runner.prepare(target, item['source'], 'Synthetic test only', provider='ark_api')
    campaign.attach(target, item['campaign'])
    # Import from the actual original, never from the preceding imported copy.
    imported = opening.import_opening_frame(target, item['failed_run'], item['image'],
        target / 'imported_opening', item['config'])
    return {**item, 'previous_run': item['target'], 'previous_image': item['target_image'],
        'previous_execution': execution, 'previous_execution_path': execution_path,
        'previous_execution_review': combined['review_path'], 'previous_grounding_dir': item['output'],
        'previous_record': runner.read(item['target'] / 'S01.json'),
        'target': target, 'target_image': Path(imported['image']),
        'failed_run': item['target'], 'output': target / 'terminal_grounding_v1'}


def collect(item):
    return grounding.collect_grounding_source(item['target'], item['target_image'],
        item['failed_run'], item['config'], focus='terminal-attention')


def focused_args(item):
    return args(item) + ['--focus', 'terminal-attention']


def test_terminal_focus_uses_actual_execution_without_obsolete_live_failure_gate(terminal_case):
    item = terminal_case
    before = {path: path.read_bytes() for path in item['previous_run'].rglob('*') if path.is_file()}
    # Its old grounding correctly cannot be newly submitted against failure nine.
    with pytest.raises(ValueError):
        compact.require_compact_execution(item['previous_run'], item['previous_image'],
            item['previous_execution_path'], item['previous_execution_review'], item['config'])
    source = collect(item)
    assert source['focus']['schema'] == 'execution_grounding_focus/v1'
    assert source['focus']['name'] == 'terminal-attention'
    previous = source['previous_actual_execution']
    assert previous['prompt'] == item['previous_record']['request']['content'][0]['text']
    assert previous['prompt_sha256'] == item['previous_record']['prompt_sha256']
    assert previous['visual_bindings'] == item['previous_execution']['grounding_text']['visual_bindings']
    for key, path in (('plan', item['previous_execution_path']), ('review', item['previous_execution_review']),
                      ('record', item['previous_run'] / 'S01.json')):
        assert previous[key] == {'path': str(path.resolve()), 'sha256': runner.sha(path)}
    messages = grounding.build_messages(source)
    assert messages[0]['content'] == grounding.TERMINAL_SYSTEM_PROMPT
    assert messages[0]['content'] != grounding.SYSTEM_PROMPT
    assert 'action_constraints只针对已观察失败澄清原动作的持续接触、不可换纸等限制' not in messages[0]['content']
    user_input = json.loads(messages[1]['content'])
    assert user_input['previous_actual_execution']['prompt'] == previous['prompt']
    assert user_input['previous_actual_execution']['visual_bindings'] == previous['visual_bindings']
    assert 'https://' not in messages[1]['content']
    assert all(path.read_bytes() == raw for path, raw in before.items())
    default = grounding.collect_grounding_source(item['target'], item['target_image'], item['failed_run'], item['config'])
    assert 'focus' not in default and 'previous_actual_execution' not in default
    assert grounding.build_messages(default)[0]['content'] == grounding.SYSTEM_PROMPT


def test_terminal_model_keeps_visual_binding_and_requires_new_execution_review(terminal_case, monkeypatch):
    item = terminal_case
    before = {path: path.read_bytes() for path in item['previous_run'].rglob('*') if path.is_file()}
    calls = fake_client(monkeypatch, json.dumps(TERMINAL_VALUE, ensure_ascii=False))
    cli.main(focused_args(item))
    grounding_path = item['output'] / 'grounding_plan.json'
    value, proof = grounding.require_grounding(item['target'], item['target_image'], grounding_path, item['config'])
    assert value == TERMINAL_VALUE and proof
    assert proof['focus']['name'] == 'terminal-attention'
    assert len([row for row in calls if row[0] == 'call']) == 1
    user_input = json.loads(calls[1][1][1]['content'])
    assert user_input['previous_actual_execution']['prompt'] == item['previous_record']['prompt']
    assert user_input['previous_actual_execution']['visual_bindings'] == VALUE['visual_bindings']
    execution_path = item['target'] / 'terminal_execution/plan.json'
    execution = compact.prepare_compact_execution(item['target'], item['target_image'], execution_path,
        item['config'], grounding_plan=grounding_path)
    assert execution['text_review'] == execution['media_review'] == 'pending'
    assert execution['grounding_text']['visual_bindings'] == VALUE['visual_bindings']
    assert execution['grounding']['focus'] == proof['focus']
    assert '原末态注意力与接触：' in execution['prompt']
    assert '原动作接触范围：' not in execution['prompt']
    assert execution['prompt'].count(item['script']['shots'][0]['dialogue']) == 1
    monkeypatch.setattr(SeedanceClient, 'create_task', lambda *a, **kw: pytest.fail('Unreviewed terminal plan called API'))
    with pytest.raises(FileNotFoundError):
        runner.submit(item['target'], 'S01', SeedanceClient(item['config']), [], first_frame=item['target_image'],
            execution_plan=execution_path, execution_review=execution_path.with_name('independent_review.json'))
    assert campaign.read(item['campaign'])['failed_outputs'] == 9
    assert not (item['target'] / 'S01.json').exists()
    assert all(path.read_bytes() == raw for path, raw in before.items())


def test_terminal_output_cannot_rewrite_previously_executed_visual_bindings(terminal_case, monkeypatch):
    item = terminal_case
    value = copy.deepcopy(TERMINAL_VALUE)
    value['visual_bindings'] = ['角色乙在左，角色甲在右。']
    calls = fake_client(monkeypatch, json.dumps(value, ensure_ascii=False))
    with pytest.raises(ValueError):
        cli.main(focused_args(item))
    run = runner.read(item['output'] / 'run.json')
    assert run['status'] == 'failed_model_output' and run['model_calls'] == 1
    assert not (item['output'] / 'grounding_plan.json').exists()
    assert len([row for row in calls if row[0] == 'call']) == 1
    # A known rejected focus candidate may be revised, but its parent guidance
    # must remain terminal-specific rather than falling back to hand-only rules.
    _reject_parent(item)
    feedback = item['output'] / 'terminal_feedback.md'
    feedback.write_text('Synthetic terminal feedback: 保留上一版人物与纸张对应，只澄清源末态。', encoding='utf-8')
    revision_source = grounding.collect_grounding_source(item['target'], item['target_image'],
        item['failed_run'], item['config'], focus='terminal-attention',
        previous_grounding_run=item['output'], feedback_file=feedback)
    assert revision_source['parent_revision']['revision_guidance'] == grounding.TERMINAL_GUIDANCE
    assert revision_source['parent_revision']['revision_guidance'] != grounding.REVISION_GUIDANCE
    revision_messages = grounding.build_messages(revision_source)
    assert revision_messages[0]['content'] == grounding.TERMINAL_SYSTEM_PROMPT
    revision_user = json.loads(revision_messages[1]['content'])
    assert revision_user['previous_grounding_revision']['revision_guidance'] == grounding.TERMINAL_GUIDANCE


@pytest.mark.parametrize('changed', ['plan', 'review', 'grounding_output', 'actual_payload'])
def test_terminal_source_rejects_changed_historical_execution_proof(terminal_case, changed):
    item = terminal_case
    if changed == 'actual_payload':
        path = item['previous_run'] / 'S01.json'
        record = runner.read(path)
        record['request']['duration'] = 15
        runner.write(path, record)
    else:
        path = {'plan': item['previous_execution_path'], 'review': item['previous_execution_review'],
                'grounding_output': item['previous_grounding_dir'] / 'model_output.json'}[changed]
        path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(ValueError):
        collect(item)


@pytest.mark.parametrize('guard', ['ten_failures', 'unknown'])
def test_terminal_focus_never_clears_failure_cap_or_outstanding_work(terminal_case, monkeypatch, guard):
    item = terminal_case
    data = campaign.read(item['campaign'])
    if guard == 'ten_failures':
        data['failed_outputs'] = 10
    else:
        data['attempts'].append({'id': 'synthetic_unknown', 'shot': 'S01', 'series_id': 'series_001',
            'status': 'awaiting_generation_or_review'})
    campaign.write(item['campaign'], data)
    before = item['campaign'].read_bytes()
    calls = fake_client(monkeypatch, json.dumps(TERMINAL_VALUE, ensure_ascii=False))
    with pytest.raises(ValueError):
        cli.main(focused_args(item))
    assert not [row for row in calls if row[0] == 'call']
    assert item['campaign'].read_bytes() == before


def test_historical_terminal_execution_replays_at_cap_without_reopening_generation(terminal_case, monkeypatch):
    item = terminal_case
    current_source = collect(item)
    fake_client(monkeypatch, json.dumps(TERMINAL_VALUE, ensure_ascii=False))
    cli.main(focused_args(item))
    execution_path = item['target'] / 'terminal_execution/plan.json'
    execution = compact.prepare_compact_execution(item['target'], item['target_image'], execution_path,
        item['config'], grounding_plan=item['output'] / 'grounding_plan.json')
    combined = {**item, 'folder': item['target'], 'image': item['target_image'],
        'plan': execution, 'plan_path': execution_path,
        'review_path': execution_path.with_name('independent_review.json')}
    review(combined)
    video_calls = []
    monkeypatch.setattr(SeedanceClient, 'create_task',
        lambda self, payload: video_calls.append(copy.deepcopy(payload)) or {'id': 'synthetic-terminal-history'})
    runner.submit(item['target'], 'S01', SeedanceClient(item['config']), [], first_frame=item['target_image'],
        execution_plan=execution_path, execution_review=combined['review_path'])
    record = runner.read(item['target'] / 'S01.json')
    review_path = generated_review(item['target'], record, False)
    assert campaign.review(item['target'], 'S01', review_path)['failed_outputs'] == 10
    record = runner.read(item['target'] / 'S01.json')
    attempt = campaign.read(item['campaign'])['attempts'][-1]
    assert attempt['status'] == 'failed' and len(video_calls) == 1
    before = {path: path.read_bytes() for path in item['target'].parent.rglob('*') if path.is_file()}
    # Historical replay reads what was actually submitted, including its focus.
    historical = grounding._recorded_execution(item['target'], record, attempt, item['config'], current_source)
    assert historical['prompt'] == record['request']['content'][0]['text'] == execution['prompt']
    assert '原末态注意力与接触：' in historical['prompt']
    assert '原动作接触范围：' not in historical['prompt']
    assert historical['grounding']['focus'] == execution['grounding']['focus']
    assert historical['grounding']['focus']['name'] == 'terminal-attention'
    assert all(path.read_bytes() == raw for path, raw in before.items())
    # Reading historical proof never resets the ledger or grants generation.
    with pytest.raises(ValueError, match='limit|failure|hold'):
        collect(item)
    assert campaign.read(item['campaign'])['failed_outputs'] == 10
    changed = copy.deepcopy(record)
    del changed['execution_prompt']['grounding']['focus']
    with pytest.raises(ValueError):
        grounding._recorded_execution(item['target'], changed, attempt, item['config'], current_source)
    assert all(path.read_bytes() == raw for path, raw in before.items())
