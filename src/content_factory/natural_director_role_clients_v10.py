"""Explicit DeepSeek JSON output, while MiniMax remains native natural text.

This adapter never retries or adds tools. It preserves a received native
envelope before rejecting unknown usage, truncation, or a wrong response.
"""
from __future__ import annotations

from copy import deepcopy

from .creative_workflow_roles import (
    CreativeRoleClients, RoleResult, RoleResponseError, role_config,
    _response_model_matches,
)
from src.shared.config import settings

VERSION = "natural_director_role_clients/v10"
JSON_OBJECT = {"type": "json_object"}


class NaturalDirectorRoleClients(CreativeRoleClients):
    def call(self, role, messages, *, max_tokens=12000, temperature=0.4,
             thinking=None, response_format=None, structured_schema=None):
        if structured_schema is not None:
            raise ValueError("Natural director route cannot use structured tools")
        if role == "writer":
            if response_format is not None:
                raise ValueError("MiniMax natural text cannot use JSON output or tools")
            return super().call(role, messages, max_tokens=max_tokens,
                                temperature=temperature, thinking=thinking)
        if role != "director" or response_format != JSON_OBJECT:
            raise ValueError("DeepSeek review requires explicit recorded JSON-object output")
        if thinking not in (None, "disabled"):
            raise ValueError("Only the verified DeepSeek thinking setting is accepted")
        if type(max_tokens) is not int or not 1 <= max_tokens <= 20000:
            raise ValueError("Review output exceeds this adapter's bounded request range")
        # Official JSON Output requires an explicit JSON instruction as well.
        if not any("JSON" in str(message.get("content", "")).upper() for message in messages):
            raise ValueError("JSON Output requires an explicit JSON instruction")
        from openai import OpenAI
        config = role_config(role)
        parameters = {"model": config.model, "messages": messages,
                      "max_tokens": max_tokens, "temperature": temperature,
                      "response_format": deepcopy(response_format)}
        if thinking == "disabled":
            parameters["extra_body"] = {"thinking": {"type": "disabled"}}
        client = OpenAI(api_key=config.api_key, base_url=config.base_url,
                        timeout=settings.SCRIPT_LLM_TIMEOUT_SECONDS, max_retries=0)
        try:
            response = client.chat.completions.create(**parameters)
        except Exception as exc:
            status, request_id = getattr(exc, "status_code", None), getattr(exc, "request_id", None)
            raise RuntimeError(
                f"{role} API call failed: {type(exc).__name__}; "
                f"status={status if type(status) is int else 'unknown'}; "
                f"request_id={request_id if isinstance(request_id, str) else 'unknown'}"
            ) from None
        # Save the complete received object, including native usage/reasoning.
        snapshot = response.model_dump(mode="json")
        choices = getattr(response, "choices", None) or []
        choice = choices[0] if len(choices) == 1 else None
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None)
        metadata = {"role": role, "provider": config.provider,
                    "requested_model": config.model,
                    "response_model": str(getattr(response, "model", "") or ""),
                    "response_id": str(getattr(response, "id", "") or ""),
                    "finish_reason": str(getattr(choice, "finish_reason", "") or ""),
                    "thinking_mode": thinking or "provider_default", "output_mode": "content",
                    "response_format": deepcopy(response_format), "client_version": VERSION}
        usage = getattr(response, "usage", None)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = getattr(usage, key, None)
            if type(value) is int and value >= 0:
                metadata[key] = value

        def reject(code, detail):
            metadata["response_fault_code"] = code
            raise RoleResponseError(detail, metadata, response_text=content,
                                    response_payload=snapshot)

        if metadata["finish_reason"] == "length":
            reject("RESPONSE_TRUNCATED", "DeepSeek native response reached its output bound")
        if choice is None:
            reject("INVALID_RESPONSE_CHOICES", "A single native review choice is required")
        if not _response_model_matches(role, config.model, metadata["response_model"]):
            reject("MODEL_MISMATCH", "Native model differs from the frozen review model")
        if metadata["finish_reason"] != "stop":
            reject("RESPONSE_NOT_COMPLETED", "Native review did not explicitly stop")
        if getattr(message, "tool_calls", None):
            reject("UNEXPECTED_TOOL_CALL", "Natural director review does not use tools")
        if not isinstance(content, str) or not content.strip():
            reject("EMPTY_RESPONSE", "Native review content is missing")
        if any(key not in metadata for key in ("prompt_tokens", "completion_tokens", "total_tokens")):
            reject("USAGE_UNKNOWN", "Native review usage is missing or invalid")
        if metadata["total_tokens"] != metadata["prompt_tokens"] + metadata["completion_tokens"]:
            reject("USAGE_MISMATCH", "Native review usage does not reconcile")
        return RoleResult(content, metadata, snapshot)
