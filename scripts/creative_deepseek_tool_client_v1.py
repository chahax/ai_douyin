"""Explicit DeepSeek ordinary-tool experiment; no strict/beta guarantee.

Writer calls delegate unchanged to the frozen creative role client. Director
calls retain its configured provider, endpoint and model, while requiring one
named function result. A response is still locally validated by the operator.
"""
from __future__ import annotations
from copy import deepcopy
from typing import Any

from src.content_factory.creative_workflow_roles import (
    CreativeRoleClients as FrozenCreativeRoleClients,
    RoleResult, RoleResponseError, role_config, _response_model_matches,
)
from src.shared.config import settings

VERSION = 'creative_deepseek_ordinary_tool_client/v1'
TOOL_NAME = 'submit_creative_json'


class DeepSeekToolPreflightError(RuntimeError):
    provider_dispatch_started = False


def _api_error(exc, *, started):
    # SDK errors can contain headers and full request bodies; never stringify them.
    status = getattr(exc, 'status_code', None)
    request_id = getattr(exc, 'request_id', None)
    error = RuntimeError(
        f'director API 调用失败: {type(exc).__name__}; '
        f"status={status if type(status) is int else 'unknown'}; "
        f"request_id={request_id if isinstance(request_id, str) else 'unknown'}"
    )
    error.provider_dispatch_started = started
    return error


class CreativeDeepSeekToolClients:
    """Same call interface; only the explicitly requested director transport changes."""

    def call(self, role: str, messages: list[dict[str, str]], *, max_tokens: int = 12000,
             temperature: float = 0.4, thinking: str | None = None,
             structured_schema: dict[str, Any] | None = None,
             writer_model: str | None = None) -> RoleResult:
        if role == 'writer':
            return FrozenCreativeRoleClients().call(
                role, messages, max_tokens=max_tokens, temperature=temperature,
                thinking=thinking, structured_schema=structured_schema, writer_model=writer_model)
        if role != 'director':
            raise DeepSeekToolPreflightError('该实验客户端仅用于已确认的创作角色')
        if writer_model is not None:
            raise DeepSeekToolPreflightError('director不能覆盖编剧型号')
        if not isinstance(structured_schema, dict) or not structured_schema:
            raise DeepSeekToolPreflightError('director工具实验必须绑定完整本地验收schema')
        if thinking not in (None, 'disabled'):
            raise DeepSeekToolPreflightError('命名强制工具仅使用已确认的disabled模式')
        if type(max_tokens) is not int or not 0 < max_tokens <= 32000:
            raise DeepSeekToolPreflightError('需要明确有限的正整数输出上限')
        if temperature != 0.4 or isinstance(temperature, bool):
            raise DeepSeekToolPreflightError('工具实验保持已确认的temperature=0.4')
        try:
            from openai import OpenAI
            config = role_config('director')
            client = OpenAI(api_key=config.api_key, base_url=config.base_url,
                            timeout=settings.SCRIPT_LLM_TIMEOUT_SECONDS, max_retries=0)
        except Exception as exc:
            raise _api_error(exc, started=False) from None
        parameters = {
            'model': config.model, 'messages': deepcopy(messages),
            'temperature': temperature, 'max_tokens': max_tokens,
            'extra_body': {'thinking': {'type': 'disabled'}},
            'tools': [{'type': 'function', 'function': {
                'name': TOOL_NAME, 'description': '提交本阶段完整文本审核结果，保留所有结论及真实证据',
                'parameters': deepcopy(structured_schema),
            }}],
            'tool_choice': {'type': 'function', 'function': {'name': TOOL_NAME}},
        }
        try:
            response = client.chat.completions.create(**parameters)
        except Exception as exc:
            raise _api_error(exc, started=True) from None
        choices = getattr(response, 'choices', None) or []
        choice = choices[0] if choices else None
        metadata = {
            'role': role, 'provider': config.provider, 'requested_model': config.model,
            'response_model': str(getattr(response, 'model', '') or ''),
            'response_id': str(getattr(response, 'id', '') or ''),
            'finish_reason': str(getattr(choice, 'finish_reason', '') or '') if choice else '',
            'thinking_mode': 'disabled', 'output_mode': 'unusable_response',
            'transport_version': VERSION, 'strict_mode': False,
            'server_schema_guarantee': False,
        }
        usage = getattr(response, 'usage', None)
        if usage is not None:
            for name in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
                value = getattr(usage, name, None)
                if type(value) is int and value >= 0:
                    metadata[name] = value
        snapshot_choices = []
        for item in choices:
            message = getattr(item, 'message', None)
            tools = getattr(message, 'tool_calls', None) or []
            snapshot_choices.append({
                'finish_reason': getattr(item, 'finish_reason', None),
                'message': {
                    'content': getattr(message, 'content', None),
                    'reasoning_content': getattr(message, 'reasoning_content', None),
                    'tool_calls': [{
                        'id': getattr(tool, 'id', None), 'type': getattr(tool, 'type', None),
                        'function': {
                            'name': getattr(getattr(tool, 'function', None), 'name', None),
                            'arguments': getattr(getattr(tool, 'function', None), 'arguments', None),
                        },
                    } for tool in tools],
                },
            })
        snapshot = {
            'id': metadata['response_id'], 'model': metadata['response_model'],
            'choices': snapshot_choices,
            'usage': {key: metadata[key] for key in ('prompt_tokens', 'completion_tokens', 'total_tokens') if key in metadata},
        }
        message = getattr(choice, 'message', None) if choice else None
        content = getattr(message, 'content', None)
        tools = getattr(message, 'tool_calls', None) or []
        correct_tool = (len(tools) == 1 and getattr(getattr(tools[0], 'function', None), 'name', None) == TOOL_NAME
                        and getattr(tools[0], 'type', 'function') == 'function')
        if correct_tool:
            content = getattr(tools[0].function, 'arguments', None)
            metadata['output_mode'] = 'tool_call'

        def reject(code, message):
            metadata['response_fault_code'] = code
            raise RoleResponseError(message, metadata, response_text=content, response_payload=snapshot)

        # Preserve known billing and the complete envelope before any rejection.
        if metadata['finish_reason'] == 'length':
            reject('RESPONSE_TRUNCATED', 'director API 正文未正常结束: length')
        if not choice:
            reject('NO_RESPONSE_CHOICES', 'director API 未返回候选内容')
        if len(choices) != 1:
            reject('UNEXPECTED_RESPONSE_CHOICES', 'director API 未返回唯一候选内容')
        if not metadata['response_model'].strip() or not _response_model_matches(role, config.model, metadata['response_model']):
            reject('MODEL_MISMATCH', 'director API 返回模型与已确认角色配置不符')
        if metadata['finish_reason'] not in ('stop', 'tool_calls'):
            reject('RESPONSE_NOT_COMPLETED', 'director API 正文未正常结束')
        if not correct_tool:
            reject('REQUIRED_TOOL_MISSING' if not tools else 'UNEXPECTED_TOOL_CALL',
                   'director API 未返回唯一的结构化工具调用')
        if not isinstance(content, str) or not content.strip():
            reject('EMPTY_RESPONSE', 'director API 返回空工具参数')
        return RoleResult(text=content, metadata=metadata, response_payload=snapshot)
