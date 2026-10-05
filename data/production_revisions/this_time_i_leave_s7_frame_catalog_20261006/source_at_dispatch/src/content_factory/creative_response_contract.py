"""Response faults are distinct from creative validation faults; never dispatch."""
from __future__ import annotations
from .creative_workflow_contract import CreativeContractError


class CreativeResponseContractError(CreativeContractError):
    def __init__(self, failure):
        self.detail = failure
        super().__init__(failure['code'] + ': ' + failure['next_action'])


def fault(code, category, next_action, *, received=False):
    return {'schema': 'creative_failure/v1', 'code': code, 'category': category,
            'next_action': next_action, 'response_received': received,
            'automatic_retry': False, 'blocks_handoff': True}


def response_failure(metadata, text, *, require_tool=False):
    """Length precedes missing tool, including legacy content fallback."""
    reason = metadata.get('finish_reason')
    if reason == 'length':
        return fault('RESPONSE_TRUNCATED', 'interface', 'diagnose_output_protocol', received=True)
    if reason not in (None, '', 'stop', 'tool_calls'):
        return fault('RESPONSE_NOT_COMPLETED', 'interface', 'diagnose_output_protocol', received=True)
    code = metadata.get('response_fault_code')
    if code:
        return fault(code, 'interface', 'diagnose_output_protocol', received=True)
    if require_tool and metadata.get('output_mode') != 'tool_call':
        return fault('REQUIRED_TOOL_MISSING', 'interface', 'diagnose_output_protocol', received=True)
    if not isinstance(text, str) or not text.strip():
        return fault('EMPTY_RESPONSE', 'interface', 'diagnose_output_protocol', received=True)
    return None


def receipt_failure(record, *, require_tool=False):
    if record.get('failure'):
        return record['failure']
    metadata = record.get('response_metadata', {})
    status = record.get('status')
    if status in ('response_received', 'incomplete_response') or metadata:
        return response_failure(metadata, record.get('response_text'), require_tool=require_tool)
    if status in ('pending_response', 'call_failed_or_uncertain'):
        error = str(record.get('call_error', record.get('error', '')))
        if 'API 未返回唯一的结构化工具调用' in error:
            return fault('REQUIRED_TOOL_MISSING', 'interface', 'diagnose_output_protocol', received=True)
        if 'API 返回空正文' in error:
            return fault('EMPTY_RESPONSE', 'interface', 'diagnose_output_protocol', received=True)
        return fault('OUTCOME_UNKNOWN', 'interface', 'reconcile_original_request')
    return None


def exception_failure(exc):
    if getattr(exc, 'provider_dispatch_started', None) is False:
        return fault('BLOCKED_BEFORE_DISPATCH', 'control', 'resolve_dispatch_gate')
    metadata = getattr(exc, 'response_metadata', None)
    if isinstance(metadata, dict):
        return response_failure(metadata, getattr(exc, 'response_text', None)) or fault(
            'UNUSABLE_RESPONSE', 'interface', 'diagnose_output_protocol', received=True)
    return receipt_failure({'status': 'call_failed_or_uncertain', 'error': str(exc)})


def validation_failure(error):
    detail = getattr(error, 'detail', {})
    message = str(error)
    code = detail.get('code') or message.split(':', 1)[0]
    if code == 'PLAN_SCHEMA_INVALID':
        category, action = 'state_contract', 'bounded_schema_repair_then_full_validation'
    elif code.startswith('MODULE_'):
        category, action = 'state_contract', 'complete_new_draft_then_full_review'
    elif code.startswith('PLAN_'):
        category, action = 'state_contract', 'complete_new_plan_then_full_review'
    elif '无法排入' in message or code.startswith('EXPRESSION_'):
        category, action = 'compilation', 'review_expression_contract_or_complete_new_plan'
    else:
        category, action = 'validation', 'existing_bounded_contract_repair'
    return fault(code, category, action, received=True)
