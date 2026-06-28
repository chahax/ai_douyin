# -*- coding: utf-8 -*-
"""
src/shared/token_counter.py — I-4 LLM Token 计量 + 成本估算

设计原则：
  - tiktoken 作为主路径（OpenAI / DeepSeek / MiniMax 等兼容 cl100k_base）
  - 未知模型族降级到 cl100k_base（保守估计）
  - 本地 Ollama / mock 模型返回 cost_usd=0.0
  - 单价表存代码里（每年校准一次即可），如需外部化可改 YAML

调用方式：
    from src.shared.token_counter import count_tokens, estimate_cost
    n = count_tokens("gpt-4o", "hello world")
    cost = estimate_cost("gpt-4o", prompt_tokens=100, completion_tokens=50)
"""

from typing import Dict

import tiktoken


# 启动时构建的 encoding 缓存（避免重复加载）
_ENCODINGS: Dict[str, tiktoken.Encoding] = {}


def _get_encoding(model: str) -> tiktoken.Encoding:
    """按模型族选 encoding。未知模型降级到 cl100k_base。"""
    enc = _ENCODINGS.get(model)
    if enc is not None:
        return enc
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        # 未知模型 → 降级到 cl100k_base
        enc = tiktoken.get_encoding("cl100k_base")
    _ENCODINGS[model] = enc
    return enc


def count_tokens(model: str, text: str) -> int:
    """计算文本的 token 数。空文本返回 0。"""
    if not text:
        return 0
    try:
        return len(_get_encoding(model).encode(text))
    except Exception:
        # 极端情况（如编码器加载失败）→ 降级到字符数 / 4
        return max(1, len(text) // 4)


# USD / 1K tokens（2026-06 最新；如需外部化可改 YAML）
PRICE_TABLE: Dict[str, Dict[str, float]] = {
    # OpenAI
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    # DeepSeek
    "deepseek-chat": {"input": 0.00027, "output": 0.0011},
    "deepseek-reasoner": {"input": 0.00055, "output": 0.00219},
    # Anthropic Claude
    "claude-3-5-sonnet-20240620": {"input": 0.003, "output": 0.015},
    "claude-3-5-haiku-20241022": {"input": 0.0008, "output": 0.004},
    # MiniMax（示例用；按用户实际合同调整）
    "MiniMax-M2.7": {"input": 0.001, "output": 0.001},
    "Minimax-M2.7": {"input": 0.001, "output": 0.001},
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """
    估算单次调用的成本（USD）。

    未知模型返回 0.0（Ollama 本地 / mock）。
    """
    price = PRICE_TABLE.get(model)
    if price is None:
        return 0.0
    cost_in = prompt_tokens * price["input"] / 1000.0
    cost_out = completion_tokens * price["output"] / 1000.0
    return cost_in + cost_out


def is_local_model(model: str) -> bool:
    """判断是否为本地 / 免计费模型（Ollama / mock）。"""
    return model not in PRICE_TABLE
