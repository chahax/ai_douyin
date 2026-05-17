from openai import OpenAI

from src.shared.llm_providers.base import BaseLLMProvider
from src.shared.logger import logger


class OpenAICompatibleProvider(BaseLLMProvider):
    def __init__(self, api_key: str, base_url: str, model: str, timeout_seconds: int = 120):
        self.client = OpenAI(
            api_key=api_key or "EMPTY",
            base_url=base_url,
            timeout=timeout_seconds,
        )
        self.model = model

    def chat_completion(self, messages, temperature=0.7, json_mode=False):
        try:
            response_format = {"type": "json_object"} if json_mode else None
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                response_format=response_format,
            )
            content = response.choices[0].message.content
            if json_mode:
                normalized = self.normalize_json_content(content)
                if normalized:
                    return normalized
                logger.error("OpenAI-compatible provider returned non-JSON content in json_mode.")
                return None
            return self.normalize_text_content(content)
        except Exception as exc:
            logger.error(f"OpenAI-compatible LLM error: {exc}")
            return None
