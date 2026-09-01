"""Registry for swappable workflow-node implementations."""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Iterable

from src.workflow.contracts import NodeImplementationSpec


_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class WorkflowNodeRegistry:
    """Catalog implementations and enforce one interface per stage."""

    def __init__(self) -> None:
        self._by_stage: OrderedDict[str, OrderedDict[str, NodeImplementationSpec]] = OrderedDict()

    def register(self, spec: NodeImplementationSpec) -> None:
        self._validate_identifier("stage", spec.stage)
        self._validate_identifier("implementation_id", spec.implementation_id)
        implementations = self._by_stage.setdefault(spec.stage, OrderedDict())
        if spec.implementation_id in implementations:
            raise ValueError(f"duplicate workflow implementation: {spec.key}")
        if implementations:
            expected = next(iter(implementations.values())).contract_signature()
            if spec.contract_signature() != expected:
                raise ValueError(
                    f"contract mismatch for stage {spec.stage}: {spec.implementation_id}"
                )
        if spec.default and any(item.default for item in implementations.values()):
            raise ValueError(f"stage {spec.stage} already has a default implementation")
        implementations[spec.implementation_id] = spec

    def stages(self) -> tuple[str, ...]:
        return tuple(self._by_stage)

    def implementations(self, stage: str) -> tuple[NodeImplementationSpec, ...]:
        try:
            return tuple(self._by_stage[stage].values())
        except KeyError as exc:
            raise KeyError(f"unknown workflow stage: {stage}") from exc

    def all(self) -> tuple[NodeImplementationSpec, ...]:
        return tuple(
            implementation
            for stage in self._by_stage.values()
            for implementation in stage.values()
        )

    def get(self, stage: str, implementation_id: str) -> NodeImplementationSpec:
        try:
            return self._by_stage[stage][implementation_id]
        except KeyError as exc:
            raise KeyError(
                f"unknown implementation for {stage}: {implementation_id}"
            ) from exc

    def default_for(self, stage: str) -> NodeImplementationSpec:
        implementations = self.implementations(stage)
        selected = next((item for item in implementations if item.default), None)
        if selected is None:
            raise ValueError(f"stage {stage} has no default implementation")
        return selected

    def default_selections(self) -> dict[str, str]:
        return {stage: self.default_for(stage).implementation_id for stage in self.stages()}

    def normalize_selections(self, selections: dict[str, str] | None) -> dict[str, str]:
        normalized = self.default_selections()
        for stage, implementation_id in (selections or {}).items():
            if stage not in self._by_stage:
                raise ValueError(f"unknown workflow stage: {stage}")
            self.get(stage, implementation_id)
            normalized[stage] = implementation_id
        return normalized

    def validate_complete(self, selections: dict[str, str]) -> None:
        normalized = self.normalize_selections(selections)
        if normalized != selections:
            missing = sorted(set(normalized) - set(selections))
            raise ValueError(f"workflow selections are incomplete: {', '.join(missing)}")

    @staticmethod
    def _validate_identifier(kind: str, value: str) -> None:
        if not _ID_PATTERN.fullmatch(value):
            raise ValueError(f"invalid {kind}: {value!r}")


def register_many(
    registry: WorkflowNodeRegistry,
    specifications: Iterable[NodeImplementationSpec],
) -> WorkflowNodeRegistry:
    for specification in specifications:
        registry.register(specification)
    return registry
