"""Collection-specific interval limiting and hard page budgets."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable


class PageBudgetExceeded(RuntimeError):
    pass


@dataclass(slots=True)
class PageBudget:
    max_pages_per_run: int
    daily_page_cap: int
    pages_used_today: int = 0
    pages_reserved_this_run: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if self.max_pages_per_run < 0 or self.daily_page_cap < 0:
            raise ValueError("page limits cannot be negative")
        if self.pages_used_today < 0 or self.pages_reserved_this_run < 0:
            raise ValueError("page usage cannot be negative")

    def reserve_page(self) -> None:
        with self._lock:
            if self.pages_reserved_this_run >= self.max_pages_per_run:
                raise PageBudgetExceeded("per-run page cap reached")
            if self.pages_used_today + self.pages_reserved_this_run >= self.daily_page_cap:
                raise PageBudgetExceeded("daily page cap reached")
            self.pages_reserved_this_run += 1

    @property
    def remaining_this_run(self) -> int:
        return max(0, self.max_pages_per_run - self.pages_reserved_this_run)

    @property
    def remaining_today(self) -> int:
        return max(0, self.daily_page_cap - self.pages_used_today - self.pages_reserved_this_run)


class CollectionRateLimiter:
    """Reserve access slots per source key using a monotonic clock.

    This is intentionally separate from ``src.shared.rate_limiter``, which limits
    LLM QPS.  A slot is reserved while holding a lock, so concurrent local workers
    cannot all pass at the same instant.
    """

    def __init__(
        self,
        min_interval_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds cannot be negative")
        self.min_interval_seconds = float(min_interval_seconds)
        self._clock = clock
        self._sleeper = sleeper
        self._next_allowed_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def acquire(self, source_key: str) -> float:
        """Reserve one source slot, sleep if needed, and return wait seconds."""

        if not source_key.strip():
            raise ValueError("source_key cannot be empty")
        with self._lock:
            now = self._clock()
            ready_at = max(now, self._next_allowed_at.get(source_key, now))
            wait_seconds = max(0.0, ready_at - now)
            self._next_allowed_at[source_key] = ready_at + self.min_interval_seconds
        if wait_seconds:
            self._sleeper(wait_seconds)
        return wait_seconds

    def seconds_until_ready(self, source_key: str) -> float:
        if not source_key.strip():
            raise ValueError("source_key cannot be empty")
        with self._lock:
            return max(0.0, self._next_allowed_at.get(source_key, 0.0) - self._clock())

    def reset(self, source_key: str | None = None) -> None:
        with self._lock:
            if source_key is None:
                self._next_allowed_at.clear()
            else:
                self._next_allowed_at.pop(source_key, None)
