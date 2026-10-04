"""Version-bound focused review execution; immutable raw receipts, no hidden retries."""
from datetime import datetime, timezone
import json
from pathlib import Path
from time import monotonic

from .creative_review_gate import digest
from .creative_workflow_contract import CreativeContractError

VERSION = 'focused_review_packet_v1'


def enabled(workflow, name, context):
    return (workflow.state.get('review_packet_version') == VERSION
            and name.startswith('writer_check') and bool(context.get('state_plan')))


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write(path, value, immutable=False):
    path = Path(path)
    if immutable and path.exists() and _read(path) != value:
        raise RuntimeError('聚焦审核回执与原绑定不一致: ' + path.name)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def _effective_raw(root, name, raw, context):
    resolution_path = Path(root) / (name + "__focused_resolution.json")
    if not resolution_path.exists():
        return raw, None
    from .creative_review_resolution import apply_resolution
    resolution = _read(resolution_path)
    return apply_resolution(raw, context, resolution), digest(resolution)


def _expansion(raw, context, resolved=None, resolution_sha256=None):
    from .creative_review_packet import to_legacy_review
    effective = to_legacy_review(resolved if resolved is not None else raw, context)
    return {'schema': 'focused_review_expansion/v1', 'context_sha256': digest(context),
            'raw_review_sha256': digest(raw), 'resolution_sha256': resolution_sha256,
            'effective_review_sha256': digest(effective),
            'effective_review': effective, 'automatic_approval': False}


