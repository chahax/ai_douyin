"""HTTP-boundary checks; no real services or credentials."""
from types import SimpleNamespace
from copy import deepcopy

import pytest

from src.content_factory import natural_director_role_clients_v10 as module
from src.content_factory.creative_workflow_roles import RoleResponseError, RoleResult


def native(**changes):
    value = {"id": "test-response", "model": "deepseek-v4.1-flash", "choices": [
        {"finish_reason": "stop", "message": {"content": '{"verdict":"pass"}', "tool_calls": None}}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}}
    value.update(changes)
    return value


def install(monkeypatch, raw=None, error=None):
    import openai
    data = native() if raw is None else raw
    calls = {}

    class Response:
        def __init__(self):
            self.id, self.model = data["id"], data["model"]
            self.choices = [SimpleNamespace(finish_reason=row["finish_reason"],
                message=SimpleNamespace(**row["message"])) for row in data["choices"]]
            self.usage = SimpleNamespace(**data["usage"]) if data["usage"] is not None else None

        def model_dump(self, mode):
            assert mode == "json"
            return deepcopy(data)

    def create(**kwargs):
        calls["request"] = kwargs
        if error:
            raise error
        return Response()

    def client(**kwargs):
        calls["client"] = kwargs
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(openai, "OpenAI", client)
    monkeypatch.setattr(module, "role_config", lambda role: SimpleNamespace(
        model="deepseek-flash", provider="deepseek", api_key="test-secret", base_url="https://invalid.test/v1"))
    return calls


MESSAGES = [{"role": "system", "content": "Return one complete JSON object."}]


def run():
    return module.NaturalDirectorRoleClients().call("director", MESSAGES,
        thinking="disabled", response_format={"type": "json_object"}, max_tokens=16000)


def test_actual_http_is_explicit_json_no_tools_no_retry(monkeypatch):
    calls = install(monkeypatch)
    result = run()
    assert calls["client"]["max_retries"] == 0
    assert calls["request"]["response_format"] == {"type": "json_object"}
    assert calls["request"]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "tools" not in calls["request"] and "structured_schema" not in calls["request"]
    assert result.metadata["total_tokens"] == 12
    assert result.metadata["output_mode"] == "content"
    assert result.response_payload == native()


@pytest.mark.parametrize("change,code", [
    ({"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]}, "RESPONSE_TRUNCATED"),
    ({"choices": []}, "INVALID_RESPONSE_CHOICES"),
    ({"model": "wrong"}, "MODEL_MISMATCH"),
    ({"choices": [{"finish_reason": "stop", "message": {"content": "", "tool_calls": None}}]}, "EMPTY_RESPONSE"),
    ({"choices": [{"finish_reason": "stop", "message": {"content": "x", "tool_calls": [1]}}]}, "UNEXPECTED_TOOL_CALL"),
    ({"usage": None}, "USAGE_UNKNOWN"),
    ({"usage": {"prompt_tokens": True, "completion_tokens": 4, "total_tokens": 5}}, "USAGE_UNKNOWN"),
    ({"usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 99}}, "USAGE_MISMATCH"),
])
def test_rejected_received_native_preserved(monkeypatch, change, code):
    data = native(**change)
    install(monkeypatch, data)
    with pytest.raises(RoleResponseError) as caught:
        run()
    assert caught.value.response_metadata["response_fault_code"] == code
    assert caught.value.response_payload == data


def test_writer_uses_existing_native_text_protocol(monkeypatch):
    calls = {}
    def call(self, role, messages, **kwargs):
        calls.update(role=role, messages=messages, **kwargs)
        return RoleResult("完整自然文本", {})
    monkeypatch.setattr(module.CreativeRoleClients, "call", call)
    result = module.NaturalDirectorRoleClients().call("writer", MESSAGES,
        thinking="disabled", structured_schema=None)
    assert result.text == "完整自然文本"
    assert "response_format" not in calls and "structured_schema" not in calls


@pytest.mark.parametrize("role,extra", [
    ("director", {}), ("writer", {"response_format": {"type": "json_object"}}),
    ("writer", {"structured_schema": {"type": "object"}}),
])
def test_wrong_protocol_rejected_before_http(role, extra):
    with pytest.raises(ValueError):
        module.NaturalDirectorRoleClients().call(role, MESSAGES, **extra)


def test_transport_error_does_not_expose_secret(monkeypatch):
    install(monkeypatch, error=RuntimeError("secret-body test-secret"))
    with pytest.raises(RuntimeError) as caught:
        run()
    assert "test-secret" not in str(caught.value) and "secret-body" not in str(caught.value)
