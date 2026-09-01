"""Process-local access to the active workflow-node profile."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.workflow.catalog import build_default_registry
from src.workflow.registry import WorkflowNodeRegistry
from src.workflow.selection_store import WorkflowSelectionStore


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SELECTION_PATH = PROJECT_ROOT / "config" / "workflow_nodes.json"


@lru_cache(maxsize=1)
def get_node_registry() -> WorkflowNodeRegistry:
    return build_default_registry()


@lru_cache(maxsize=1)
def get_selection_store() -> WorkflowSelectionStore:
    return WorkflowSelectionStore(DEFAULT_SELECTION_PATH, get_node_registry())


def resolve_node_implementation(stage: str, requested: str | None = None) -> str:
    """Resolve an explicit override or the current active profile selection."""

    return get_selection_store().resolve(stage, requested)


def active_selections() -> dict[str, str]:
    return dict(get_selection_store().load().active.selections)
