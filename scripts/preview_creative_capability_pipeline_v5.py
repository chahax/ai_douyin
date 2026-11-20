"""Read-only integration preview of capability-first creative development.

This entry has no generation/client/submit operation. It verifies the exact
current native source, current frozen ledgers and exhausted coordinator state.
All output is written to a new directory, never into a production run.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import audit_creative_provider_environment_v1 as audit
from scripts import run_creative_shared_full_production_v3 as parent_preview
from scripts import run_creative_shared_full_production_v1 as original
from src.content_factory import creative_director_endpoint_contract_v4 as endpoint
from src.content_factory import creative_production_revision_loop_v3 as loop

TRIAL = audit.TRIAL
DEFAULT_OUTPUT = PROJECT / 'data/qa/creative_capability_first_20261012/integrated_preview'


def verified_freezes():
    reports = [audit.freeze_audit(PROJECT, TRIAL / name) for name in ('run_01', 'probe_v4')]
    if not all(row['frozen_sources_unchanged'] for row in reports):
        raise ValueError('a previously frozen source changed; preview stopped')
    # Check actual immutable call files as well as working/frozen source bytes.
    for name in ('run_01', 'probe_v4'):
        root = PROJECT / TRIAL / name
        ledger = audit.read(root / 'CALL_LEDGER.json')
        if audit.sha(root / 'AUTHORIZATION.json') != ledger['authorization_sha256']:
            raise ValueError('original authorization changed')
        if len({row['receipt'] for row in ledger['calls']}) != len(ledger['calls']):
            raise ValueError('duplicate original ledger receipt')
        for row in ledger['calls']:
            path = (root / row['receipt']).resolve()
            if not path.is_relative_to(root.resolve()) or audit.sha(path) != row['receipt_sha256']:
                raise ValueError('original receipt path or bytes changed')
    return reports


def build_preview(output=DEFAULT_OUTPUT):
    # Lazy imports: this independent entry may be examined while development is
    # in progress. No production dispatch function is imported or exposed.
    from src.content_factory import creative_provider_preflight_v1 as preflight
    from src.content_factory import creative_complete_production_coordinator_v4 as coordinator
    from src.content_factory import creative_complete_production_pipeline_v4 as pipeline

    before = verified_freezes()
    x, script, manifest, initial, _old_three_candidate_state, proof = parent_preview.verified_parent()
    # This binds exact already-frozen production inputs. It does not pretend
    # that the original script reviewer semantically approved video preferences.
    proof['production_context_sha256'] = endpoint.digest({
        'brief': x['brief'], 'reference_fulltext': x['reference_fulltext'],
        'production_preferences': x['production_preferences']})
    proof['production_context_binding_kind'] = 'verified_frozen_input_not_semantic_approval'
    current_root = PROJECT / TRIAL / 'probe_v4'
    state_path = current_root / 'LOOP_STATE.json'
    original_state_sha = audit.sha(state_path)
    state = audit.read(state_path)
    capacity = loop.candidate_capacity(state)
    if capacity['attempts_including_claims'] != 4 or capacity['remaining'] != 0:
        raise ValueError('current exact inherited gate changed; preview requires an explicit review')
    current_receipt = audit.read(current_root / 'call_517_whole_direction_v3_3.json')
    normalized = loop.normalize_receipt(current_receipt)
    if not normalized['known_complete'] or normalized['status'] != 'contract_rejected':
        raise ValueError('current native rejected direction evidence changed')
    diagnostic = pipeline.known_failure_diagnostic(normalized, script)
    inputs = endpoint.build_director_input(script, manifest, initial, x['reference_fulltext'],
                                         x['production_preferences'], [diagnostic])
    models = audit.read(original.ROOT / 'ANCHOR.json')['models']
    inputs['brief'] = deepcopy(x['brief'])
    inputs['production_context_binding'] = {
        'production_context_sha256': proof['production_context_sha256'],
        'binding_kind': 'external_frozen_input_identity', 'prior_semantic_review_claim': False}
    request = pipeline.build_request('whole_direction', inputs,
        pipeline.whole_direction_schema(script, manifest), models['writer']['model'])
    capability = preflight.preflight_text_request(request)
    invocations = []
    saved_states = []

    def forbidden_dispatch(*args, **kwargs):
        invocations.append('forbidden')
        raise AssertionError('read-only preview must never invoke a generation provider')

    flow = coordinator.CompleteProductionCoordinator(
        invoke=forbidden_dispatch, persist_state=lambda value: saved_states.append(deepcopy(value)),
        verify_frozen_source=verified_freezes,
        opening_context_builder=lambda row: (_ for _ in ()).throw(AssertionError('no opening media in exhausted preview')),
        models={role: value['model'] for role, value in models.items()})
    result = flow.run(script=script, manifest=manifest, initial=initial,
        reference_fulltext=x['reference_fulltext'], preferences=x['production_preferences'], brief=x['brief'],
        source_review_binding=proof, state=state, scope=audit.read(original.ROOT / 'USER_SCOPE.json'))
    if invocations or result['reason'] != 'INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED':
        raise AssertionError('new coordinator did not preserve the real exhausted gate')
    after = verified_freezes()
    if before != after or audit.sha(state_path) != original_state_sha:
        raise AssertionError('read-only integration changed original evidence')

    asset_pending = {'schema': 'creative_capability_preview/asset_pending',
        'director_visual_request_enriched': False, 'approved_new_cast_assets_available': False,
        'actor_bindings': [{
            'actor_id': actor['id'], 'name': actor['name'],
            'asset_binding_status': actor['asset_binding']['status'],
            'voice_status': actor['voice']['status']} for actor in manifest['actors']],
        'reason': 'Current frozen source has new casting preferences but no approved original identity images or voice inputs.',
        'next_requirement': 'Bind specific subjects to verified original images/audio, then use the reference compiler in a new frozen run.',
        'remote_trust_or_human_quality_proven': False}
    result_summary = {'schema': 'creative_capability_preview/v5',
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'source_title': script['title'], 'source_review_proof': proof,
        'director_contract': endpoint.VERSION,
        'director_numeric_bounds': inputs['endpoint_graph']['numeric_plan_bounds'],
        'director_actual_new_request_sha256': endpoint.digest(request),
        'source_reference_fulltext_sha256': endpoint.digest(x['reference_fulltext']),
        'preflight': capability, 'current_capacity': capacity,
        'actual_gate_status': result['status'], 'actual_gate_reason': result['reason'],
        'current_original_state_sha256': original_state_sha,
        'frozen_sources_before': before, 'frozen_sources_after': after,
        'actual_provider_invocations': len(invocations),
        'new_generation_calls': 0, 'new_media_calls': 0, 'new_publications': 0,
        'budget_reset': False, 'new_candidate_grant': False,
        'complete_text_handoff_ready': False, 'production_dispatch_entry_integrated': False,
        'human_creative_quality_passed': False, 'actual_media_quality_passed': False,
        'reference_adapter_available_for_explicit_future_binding': True,
        'asset_status': asset_pending}
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    documents = {'DIRECTOR_REQUEST.preview.json': request,
        'SOURCE_REVIEW_PROOF.json': proof, 'ASSET_BINDING_PENDING.json': asset_pending,
        'ACTUAL_EXHAUSTED_GATE_RESULT.json': result_summary}
    for name, value in documents.items():
        with (output / name).open('x', encoding='utf-8') as file:
            json.dump(value, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.write('\n')
    sections = [('真实停点与离线接线', result_summary), ('完整原生剧本', script),
        ('完整导演请求预览（未派发）', request), ('实际角色与声音绑定待完成', asset_pending)]
    body = ["<!doctype html><meta charset='utf-8'><title>能力优先流程接线预览</title>",
        '<style>body{max-width:1100px;margin:32px auto;padding:0 24px;font:16px/1.7 system-ui;color:#20242b;background:#f7f8fc}section,details{padding:20px;margin:16px 0;background:white;border-radius:10px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.55 Consolas,monospace}.warn{background:#fff2d5}</style>',
        '<h1>能力优先流程：代码接线与真实门禁</h1>',
        '<section class="warn">剧本512及全文复审513保持原生绑定。当前导演候选4/4已用完，本入口零派发；导演、实际表演、制作交接和新视频尚未完成。离线合同通过不能代表创作质量。</section>',
        '<section>整片导演选终点和预算档，程序推导连续起点；局部表演安排实际反应窗口。能力预检先于派发，明确批准的原素材进入实际多模态请求；素材资格、URL可访问性与用户观感分别记录。本页没有虚构人物图或声线批准。</section>']
    for title, value in sections:
        body.append('<details><summary>' + html.escape(title) + '</summary><pre>' +
            html.escape(json.dumps(value, ensure_ascii=False, indent=2)) + '</pre></details>')
    (output / 'WORKFLOW_REVIEW.html').write_text('\n'.join(body), encoding='utf-8')
    return {**result_summary, 'output': str(output), 'review_path': str(output / 'WORKFLOW_REVIEW.html')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_preview(args.output)
    print(json.dumps({key: result[key] for key in ('output', 'review_path', 'actual_gate_reason',
        'new_generation_calls', 'new_media_calls', 'budget_reset')}, ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
