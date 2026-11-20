"""Shared account identities and strategy profiles for operation workflows."""

from .models import (
    AccountBinding,
    AccountProfile,
    AccountRuntimeState,
    DouyinIdentity,
    stable_account_uuid,
)
from .repository import (
    AccountBindingConflict,
    AccountBindingNotFound,
    AccountBindingRepository,
    AccountOAuthStateError,
    AccountProfileConflict,
    AccountProfileNotFound,
    AccountProfileRepository,
    AccountRuntimeUnavailable,
)

# Keep package initialization independent of browser/runtime imports. Concurrent
# scheduler imports can use the light models/repository before runtime is needed.
_RUNTIME_EXPORTS = frozenset({
    "AccountRuntimeContext", "AccountRuntimeError", "AccountRuntimeService",
    "PreparedBrowserEnvironment", "RuntimeIdentityCheck",
})


def __getattr__(name):
    if name in _RUNTIME_EXPORTS:
        from importlib import import_module
        value = getattr(import_module(".runtime", __name__), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(__all__))

__all__ = [
    "AccountBinding",
    "AccountBindingConflict",
    "AccountBindingNotFound",
    "AccountBindingRepository",
    "AccountOAuthStateError",
    "AccountProfile",
    "AccountProfileConflict",
    "AccountProfileNotFound",
    "AccountProfileRepository",
    "AccountRuntimeState",
    "AccountRuntimeContext",
    "AccountRuntimeError",
    "AccountRuntimeService",
    "AccountRuntimeUnavailable",
    "DouyinIdentity",
    "PreparedBrowserEnvironment",
    "RuntimeIdentityCheck",
    "stable_account_uuid",
]
