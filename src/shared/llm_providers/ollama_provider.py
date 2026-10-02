import requests

from src.shared.llm_providers.base import BaseLLMProvider
from src.shared.logger import logger


class OllamaProvider(BaseLLMProvider):
    def __init__(self, base_url: str, model: str, timeout_seconds: int = 120):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def chat_completion(self, messages, temperature=0.7, json_mode=False):
        attempt_messages = messages
        max_attempts = 2 if json_mode else 1

        for attempt in range(1, max_attempts + 1):
            payload = {
                "model": self.model,
                "messages": attempt_messages,
                "stream": False,
                "options": {"temperature": temperature},
            }
            if json_mode:
                payload["format"] = "json"

            try:
                response = requests.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                data = response.json()
                message = data.get("message", {})
                content = message.get("content")

                if json_mode:
                    normalized = self.normalize_json_content(content)
                    if normalized:
                        return normalized
                    logger.warning(f"Ollama returned non-JSON content in json_mode on attempt {attempt}.")
                    attempt_messages = self._build_json_retry_messages(messages)
                    continue

                normalized = self.normalize_text_content(content)
                if normalized:
                    return normalized

                logger.error(f"Ollama returned an unexpected payload: {data}")
                return None
            except Exception as exc:
                logger.error(f"Ollama LLM error on attempt {attempt}: {exc}")

        return None

    def chat_with_tools(self, messages, tools, temperature=0.3, tool_choice="auto"):
        """Use Ollama's native ``/api/chat`` tool envelope.

        Ollama does not expose the OpenAI ``tool_choice`` field consistently.
        ``none`` therefore omits tool definitions; ``auto`` and ``required``
        send them and preserve returned calls for the shared normalization
        layer. An absent required call is reported as an empty result, never
        fabricated into an executed side effect.
        """

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if tool_choice != "none" and tools:
            payload["tools"] = tools
        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            message = data.get("message") or {}
            content = self.normalize_text_content(message.get("content")) or ""
            tool_calls = message.get("tool_calls") or []
            if not isinstance(tool_calls, list):
                logger.error("Ollama returned invalid tool_calls payload")
                tool_calls = []
            if tool_choice == "required" and not tool_calls:
                logger.warning("Ollama returned no tool call when one was required")
            return {"content": content, "tool_calls": tool_calls}
        except Exception as exc:
            logger.error(f"Ollama tools LLM error: {exc}")
            return {"content": "", "tool_calls": []}

    @staticmethod
    def _build_json_retry_messages(messages):
        retry_messages = list(messages)
        retry_messages.append(
            {
                "role": "user",
                "content": "请只返回合法 JSON，不要使用 markdown 代码块，不要添加任何解释文字。",
            }
        )
        return retry_messages
