"""Prepare and author the evidence-led narrative workflow; never submit video."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.trend_intelligence.narrative_workflow import (
    STAGES, digest, identity, verify_file, read, validate_reference, validate_candidate,
    review_template, require_review, media_handoff_report, expand_script_delta,
)
from src.trend_intelligence.narrative_sources import verify_workflow_sources
from scripts.revise_script_candidate import _source_input


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def new_output(path):
    path = Path(path).resolve()
    path.relative_to(ROOT / 'data')
    path.mkdir(parents=True, exist_ok=False)
    return path


def build_context(restored, blueprint, brief):
    payload = json.loads(restored[1]['content'])
    if blueprint['source_id'] in {s['source_id'] for s in payload['source_evidence']}:
        raise ValueError('Style reference cannot replace a cohort source')
    context = {k: payload[k] for k in ('source_evidence', 'expression_patterns', 'account_positioning')}
    context.update(reference=blueprint, brief=brief, short_seconds=45, long_seconds=180,
                   constraints={'narration': False, 'native_audio': True,
                       'style_reference_counts_toward_cohort': False,
                       'video_generation_unit_is_not_edit_shot': True,
                       'no_automatic_media_submission': True})
    return context


def source_digest(source):
    """Keep all cohort semantics, but not redundant frame inventories or media paths."""
    expression = source.get('expression_analysis', {})
    evidence = expression.get('evidence', [])
    wanted = []

    def endpoints(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'evidence_ids' and isinstance(child, list) and child:
                    wanted.extend([child[0], child[-1]])
                else:endpoints(child)
        elif isinstance(value, list):
            for child in value:endpoints(child)

    semantic = {k: v for k, v in expression.items() if k != 'evidence'}
    endpoints(semantic)
    for channel in ('visual', 'asr'):
        rows = [e for e in evidence if e.get('channel') == channel]
        if rows:wanted.extend([rows[0]['id'], rows[-1]['id']])
    selected_ids = list(dict.fromkeys(wanted))
    if not selected_ids:selected_ids = [e['id'] for e in evidence[:12]]
    # Retain every selected original row verbatim. This is a disclosed projection,
    # not a replacement for the full-source verification before every model call.
    selected = [e for e in evidence if e['id'] in set(selected_ids)]
    projected = {k: source[k] for k in ('source_id', 'analysis_id', 'title', 'hashtags',
                 'metric_kind', 'metric_value', 'collected_at', 'published_at', 'content_summary') if k in source}
    projected['expression_analysis'] = {**semantic, 'evidence': selected}
    projected['evidence_projection'] = {'method': 'semantic_claim_endpoints_plus_channel_endpoints',
        'total_evidence_rows': len(evidence), 'included_evidence_rows': len(selected),
        'notice': 'Only cite evidence rows included here. Full original evidence stays bound and locally verified.'}
    for key in ('independent_review', 'emotion_analysis'):
        value = source.get(key, {})
        projected[key] = {k: value[k] for k in ('status', 'decision', 'coverage', 'limitations',
                            'limits', 'notice', 'acoustic_status') if k in value}
    return projected


def author_payload(context, stage, parent, feedback=None, projection_version=None, requested_kind=None):
    public_reference = {k: v for k, v in context['reference'].items() if k not in ('source', 'evidence_files')}
    payload = {**context, 'reference': public_reference, 'stage': stage, 'approved_parent': parent}
    if projection_version == 'source_digest_v2':
        payload['source_evidence'] = [source_digest(s) for s in context['source_evidence']]
        payload['source_projection'] = projection_version
    elif projection_version == 'source_digest_v3':
        ranked = sorted(context['source_evidence'], key=lambda s: -(s.get('metric_value') or 0))
        detailed = []
        for mode in ('conflict_drama', 'prop_demonstration'):
            detailed.extend(s['source_id'] for s in [r for r in ranked if mode in {
                m.get('mode') for m in r.get('expression_analysis', {}).get('expression_modes', [])}][:2])
        sources = []
        for source in context['source_evidence']:
            projected = source_digest(source)
            if source['source_id'] not in detailed:
                expression = source.get('expression_analysis', {})
                core = expression.get('core_message', {})
                core_ids = core.get('evidence_ids', [])
                keep = set(core_ids[:1] + core_ids[-1:])
                projected['expression_analysis'] = {
                    'core_message': core,
                    'expression_modes': expression.get('expression_modes', []),
                    'uncertainties': expression.get('uncertainties', []),
                    'evidence': [e for e in expression.get('evidence', []) if e['id'] in keep]}
                projected['evidence_projection'].update(method='cohort_overview_with_core_endpoints',
                    included_evidence_rows=len(projected['expression_analysis']['evidence']))
            sources.append(projected)
        payload['source_evidence'] = sources
        payload['source_projection'] = projection_version
        payload['detailed_source_ids'] = list(dict.fromkeys(detailed))
        payload['source_selection_notice'] = 'All 20 remain locally verified. Detailed cohort examples: up to two highest displayed-metric conflict dramas and two prop demonstrations; no causal popularity claim. The user-designated local video is the primary style reference.'
    elif projection_version == 'source_digest_v4':
        payload = author_payload(context, stage, parent, feedback, 'source_digest_v3')
        payload['source_projection'] = projection_version
        for source in payload['source_evidence']:
            source['expression_analysis'] = json.loads(json.dumps(source['expression_analysis']))
            allowed = {e['id'] for e in source['expression_analysis']['evidence']}

            def prune(value):
                if isinstance(value, dict):
                    for key, child in value.items():
                        if key == 'evidence_ids' and isinstance(child, list):
                            value[key] = [v for v in child if v in allowed]
                        else:prune(child)
                elif isinstance(value, list):
                    for child in value:prune(child)

            prune(source['expression_analysis'])
            source['evidence_projection']['claim_reference_scope'] = 'Only actually included rows are listed in claim evidence_ids; full original references remain frozen locally.'
    elif projection_version == 'source_overview_v5':
        sources = []
        for source in context['source_evidence']:
            expression = source.get('expression_analysis', {})
            core = expression.get('core_message', {})
            review = source.get('independent_review', {})
            sources.append({
                **{k: source[k] for k in ('source_id', 'analysis_id', 'title', 'metric_kind', 'metric_value') if k in source},
                'expression_analysis': {'core_message': {'text': core.get('text', source.get('content_summary', ''))},
                    'expression_modes': [{'mode': m['mode']} for m in expression.get('expression_modes', [])],
                    'evidence': []},
                'review_scope': {k: review[k] for k in ('decision', 'acoustic_status') if k in review},
                'evidence_projection': {'method': 'account_background_overview_only', 'direct_citation_allowed': False,
                    'notice': 'This is a source overview, not direct evidence. Full media and review limits stay verified locally. Do not quote this source as a direct expression reference or verified legal conclusion.'}})
        payload['source_evidence'] = sources
        payload['source_projection'] = projection_version
        payload['source_selection_notice'] = 'All 20 sources remain account/sample background. Direct expression evidence for this focused authoring request comes only from the reviewed user-designated reference insights. No claim that the cohort was reanalyzed or that audience effects were measured.'
    elif projection_version == 'frozen_parent_v6':
        if stage not in ('script', 'production') or parent is None:raise ValueError('Frozen parent projection requires reviewed parent')
        payload = {k: context[k] for k in ('account_positioning', 'constraints', 'short_seconds', 'long_seconds')}
        payload.update(stage=stage, approved_parent=parent, source_evidence=[], source_projection=projection_version,
            source_selection_notice='Source evidence was verified locally and reviewed at outline stage. This stage expands only the approved parent; it cannot add source claims or change the story.')
    elif projection_version is not None:
        raise ValueError('Unknown source projection version')
    if feedback is not None:payload['current_feedback'] = feedback
    if requested_kind is not None:
        if stage != 'script' or requested_kind not in ('short', 'long'):
            raise ValueError('Only script supports a requested version')
        payload['requested_kind'] = requested_kind
    return payload


def verify_workflow(path):
    workflow = read(path)
    if workflow.get('schema') != 'narrative_impact_workflow/v1':
        raise ValueError('Wrong workflow schema')
    for binding in workflow['inputs'].values():verify_file(binding)
    context = read(verify_file(workflow['context']))
    original = read(workflow['inputs']['workflow_request']['path'])
    restored, _ = _source_input(original, Path(workflow['inputs']['full_sources']['path']))
    blueprint = validate_reference(read(workflow['inputs']['reference']['path']))
    brief = Path(workflow['inputs']['brief']['path']).read_text(encoding='utf-8-sig').strip()
    if context != build_context(restored, blueprint, brief):
        raise ValueError('Frozen workflow context changed')
    gate = verify_workflow_sources(restored)
    return workflow, context, gate


def prepare(args):
    output = new_output(args.output_dir)
    status = {'status': 'preflight_running', 'started_at_bjt': now(), 'model_calls': 0, 'media_calls': 0}
    save(output / 'prepare_status.json', status)
    try:
        request = Path(args.workflow_request).resolve()
        full_path = request.with_name('source_evidence.full.json')
        restored, full = _source_input(read(request), full_path)
        if full is None:raise ValueError('Full cohort evidence file required')
        blueprint = validate_reference(read(args.reference))
        brief = Path(args.brief_file).read_text(encoding='utf-8-sig').strip()
        if not brief:raise ValueError('New creative brief required')
        # Fresh brief deliberately replaces legacy fixed-contract editor prompts.
        context = build_context(restored, blueprint, brief)
        save(output / 'context.json', context)
        gate = verify_workflow_sources(restored)
        save(output / 'source_gate.json', gate)
        workflow = {'schema': 'narrative_impact_workflow/v1', 'created_at_bjt': now(),
            'status': 'ready_for_outline_authoring', 'inputs': {
                'workflow_request': identity(request), 'full_sources': identity(full_path),
                'reference': identity(args.reference), 'brief': identity(args.brief_file)},
            'context': identity(output / 'context.json'), 'stages': list(STAGES),
            'stage_order': ['full_source_analysis', 'reference_impact_review', 'outline', 'outline_review',
                'script', 'script_review', 'production', 'production_review', 'execution_adapter',
                'segment_generation_and_review', 'final_av_and_narrative_review'],
            'media_automatic_submit': False,
            'execution_status': 'new_schema_requires_reviewed_video_adapter',
            'failure_policy': 'new screenplay starts at 0; same screenplay retries accumulate; default 10; history preserved'}
        save(output / 'workflow.json', workflow)
        status.update(status='workflow_ready', workflow=str(output / 'workflow.json'))
    except Exception as exc:
        status.update(status='preflight_rejected', error=str(exc))
        raise
    finally:
        status['finished_at_bjt'] = now();save(output / 'prepare_status.json', status)
    return status


def read_candidate(run_dir, workflow_path, expected_stage, context, depth=0):
    if depth > 3:raise ValueError('Stage parent chain too deep')
    folder = Path(run_dir).resolve();run = read(folder / 'run.json')
    if run.get('schema') == 'narrative_script_pair/v1':
        if (expected_stage != 'script' or run.get('stage') != 'script'
                or run.get('workflow') != identity(workflow_path)
                or run.get('status') != 'candidate_pending_independent_review'
                or run.get('model_calls') != 0 or set(run['parts']) != {'short', 'long'}):
            raise ValueError('Invalid script assembly identity')
        combined = {}
        for kind, binding in run['parts'].items():
            part_path = verify_file(binding)
            if part_path.name != 'run.json':raise ValueError('Part must bind original run')
            part_run = read(part_path)
            if part_run.get('kind') != kind or part_run.get('parent') != run['parent']:
                raise ValueError('Script versions have different approved parents')
            part = read_candidate(part_path.parent, workflow_path, 'script', context, depth + 1)
            combined[kind] = part[kind]
        if set(run['artifacts']) != {'candidate.json'}:
            raise ValueError('Unexpected assembled artifacts')
        candidate_path = verify_file(run['artifacts']['candidate.json'])
        if candidate_path != folder / 'candidate.json' or read(candidate_path) != combined:
            raise ValueError('Assembled candidate differs from model-authored versions')
        parent_path = verify_file(run['parent']['run'])
        verify_file(run['parent']['review'])
        parent = read_candidate(parent_path.parent, workflow_path, 'outline', context, depth + 1)
        require_review(read(run['parent']['review']['path']), 'outline', parent_path.parent / 'candidate.json', workflow_path)
        validate_candidate(combined, 'script', context, parent)
        return combined
    if (run.get('schema') != 'narrative_author_run/v1' or run.get('stage') != expected_stage
            or run.get('status') != 'candidate_pending_independent_review'
            or run.get('workflow') != identity(workflow_path) or run.get('model_calls') != 1):
        raise ValueError('Completed model-authored stage from this workflow required')
    if set(run['artifacts']) != {'request.json', 'prompt.md', 'model_output.json', 'response.json', 'candidate.json'}:
        raise ValueError('Missing original model evidence')
    for name, binding in run['artifacts'].items():
        if Path(binding['path']).resolve() != folder / name:
            raise ValueError('Stage artifact path changed')
        verify_file(binding)
    candidate = read(folder / 'candidate.json')
    parent = None
    if expected_stage != 'outline':
        parent_stage = STAGES[STAGES.index(expected_stage) - 1]
        parent_binding = run['parent'];verify_file(parent_binding['run']);verify_file(parent_binding['review'])
        parent_folder = Path(parent_binding['run']['path']).parent
        parent = read_candidate(parent_folder, workflow_path, parent_stage, context, depth + 1)
        require_review(read(parent_binding['review']['path']), parent_stage,
                       parent_folder / 'candidate.json', workflow_path)
    actual_output = read(folder / 'model_output.json')
    if run.get('script_format') == 'delta_v1':
        if expected_stage != 'script':raise ValueError('Delta only supports script')
        actual_output = expand_script_delta(actual_output, parent, run.get('kind'))
    elif run.get('script_format') is not None:raise ValueError('Unknown script format')
    if candidate != actual_output:raise ValueError('Candidate differs from actual model output/declared expansion')
    feedback = None
    if 'feedback' in run:
        feedback = verify_file(run['feedback']).read_text(encoding='utf-8-sig')
    request = read(folder / 'request.json')
    expected = [{'role': 'system', 'content': (folder / 'prompt.md').read_text(encoding='utf-8')},
                {'role': 'user', 'content': json.dumps(author_payload(context, expected_stage, parent, feedback, run.get('source_projection'), run.get('kind')), ensure_ascii=False)}]
    if request != expected:
        raise ValueError('Saved author request does not replay bound stage/context/parent')
    validation_context = context
    if run.get('source_projection'):
        validation_context = {**context, 'source_evidence': author_payload(context, expected_stage, parent, feedback, run['source_projection'])['source_evidence']}
    validate_candidate(candidate, expected_stage, validation_context, parent, kind=run.get('kind'))
    return candidate


def assemble_script(args):
    _, context, _ = verify_workflow(args.workflow)
    combined = {}; parts = {}; parent_binding = None
    for kind in ('short', 'long'):
        folder = Path(getattr(args, kind + '_run')).resolve()
        part_run = read(folder / 'run.json')
        if part_run.get('kind') != kind:raise ValueError('Wrong script version supplied')
        part = read_candidate(folder, args.workflow, 'script', context)
        if parent_binding is not None and part_run['parent'] != parent_binding:
            raise ValueError('Cannot combine different approved outlines')
        parent_binding = part_run['parent']
        combined[kind] = part[kind];parts[kind] = identity(folder / 'run.json')
    parent = read_candidate(Path(parent_binding['run']['path']).parent, args.workflow, 'outline', context)
    validate_candidate(combined, 'script', context, parent)
    output = new_output(args.output_dir)
    save(output / 'candidate.json', combined)
    run = {'schema': 'narrative_script_pair/v1', 'stage': 'script', 'assembled_at_bjt': now(),
        'status': 'candidate_pending_independent_review', 'model_calls': 0, 'media_calls': 0,
        'workflow': identity(args.workflow), 'parent': parent_binding, 'parts': parts,
        'artifacts': {'candidate.json': identity(output / 'candidate.json')}}
    save(output / 'run.json', run)
    save(output / 'review.template.json', review_template('script', output / 'candidate.json', args.workflow))
    return run


def author(args):
    output = new_output(args.output_dir)
    run = {'schema': 'narrative_author_run/v1', 'stage': args.stage, 'started_at_bjt': now(),
           'status': 'preflight_running', 'model_calls': 0, 'media_calls': 0, 'artifacts': {}}
    save(output / 'run.json', run)
    try:
        kind = getattr(args, 'kind', None)
        if kind is not None:
            if args.stage != 'script':raise ValueError('Single version only supports script')
            run['kind'] = kind
        _, context, gate = verify_workflow(args.workflow)
        run['workflow'] = identity(args.workflow);save(output / 'source_gate.json', gate)
        parent = None
        if args.stage != 'outline':
            if not args.parent_run or not args.review:raise ValueError('Previous stage and actual independent review required')
            previous_stage = STAGES[STAGES.index(args.stage) - 1]
            parent = read_candidate(args.parent_run, args.workflow, previous_stage, context)
            if args.stage == 'production' and set(parent) != {'short', 'long'}:
                raise ValueError('Assemble and review both script versions before production')
            require_review(read(args.review), previous_stage, Path(args.parent_run) / 'candidate.json', args.workflow)
            run['parent'] = {'run': identity(Path(args.parent_run) / 'run.json'), 'review': identity(args.review)}
        elif args.parent_run or args.review:
            raise ValueError('Outline has no previous stage')
        prompt_path = ROOT / 'src/trend_intelligence/prompts/narrative_impact_workflow.md'
        prompt = prompt_path.read_text(encoding='utf-8')
        script_format = getattr(args, 'script_format', None)
        if script_format:
            if args.stage != 'script' or not kind:raise ValueError('Delta requires single script version')
            run['script_format'] = script_format
            prompt += '\n' + (ROOT / 'src/trend_intelligence/prompts/narrative_script_delta.md').read_text(encoding='utf-8')
        feedback = None
        if args.feedback_file:
            feedback = Path(args.feedback_file).read_text(encoding='utf-8-sig')
            run['feedback'] = identity(args.feedback_file)
        run['source_projection'] = getattr(args, 'source_projection', None) or 'source_digest_v4'
        payload = author_payload(context, args.stage, parent, feedback, run['source_projection'], kind)
        messages = [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
        save(output / 'request.json', messages);(output / 'prompt.md').write_text(prompt, encoding='utf-8')
        # Identical author requests cannot be retried by changing the output folder.
        reservation_dir = Path(args.workflow).resolve().parent / 'author_reservations';reservation_dir.mkdir(exist_ok=True)
        request_sha = digest(output / 'request.json')
        with (reservation_dir / (request_sha + '.json')).open('x', encoding='utf-8') as stream:
            json.dump({'run_dir': str(output), 'reserved_at_bjt': now()}, stream)
        from src.shared.config import settings
        from src.shared.llm_client import LLMClient
        model = getattr(args, 'model', None) or settings.SCRIPT_LLM_MODEL or settings.LLM_MODEL
        thinking = getattr(args, 'thinking', None) or (settings.SCRIPT_LLM_THINKING if model.lower() == 'minimax-m3' else None)
        extra = None
        if thinking:
            if model.lower() != 'minimax-m3' or thinking not in ('adaptive', 'disabled'):
                raise ValueError('Unsupported thinking configuration')
            extra = {'thinking': {'type': thinking}, 'reasoning_split': True}
        client = LLMClient(model=model, extra_body=extra, timeout_seconds=settings.SCRIPT_LLM_TIMEOUT_SECONDS,
                           max_retries=0, max_tokens=settings.SCRIPT_LLM_MAX_TOKENS, preserve_invalid_json=True)
        if client.provider_name == 'mock':raise ValueError('Real project model required')
        run.update(status='running', model=model, thinking=thinking, model_calls=1);save(output / 'run.json', run)
        try:
            raw = client.chat_completion_tracked(messages, caller='narrative_impact_' + args.stage,
                                                temperature=.4, json_mode=True, use_cache=False)
        finally:save(output / 'response.json', getattr(client.provider, 'last_response_metadata', {}))
        (output / 'model_output.json').write_text(raw or 'null', encoding='utf-8')
        if not raw:
            metadata = read(output / 'response.json')
            raise ValueError('No usable model body; finish_reason=' + str(metadata.get('finish_reason'))
                             + '; error_type=' + str(metadata.get('error_type'))
                             + '. Retained response metadata; no candidate produced.')
        candidate = read(output / 'model_output.json')
        if script_format == 'delta_v1':candidate = expand_script_delta(candidate, parent, kind)
        validate_candidate(candidate, args.stage, {**context, 'source_evidence': payload['source_evidence']}, parent, kind=kind)
        save(output / 'candidate.json', candidate)
        for name in ('request.json', 'prompt.md', 'model_output.json', 'response.json', 'candidate.json'):
            run['artifacts'][name] = identity(output / name)
        save(output / 'review.template.json', review_template(args.stage, output / 'candidate.json', args.workflow))
        if args.stage == 'production':save(output / 'media_handoff.json', media_handoff_report(candidate))
        run['status'] = 'candidate_pending_independent_review'
    except Exception as exc:
        run.update(status='failed' if run['model_calls'] else 'preflight_rejected', error=str(exc));raise
    finally:
        run['finished_at_bjt'] = now();save(output / 'run.json', run)
    return run


def main():
    if hasattr(sys.stdout, 'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__);sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    for name in ('workflow-request', 'reference', 'brief-file', 'output-dir'):p.add_argument('--' + name, required=True)
    p = sub.add_parser('author');p.add_argument('--stage', choices=STAGES, required=True)
    p.add_argument('--script-format', choices=('delta_v1',), help='Model-authored state changes; deterministic frozen event/state expansion')
    p.add_argument('--kind', choices=('short', 'long'), help='Generate one script version; assemble both before review/production')
    p.add_argument('--model', choices=('MiniMax-M3', 'MiniMax-M2.7'), help='Run-scoped project-compatible text model')
    p.add_argument('--source-projection', choices=('source_digest_v4', 'source_overview_v5', 'frozen_parent_v6'),
                   help='Full local verification always runs; v5 directly cites only the reviewed designated reference')
    p.add_argument('--thinking', choices=('adaptive', 'disabled'), help='This run only; does not change project defaults')
    for name in ('workflow', 'output-dir'):p.add_argument('--' + name, required=True)
    for name in ('parent-run', 'review', 'feedback-file'):p.add_argument('--' + name)
    p = sub.add_parser('check');p.add_argument('--workflow', required=True)
    p = sub.add_parser('assemble-script')
    for name in ('workflow', 'short-run', 'long-run', 'output-dir'):p.add_argument('--' + name, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':result = prepare(args)
    elif args.command == 'author':result = author(args)
    elif args.command == 'assemble-script':result = assemble_script(args)
    else:
        workflow, _, gate = verify_workflow(args.workflow)
        result = {'workflow': args.workflow, 'source_gate': gate, 'status': workflow['status'],
                  'media_automatic_submit': False, 'execution_status': workflow['execution_status']}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':main()
