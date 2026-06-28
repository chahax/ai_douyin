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

        # 步骤 1: 剥 reasoning model 的 <think>...</think> 思考块
        # (DeepSeek-R1 / MiniMax-M2 / QwQ 等推理模型会在 JSON 前后输出思考过程)
        # 兼容多种变体: <think>...</think> / <|begin▁of▁think|>...<|end▁of▁think|> / <thinking>...</thinking>
        text = re.sub(
            r"<think>.*?</think>\s*|<\|begin▁of▁think\|>.*?<\|end▁of▁think\|>\s*|<thinking>.*?</thinking>\s*",
            "",
            text,
            flags=re.DOTALL,
        ).strip()
        if not text:
            return None

        # 步骤 2: 剥 markdown 代码块包装 (```json ... ``` 或 ``` ... ```)
        candidate = text.replace("```json", "").replace("```", "").strip()
        if self._is_valid_json(candidate):
            return candidate

        # 步骤 3: 兜底 — 提取第一个 {} 或 [] 块
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
