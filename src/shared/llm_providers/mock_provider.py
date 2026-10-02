import json

from src.shared.llm_providers.base import BaseLLMProvider
from src.shared.logger import logger


class MockProvider(BaseLLMProvider):
    def chat_completion(self, messages, temperature=0.7, json_mode=False):
        last_msg = messages[-1]["content"] if messages else ""
        logger.info(f"[Mock LLM] Processing: {last_msg[:50]}...")

        if json_mode or "JSON" in last_msg or "json" in last_msg:
            return json.dumps(
                {
                    "title": "Mock Wisdom",
                    "core_message": "This is a mock response because no real LLM provider is configured.",
                    "actionable": "Configure LLM_PROVIDER and model settings in .env.",
                }
            )
        return "This is a mock response from MockProvider."

    def chat_with_tools(self, messages, tools, temperature=0.3, tool_choice="auto"):
        """Return a deterministic provider-compatible tool envelope.

        The mock never invents an external side effect in ``auto`` mode. A
        caller that explicitly requires a tool receives one empty-argument call
        for the first declared function, which is sufficient for offline loop
        and contract tests.
        """

        if tool_choice == "required" and tools:
            first = tools[0]
            function = first.get("function", first) if isinstance(first, dict) else {}
            name = function.get("name") if isinstance(function, dict) else None
            if name:
                arguments = "{}"
                return {
                    "content": "",
                    "tool_calls": [{
                        "id": "mock-tool-call-1",
                        "name": name,
                        "args": arguments,
                        "function": {"name": name, "arguments": arguments},
                    }],
                }
        return {
            "content": self.chat_completion(messages, temperature=temperature) or "",
            "tool_calls": [],
        }
