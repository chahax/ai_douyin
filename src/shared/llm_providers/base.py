import json
import re
from abc import ABC, abstractmethod


# 推理模型（DeepSeek-R1 / MiniMax-M2 / QwQ 等）会在回复前输出"思考"块。
# 用 chr() 构造 < 和 > 字符，避免源码被中间环节替换。
_LT = chr(60)                                  # <
_GT = chr(62)                                  # >

# 三种变体。open_tag 只到标签名（不含 >），因为 LLM 通常立即输出内容，
# 不是 思考\n。close_tag 包含整个闭合标签 思考。
_OPEN1 = "think"
_CLOSE1 = _LT + "/think" + _GT
_OPEN2 = "|begin▁of▁think"     # 同上，只到标签名
_CLOSE2 = _LT + "|end▁of▁think|" + _GT
_OPEN3 = "thinking"
_CLOSE3 = _LT + "/thinking" + _GT

# 完整 match prefix：< + tag 名
_OPEN_PREFIX_1 = _LT + _OPEN1
_OPEN_PREFIX_2 = _LT + _OPEN2


class BaseLLMProvider(ABC):
    @abstractmethod
    def chat_completion(self, messages, temperature=0.7, json_mode=False):
        """Return the model response content as a string or None on failure."""
        raise NotImplementedError

    @abstractmethod
    def chat_with_tools(self, messages, tools, temperature=0.3, tool_choice="auto"):
        """Native tool calling. Return dict: {content, tool_calls}.

        tool_choice:
          "auto"     — 模型自行决定调工具还是直接答（多轮 loop 必须用这个，
                       否则模型永远被强制调工具、无法输出最终自然语言回复）
          "required" — 强制至少一个 tool call（仅"必然要动作"的单步场景才用）
          "none"     — 禁止工具
        """
        raise NotImplementedError

    def chat_with_tools_stream(self, messages, tools, temperature=0.3, tool_choice="auto"):
        """Native tool calling stream（OpenAI 兼容协议）。

        默认实现：直接复用 chat_with_tools 拿到完整 response 后，
        一次性 yield 完整 content（不真正流）。子类可 override 真正流。

        Yields:
            (event_type, data) tuples:
              ("token", str)   — content 的 token 增量
              ("tool_call", dict)  — tool_call 收尾时给出 1 次
              ("done", None)  — 流结束标记
        """
        result = self.chat_with_tools(messages, tools, temperature, tool_choice)
        if result.get("content"):
            yield ("token", result["content"])
        for tc in result.get("tool_calls") or []:
            yield ("tool_call", tc)
        yield ("done", None)

    def _strip_thought_block(self, content: str) -> str:
        """剥掉推理模型开头的"思考"块（如果有）。

        支持 3 种变体：
          1. <think>...</think>
          2. <|begin▁of▁think|>...<|end▁of▁think|>
          3. <thinking>...</thinking>
        """
        if not content:
            return content
        stripped = content.lstrip()

        pairs_open = [_OPEN_PREFIX_1, _OPEN_PREFIX_2, _LT + _OPEN3]
        all_closes = [_CLOSE1, _CLOSE2, _CLOSE3]

        # Step 1: 找匹配的 open tag
        matched_open = None
        for ot in pairs_open:
            if stripped.startswith(ot):
                matched_open = ot
                break
        if matched_open is None:
            return stripped

        # Step 2: 找到 open 后，搜遍所有 close 找最近的
        search_start = len(matched_open)
        for ct in all_closes:
            idx = stripped.find(ct, search_start)
            if idx >= 0:
                return stripped[idx + len(ct):].lstrip()
        # 没有任何 close tag 匹配：整段当思考剥掉
        return ""

    def normalize_text_content(self, content):
        if not isinstance(content, str):
            return None
        cleaned = self._strip_thought_block(content)
        return cleaned or None

    def normalize_json_content(self, content):
        text = self.normalize_text_content(content)
        if not text:
            return None
        # 二次剥离（防御性）
        text = self._strip_thought_block(text)
        if not text:
            return None

        # 步骤 2: 剥 markdown 代码块包装 (```json ... ``` 或 ``` ... ```)
        candidate = text.replace("```json", "").replace("```", "").strip()
        if self._is_valid_json(candidate):
            return candidate

        # 步骤 3: 用 JSON 解码器提取第一个完整的顶层值。
        # 贪婪正则会把 JSON 后的说明或第二个 JSON 一起吞掉，导致 Extra data。
        decoder = json.JSONDecoder()
        for start, char in enumerate(candidate):
            if char not in "[{":
                continue
            try:
                _, length = decoder.raw_decode(candidate[start:])
            except json.JSONDecodeError:
                continue
            end = start + length
            trailing = candidate[end:].strip()
            # 说明文字可以丢弃；多个并列 JSON 含义不唯一，继续拒绝。
            if self._contains_independent_json(trailing):
                return None
            return candidate[start:end].strip()

        return None

    @staticmethod
    def _contains_independent_json(text: str) -> bool:
        if not text:
            return False
        decoder = json.JSONDecoder()
        for start, char in enumerate(text):
            if char not in "[{":
                continue
            try:
                decoder.raw_decode(text[start:])
            except json.JSONDecodeError:
                continue
            return True
        return False

    @staticmethod
    def _is_valid_json(text: str) -> bool:
        try:
            json.loads(text)
            return True
        except Exception:
            return False

