"""Explicit three-cycle, text-only production continuation from an approved screenplay.

Each invocation runs one round to its next real assistant review gate or terminal
outcome. Record that gate with record_creative_text_review.py, then repeat the
same command. No media provider is called. Historical parents remain read-only.
"""
from __future__ import annotations
import argparse
import json
import hashlib
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.content_factory.creative_workflow import (
    CreativeWorkflow, CREATE_REVIEW_PROFILE, EVENT_WRITER_VERSION,
    _hash, _read, _write, _validate_production_design, _execution_draft,
    audit_creative_executor, build_seedance_segment_plan, _review_packet,
)
from src.content_factory.creative_segmented_director import bind_segmented_director, generate_reviewed_beats
from src.content_factory.creative_review_gate import validate_review
from src.content_factory.creative_original_director import bind_original_director
from src.content_factory.creative_original_prompt import bind_brief_priority

NEW_SERIES = '20260928'
TWO_SERIES = '20260928_v3_two'
OPTIMIZED_SERIES = '20260928_action_one'
GOVERNED_SERIES = '20260928_governed_two'
PRIOR_ROOT = ROOT / 'data/production_trials/say_no_three_production_cycles_20260927'


def source_snapshot():
    paths = ['scripts/run_three_cycle_text_production.py',
             'src/content_factory/creative_workflow.py',
             'src/content_factory/creative_segmented_director.py',
             'src/content_factory/creative_review_v6.py',
             'src/content_factory/creative_state_plan_v6.py',
             'src/content_factory/creative_state_plan_v2.py',
             'src/content_factory/creative_state_plan_v3.py',
             'src/content_factory/creative_workflow_roles.py',
             'src/content_factory/creative_state_plan_binding.py',
             'src/content_factory/creative_state_plan_guidance.py',
             'src/content_factory/creative_action_plan_v1.py',
             'src/content_factory/creative_plan_patch.py',
             'src/content_factory/creative_review_evidence_catalog.py',
             'src/content_factory/creative_review_evidence_ids.py']
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in paths if (ROOT / name).exists()}


def inherited_asset_catalog(parent):
    record = _read(parent / 'director_brief.json')
    request = record.get('request', {})
    if not request.get('messages'):
        raise RuntimeError('父任务缺少真实资产目录请求，不能用空目录替代')
    payload = json.loads(request['messages'][-1]['content'])
    if 'asset_catalog' in payload:
        return payload['asset_catalog']
    metadata = payload.get('materials', {}).get('metadata', {})
    if 'asset_catalog' not in metadata:
        raise RuntimeError('父任务缺少已绑定资产目录')
    return metadata['asset_catalog']


TERMINAL = {'needs_revision', 'production_exception', 'media_handoff_pending_capability'}


def now():
    return datetime.now(timezone.utc).isoformat()


def bind_inputs(parent, screenplay, *, series=None):
    state = _read(parent / 'state.json')
    return {
        'schema': 'approved_screenplay_continuation_inputs/v1',
        'same_story': True,
        'parent_run': str(parent.resolve()),
        'parent_state_sha256': _hash(state),
        'parent_calls_started': state['calls_started'],
        'parent_revision_rounds': state['revision_rounds'],
        'approved_screenplay_path': str(screenplay.resolve()),
        'script': _read(screenplay),
        'director_brief': _read(parent / 'director_brief.json')['output'],
        'writer_prompt_binding': state['writer_prompt_binding'],
        'asset_catalog': inherited_asset_catalog(parent) if series else [],
    }


