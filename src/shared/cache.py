# -*- coding: utf-8 -*-
"""
src/shared/cache.py — 简单内存 LRU+TTL 缓存

用于 LLM 分类、错误诊断等"同输入→同输出"的场景，避免重复
调用 LLM。线程安全（用 threading.Lock 保护）。

API：
    cache = TTLCache(maxsize=500, ttl=600)
    cache[key] = value
    value = cache.get(key)        # None if missing/expired
    "key" in cache                # 检查存在
    cache.clear()                 # 测试用
"""

import time
from collections import OrderedDict
from threading import Lock


class TTLCache:
    """LRU + TTL 内存缓存。"""

    def __init__(self, maxsize: int = 500, ttl: int = 600):
        self.maxsize = maxsize
        self.ttl = ttl
        self._data: "OrderedDict[str, tuple[float, object]]" = OrderedDict()
        self._lock = Lock()

    def get(self, key: str):
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            ts, value = entry
            if time.time() - ts > self.ttl:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = (time.time(), value)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def __setitem__(self, key: str, value) -> None:
        self.set(key, value)

    def __getitem__(self, key: str):
        v = self.get(key)
        if v is None:
            raise KeyError(key)
        return v

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
