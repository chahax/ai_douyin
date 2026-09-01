"""Stable contracts shared by every swappable workflow node.

The existing implementations do not have to inherit from one base class.  An
adapter only has to accept :class:`NodeExecutionRequest` and return
:class:`NodeExecutionResult`.  This keeps model/tool specific parameters out of
the workflow graph and gives all runners the same success/error envelope.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable


class ActivationMode(str, Enum):
    """How a saved selection becomes effective."""

    HOT_SWITCH = "hot_switch"
    PROFILE_ONLY = "profile_only"
    EXTERNAL_CONFIG = "external_config"
    RESTART_REQUIRED = "restart_required"


@dataclass(frozen=True, slots=True)
class NodePort:
    """One named input or output in a stage-level interface."""

    name: str
    artifact_type: str
    required: bool = True
    description: str = ""

    def signature(self) -> tuple[str, str, bool]:
        return self.name, self.artifact_type, self.required


@dataclass(frozen=True, slots=True)
class NodeImplementationSpec:
    """Metadata and interface contract for one implementation of a stage."""

    stage: str
    implementation_id: str
    label: str
    description: str
    entrypoint: str
    activation_mode: ActivationMode
    inputs: tuple[NodePort, ...]
    outputs: tuple[NodePort, ...]
    version: str = "1"
    default: bool = False
    notes: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.stage}:{self.implementation_id}"

    def contract_signature(self) -> tuple[tuple[tuple[str, str, bool], ...], tuple[tuple[str, str, bool], ...]]:
        return (
            tuple(port.signature() for port in self.inputs),
            tuple(port.signature() for port in self.outputs),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["activation_mode"] = self.activation_mode.value
        value["key"] = self.key
        return value


@dataclass(frozen=True, slots=True)
class NodeHealth:
    status: str
    message: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NodeExecutionRequest:
    """Provider-neutral invocation envelope.

    ``inputs`` contains artifacts declared by the stage contract.  Provider
    knobs belong in ``parameters`` and must never change the stage ports.
    """

    run_id: str
    node_id: str
    stage: str
    implementation_id: str
    inputs: Mapping[str, Any]
    parameters: Mapping[str, Any] = field(default_factory=dict)
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NodeExecutionResult:
    """Provider-neutral result envelope with provenance and retry semantics."""

    success: bool
    status: str
    outputs: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""
    retryable: bool = False

    @classmethod
    def ok(
        cls,
        outputs: Mapping[str, Any],
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> "NodeExecutionResult":
        return cls(
            success=True,
            status="succeeded",
            outputs=dict(outputs),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def fail(
        cls,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> "NodeExecutionResult":
        return cls(
            success=False,
            status="failed",
            metadata=dict(metadata or {}),
            error_code=code,
            error_message=message,
            retryable=retryable,
        )


@runtime_checkable
class WorkflowNodeExecutor(Protocol):
    """Adapter interface implemented by a runnable workflow node."""

    @property
    def spec(self) -> NodeImplementationSpec: ...

    def healthcheck(self) -> NodeHealth: ...

    def execute(self, request: NodeExecutionRequest) -> NodeExecutionResult: ...
