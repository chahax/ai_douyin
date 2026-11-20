from src.platform_adapter.models import (
    BrowserSessionConfig,
    CommentQuery,
    CommentRecord,
    CommentSyncResult,
    PublishRequest,
    PublishResult,
    SessionState,
)

_LAZY_EXPORTS = {
    "BrowserSession": ".browser_session",
    "build_default_browser_session_config": ".browser_session",
    "CommentWorkflow": ".comment_workflow",
    "DouyinAdapter": ".douyin_adapter",
    "PublishWorkflow": ".publish_workflow",
}


def __getattr__(name):
    module = _LAZY_EXPORTS.get(name)
    if module is not None:
        from importlib import import_module
        value = getattr(import_module(module, __name__), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(__all__))

__all__ = [
    "BrowserSession",
    "BrowserSessionConfig",
    "CommentQuery",
    "CommentRecord",
    "CommentSyncResult",
    "CommentWorkflow",
    "DouyinAdapter",
    "PublishRequest",
    "PublishResult",
    "PublishWorkflow",
    "SessionState",
    "build_default_browser_session_config",
]
