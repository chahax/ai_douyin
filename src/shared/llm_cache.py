# -*- coding: utf-8 -*-
"""
src/shared/llm_cache.py — I-4 LLM 调用结果缓存

基于 diskcache（落盘 + TTL），按 model + 完整 messages + 参数算 sha256 作 key。

CLI 关闭：LLM_DISABLE_CACHE=1（用于对比测试 / 调试）

调用方式：
    from src.shared.llm_cache import make_key, get_cached, set_cached, is_enabled

    if is_enabled():
        key = make_key(model, messages, temperature, json_mode)
        hit = get_cached(key)
        if hit is not None:
            return hit
        # ... 调 LLM ...
        set_cached(key, result, ttl_seconds=86400)
"""

import hashlib
import json
import os
from typing import Any, List, Optional

import diskcache


# 缓存目录：./data/llm_cache/（gitignore 已排除 .venv/.local_py 等；data/ 下产物不入库）
_CACHE_DIR = os.getenv("LLM_CACHE_DIR", "./data/llm_cache")
_DEFAULT_TTL = 24 * 3600  # 24 小时

_cache: Optional[diskcache.Cache] = None


def _get_cache() -> diskcache.Cache:
    global _cache
    if _cache is None:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        _cache = diskcache.Cache(_CACHE_DIR, size_limit=1 << 30)  # 1 GB
    return _cache


def is_enabled() -> bool:
    """LLM_DISABLE_CACHE=1 时关闭缓存。"""
    return os.getenv("LLM_DISABLE_CACHE", "0") != "1"


def make_key(model: str, messages: List[dict], temperature: float, json_mode: bool) -> str:
    """
    基于 model + messages + 参数算稳定 hash。
    """
    payload = json.dumps(
        {
            "model": model,
            "messages": messages,
            "temperature": round(temperature, 4),
            "json_mode": json_mode,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_cached(key: str) -> Optional[Any]:
    """命中返回缓存值（原始 LLM 返回的字符串或 dict），未命中返回 None。"""
    if not is_enabled():
        return None
    try:
        return _get_cache().get(key)
    except Exception:
        return None


def set_cached(key: str, value: Any, ttl_seconds: int = _DEFAULT_TTL) -> None:
    """写缓存。TTL 默认 24 小时。"""
    if not is_enabled():
        return
    try:
        _get_cache().set(key, value, expire=ttl_seconds)
    except Exception:
        pass  # 写失败不致命


def clear_all() -> int:
    """清空整个缓存（调试用）。返回删除条数。"""
    return _get_cache().clear()


def stats() -> dict:
    """诊断用：返回当前缓存统计。"""
    c = _get_cache()
    return {
        "size": len(c),
        "volume_bytes": c.volume(),
        "directory": _CACHE_DIR,
        "enabled": is_enabled(),
    }