def run_review(workflow, name, role, context):
    from .creative_review_packet import build_packet, build_prompt, validate_review, review_disposition
    packet = build_packet(context)
    prompt = build_prompt(packet)
    from .creative_narrative_focus import prompt_for_stage
    prompt += prompt_for_stage(workflow.state.get("narrative_focus_binding"), name)
    if context.get('debug_must_fix_feedback'):
        prompt += '\n用户必修复核反馈（逐项回到原始证据复核，不代写正文）：' + json.dumps(context['debug_must_fix_feedback'], ensure_ascii=False)
    messages = [{'role': 'system', 'content': prompt},
                {'role': 'user', 'content': json.dumps(packet, ensure_ascii=False, separators=(',', ':'))}]
    root = Path(workflow.run_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / (name + '.json')
    from .creative_stage_contracts import record_input, reconcile_cached_stage
    record_input(workflow, name, role, context, digest(prompt), digest(context))
    reconcile_cached_stage(workflow, name, digest(context), digest(prompt))
    _write(root / (name + '__focused_input.json'), packet, immutable=True)
    binding = {'input_sha256': digest(context), 'packet_sha256': digest(packet),
               'prompt_sha256': digest(prompt), 'request_sha256': digest(messages)}
    workflow._active_stage_name = name
    if path.exists():
        record = _read(path)
        if any(record.get(k) != v for k, v in binding.items()):
            raise RuntimeError('聚焦审核恢复时上下文/规则/请求已改变')
        if record.get('status') not in ('response_received', 'validated'):
            raise RuntimeError('聚焦审核上次响应未确认或契约失败；禁止自动重复付费')
        if record.get('request', {}).get('messages') != messages:
            raise RuntimeError('聚焦审核请求回执被改变')
    else:
        if workflow.state['calls_started'] >= workflow.max_calls:
            raise RuntimeError('模型调用预算已满；聚焦审核未发送')
        from .creative_execution_control import check_dispatch
        check_dispatch(workflow, name)
        budget = workflow._reserve_tokens(role, messages, max_tokens=12000)
        record = {'schema': 'creative_stage/v1', 'status': 'pending_response',
                  'stage': name, 'role': role, **binding, 'context_budget': budget,
                  'request': {'messages': messages, 'parameters': {
                      'max_tokens': 12000, 'temperature': 0.2, 'thinking': 'disabled'}},
                  'started_at': datetime.now(timezone.utc).isoformat()}
        _write(path, record)
        workflow.state['calls_started'] += 1
        workflow._save()
        started = monotonic()
        try:
            response = workflow._call_model(role, messages, max_tokens=12000,
                temperature=0.2, thinking='disabled', structured_schema=None)
        except Exception as exc:
            record.update(status='blocked_before_dispatch' if getattr(exc, 'provider_dispatch_started', None) is False else 'call_failed_or_uncertain', provider_dispatch_started=getattr(exc, 'provider_dispatch_started', None), error=str(exc),
                          elapsed_seconds=monotonic()-started)
            _write(path, record)
            raise
        record.update(response_text=response.text, response_metadata=response.metadata,
                      status='response_received', elapsed_seconds=monotonic()-started,
                      completed_at=datetime.now(timezone.utc).isoformat())
        _write(path, record)
    try:
        if record.get('response_metadata', {}).get('finish_reason') not in (None, 'stop', 'tool_calls'):
            raise CreativeContractError('FOCUSED_REVIEW_INCOMPLETE_RESPONSE')
        # JSON parsing never calls a format-repair model. Original content remains intact.
        raw = json.loads(record['response_text'])
        validate_review(raw, packet)
        if 'output' in record and (record['output'] != raw or record.get('output_sha256') != digest(raw)):
            raise RuntimeError('聚焦审核原始响应与已存输出不一致')
    except (ValueError, CreativeContractError) as exc:
        record.update(status='contract_failed', error=str(exc))
        _write(path, record)
        raise
    record.update(status='validated', output=raw, output_sha256=digest(raw))
    _write(path, record)
    if not any(s['name'] == name and s.get('input_sha256') == binding['input_sha256'] and s.get('output_sha256') == digest(raw) for s in workflow.state['stages']):
        workflow.state['stages'].append({'name': name, 'role': role,
            'input_sha256': binding['input_sha256'], 'output_sha256': digest(raw),
            'context_budget': record.get('context_budget'), 'usage': record.get('response_metadata')})
    disposition = review_disposition(raw, packet)
    _write(root / (name + '__disposition.json'), disposition, immutable=True)
    resolved, resolution_hash = _effective_raw(root, name, raw, context)
    effective_disposition = review_disposition(resolved, packet)
    if effective_disposition['requires_resolution']:
        workflow.state.update(status='needs_attention', pending_focused_review={
            'key': name, 'disposition': disposition, 'raw_review_sha256': digest(raw),
            'context_sha256': digest(context), 'automatic_retry': False})
        workflow._save()
        raise CreativeContractError('FOCUSED_REVIEW_NEEDS_RESOLUTION: ' + disposition['disposition'])
    expansion = _expansion(raw, context, resolved, resolution_hash)
    if workflow.state.get('pending_focused_review', {}).get('key') == name:
        workflow.state.pop('pending_focused_review')
    _write(root / (name + '__focused_review_expansion.json'), expansion, immutable=True)
    workflow._save()
    return expansion['effective_review']


def verify_expansion(workflow, key, review, context):
    root = Path(workflow.run_dir)
    record = _read(root / (key + '.json'))
    if record.get('input_sha256') != digest(context) or record.get('status') != 'validated':
        raise RuntimeError('聚焦审核未绑定当前上下文或尚未校验')
    raw = json.loads(record['response_text'])
    if raw != record['output'] or digest(raw) != record.get('output_sha256'):
        raise RuntimeError('聚焦审核原始响应被改变')
    from .creative_review_packet import build_packet, build_prompt, review_disposition
    packet = build_packet(context)
    if digest(packet) != record['packet_sha256'] or _read(root / (key + '__focused_input.json')) != packet:
        raise RuntimeError('聚焦审核源映射被改变')
    from .creative_narrative_focus import prompt_for_stage
    prompt = build_prompt(packet) + prompt_for_stage(workflow.state.get("narrative_focus_binding"), key)
    if context.get('debug_must_fix_feedback'):
        prompt += '\n用户必修复核反馈（逐项回到原始证据复核，不代写正文）：' + json.dumps(context['debug_must_fix_feedback'], ensure_ascii=False)
    messages = [{'role':'system','content':prompt},
                {'role':'user','content':json.dumps(packet,ensure_ascii=False,separators=(',', ':'))}]
    if (record.get('request_sha256') != digest(messages)
            or record.get('request',{}).get('messages') != messages
            or record.get('prompt_sha256') != digest(prompt)):
        raise RuntimeError('聚焦审核请求或提示词回执被改变')
    if _read(root / (key + '__disposition.json')) != review_disposition(raw, packet):
        raise RuntimeError('聚焦审核处置回执被改变')
    resolved, resolution_hash = _effective_raw(root, key, raw, context)
    expansion = _expansion(raw, context, resolved, resolution_hash)
    if expansion['effective_review'] != review or _read(root / (key + '__focused_review_expansion.json')) != expansion:
        raise RuntimeError('聚焦审核展开与原模型/当前上下文不一致')
