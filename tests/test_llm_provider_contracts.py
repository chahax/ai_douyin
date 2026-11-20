from __future__ import annotations

from src.shared.llm_providers.mock_provider import MockProvider
from src.shared.llm_providers.ollama_provider import OllamaProvider


TOOLS = [{
    "type": "function",
    "function": {
        "name": "lookup_status",
        "description": "fixture",
        "parameters": {"type": "object", "properties": {}},
    },
}]


def test_mock_provider_satisfies_tool_contract_without_auto_side_effects():
    provider = MockProvider()

    automatic = provider.chat_with_tools(
        [{"role": "user", "content": "hello"}], TOOLS,
    )
    required = provider.chat_with_tools(
        [{"role": "user", "content": "run it"}], TOOLS,
        tool_choice="required",
    )

    assert automatic["tool_calls"] == []
    assert automatic["content"]
    assert required["content"] == ""
    assert required["tool_calls"][0]["function"] == {
        "name": "lookup_status", "arguments": "{}",
    }


def test_ollama_provider_satisfies_tool_contract_and_preserves_calls(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "function": {
                            "name": "lookup_status",
                            "arguments": {},
                        },
                    }],
                },
            }

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(
        "src.shared.llm_providers.ollama_provider.requests.post", post,
    )
    provider = OllamaProvider("http://127.0.0.1:11434", "fixture")
    result = provider.chat_with_tools(
        [{"role": "user", "content": "run it"}], TOOLS,
        tool_choice="required",
    )

    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["json"]["tools"] == TOOLS
    assert result["tool_calls"][0]["function"]["name"] == "lookup_status"


def test_ollama_none_choice_omits_tools(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "done"}}

    def post(_url, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(
        "src.shared.llm_providers.ollama_provider.requests.post", post,
    )
    result = OllamaProvider("http://localhost:11434", "fixture").chat_with_tools(
        [{"role": "user", "content": "answer"}], TOOLS,
        tool_choice="none",
    )

    assert "tools" not in captured["json"]
    assert result == {"content": "done", "tool_calls": []}