def open_round(root, number, parent, screenplay, clients=None, *, series=None, prior_root=PRIOR_ROOT):
    if series not in (None, NEW_SERIES, TWO_SERIES, OPTIMIZED_SERIES, GOVERNED_SERIES):
        raise ValueError('未知授权系列')
    max_rounds = 1 if series == OPTIMIZED_SERIES else 2 if series in (TWO_SERIES, GOVERNED_SERIES) else 3
    if number not in range(1, max_rounds + 1):
        raise ValueError(f'授权范围仅为{max_rounds}个完整文本生产轮次')
    root.mkdir(parents=True, exist_ok=True)
    ledger_path = root / 'THREE_CYCLE_LEDGER.json'
    inputs = bind_inputs(parent, screenplay, series=series)
    if series:
        inputs["series"] = series
        prior_path = prior_root / "THREE_CYCLE_LEDGER.json"
        inputs["prior_series_ledger"] = str(prior_path.resolve())
        inputs["prior_series_ledger_sha256"] = _hash(_read(prior_path))
    if ledger_path.exists():
        ledger = _read(ledger_path)
        if ledger.get('series') != series:
            raise RuntimeError('系列绑定不匹配；旧轮次不可升级或重置')
        if ledger['inputs_sha256'] != _hash(inputs):
            raise RuntimeError('父任务或已审核输入发生变化，拒绝改变已绑定续跑')
    else:
        ledger = {
            'schema': 'three_production_cycles_authorization/v1',
            'authorization': '用户明确授权三轮：完整文本生产、实际审核，失败由Codex子agent修复后再执行下一轮。此前三次请求不计入这三轮。',
            'created_at': now(), 'same_story': True, 'series': series,
            'prior_series_ledger': inputs.get('prior_series_ledger'),
            'prior_series_ledger_sha256': inputs.get('prior_series_ledger_sha256'),
            'inputs_sha256': _hash(inputs), 'parent_run': str(parent.resolve()),
            'parent_calls_started': inputs['parent_calls_started'],
            'prior_three_request_extension': str((ROOT / 'data/production_trials/say_no_v4_paid_three_20260927').resolve()),
            'max_rounds': max_rounds, 'per_round_max_calls': 24,
            'per_round_max_total_tokens': 250000, 'media_calls': 0, 'rounds': {},
        }
        if series:
            ledger['authorization'] = '用户于2026-09-28明确追加三轮完整文本生产闭环：根据整体分析修复，生产、分析，再修复和下一轮；此前系列完整保留，不计入本次三轮。'
        if series in (TWO_SERIES, OPTIMIZED_SERIES, GOVERNED_SERIES):
            ledger['schema'] = 'bounded_production_cycles_authorization/v1'
            ledger['authorization'] = '用户明确新增授权生产环境测试与修复两轮：每轮真实文本生产、分析与修复，第二轮需第一轮真实分析后启动；此前所有系列完整保留，不计入本次两轮。仅虚构剧本和7条项目素材目录元数据发送至官方MiniMax/DeepSeek，不生成图片或视频，不自动批准助手审核。'
            history = {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
                       for base in (parent, prior_root) for p in base.rglob('*.json')}
            _write(root / 'HISTORICAL_RECEIPT_HASHES.json', history)
            ledger['historical_receipt_hashes_sha256'] = _hash(history)
        if series == OPTIMIZED_SERIES:
            ledger['authorization'] = '用户明确授权按优化方向修改流程后再进行一次真实文本生产。采用程序排时、局部修复和证据编号；原同稿与所有历史保留。仅使用既定MiniMax/DeepSeek文本模型，无图片视频调用，无自动助手批准。'
        if series == GOVERNED_SERIES:
            ledger['authorization'] = '用户明确授权新版生产调试两次：第一轮真实文本生产、实际审查和归因修复，再启动第二轮。沿用已审剧本；每轮至多24次文本调用、250000 tokens；不生成图片视频，不自动批准审核。'
        _write(root / 'CONTINUATION_INPUTS.json', inputs)
        _write(ledger_path, ledger)
    if number > 1 and ledger['rounds'].get(str(number - 1), {}).get('status') not in TERMINAL:
        raise RuntimeError('必须完成并分析上一轮，才能启动下一轮')
    if series and number > 1:
        analysis_path = root / f'round_{number - 1:02}' / 'ROUND_ANALYSIS.json'
        if not analysis_path.exists() or _read(analysis_path).get('analysis_complete') is not True:
            raise RuntimeError('上一轮需要真实分析并记录 ROUND_ANALYSIS.json 后才能开启下一轮')
    run_dir = root / f'round_{number:02}'
    review_version = 'evidence_review_v6' if series else 'evidence_review_v5'
    workflow = CreativeWorkflow(
        run_dir, clients=clients, max_calls=24, max_total_tokens=250000,
        max_revisions=2, max_contract_repairs=2,
        model_profile=CREATE_REVIEW_PROFILE, writer_prompt_version=EVENT_WRITER_VERSION,
        review_policy_version=review_version,
        production_protocol="governed_production_v1" if series == GOVERNED_SERIES else None,
        logical_task_id=f'authorized-three-cycle:{_hash(inputs)}:{number}',
    )
    workflow._reusable_generation = True
    if workflow.state_path.exists():
        workflow.state = _read(workflow.state_path)
        if workflow.state['continuation_inputs_sha256'] != _hash(inputs):
            raise RuntimeError('续跑输入绑定变化')
    else:
        run_dir.mkdir(parents=True, exist_ok=True)
        workflow.state = {
            'schema': 'creative_workflow_state/v1', 'created_at': now(),
            'status': 'approved_script_continuation', 'source_driver': 'original',
            'model_profile': CREATE_REVIEW_PROFILE, 'writer_prompt_version': EVENT_WRITER_VERSION,
            'review_policy_version': review_version,
            **({'production_protocol':'governed_production_v1','review_packet_version':'focused_review_packet_v1'} if series == GOVERNED_SERIES else {}),
            **({'review_evidence_interface_version': ('evidence_ids_v1' if series == OPTIMIZED_SERIES else 'leaf_catalog_v1')} if series else {}),
            **({'evidence_id_repair_hints_version': 'missing_source_candidates_v1'} if series == OPTIMIZED_SERIES else {}),
            'segmented_director_binding': (bind_segmented_director(authoritative=True,static_visual=True,state_plan=True,state_plan_version='whole_film_action_plan_v2',plan_thinking_mode='disabled')
                if series == GOVERNED_SERIES else bind_segmented_director(authoritative=True, static_visual=True, state_plan=True, state_plan_version='whole_film_action_plan_v1', plan_thinking_mode='disabled')
                if series == OPTIMIZED_SERIES else bind_segmented_director(authoritative=True, static_visual=True, state_plan=True, state_plan_version='whole_film_state_plan_v3', plan_thinking_mode='disabled', state_plan_guidance_version='completed_action_hold_v2')
                if series else bind_segmented_director(authoritative=True, static_visual=True)),
            'original_director_binding': bind_original_director(),
            'original_brief_priority_binding': bind_brief_priority(),
            'writer_prompt_binding': deepcopy(inputs['writer_prompt_binding']),
            'logical_task_id': workflow.logical_task_id,
            'creative_focus': '', 'continuation_inputs_sha256': _hash(inputs),
            'material_sha256': _hash(inputs), 'same_story': True,
            'authorized_round': number, 'parent_run': str(parent.resolve()),
            'calls_started': 0, 'max_calls': 24, 'max_total_tokens': 250000,
            'max_revisions': 2, 'budget_policy_version': workflow.budget_policy_version,
            'max_contract_repairs': 2, 'contract_repairs_used': 0, 'format_repairs_used': 0,
            'revision_rounds': 0, 'revision_committed': [], 'stages': [],
            'assistant_review_required': True, 'text_pass_sequence': 0, 'video_pass_sequence': 0,
        }
        if series == GOVERNED_SERIES:
            from src.content_factory.creative_governed_runtime import bind_new_task
            workflow.state['rule_registry_binding'] = bind_new_task()
        _write(run_dir / 'CONTINUATION_INPUTS.json', inputs)
        _write(run_dir / 'SCREENPLAY.json', inputs['script'])
        workflow._save()
    ledger['rounds'].setdefault(str(number), {'run_dir': str(run_dir.resolve()), 'started_at': now(),
        'source_at_start': source_snapshot(), 'review_policy_version': workflow.state['review_policy_version'],
        'segmented_director_binding': workflow.state['segmented_director_binding']})
    _write(ledger_path, ledger)
    return workflow, inputs, ledger


