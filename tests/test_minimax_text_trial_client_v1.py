from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.content_factory import minimax_text_trial_client_v1 as trial
from src.content_factory.creative_workflow_roles import (
    ROLE_CONTEXT_CAPABILITIES, RoleConfig, RoleResponseError,
)


class NativeResponse:
    def __init__(self, payload):
        self.payload = deepcopy(payload)
        self.id = payload.get("id")
        self.model = payload.get("model")
        self.choices = [SimpleNamespace(
            finish_reason=choice["finish_reason"],
            message=SimpleNamespace(**choice["message"]),
        ) for choice in payload["choices"]]
        self.usage = SimpleNamespace(**payload["usage"]) if payload["usage"] else None

    def model_dump(self, *, mode):
        assert mode == "json"
        return deepcopy(self.payload)


@pytest.fixture
def sdk(monkeypatch):
    import openai
    state = {
        "payload": {
            "id": "native-1", "model": trial.MODEL,
            "choices": [{"finish_reason": "stop", "message": {
                "content": '{"facts": []}', "reasoning_content": "native reasoning",
                "tool_calls": None,
            }}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 30, "total_tokens": 50,
                      "completion_tokens_details": {"reasoning_tokens": 12}},
            "provider_extra": {"kept": True},
        },
        "requests": [], "clients": [], "role_requests": [], "error": None,
    }
    config = RoleConfig("minimax", "MiniMax-M3", "https://example.invalid/v1", "fixture-secret")

    def get_config(role):
        state["role_requests"].append(role)
        return config

    def create(**parameters):
        state["requests"].append(parameters)
        if state["error"]:
            raise state["error"]
        return NativeResponse(state["payload"])

    def new_client(**parameters):
        state["clients"].append(parameters)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(trial, "role_config", get_config)
    monkeypatch.setattr(openai, "OpenAI", new_client)
    return state


def call(client=None, **kwargs):
    return (client or trial.MiniMaxTextTrialClient()).call(
        "writer", [{"role": "user", "content": "Return JSON facts"}], **kwargs)


def test_native_request_preserves_config_and_reasoning(sdk):
    defaults = deepcopy(ROLE_CONTEXT_CAPABILITIES)
    result = call(max_tokens=16384, temperature=0.1, thinking="adaptive")
    request = sdk["requests"][0]
    assert request["model"] == "MiniMax-M3.1-Flash"
    assert request["max_completion_tokens"] == 16384
    assert request["reasoning_effort"] == "medium"
    assert request["extra_body"] == {"thinking": {"type": "adaptive"}, "reasoning_split": True}
    assert not {"temperature", "top_p", "response_format", "tools", "max_tokens"} & request.keys()
    assert sdk["clients"][0] == {
        "api_key": "fixture-secret", "base_url": "https://example.invalid/v1",
        "timeout": trial.settings.SCRIPT_LLM_TIMEOUT_SECONDS, "max_retries": 0,
    }
    assert sdk["role_requests"] == ["writer"]
    assert ROLE_CONTEXT_CAPABILITIES == defaults
    assert ROLE_CONTEXT_CAPABILITIES["writer"]["model"] == "MiniMax-M3"
    assert result.response_payload == sdk["payload"]
    assert result.metadata["total_tokens"] == 50
    assert result.metadata["thinking_mode"] == "adaptive"
    assert result.response_payload["usage"]["completion_tokens_details"]["reasoning_tokens"] == 12


@pytest.mark.parametrize("kwargs", [
    {"thinking": "disabled"}, {"thinking": "enabled"},
    {"response_format": {"type": "json_object"}},
    {"max_tokens": True}, {"max_tokens": 0}, {"max_tokens": 1.5},
])
def test_unsupported_requests_fail_before_dispatch(sdk, kwargs):
    with pytest.raises(ValueError):
        call(**kwargs)
    assert not sdk["requests"]
    assert not sdk["clients"]


@pytest.mark.parametrize("kwargs", [{"model": "MiniMax-M3"}, {"reasoning_effort": "none"}])
def test_constructor_rejects_unfrozen_model_or_effort(kwargs):
    with pytest.raises(ValueError):
        trial.MiniMaxTextTrialClient(**kwargs)


def test_other_roles_rejected(sdk):
    with pytest.raises(ValueError):
        trial.MiniMaxTextTrialClient().call("director", [])
    assert not sdk["requests"]


@pytest.mark.parametrize("change,code", [
    (lambda p: p["choices"][0].update(finish_reason="length"), "RESPONSE_TRUNCATED"),
    (lambda p: p.update(choices=[]), "INVALID_RESPONSE_CHOICES"),
    (lambda p: p["choices"].append(deepcopy(p["choices"][0])), "INVALID_RESPONSE_CHOICES"),
    (lambda p: p.update(model="MiniMax-M3"), "MODEL_MISMATCH"),
    (lambda p: p["choices"][0].update(finish_reason="tool_calls"), "RESPONSE_NOT_COMPLETED"),
    (lambda p: p["choices"][0]["message"].update(tool_calls=[{"id": "unexpected"}]), "UNEXPECTED_TOOL_CALL"),
    (lambda p: p["choices"][0]["message"].update(content=" "), "EMPTY_RESPONSE"),
    (lambda p: p.update(usage=None), "USAGE_UNKNOWN"),
    (lambda p: p["usage"].update(prompt_tokens=True), "USAGE_UNKNOWN"),
    (lambda p: p["usage"].update(completion_tokens=-1), "USAGE_UNKNOWN"),
    (lambda p: p["usage"].update(total_tokens=50.0), "USAGE_UNKNOWN"),
    (lambda p: p["usage"].update(total_tokens=51), "USAGE_MISMATCH"),
])
def test_known_bad_native_response_keeps_entire_envelope(sdk, change, code):
    change(sdk["payload"])
    with pytest.raises(RoleResponseError) as error:
        call()
    assert error.value.response_metadata["response_fault_code"] == code
    assert error.value.response_payload == sdk["payload"]
    assert len(sdk["requests"]) == 1


def test_api_errors_are_sanitized_and_not_retried(sdk):
    error = RuntimeError("fixture-secret and private request body")
    error.status_code = 429
    error.request_id = "req-safe-123"
    sdk["error"] = error
    with pytest.raises(RuntimeError) as caught:
        call()
    assert str(caught.value) == "writer API call failed: RuntimeError; status=429; request_id=req-safe-123"
    assert "fixture-secret" not in str(caught.value)
    assert len(sdk["requests"]) == 1


def test_unexpected_error_request_id_is_not_exposed(sdk):
    error = RuntimeError("private body")
    error.request_id = "Authorization: fixture-secret\n"
    sdk["error"] = error
    with pytest.raises(RuntimeError) as caught:
        call()
    assert "fixture-secret" not in str(caught.value)
    assert "request_id=unknown" in str(caught.value)
