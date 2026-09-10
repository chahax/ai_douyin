"""Fail-closed executor used by workflow stages retired during a reset."""

from __future__ import annotations

from src.workflow.contracts import NodeExecutionRequest, NodeExecutionResult


def reject_execution(request: NodeExecutionRequest) -> NodeExecutionResult:
    """Reject an invocation without touching providers, accounts, or artifacts."""
    return NodeExecutionResult.fail(
        "VIDEO_PIPELINE_DISABLED",
        f"工作流节点 {request.stage} 已重置，Video Pipeline V2 验收前禁止执行。",
        retryable=False,
        metadata={
            "stage": request.stage,
            "implementation_id": request.implementation_id,
        },
    )
