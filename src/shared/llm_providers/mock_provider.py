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
