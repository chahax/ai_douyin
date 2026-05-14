import json
import re
from abc import ABC, abstractmethod


class BaseLLMProvider(ABC):
    @abstractmethod
    def chat_completion(self, messages, temperature=0.7, json_mode=False):
        """Return the model response content as a string or None on failure."""
        raise NotImplementedError

    def normalize_text_content(self, content):
        if not isinstance(content, str):
            return None
        cleaned = content.strip()
        return cleaned or None

    def normalize_json_content(self, content):
        text = self.normalize_text_content(content)
        if not text:
            return None

        candidate = text.replace("```json", "").replace("```", "").strip()
        if self._is_valid_json(candidate):
            return candidate

        match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", candidate)
        if match:
            extracted = match.group(1).strip()
            if self._is_valid_json(extracted):
                return extracted

        return None

    @staticmethod
    def _is_valid_json(text: str) -> bool:
        try:
            json.loads(text)
            return True
        except Exception:
            return False
