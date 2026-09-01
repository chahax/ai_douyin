"""Reusable collection runtime primitives.

These primitives are platform-neutral and do not contain scraping selectors,
credentials, anti-detection logic, or network clients.
"""

from .checkpoint import CollectionCheckpoint, FileCheckpointStore
from .job import CollectionJob, CollectionJobManager, CollectionJobStatus
from .rate_limiter import CollectionRateLimiter, PageBudget, PageBudgetExceeded

__all__ = [
    "CollectionCheckpoint",
    "CollectionJob",
    "CollectionJobManager",
    "CollectionJobStatus",
    "CollectionRateLimiter",
    "FileCheckpointStore",
    "PageBudget",
    "PageBudgetExceeded",
]
