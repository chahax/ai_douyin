"""Fail-closed, role-specific API clients for the creative workflow."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from src.shared.config import settings


ROLE_CONTEXT_CAPABILITIES: dict[str, dict[str, Any]] = {
    "writer": {
        "provider": "minimax",
        "model": "MiniMax-M3",
        # MiniMax advertises up to 1M and guarantees at least 512K for M3.
        # Planning against the guaranteed floor avoids treating "up to" as a
        # promise for every endpoint/account configuration.
        "planning_context_window_tokens": 512_000,
        "advertised_context_window_tokens": 1_000_000,
        "source_url": "https://www.minimax.io/models/text/m3",
        "verified_on": "2026-09-24",
    },
    "director": {
        "provider": "deepseek",
        "model": "deepseek-flash",
        "planning_context_window_tokens": 1_000_000,
        "advertised_context_window_tokens": 1_000_000,
        "source_url": "https://api-docs.deepseek.com/quick_start/pricing/",
        "verified_on": "2026-09-24",
    },
}


def role_context_capability(role: str) -> dict[str, Any]:
    """Return the documented context basis used for pre-call planning."""
    if role not in ROLE_CONTEXT_CAPABILITIES:
        raise ValueError(f"未知创作角色: {role}")
    return dict(ROLE_CONTEXT_CAPABILITIES[role])


def _response_model_matches(role: str, requested: str, returned: str) -> bool:
    normalized = returned.strip().lower()
    if role == "writer":
        return normalized == requested.lower()
    if role == "director":
        return normalized in {
            requested.lower(), "deepseek-v4.1-flash", "deepseek-v4_1-flash",
        }
    return False


class RoleResponseError(RuntimeError):
    """Provider responded, but output is unusable; preserve known billing safely."""
    def __init__(self, message, metadata, *, response_text=None, response_payload=None):
        super().__init__(message)
        self.response_metadata = dict(metadata)
        self.response_text = response_text
        self.response_payload = response_payload


@dataclass(frozen=True)
class RoleResult:
    text: str
    metadata: dict[str, Any]
    response_payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class RoleConfig:
    provider: str
    model: str
    base_url: str
    api_key: str


def role_config(role: str) -> RoleConfig:
    if role == "writer":
        value = RoleConfig(
            settings.WRITER_AGENT_PROVIDER,
            settings.WRITER_AGENT_MODEL,
            settings.WRITER_AGENT_BASE_URL,
            settings.WRITER_AGENT_API_KEY,
        )
        if value.provider != "minimax" or value.model != "MiniMax-M3":
            raise ValueError("编剧角色必须使用已确认的 MiniMax-M3")
    elif role == "director":
        value = RoleConfig(
            settings.DIRECTOR_AGENT_PROVIDER,
            settings.DIRECTOR_AGENT_MODEL,
            settings.DIRECTOR_AGENT_BASE_URL,
            settings.DIRECTOR_AGENT_API_KEY,
        )
        if value.provider != "deepseek" or value.model != "deepseek-flash":
            raise ValueError("导演角色必须使用已确认的 DeepSeek V4.1 Flash")
    else:
        raise ValueError(f"未知创作角色: {role}")
    if not value.api_key.strip():
        raise ValueError(f"{role} Token 尚未配置")
    return value


class CreativeRoleClients:
    """No fallback to the project's single generic LLM route or another vendor."""

    def call(
        self,
        role: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 12000,
        temperature: float = 0.4,
        thinking: str | None = None,
        structured_schema: dict[str, Any] | None = None,
        writer_model: str | None = None,
    ) -> RoleResult:
        from openai import OpenAI

        config = role_config(role)
        if writer_model is not None:
            if role != "writer" or writer_model not in ("MiniMax-M3", "MiniMax-M2.7"):
                raise ValueError("显式编剧测试型号仅支持同供应商的M3或M2.7")
            config = replace(config, model=writer_model)
        client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=settings.SCRIPT_LLM_TIMEOUT_SECONDS,
            max_retries=0,
        )
        if thinking not in (None, "disabled", "adaptive") or (thinking == "adaptive" and role != "writer"):
            raise ValueError("仅MiniMax编剧支持adaptive思考，其他角色沿用已验证模式")
        if structured_schema is not None and role != "writer":
            raise ValueError("结构化工具调用仅用于已验证的 MiniMax 编剧角色")
        try:
            parameters: dict[str, Any] = {
                "model": config.model,
                "messages": messages,
                "temperature": temperature,
            }
            if role == "writer":
                parameters["max_completion_tokens"] = max_tokens
                if thinking in ("disabled", "adaptive"):
                    parameters["extra_body"] = {"thinking": {"type": thinking}}
                    if thinking == "adaptive":
                        parameters["extra_body"]["reasoning_split"] = True
                if writer_model == "MiniMax-M2.7":
                    parameters.setdefault("extra_body", {})["reasoning_split"] = True
                if structured_schema is not None:
                    parameters["tools"] = [{
                        "type": "function",
                        "function": {
                            "name": "submit_creative_json",
                            "description": "提交本阶段完整结构化创作结果",
                            "parameters": structured_schema,
                        },
                    }]
                    parameters["tool_choice"] = {
                        "type": "function", "function": {"name": "submit_creative_json"},
                    }
            else:
                parameters["max_tokens"] = max_tokens
                if thinking == "disabled":
                    parameters["extra_body"] = {"thinking": {"type": "disabled"}}
            response = client.chat.completions.create(
                **parameters,
            )
        except Exception as exc:
            # API exceptions can include request bodies; expose only safe fields.
            status = getattr(exc, "status_code", None)
            request_id = getattr(exc, "request_id", None)
            raise RuntimeError(
                f"{role} API 调用失败: {type(exc).__name__}; "
                f"status={status if isinstance(status, int) else 'unknown'}; "
                f"request_id={request_id if isinstance(request_id, str) else 'unknown'}"
            ) from None

        metadata: dict[str, Any] = {
            "role": role,
            "provider": config.provider,
            "requested_model": config.model,
            "response_model": str(getattr(response, "model", "") or ""),
            "response_id": str(getattr(response, "id", "") or ""),
            "finish_reason": str(getattr(response.choices[0], "finish_reason", "") or "") if response.choices else "",
            "thinking_mode": thinking or "provider_default",
            "output_mode": "unusable_response",
        }
        usage = getattr(response, "usage", None)
        if usage is not None:
            for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = getattr(usage, name, None)
                if type(value) is int and value >= 0:
                    metadata[name] = value
        # Preserve the received envelope before rejecting it. This contains no
        # request headers, credentials or request body.
        snapshot = {
            "id": metadata["response_id"], "model": metadata["response_model"],
            "choices": [{
                "finish_reason": getattr(c, "finish_reason", None),
                "message": {
                    "content": getattr(c.message, "content", None),
                    "reasoning_content": getattr(c.message, "reasoning_content", None),
                    "tool_calls": [{
                        "id": getattr(t, "id", None), "type": getattr(t, "type", None),
                        "function": {"name": t.function.name, "arguments": t.function.arguments},
                    } for t in (getattr(c.message, "tool_calls", None) or [])],
                },
            } for c in response.choices],
            "usage": {k: metadata[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens") if k in metadata},
        }
        choice = response.choices[0] if response.choices else None
        content = getattr(choice.message, "content", None) if choice else None
        tools = (getattr(choice.message, "tool_calls", None) or []) if choice else []
        correct_tool = len(tools) == 1 and tools[0].function.name == "submit_creative_json"
        if structured_schema is not None and correct_tool:
            content = tools[0].function.arguments
            metadata["output_mode"] = "tool_call"
        elif structured_schema is None:
            metadata["output_mode"] = "content"

        def reject(code, message):
            metadata["response_fault_code"] = code
            raise RoleResponseError(message, metadata, response_text=content, response_payload=snapshot)

        # Never misclassify truncation as a tool or JSON repair.
        if metadata["finish_reason"] == "length":
            reject("RESPONSE_TRUNCATED", f"{role} API 正文未正常结束: length")
        if not choice:
            reject("NO_RESPONSE_CHOICES", f"{role} API 未返回候选内容")
        response_model = metadata["response_model"].strip()
        if not response_model or not _response_model_matches(role, config.model, response_model):
            reject("MODEL_MISMATCH", f"{role} API 返回模型与已确认角色配置不符: requested={config.model}; returned={response_model or 'missing'}")
        if metadata["finish_reason"] not in ("stop", "tool_calls"):
            reject("RESPONSE_NOT_COMPLETED", f"{role} API 正文未正常结束: {metadata['finish_reason']}")
        if structured_schema is not None and not correct_tool:
            reject("REQUIRED_TOOL_MISSING" if not tools else "UNEXPECTED_TOOL_CALL",
                   f"{role} API 未返回唯一的结构化工具调用; tool_count={len(tools)}")
        if not isinstance(content, str) or not content.strip():
            reject("EMPTY_RESPONSE", f"{role} API 返回空正文")
        return RoleResult(text=content, metadata=metadata, response_payload=snapshot)
