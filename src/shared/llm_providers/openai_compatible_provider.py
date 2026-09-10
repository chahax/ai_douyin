# -*- coding: utf-8 -*-
from openai import OpenAI

from src.shared.llm_providers.base import BaseLLMProvider
from src.shared.logger import logger


def _field(value, name):
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _usage_counts(value):
    """Retain supplied token counts only; absent/unknown values are not zero."""
    fields = value if isinstance(value, dict) else getattr(value, '__dict__', {})
    result = {}
    for key, item in fields.items():
        if not isinstance(key, str):
            continue
        if key.endswith('_tokens') and type(item) is int and item >= 0:
            result[key] = item
        elif key.endswith('_tokens_details'):
            details = _usage_counts(item)
            if details:
                result[key] = details
    return result


def _response_metadata(response):
    """Read an allowlist, never response bodies, headers or reasoning text."""
    result = {}
    for source, target in (('id', 'response_id'), ('model', 'response_model')):
        value = _field(response, source)
        if isinstance(value, str) and value:
            result[target] = value
    usage = _usage_counts(_field(response, 'usage'))
    if usage:
        result['usage'] = usage
    choices = _field(response, 'choices')
    reason = _field(choices[0], 'finish_reason') if isinstance(choices, (list, tuple)) and choices else None
    if isinstance(reason, str) and reason:
        result['finish_reason'] = reason
    return result


class OpenAICompatibleProvider(BaseLLMProvider):
    def __init__(self, api_key: str, base_url: str, model: str, timeout_seconds: int = 120,
                 max_retries: int = 2, max_tokens=None, preserve_invalid_json=False, extra_body=None):
        self.client = OpenAI(
            api_key=api_key or "EMPTY",
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
        self.model = model
        self.max_tokens = max_tokens
        self.preserve_invalid_json = preserve_invalid_json
        self.last_response_metadata = {}
        self.extra_body = extra_body

    def chat_completion(self, messages, temperature=0.7, json_mode=False):
        # Callers' model_output files contain this provider's cleaned text, not
        # an exact HTTP response. JSON normalization can remove wrappers/fences;
        # both paths can remove a leading thought block. No reasoning is saved.
        self.last_response_metadata = {
            'content_processing': 'json_normalization' if json_mode else 'text_normalization',
            'content_is_raw_http_response': False,
        }
        try:
            # MiniMax 等部分 OpenAI 兼容服务要求 response_format 字段始终存在
            response_format = {"type": "json_object"} if json_mode else {"type": "text"}
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                response_format=response_format,
                **({'max_tokens': self.max_tokens} if self.max_tokens is not None else {}),
                **({'extra_body': self.extra_body} if self.extra_body is not None else {}),
            )
            self.last_response_metadata.update(_response_metadata(response))
            content = response.choices[0].message.content
            if json_mode:
                normalized = self.normalize_json_content(content)
                if normalized:
                    return normalized
                logger.error("OpenAI-compatible provider returned non-JSON content in json_mode; finish_reason={}",
                             response.choices[0].finish_reason)
                if self.preserve_invalid_json:
                    # The script workflow owns validation and retains malformed drafts for repair.
                    self.last_response_metadata['content_processing'] = 'text_normalization_after_invalid_json'
                    return self.normalize_text_content(content)
                return None
            return self.normalize_text_content(content)
        except Exception as exc:
            # A status error may expose safe response fields in its parsed body.
            # Retain metadata already captured before a content-processing error.
            body = getattr(exc, 'body', None)
            if isinstance(body, dict):
                self.last_response_metadata.update(_response_metadata(body))
            self.last_response_metadata['error_type'] = type(exc).__name__
            request_id = getattr(exc, 'request_id', None)
            if isinstance(request_id, str) and request_id:
                self.last_response_metadata['request_id'] = request_id
            status = getattr(exc, 'status_code', None)
            if type(status) is int:
                self.last_response_metadata['status_code'] = status
            logger.error('OpenAI-compatible LLM error: {}', type(exc).__name__)
            return None

    def chat_with_tools(self, messages, tools, temperature=0.3, tool_choice="auto"):
        """Native tool calling 入口（OpenAI 兼容协议）。

        Returns:
            dict: {"content": str, "tool_calls": list[raw]}
            tool_calls 是 LLM 原始 shape（dict 之间），跨供应商归一化在
            src/shared/llm_client.py:_normalize_tool_calls() 层做。

        tool_choice：默认 "auto"，让模型在"继续调工具"和"输出最终自然语言回复"
        之间自由选择——这是多轮 tool loop 能收敛的前提。调用方在"必然要动作"的
        单步场景可显式传 "required"。
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                tools=tools,
                tool_choice=tool_choice,
            )
            msg = response.choices[0].message
            content = msg.content or ""

            # OpenAI 兼容 provider 通常给出 dict 形态 tool_calls
            raw_calls = []
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    # tc 是 openai.types.chat.chat_completion_message_function_tool_call
                    if hasattr(tc, "function") and hasattr(tc.function, "name"):
                        # 序列化为 dict 让上层统一处理
                        args_str = tc.function.arguments or "{}"
                        raw_calls.append({
                            "id": getattr(tc, "id", None),
                            "name": tc.function.name,
                            "args": args_str,   # 留 string，让 _normalize_tool_call() 解析
                            # 也保留 function 兜底（部分客户端返回另一种形态）
                            "function": {
                                "name": tc.function.name,
                                "arguments": args_str,
                            }
                        })
                    elif isinstance(tc, dict):
                        raw_calls.append(tc)
            return {"content": content, "tool_calls": raw_calls}
        except Exception as exc:
            logger.error(f"OpenAI-compatible tools LLM error: {exc}")
            return {"content": "", "tool_calls": []}
