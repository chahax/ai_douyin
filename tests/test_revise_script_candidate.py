"""The short-only candidate tool must preserve the failed long draft and never certify it."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from script_pair_fixture import pair_payload
from test_script_outline import workflow


@pytest.fixture
def case(tmp_path, monkeypatch, workflow):
    spec = importlib.util.spec_from_file_location('candidate_revision_cli',
        Path(__file__).resolve().parents[1] / 'scripts/revise_script_candidate.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / 'project'
    monkeypatch.setattr(module, '__file__', str(root/'scripts/revise_script_candidate.py'))
    folder = root/'data/pre_video_scripts/_runs/baseline'
    folder.mkdir(parents=True)
    source, baseline, feedback = folder/'request.json', folder/'draft_3.json', root/'feedback.md'
    source.write_text(json.dumps(workflow, ensure_ascii=False), encoding='utf-8')
    data = pair_payload()
    # A real structural defect in long must remain untouched and unapproved.
    data['long']['shots'][-1]['end_seconds'] = 181
    baseline.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    feedback.write_bytes('只修短稿\r\n不要凭空出现打印机。'.encode('utf-8'))
    output = root/'data/qa/revision'
    monkeypatch.setattr(module, 'settings', SimpleNamespace(SCRIPT_LLM_MODEL='MiniMax-M3', LLM_MODEL='fallback',
        SCRIPT_LLM_THINKING='disabled', SCRIPT_LLM_TIMEOUT_SECONDS=30, SCRIPT_LLM_MAX_TOKENS=24000))
    monkeypatch.setattr(module.sys, 'argv', ['revise_script_candidate.py', '--workflow-request', str(source),
        '--baseline-draft', str(baseline), '--editor-feedback-file', str(feedback), '--output-dir', str(output),
        '--reference-source-id', 'douyin:0000000000000000000'])
    return SimpleNamespace(module=module, source=source, baseline=baseline, feedback=feedback, output=output,
                           workflow=workflow, data=data)


def client_for(monkeypatch, case, response, *, error=None, provider='fixture'):
    calls = []
    class Client:
        provider_name = provider
        def __init__(self, **kwargs):
            calls.append(('init', kwargs))
            self.provider = SimpleNamespace(last_response_metadata={'local_test': True})
        def chat_completion_tracked(self, messages, **kwargs):
            calls.append(('call', copy.deepcopy(messages), kwargs))
            if error:
                raise error
            return response
    monkeypatch.setattr(case.module, 'LLMClient', Client)
    return calls


def patch(**kwargs):
    return json.dumps({'changes': [{'script': 'short', 'shot_id': 'S01', 'field': 'action',
                                   'value': '把笔放回原来位置，明确本次暂不签字。', **kwargs}]}, ensure_ascii=False)


def test_one_short_patch_freezes_invalid_long_and_saves_exact_pending_candidate(case, monkeypatch):
    raw = json.dumps({'changes': [json.loads(patch())['changes'][0],
        {'script': 'both', 'shot_id': '', 'field': 'core_message', 'value': '本次决定已执行。'}]}, ensure_ascii=False)
    calls = client_for(monkeypatch, case, raw)
    originals = {p: p.read_bytes() for p in (case.source, case.baseline, case.feedback)}
    case.module.main()
    state = json.loads((case.output/'run.json').read_text(encoding='utf-8'))
    candidate = json.loads((case.output/'candidate.json').read_text(encoding='utf-8'))
    assert candidate['long'] == case.data['long']
    assert candidate['long']['shots'][-1]['end_seconds'] == 181
    assert candidate['short']['shots'][1:] == case.data['short']['shots'][1:]
    assert candidate['core_message'] == '本次决定已执行。'
    assert state['status'] == 'candidate_pending_independent_review'
    assert state['short_review_status'] == 'not_reviewed' and state['long_review_status'] == 'unchanged_no_new_approval'
    assert state['shared_core_changed'] is True and state['media_generation'] is False
    assert state['long_original_sha256'] == state['long_candidate_sha256']
    assert 'passed' not in state and 'approved' not in state
    assert state['started_at'].endswith('+08:00') and state['finished_at'].endswith('+08:00')
    assert state['model_calls'] == 1 and len([c for c in calls if c[0] == 'call']) == 1
    sent = json.loads(calls[-1][1][-1]['content'])
    assert list(sent)[-1] == 'current_editor_feedback'
    assert sent['current_editor_feedback'] == case.feedback.read_bytes().decode('utf-8')
    assert sent['current_pair'] == case.data and len(sent['source_overview']) == 20
    assert len(sent['source_evidence']) == 1
    assert sent['source_evidence'][0] == json.loads(case.workflow[1]['content'])['source_evidence'][0]
    assert calls[-1][1][0]['content'].endswith('本轮不生成视频。')
    assert calls[-1][2]['caller'] == 'pre_video_script_candidate_revision' and calls[-1][2]['use_cache'] is False
    assert all(p.read_bytes() == text for p, text in originals.items())
    assert (case.output/'baseline.original.json').read_bytes() == originals[case.baseline]
    assert (case.output/'feedback.md').read_bytes() == originals[case.feedback]
    assert (case.output/'model_patch.json').read_bytes().decode('utf-8') == raw
    assert state['candidate_sha256'] == case.module.text_sha((case.output/'candidate.json').read_bytes().decode('utf-8'))


@pytest.mark.parametrize('failure', ['long', 'new_shot', 'rename_shot', 'unknown_field', 'full_pair', 'invalid_json', 'empty', 'request_error', 'mock'])
def test_failed_patch_never_creates_candidate_or_retries(case, monkeypatch, failure):
    raw = {'long': patch(script='long'), 'new_shot': patch(shot_id='S99'),
        'rename_shot': patch(field='shot_id', value='S99'), 'unknown_field': patch(field='approved', value=True),
        'full_pair': json.dumps(case.data), 'invalid_json': '{broken', 'empty': None}.get(failure, patch())
    calls = client_for(monkeypatch, case, raw, provider='mock' if failure == 'mock' else 'fixture',
        error=RuntimeError('test request failure') if failure == 'request_error' else None)
    with pytest.raises((ValueError, RuntimeError)):
        case.module.main()
    state = json.loads((case.output/'run.json').read_text(encoding='utf-8'))
    assert state['status'] == 'failed' and state['finished_at']
    assert state['media_generation'] is False
    assert not (case.output/'candidate.json').exists()
    assert len([c for c in calls if c[0] == 'call']) <= 1


@pytest.mark.parametrize('defect', ['wrong_directory', 'nineteen', 'unreviewed_unselected', 'unknown_source', 'duplicate_source', 'stale_full'])
def test_input_binding_and_all_twenty_review_gate_fail_before_api(case, monkeypatch, defect):
    calls = client_for(monkeypatch, case, patch())
    args = list(case.module.sys.argv)
    if defect == 'wrong_directory':
        args[args.index('--baseline-draft')+1] = str(case.feedback)
    elif defect in ('unknown_source', 'duplicate_source'):
        args.extend(['--reference-source-id', 'unknown' if defect == 'unknown_source' else 'douyin:0000000000000000000'])
    else:
        workflow = copy.deepcopy(case.workflow); payload = json.loads(workflow[1]['content'])
        if defect == 'nineteen': payload['source_evidence'].pop()
        elif defect == 'unreviewed_unselected': payload['source_evidence'][-1]['independent_review']['decision'] = 'failed'
        else:
            changed = copy.deepcopy(payload['source_evidence']); changed[0]['expression_analysis']['core_message']['text'] = '篡改来源'
            case.source.with_name('source_evidence.full.json').write_text(json.dumps(changed), encoding='utf-8')
        workflow[1]['content'] = json.dumps(payload)
        case.source.write_text(json.dumps(workflow), encoding='utf-8')
    monkeypatch.setattr(case.module.sys, 'argv', args)
    with pytest.raises(ValueError): case.module.main()
    assert calls == [] and not case.output.exists()


def complete_short(case):
    short = copy.deepcopy(case.data['short'])
    for shot in short['shots']:
        shot.pop('camera', None)
        shot['blocking'] = '新稿人物位置。'
        shot['audio'] = '新稿稳定声线及现场环境声。'
        shot['transition'] = '新稿衔接状态。'
    short['premise'] = '新的短稿前提。'
    short['resolution'] = '新的眼前决定已经执行。'
    return {'core_message': '新的共同核心。', 'short': short}


def test_complete_rewrite_replaces_every_short_field_without_sending_or_changing_long(case, monkeypatch):
    rewritten = complete_short(case)
    case.data['short']['legacy_metadata'] = '旧签约状态，不得继承'
    case.baseline.write_text(json.dumps(case.data, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(case.module.sys, 'argv', [*case.module.sys.argv, '--rewrite-short'])
    raw = json.dumps(rewritten, ensure_ascii=False)
    calls = client_for(monkeypatch, case, raw)
    case.module.main()
    candidate = json.loads((case.output/'candidate.json').read_text(encoding='utf-8'))
    assert candidate['short'] == rewritten['short']
    assert candidate['long'] == case.data['long']
    assert 'legacy_metadata' not in candidate['short']
    assert all('camera' not in shot for shot in candidate['short']['shots'])
    sent = json.loads(calls[-1][1][1]['content'])
    assert 'current_pair' not in sent and 'long' not in sent and 'long_seconds' not in sent
    assert sent['current_short'] == case.data['short']
    assert case.data['long']['premise'] not in calls[-1][1][1]['content']
    assert len(sent['source_overview']) == 20 and len(sent['source_evidence']) == 1
    assert list(sent)[-1] == 'current_editor_feedback'
    assert calls[-1][1][0]['content'].startswith(case.module.PROMPT_PATH.read_text(encoding='utf-8'))
    assert calls[-1][1][0]['content'].endswith('本轮不生成视频。')
    state = json.loads((case.output/'run.json').read_text(encoding='utf-8'))
    assert state['revision_mode'] == 'complete_short_replacement'
    assert state['status'] == 'candidate_pending_independent_review' and state['model_calls'] == 1
    assert state['long_original_sha256'] == state['long_candidate_sha256']
    assert state['short_review_status'] == 'not_reviewed' and state['media_generation'] is False
    assert (case.output/'model_rewrite.json').read_text(encoding='utf-8') == raw
    assert not (case.output/'model_patch.json').exists()


@pytest.mark.parametrize('defect', ['changes', 'extra_long', 'missing_metadata', 'missing_audio', 'missing_transition',
                                   'missing_plan_field', 'missing_character_field', 'legacy_camera', 'new_shot', 'renamed_shot'])
def test_complete_rewrite_missing_or_out_of_scope_fields_stop_without_inheritance(case, monkeypatch, defect):
    rewritten = complete_short(case)
    if defect == 'changes': rewritten = json.loads(patch())
    elif defect == 'extra_long': rewritten['long'] = case.data['long']
    elif defect == 'missing_metadata': del rewritten['short']['resolution']
    elif defect == 'missing_audio': del rewritten['short']['shots'][1]['audio']
    elif defect == 'missing_transition': del rewritten['short']['shots'][1]['transition']
    elif defect == 'missing_plan_field': del rewritten['short']['expression_plan']['ending']
    elif defect == 'missing_character_field': del rewritten['short']['characters'][0]['wardrobe']
    elif defect == 'legacy_camera': rewritten['short']['shots'][0]['camera'] = '旧摄影摘要'
    elif defect == 'new_shot': rewritten['short']['shots'].append(copy.deepcopy(rewritten['short']['shots'][0]))
    elif defect == 'renamed_shot': rewritten['short']['shots'][0]['shot_id'] = 'S99'
    monkeypatch.setattr(case.module.sys, 'argv', [*case.module.sys.argv, '--rewrite-short'])
    calls = client_for(monkeypatch, case, json.dumps(rewritten, ensure_ascii=False))
    with pytest.raises(ValueError): case.module.main()
    state = json.loads((case.output/'run.json').read_text(encoding='utf-8'))
    assert state['status'] == 'failed' and state['finished_at']
    assert not (case.output/'candidate.json').exists()
    assert len([call for call in calls if call[0] == 'call']) == 1


def test_rewrite_required_fields_match_current_author_schema(case):
    prompt = case.module.PROMPT_PATH.read_text(encoding='utf-8')
    schema_text = prompt.split('字段全部必填，不输出 Markdown 代码围栏：', 1)[1].lstrip()
    schema, _ = json.JSONDecoder().raw_decode(schema_text)
    assert set(schema) == case.module.SHORT_FIELDS
    assert set(schema['shots'][0]) == case.module.SHOT_FIELDS


def previous_candidate(case):
    folder = case.output.parent/'previous'
    folder.mkdir(parents=True)
    candidate = copy.deepcopy(case.data)
    candidate['core_message'] = '上一候选已经修正的核心'
    candidate['short']['premise'] = '上一候选已经修正的前提'
    candidate['short']['shots'][0]['action'] = '上一候选已删除错误签署，不应退回旧稿。'
    path = folder/'candidate.json'
    path.write_text(json.dumps(candidate, ensure_ascii=False), encoding='utf-8')
    state = {'schema': 'script_candidate_revision_run/v1', 'status': 'candidate_pending_independent_review',
        'candidate_sha256': case.module.text_sha(path.read_bytes().decode('utf-8')),
        'workflow_request_sha256': case.module.text_sha(case.source.read_bytes().decode('utf-8')),
        'baseline_draft_sha256': case.module.text_sha(case.baseline.read_bytes().decode('utf-8'))}
    path.with_name('run.json').write_text(json.dumps(state), encoding='utf-8')
    return path, candidate, state


def test_patch_continues_previous_candidate_without_reverting_or_mutating_originals(case, monkeypatch):
    path, previous, prior_run = previous_candidate(case)
    originals = {p: p.read_bytes() for p in (path, path.with_name('run.json'), case.source, case.baseline)}
    monkeypatch.setattr(case.module.sys, 'argv', [*case.module.sys.argv, '--previous-candidate', str(path)])
    calls = client_for(monkeypatch, case, patch(shot_id='S06', field='audio', value='只修末镜的声音。'))
    case.module.main()
    result = json.loads((case.output/'candidate.json').read_text(encoding='utf-8'))
    assert result['core_message'] == previous['core_message']
    assert result['short']['premise'] == previous['short']['premise']
    assert result['short']['shots'][0] == previous['short']['shots'][0]
    assert result['short']['shots'][-1]['audio'] == '只修末镜的声音。'
    assert result['long'] == case.data['long']
    assert json.loads(calls[-1][1][-1]['content'])['current_pair'] == previous
    state = json.loads((case.output/'run.json').read_text(encoding='utf-8'))
    assert state['status'] == 'candidate_pending_independent_review'
    assert state['previous_candidate']['sha256'] == prior_run['candidate_sha256']
    assert state['previous_candidate']['run_sha256'] == case.module.text_sha(originals[path.with_name('run.json')].decode('utf-8'))
    assert state['baseline_draft_sha256'] == prior_run['baseline_draft_sha256']
    assert state['workflow_request_sha256'] == prior_run['workflow_request_sha256']
    assert state['shared_core_changed'] is False
    assert (case.output/'baseline.original.json').read_bytes() == originals[case.baseline]
    assert (case.output/'previous_candidate.original.json').read_bytes() == originals[path]
    assert all(p.read_bytes() == text for p, text in originals.items())


@pytest.mark.parametrize('defect', ['status', 'schema', 'candidate_sha', 'request_sha', 'baseline_sha', 'long_changed', 'shot_added'])
def test_previous_candidate_binding_or_scope_failure_stops_before_api(case, monkeypatch, defect):
    path, candidate, state = previous_candidate(case)
    if defect == 'status': state['status'] = 'failed'
    elif defect == 'schema': state['schema'] = 'unrelated_tool/v1'
    elif defect == 'candidate_sha': state['candidate_sha256'] = '0'*64
    elif defect == 'request_sha': state['workflow_request_sha256'] = '0'*64
    elif defect == 'baseline_sha': state['baseline_draft_sha256'] = '0'*64
    else:
        if defect == 'long_changed': candidate['long']['resolution'] = '不允许继承被改过的长稿'
        else:
            candidate['short']['shots'].append({**copy.deepcopy(candidate['short']['shots'][-1]), 'shot_id': 'S07'})
        path.write_text(json.dumps(candidate, ensure_ascii=False), encoding='utf-8')
        state['candidate_sha256'] = case.module.text_sha(path.read_bytes().decode('utf-8'))
    path.with_name('run.json').write_text(json.dumps(state), encoding='utf-8')
    monkeypatch.setattr(case.module.sys, 'argv', [*case.module.sys.argv, '--previous-candidate', str(path)])
    calls = client_for(monkeypatch, case, patch())
    with pytest.raises(ValueError): case.module.main()
    assert calls == [] and not case.output.exists()


def test_omit_rejected_short_requires_rewrite_before_any_api(case, monkeypatch):
    monkeypatch.setattr(case.module.sys, 'argv', [*case.module.sys.argv, '--omit-rejected-short'])
    calls = client_for(monkeypatch, case, patch())
    with pytest.raises(ValueError, match='仅可与--rewrite-short'):
        case.module.main()
    assert not calls and not case.output.exists()


@pytest.mark.parametrize('changed_identity', [False, True])
def test_omit_rejected_short_sends_only_role_constraints_and_preserves_local_baseline(case, monkeypatch, changed_identity):
    case.data['short']['characters'].append({**copy.deepcopy(case.data['short']['characters'][0]),
                                           'name': '对方', 'identity': '对方当事人'})
    case.data['core_message'] = '旧共同核心错误句必须不发送'
    case.data['short']['resolution'] = '旧短稿已签归档错误句必须不发送'
    case.data['short']['shots'][0]['action'] = '旧动作凭空重印错误句必须不发送'
    case.data['long']['resolution'] = '长稿私有错误句必须不发送'
    case.baseline.write_text(json.dumps(case.data, ensure_ascii=False), encoding='utf-8')
    original = case.baseline.read_bytes()
    rewritten = complete_short(case)
    if changed_identity:
        rewritten['short']['characters'][0]['identity'] = '新身份不在约束内'
    monkeypatch.setattr(case.module.sys, 'argv', [*case.module.sys.argv, '--rewrite-short', '--omit-rejected-short'])
    calls = client_for(monkeypatch, case, json.dumps(rewritten, ensure_ascii=False))
    if changed_identity:
        with pytest.raises(ValueError, match='name/identity约束'): case.module.main()
    else:
        case.module.main()
    sent = json.loads(calls[-1][1][1]['content'])
    assert 'current_short' not in sent and 'current_core_message' not in sent and 'current_pair' not in sent
    assert '错误句必须不发送' not in calls[-1][1][1]['content']
    assert sent['character_constraints'] == [{'name': c['name'], 'identity': c['identity']} for c in case.data['short']['characters']]
    assert sent['candidate_revision_scope']['required_shot_ids'] == ['S01', 'S02', 'S03', 'S04', 'S05', 'S06']
    assert sent['short_seconds'] == 45 and list(sent)[-1] == 'current_editor_feedback'
    assert len(sent['source_overview']) == 20 and len(sent['source_evidence']) == 1
    assert sent['source_evidence'][0] == json.loads(case.workflow[1]['content'])['source_evidence'][0]
    assert case.baseline.read_bytes() == original
    assert (case.output/'baseline.original.json').read_bytes() == original
    state = json.loads((case.output/'run.json').read_text(encoding='utf-8'))
    assert state['rejected_short_sent_to_model'] is False and state['model_calls'] == 1
    if changed_identity:
        assert state['status'] == 'failed' and not (case.output/'candidate.json').exists()
    else:
        candidate = json.loads((case.output/'candidate.json').read_text(encoding='utf-8'))
        assert candidate['short'] == rewritten['short'] and candidate['long'] == case.data['long']
        assert state['status'] == 'candidate_pending_independent_review'
