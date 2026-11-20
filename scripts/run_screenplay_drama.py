"""Optional drama draft/revise/state stages; no media or automatic approval."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.revise_script_candidate import _source_input
from scripts.run_screenplay_stage import now, sha, read_related_story
from src.shared.config import settings
from src.shared.llm_client import LLMClient
from src.trend_intelligence.script_outline import build_outline_messages
from src.trend_intelligence.script_drama import (
    validate_drama, merge_drama_states, validate_revision_fields, apply_drama_revision,
    validate_state_revision_fields, apply_state_revision,
)

MAX_DRAMA_LINEAGE = 64


def _bound_identity(value, label):
    if (not isinstance(value, dict) or set(value) != {'path', 'sha256', 'run_path', 'run_sha256'}
            or any(not isinstance(value.get(key), str) or not value[key]
                   for key in ('path', 'run_path', 'sha256', 'run_sha256'))
            or any(len(value[key]) != 64 or any(c not in '0123456789abcdef' for c in value[key])
                   for key in ('sha256', 'run_sha256'))):
        raise ValueError(label + ': exact path and byte SHA provenance required')
    return value


def parse_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('JSON contains duplicate key: ' + key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def read_artifact(value):
    path = Path(value).resolve()
    path.relative_to(ROOT / 'data')
    raw = path.read_bytes()
    return path, raw, parse_json(raw)


def read_drama(value, kind, duration, *, workflow_sha, source_sha, sources,
               reference_source_ids, expected_run_sha='', _lineage=()):
    candidate_path = Path(value).resolve()
    if candidate_path in _lineage:
        raise ValueError('drama revision lineage cycle detected')
    if len(_lineage) >= MAX_DRAMA_LINEAGE:
        raise ValueError('drama revision lineage exceeds bounded depth')
    path, raw, data = read_artifact(value)
    run_path, run_raw, run = read_artifact(path.with_name('run.json'))
    if (path.name != 'drama.json' or not isinstance(run, dict)
            or run.get('schema') != 'script_screenplay_stage_run/v1'
            or run.get('pipeline') != 'drama_then_state/v1'
            or run.get('stage') not in ('draft', 'revise') or run.get('kind') != kind
            or run.get('status') != 'candidate_pending_independent_review'
            or run.get('candidate_sha256') != sha(raw)
            or run.get('workflow_request_sha256') != workflow_sha
            or run.get('source_evidence_sha256') != source_sha
            or run.get('reference_source_ids') != list(reference_source_ids)
            or (expected_run_sha and expected_run_sha != sha(run_raw))):
        raise ValueError('drama must be the completed, exactly bound draft/revise from this workflow, source batch and selection')
    companion, companion_identity = None, None
    inputs = run.get('inputs')
    if not isinstance(inputs, dict):
        raise ValueError('draft input provenance is missing')
    if run['stage'] == 'revise':
        previous = inputs.get('drama')
        if (run.get('unchanged_fields_preserved') is not True
                or run.get('revision_after_sha256') != sha(raw)
                or not isinstance(previous, dict)
                or set(previous) != {'path', 'sha256', 'run_path', 'run_sha256'}
                or any(not isinstance(previous.get(key), str) or not previous[key]
                       for key in ('path', 'run_path', 'sha256', 'run_sha256'))
                or any(len(previous[key]) != 64 or any(c not in '0123456789abcdef' for c in previous[key])
                       for key in ('sha256', 'run_sha256'))
                or run.get('revision_before_sha256') != previous.get('sha256')):
            raise ValueError('revise candidate lacks exact before/after provenance')
        validate_revision_fields(data, run.get('allowed_revision_fields'))
        _, revision_raw, revision = read_artifact(path.with_name('revision.json'))
        if (run.get('revision_output_sha256') != sha(revision_raw)
                or not isinstance(revision, dict)
                or set(revision) != set(run['allowed_revision_fields'])
                or any(not isinstance(value, str) or not value.strip() for value in revision.values())):
            raise ValueError('revise candidate has changed or invalid revision evidence')
        # A self-reported after SHA is not proof that frozen text stayed intact.
        # Reopen the exact parent and its run, recurse to the original draft,
        # then replay only the saved allowed patch and compare the entire value.
        parent, parent_identity, parent_companion, parent_companion_identity = read_drama(
            previous['path'], kind, duration, workflow_sha=workflow_sha, source_sha=source_sha,
            sources=sources, reference_source_ids=reference_source_ids,
            expected_run_sha=previous['run_sha256'], _lineage=(*_lineage, path))
        if parent_identity != previous:
            raise ValueError('drama revision parent path or bytes differ from recorded provenance')
        if inputs.get('companion_screenplay') != parent_companion_identity:
            raise ValueError('drama revision cannot replace or drop the original companion')
        replay = apply_drama_revision(parent, revision, run['allowed_revision_fields'], kind, duration,
                                      sources, reference_source_ids, parent_companion)
        if replay != data:
            raise ValueError('drama revision replay differs from candidate; frozen fields changed')
    if 'companion_screenplay' in inputs:
        original = inputs['companion_screenplay']
        if not isinstance(original, dict) or not isinstance(original.get('path'), str):
            raise ValueError('draft companion provenance is invalid')
        other = 'short' if kind == 'long' else 'long'
        companion, companion_identity = read_related_story(original['path'], other, 45 if other == 'short' else 180,
            workflow_sha=workflow_sha, source_sha=source_sha, sources=sources)
        if companion_identity != original:
            raise ValueError('draft companion or its run bytes have changed')
    validate_drama(data, kind, duration, sources, reference_source_ids, companion)
    return data, {'path': str(path), 'sha256': sha(raw),
                  'run_path': str(run_path), 'run_sha256': sha(run_raw)}, companion, companion_identity


def read_state_screenplay(value, kind, duration, *, workflow_sha, source_sha, sources,
                          reference_source_ids, expected_run_sha='', _lineage=()):
    """Replay complete state ancestry back to its exact original drama input."""
    candidate_path = Path(value).resolve()
    if candidate_path in _lineage:
        raise ValueError('state revision lineage cycle detected')
    if len(_lineage) >= MAX_DRAMA_LINEAGE:
        raise ValueError('state revision lineage exceeds bounded depth')
    path, raw, data = read_artifact(value)
    run_path, run_raw, run = read_artifact(path.with_name('run.json'))
    if (path.name != 'screenplay.json' or not isinstance(run, dict)
            or run.get('schema') != 'script_screenplay_stage_run/v1'
            or run.get('pipeline') != 'drama_then_state/v1' or run.get('stage') not in ('state', 'state-revise')
            or run.get('kind') != kind or run.get('status') != 'candidate_pending_independent_review'
            or run.get('candidate_sha256') != sha(raw)
            or run.get('workflow_request_sha256') != workflow_sha
            or run.get('source_evidence_sha256') != source_sha
            or run.get('reference_source_ids') != list(reference_source_ids)
            or (expected_run_sha and sha(run_raw) != expected_run_sha)
            or not isinstance(run.get('inputs'), dict)):
        raise ValueError('state screenplay must match its completed run, workflow and source batch')
    inputs = run['inputs']
    recorded_drama = _bound_identity(inputs.get('drama'), 'state original drama')
    drama, drama_identity, companion, companion_identity = read_drama(
        recorded_drama['path'], kind, duration, workflow_sha=workflow_sha, source_sha=source_sha,
        sources=sources, reference_source_ids=reference_source_ids,
        expected_run_sha=recorded_drama['run_sha256'])
    if (recorded_drama != drama_identity or run.get('frozen_drama_sha256') != drama_identity['sha256']
            or inputs.get('companion_screenplay') != companion_identity):
        raise ValueError('state screenplay changed original drama or companion binding')
    if run['stage'] == 'state':
        _, states_raw, states = read_artifact(path.with_name('states.json'))
        if run.get('state_output_sha256') != sha(states_raw) or run.get('frozen_drama_preserved') is not True:
            raise ValueError('state screenplay has stale state output or missing freeze provenance')
        replay = merge_drama_states(drama, states, kind, duration, sources, reference_source_ids, companion)
    else:
        previous = _bound_identity(inputs.get('screenplay'), 'state revision parent')
        if (run.get('non_state_fields_preserved') is not True
                or run.get('state_revision_before_sha256') != previous['sha256']
                or run.get('state_revision_after_sha256') != sha(raw)):
            raise ValueError('state revision before/after provenance is invalid')
        parent, parent_identity, _, parent_drama_identity, _, parent_companion_identity = read_state_screenplay(
            previous['path'], kind, duration, workflow_sha=workflow_sha, source_sha=source_sha,
            sources=sources, reference_source_ids=reference_source_ids,
            expected_run_sha=previous['run_sha256'], _lineage=(*_lineage, path))
        if (previous != parent_identity or parent_drama_identity != drama_identity
                or parent_companion_identity != companion_identity):
            raise ValueError('state revision parent bytes or inherited bindings changed')
        _, revision_raw, revision = read_artifact(path.with_name('state_revision.json'))
        if run.get('state_revision_output_sha256') != sha(revision_raw):
            raise ValueError('state revision evidence bytes changed')
        replay = apply_state_revision(parent, revision, run.get('allowed_revision_fields'), kind, duration,
                                      sources, reference_source_ids, companion)
    if replay != data:
        raise ValueError('state revision replay differs from candidate; frozen or unauthorized fields changed')
    return data, {'path': str(path), 'sha256': sha(raw), 'run_path': str(run_path), 'run_sha256': sha(run_raw)}, \
        drama, drama_identity, companion, companion_identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workflow-request', required=True)
    parser.add_argument('--editor-feedback-file', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--kind', choices=('short', 'long'), required=True)
    parser.add_argument('--stage', choices=('draft', 'revise', 'state', 'state-revise'), required=True)
    parser.add_argument('--reference-source-id', action='append', default=[])
    parser.add_argument('--companion-screenplay', default='')
    parser.add_argument('--drama', default='')
    parser.add_argument('--drama-run-sha256', default='')
    parser.add_argument('--screenplay', default='')
    parser.add_argument('--revise-field', action='append', default=[])
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    output.relative_to(ROOT / 'data')
    output.mkdir(parents=True, exist_ok=False)
    def save(name, value):
        raw = value if isinstance(value, bytes) else (
            value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)).encode('utf-8')
        (output / name).write_bytes(raw)
        return sha(raw)
    state = {'schema': 'script_screenplay_stage_run/v1', 'pipeline': 'drama_then_state/v1',
             'stage': args.stage, 'kind': args.kind, 'status': 'preflight', 'started_at_bjt': now(),
             'workflow_request_path': str(Path(args.workflow_request).resolve()),
             'reference_source_ids': args.reference_source_id, 'inputs': {},
             'model_calls': 0, 'media_generation': False, 'automatic_editorial_approval': False}
    try:
        save('run.json', state)
        if args.stage == 'draft' and (args.drama or args.drama_run_sha256):
            raise ValueError('draft does not accept state-stage drama inputs')
        if args.stage in ('state', 'revise') and (not args.drama or args.companion_screenplay):
            raise ValueError('state/revise requires --drama and inherits its original companion; cannot replace companion')
        if args.stage == 'state-revise' and (not args.screenplay or args.drama or args.drama_run_sha256 or args.companion_screenplay):
            raise ValueError('state-revise requires only --screenplay; original drama and companion are inherited')
        if args.stage != 'state-revise' and args.screenplay:
            raise ValueError('--screenplay is only accepted by state-revise')
        if (args.stage in ('revise', 'state-revise')) != bool(args.revise_field):
            raise ValueError('revise requires --revise-field; other stages cannot accept revision fields')
        workflow_path, workflow_raw, workflow = read_artifact(args.workflow_request)
        workflow_path.relative_to(ROOT / 'data/pre_video_scripts/_runs')
        if workflow_path.name != 'request.json':
            raise ValueError('须使用原项目工作流 request.json')
        state['workflow_request_sha256'] = save('workflow_request.original.json', workflow_raw)
        workflow, full_text = _source_input(workflow, workflow_path.with_name('source_evidence.full.json'))
        full_sources = parse_json(workflow[1]['content'])['source_evidence']
        if full_text is None:
            full_text = json.dumps(full_sources, ensure_ascii=False, indent=2)
        full_raw = full_text.encode('utf-8')
        state['source_evidence_sha256'] = save('source_evidence.full.json', full_raw)
        feedback_path = Path(args.editor_feedback_file).resolve()
        feedback_raw = feedback_path.read_bytes()
        feedback = feedback_raw.decode('utf-8')
        state['feedback_sha256'] = save('feedback.md', feedback_raw)
        state['inputs']['editor_feedback'] = {'path': str(feedback_path), 'sha256': sha(feedback_raw)}
        messages = build_outline_messages(workflow, feedback, reference_source_ids=args.reference_source_id)
        evidence = parse_json(messages[1]['content'])
        evidence['kind'] = args.kind
        duration = evidence['duration_seconds'] = evidence[f'{args.kind}_seconds']
        companion = None
        if args.stage == 'draft':
            if args.companion_screenplay:
                other = 'short' if args.kind == 'long' else 'long'
                companion, identity = read_related_story(args.companion_screenplay, other, evidence[f'{other}_seconds'],
                    workflow_sha=sha(workflow_raw), source_sha=sha(full_raw), sources=full_sources)
                # Keep the complete artifact for post-validation and SHA binding,
                # but avoid teaching the author to stretch the companion's shots.
                evidence['companion_screenplay'] = {
                    'core_message': companion['core_message'],
                    'characters': companion['characters'],
                    'version': {key: companion['version'][key] for key in
                                ('premise', 'dramatic_question', 'resolution')},
                    f'{other}_shot_count': len(companion['version']['shots']),
                }
                state['companion_author_context'] = {
                    'mode': 'shared_core_characters_and_version_summary/v1',
                    'full_artifact_retained_for_local_validation': True,
                    'sent_version_fields': ['premise', 'dramatic_question', 'resolution'],
                    'shot_actions_dialogue_and_states_sent': False,
                }
                state['inputs']['companion_screenplay'] = identity
            prompt_name = 'script_drama.md'
        elif args.stage == 'state-revise':
            screenplay, identity, drama, drama_identity, companion, companion_identity = read_state_screenplay(
                args.screenplay, args.kind, duration, workflow_sha=sha(workflow_raw), source_sha=sha(full_raw),
                sources=full_sources, reference_source_ids=args.reference_source_id)
            state['inputs'].update(screenplay=identity, drama=drama_identity)
            if companion_identity:
                state['inputs']['companion_screenplay'] = companion_identity
            state['frozen_drama_sha256'] = drama_identity['sha256']
            state['state_revision_before_sha256'] = identity['sha256']
            fields = validate_state_revision_fields(screenplay, args.revise_field)
            state['allowed_revision_fields'] = list(fields)
            evidence['screenplay'] = screenplay
            evidence['allowed_revision_fields'] = list(fields)
            prompt_name = 'script_drama_state_revision.md'
        else:
            drama, identity, companion, companion_identity = read_drama(args.drama, args.kind, duration,
                workflow_sha=sha(workflow_raw), source_sha=sha(full_raw), sources=full_sources,
                reference_source_ids=args.reference_source_id, expected_run_sha=args.drama_run_sha256)
            state['inputs']['drama'] = identity
            if companion_identity:
                state['inputs']['companion_screenplay'] = companion_identity
            evidence['drama'] = drama
            if args.stage == 'revise':
                fields = validate_revision_fields(drama, args.revise_field)
                evidence['allowed_revision_fields'] = list(fields)
                state['allowed_revision_fields'] = list(fields)
                state['revision_before_sha256'] = identity['sha256']
                prompt_name = 'script_drama_revision.md'
            else:
                state['frozen_drama_sha256'] = identity['sha256']
                # Explicit invocation requests state expansion, not approval.
                state['state_expansion_requested_explicitly'] = True
                prompt_name = 'script_drama_state.md'
        evidence['current_editor_feedback'] = evidence.pop('current_editor_feedback')
        prompt_path = ROOT / 'src/trend_intelligence/prompts' / prompt_name
        prompt_raw = prompt_path.read_bytes()
        messages = [{'role': 'system', 'content': prompt_raw.decode('utf-8')},
                    {'role': 'user', 'content': json.dumps(evidence, ensure_ascii=False)}]
        state['request_sha256'] = save('request.json', messages)
        state['prompt_sha256'] = save('prompt.md', prompt_raw)
        model = settings.SCRIPT_LLM_MODEL or settings.LLM_MODEL
        thinking = settings.SCRIPT_LLM_THINKING
        extra = None
        if thinking:
            if model.lower() != 'minimax-m3' or thinking not in ('adaptive', 'disabled'):
                raise ValueError('当前 thinking 只允许 M3 disabled/adaptive')
            extra = {'thinking': {'type': thinking}, 'reasoning_split': True}
        client = LLMClient(model=model, extra_body=extra, timeout_seconds=settings.SCRIPT_LLM_TIMEOUT_SECONDS,
                           max_retries=0, max_tokens=settings.SCRIPT_LLM_MAX_TOKENS, preserve_invalid_json=True)
        if client.provider_name == 'mock':
            raise ValueError('不允许模拟模型')
        state.update(model=model, thinking=thinking, max_output_tokens=settings.SCRIPT_LLM_MAX_TOKENS,
                     timeout_seconds=settings.SCRIPT_LLM_TIMEOUT_SECONDS, temperature=0.4,
                     provider=client.provider_name, status='running', model_calls=1)
        save('run.json', state)
        try:
            raw = client.chat_completion_tracked(messages, caller=f'pre_video_drama_{args.stage}',
                temperature=0.4, json_mode=True, use_cache=False)
        finally:
            state['response_metadata_sha256'] = save('response.json',
                getattr(client.provider, 'last_response_metadata', {}))
        state['model_output_sha256'] = save('model_output.json', raw or 'null')
        if not raw:
            raise RuntimeError('模型未返回可用内容；不自动重试')
        result = parse_json(raw)
        if args.stage == 'draft':
            validate_drama(result, args.kind, duration, full_sources, args.reference_source_id, companion)
            from src.trend_intelligence.dramatic_pacing import require_new_draft_pacing
            state['dramatic_pacing_sha256'] = save('dramatic_pacing.json', require_new_draft_pacing(result, args.kind))
            state['candidate_sha256'] = save('drama.json', result)
        elif args.stage == 'revise':
            state['revision_output_sha256'] = save('revision.json', result)
            merged = apply_drama_revision(drama, result, fields, args.kind, duration, full_sources,
                                         args.reference_source_id, companion)
            state['candidate_sha256'] = save('drama.json', merged)
            state['revision_after_sha256'] = state['candidate_sha256']
            state['unchanged_fields_preserved'] = True
        elif args.stage == 'state-revise':
            state['state_revision_output_sha256'] = save('state_revision.json', result)
            merged = apply_state_revision(screenplay, result, fields, args.kind, duration, full_sources,
                                          args.reference_source_id, companion)
            state['candidate_sha256'] = save('screenplay.json', merged)
            state['state_revision_after_sha256'] = state['candidate_sha256']
            state['non_state_fields_preserved'] = True
        else:
            state['state_output_sha256'] = save('states.json', result)
            merged = merge_drama_states(drama, result, args.kind, duration, full_sources,
                                       args.reference_source_id, companion)
            state['candidate_sha256'] = save('screenplay.json', merged)
            state['frozen_drama_preserved'] = True
        state['status'] = 'candidate_pending_independent_review'
    except Exception as exc:
        state.update(status='failed' if state['model_calls'] else 'preflight_rejected',
                     error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        state['finished_at_bjt'] = now()
        save('run.json', state)
    print(json.dumps(state, ensure_ascii=False))


if __name__ == '__main__':
    main()
