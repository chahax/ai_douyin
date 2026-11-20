"""Isolated M3.1 Flash text trial; no production routing or provider fallback."""
from __future__ import annotations

import re

from .creative_workflow_roles import RoleResponseError, RoleResult, role_config
from src.shared.config import settings

VERSION = "minimax_text_trial_client/v1"
MODEL = "MiniMax-M3.1-Flash"
REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})


class MiniMaxTextTrialClient:
    def __init__(self, model=MODEL, reasoning_effort="medium"):
        if model != MODEL:
            raise ValueError("This isolated trial only supports MiniMax-M3.1-Flash")
        if reasoning_effort not in REASONING_EFFORTS:
            raise ValueError("Unsupported MiniMax trial reasoning effort")
        self.model = model
        self.reasoning_effort = reasoning_effort

    def call(self, role, messages, *, max_tokens=12000, temperature=None,
             thinking=None, response_format=None):
        if role != "writer":
            raise ValueError("MiniMax text trial only supports the writer role")
        if thinking not in (None, "adaptive"):
            raise ValueError("MiniMax-M3.1-Flash requires adaptive thinking")
        if response_format is not None:
            raise ValueError("This natural-text trial does not use response_format")
        if type(max_tokens) is not int or max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer including thinking")
        config = role_config("writer")
        if config.provider != "minimax":
            raise ValueError("MiniMax text trial cannot use another provider")

        from openai import OpenAI

        client = OpenAI(api_key=config.api_key, base_url=config.base_url,
                        timeout=settings.SCRIPT_LLM_TIMEOUT_SECONDS, max_retries=0)
        # M3.1 always thinks; sampling parameters are fixed by the provider.
        # Keep the prompt's JSON contract, without adding tools/JSON mode.
        parameters = {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens": max_tokens,
            "reasoning_effort": self.reasoning_effort,
            "extra_body": {"thinking": {"type": "adaptive"}, "reasoning_split": True},
        }
        try:
            response = client.chat.completions.create(**parameters)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            request_id = getattr(exc, "request_id", None)
            safe_id = request_id if (
                isinstance(request_id, str)
                and re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", request_id)
            ) else "unknown"
            raise RuntimeError(
                f"writer API call failed: {type(exc).__name__}; "
                f"status={status if type(status) is int else 'unknown'}; "
                f"request_id={safe_id}"
            ) from None

        snapshot = response.model_dump(mode="json")
        choices = getattr(response, "choices", None) or []
        choice = choices[0] if len(choices) == 1 else None
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None)
        metadata = {
            "role": role, "provider": config.provider,
            "requested_model": self.model,
            "response_model": str(getattr(response, "model", "") or ""),
            "response_id": str(getattr(response, "id", "") or ""),
            "finish_reason": str(getattr(choice, "finish_reason", "") or ""),
            "thinking_mode": "adaptive", "reasoning_effort": self.reasoning_effort,
            "output_mode": "content", "client_version": VERSION,
        }
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
            reject("RESPONSE_TRUNCATED", "MiniMax trial response reached its output bound")
        if choice is None:
            reject("INVALID_RESPONSE_CHOICES", "A single native trial choice is required")
        if metadata["response_model"].strip().lower() != self.model.lower():
            reject("MODEL_MISMATCH", "Native model differs from the frozen trial model")
        if metadata["finish_reason"] != "stop":
            reject("RESPONSE_NOT_COMPLETED", "Native trial did not explicitly stop")
        if getattr(message, "tool_calls", None):
            reject("UNEXPECTED_TOOL_CALL", "MiniMax natural-text trial does not use tools")
        if not isinstance(content, str) or not content.strip():
            reject("EMPTY_RESPONSE", "Native trial content is missing")
        if any(key not in metadata for key in ("prompt_tokens", "completion_tokens", "total_tokens")):
            reject("USAGE_UNKNOWN", "Native trial usage is missing or invalid")
        if metadata["total_tokens"] != metadata["prompt_tokens"] + metadata["completion_tokens"]:
            reject("USAGE_MISMATCH", "Native trial usage does not reconcile")
        return RoleResult(content, metadata, snapshot)
