"""Trend intelligence domain package.

The package is intentionally offline by default.  Importing it must never start a
browser or make a network request.
"""

from .source_policy import (
    PolicyStatus,
    SourcePolicy,
    SourcePolicyDecision,
    SourcePolicyGate,
    SourceProvider,
    SourceRequest,
)

__all__ = [
    "PolicyStatus",
    "SourcePolicy",
    "SourcePolicyDecision",
    "SourcePolicyGate",
    "SourceProvider",
    "SourceRequest",
]