def run_round(root, number, parent, screenplay, clients=None, *, series=None, prior_root=PRIOR_ROOT):
    workflow, inputs, ledger = open_round(root, number, parent, screenplay, clients, series=series, prior_root=prior_root)
    if workflow.state['status'] in TERMINAL:
        if series == GOVERNED_SERIES and workflow.state['status'] == 'media_handoff_pending_capability':
            from src.content_factory.creative_governed_runtime import focused_artifacts
            from src.content_factory.creative_state_plan_binding import bind_reviewed_state_plan
            focused_artifacts(workflow)
            bind_reviewed_state_plan(workflow, _read(workflow.run_dir/'SCREENPLAY.json'), _read(workflow.run_dir/'STORYBOARD.json'))
            workflow._validate_output_manifest(handoff=_read(workflow.run_dir/'MEDIA_HANDOFF.json'))
        ledger['rounds'][str(number)].update(status=workflow.state['status'],
            assistant_review_outcome=workflow.state.get('assistant_review_outcome'))
        _write(root / 'THREE_CYCLE_LEDGER.json', ledger)
        return workflow.state
    script, brief = inputs['script'], inputs['director_brief']
    try:
        shots = generate_reviewed_beats(workflow, script, brief, {
            'source_driver': 'original', 'approved_script_sha256': _hash(script),
            'continuation_inputs_sha256': _hash(inputs),
        })
        if shots is None:
            return workflow.state
        _write(workflow.run_dir / 'STORYBOARD.json', shots)
        creative_brief = inputs['writer_prompt_binding']['creative_brief']
        approved_plan = None
        scheduled_context = {}
        if series:
            plan_path = workflow.run_dir / 'STATE_PLAN.json'
            if not plan_path.exists():
                raise RuntimeError('新系列缺少已审核 STATE_PLAN.json，不能给下游另一份动作依据')
            plan_record = _read(plan_path)
            if plan_record.get('schema') != 'creative_reviewed_state_plan/v1':
                raise RuntimeError('STATE_PLAN包版本不正确')
            source_stage = plan_record.get('source_stage', '')
            if not source_stage.startswith('director_state_plan__') or Path(source_stage).name != source_stage:
                raise RuntimeError('STATE_PLAN来源阶段不正确')
            approved_plan = plan_record['plan']
            if _hash(_read(workflow.run_dir / f'{source_stage}.json')['output']) != _hash(approved_plan):
                raise RuntimeError('STATE_PLAN与实际模型回执不一致')
            digest = _hash(plan_record)
            if workflow.state.get('accepted_state_plan_sha256', digest) != digest:
                raise RuntimeError('已绑定STATE_PLAN发生改变')
            workflow.state['accepted_state_plan_sha256'] = digest
            workflow._save()
            if series in (OPTIMIZED_SERIES, GOVERNED_SERIES):
                from src.content_factory.creative_state_plan_binding import bind_reviewed_state_plan
                bound_context, _ = bind_reviewed_state_plan(workflow, script, shots)
                scheduled_context = {k: v for k, v in bound_context.items() if k != 'state_plan'}
        # Bind historical assets separately: old continuation inputs stay immutable.
        source_record = _read(parent / 'director_brief.json')
        catalog = inherited_asset_catalog(parent)
        asset_binding = {'schema': 'continuation_asset_catalog_binding/v1',
                         'source_record': str((parent / 'director_brief.json').resolve()),
                         'source_record_sha256': _hash(source_record), 'asset_catalog': catalog}
        binding_path = workflow.run_dir / 'ASSET_CATALOG_BINDING.json'
        if binding_path.exists() and _read(binding_path) != asset_binding:
            raise RuntimeError('已绑定历史资产目录发生改变')
        _write(binding_path, asset_binding)
        design = workflow._stage(
            'director_production_design__review_00', 'director',
            {'creative_brief': creative_brief, 'asset_catalog': catalog,
             'script': script, 'storyboard': shots, 'previous_design': None, 'issues': [],
             **({'state_plan': approved_plan} if approved_plan is not None else {}), **scheduled_context},
            lambda value: _validate_production_design(value, shots, catalog),
        )
        _write(workflow.run_dir / 'PRODUCTION_DESIGN.json', design)
        context = {'creative_brief': creative_brief, 'script': script, 'shots': shots,
                   'production_design': design, 'asset_catalog': catalog}
        if approved_plan is not None:
            context['state_plan'] = approved_plan
        context.update(scheduled_context)
        manifest = workflow.run_dir / 'static_visual_manifest.json'
        if manifest.exists():
            context['static_visual_manifest'] = _read(manifest)['output']
        key = 'writer_check__joint_00'
        review = workflow._stage(key, 'writer', context, lambda value: validate_review(value, context))
        issues = workflow._verified_review(key, review, context)
        if issues is None:
            return workflow.state
        blocking = [i for i in issues if i.get('severity') in ('blocking', 'major')]
        if blocking or design['issues']:
            workflow.state.update(status='needs_revision', unresolved_issues=blocking,
                                  design_issues=design['issues'], reason='完整联合审核发现问题；本轮停止，修复后开启下一授权轮次')
            workflow._save()
            return workflow.state
        execution = _execution_draft(script, shots)
        audit = audit_creative_executor(shots)
        segments = build_seedance_segment_plan(script, shots, audit)
        history = {'policy': workflow.review_policy_version,
                   'decisions': workflow.state.get('evidence_review_decisions', {}),
                   'automatic_media_submit': False}
        for name, value in [('EXECUTION_DRAFT', execution), ('MEDIA_CAPABILITY_AUDIT', audit),
                            ('SEEDANCE_SEGMENT_PLAN', segments), ('TEXT_REVIEW_HISTORY', history)]:
            _write(workflow.run_dir / f'{name}.json', value)
        analysis_record = _read(parent / 'writer_analysis.json')
        analysis = (_read(parent / 'EFFECTIVE_ANALYSIS.json')
                    if (parent / 'EFFECTIVE_ANALYSIS.json').exists() else analysis_record['output'])
        packet = _review_packet(analysis, brief, script, shots, review, _hash(inputs),
                                assistant_review_required=True,
                                source_scope_audit={'source_driver': 'original', 'approved_script_continuation': True})
        _write(workflow.run_dir / 'EDITORIAL_REVIEW_PACKET.json', packet)
        _write(workflow.run_dir / 'materials.json', _read(parent / 'materials.json'))
        # These are inherited outputs, not new calls; never copy old usage as new usage.
        for name, output in [('writer_analysis', analysis), ('director_brief', brief)]:
            _write(workflow.run_dir / f'{name}.json', {
                'schema': 'inherited_creative_output/v1', 'output': output,
                'parent_run': str(parent.resolve()), 'new_model_call': False})
        handoff = {
            'schema': 'creative_media_handoff/v1', 'material_sha256': _hash(inputs),
            'analysis_sha256': _hash(analysis), 'review_packet_sha256': _hash(packet),
            'brief_sha256': _hash(brief), 'script_sha256': _hash(script), 'shots_sha256': _hash(shots),
            'execution_draft_sha256': _hash(execution), 'capability_audit_sha256': _hash(audit),
            'segment_plan_sha256': _hash(segments), 'production_design_sha256': _hash(design),
            'text_review_history_sha256': _hash(history), 'media_provider': audit['provider'],
            'media_model': audit['model'], 'text_status': 'segment_and_joint_verified_final_assistant_review_pending',
            'media_status': 'segment_templates_ready_capability_unverified',
            'reusable_production_status': 'awaiting_actual_style_and_asset_reviews',
            'automatic_submit': False, 'reason': '文本完整流程经模型与助手审核；实际画面、声音、口型及连续性未生成未审核',
        }
        if approved_plan is not None:
            handoff['state_plan_sha256'] = workflow.state['accepted_state_plan_sha256']
        if scheduled_context.get('scheduled_state_plan'):
            handoff['scheduled_state_plan_sha256'] = _hash(scheduled_context['scheduled_state_plan'])
            handoff['scheduling_report_sha256'] = _hash(scheduled_context['scheduling_report'])
        _write(workflow.run_dir / 'MEDIA_HANDOFF.json', handoff)
        workflow.state.update(status='media_handoff_pending_capability', text_pass_sequence=1,
                              handoff_sha256=_hash(handoff))
        from src.content_factory.creative_governed_runtime import focused_artifacts
        governance_artifacts = focused_artifacts(workflow)
        output_manifest = workflow._write_output_manifest(handoff=handoff, artifact_purposes={
            name: purpose for name, purpose in [*governance_artifacts.items(),
                ('CONTINUATION_INPUTS.json', 'Explicit approved-script continuation'),
                ('ASSET_CATALOG_BINDING.json', 'Inherited asset catalog'),
                *([('STATE_PLAN.json', 'Reviewed whole-film state and action plan')] if series else []),
                *([('SCHEDULED_STATE_PLAN.json', 'Program-scheduled reviewed action plan'), ('SCHEDULING_REPORT.json', 'Deterministic timing choices')] if scheduled_context else []),
                ('SCREENPLAY.json', 'Approved screenplay'), ('STORYBOARD.json', 'Reviewed storyboard'),
                ('PRODUCTION_DESIGN.json', 'Reviewed asset and first-frame plan'),
                ('EXECUTION_DRAFT.json', 'Execution draft'), ('MEDIA_CAPABILITY_AUDIT.json', 'Capability audit'),
                ('SEEDANCE_SEGMENT_PLAN.json', 'Segment templates'), ('TEXT_REVIEW_HISTORY.json', 'Actual review bindings'),
                ('EDITORIAL_REVIEW_PACKET.json', 'Final assistant editorial review packet'),
                ('MEDIA_HANDOFF.json', 'Media-locked handoff'),
            ]})
        workflow.state['output_manifest_sha256'] = _hash(output_manifest)
        workflow._save()
        return workflow.state
    except Exception as exc:
        workflow.state.update(status='production_exception', error_type=type(exc).__name__, error=str(exc))
        workflow._save()
        return workflow.state
    finally:
        ledger['rounds'][str(number)].update(
            status=workflow.state['status'], calls_started=workflow.state['calls_started'],
            reported_tokens=workflow.state.get('reported_tokens', 0), updated_at=now(),
            source_at_latest_run=source_snapshot(),
            error=workflow.state.get('error'), pending_evidence_review=workflow.state.get('pending_evidence_review'),
        )
        ledger['new_calls_started'] = sum(r.get('calls_started', 0) for r in ledger['rounds'].values())
        ledger['new_reported_tokens'] = sum(r.get('reported_tokens', 0) for r in ledger['rounds'].values())
        _write(root / 'THREE_CYCLE_LEDGER.json', ledger)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--round', type=int, required=True, choices=(1, 2, 3))
    parser.add_argument('--root', type=Path, default=ROOT / 'data/production_trials/say_no_three_production_cycles_20260928')
    parser.add_argument('--parent', type=Path, default=ROOT / 'data/creative_workflows/say_no_reviewed_segments_20260927')
    parser.add_argument('--screenplay', type=Path, default=ROOT / 'data/production_trials/say_no_reviewed_segments_20260927/REVIEWED_SCREENPLAY.json')
    parser.add_argument('--series', choices=('legacy', NEW_SERIES, TWO_SERIES, OPTIMIZED_SERIES, GOVERNED_SERIES), default=NEW_SERIES)
    parser.add_argument('--prior-root', type=Path, default=PRIOR_ROOT)
    args = parser.parse_args()
    state = run_round(args.root, args.round, args.parent, args.screenplay,
                      series=None if args.series == 'legacy' else args.series, prior_root=args.prior_root)
    print(json.dumps({k: state.get(k) for k in ('status', 'calls_started', 'reported_tokens', 'pending_evidence_review', 'blocked_segment', 'error', 'unresolved_issues')}, ensure_ascii=False, indent=2))
    return 2 if state['status'] in ('production_exception', 'needs_revision') else 0


if __name__ == '__main__':
    raise SystemExit(main())
