from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.workflow.catalog import build_default_registry
from src.workflow.contracts import (
    ActivationMode,
    NodeImplementationSpec,
    NodePort,
)
from src.workflow.registry import WorkflowNodeRegistry
from src.workflow.selection_store import (
    SCHEMA_VERSION,
    WorkflowSelectionConflict,
    WorkflowSelectionError,
    WorkflowSelectionStore,
)


def test_builtin_registry_has_one_default_and_one_contract_per_stage() -> None:
    registry = build_default_registry()

    assert {
        "trend_collection",
        "media_acquisition",
        "content_analysis",
        "opportunity_ranking",
        "tts",
        "video_pipeline",
        "video_generation",
        "portrait_animation",
    } <= set(registry.stages())
    for stage in registry.stages():
        implementations = registry.implementations(stage)
        assert sum(item.default for item in implementations) == 1
        assert len({item.contract_signature() for item in implementations}) == 1
    video_implementations = registry.implementations("video_pipeline")
    assert [item.implementation_id for item in video_implementations] == [
        "disabled_pending_redesign"
    ]
    for stage in (
        "background",
        "portrait_animation",
        "video_generation",
        "frame_interpolation",
        "composition",
    ):
        assert [item.implementation_id for item in registry.implementations(stage)] == [
            "disabled_pending_redesign"
        ]


def test_registry_rejects_contract_mismatch() -> None:
    registry = WorkflowNodeRegistry()
    common = dict(
        stage="sample_stage",
        label="Sample",
        description="",
        entrypoint="sample:run",
        activation_mode=ActivationMode.HOT_SWITCH,
        outputs=(NodePort("result", "sample_result/v1"),),
    )
    registry.register(
        NodeImplementationSpec(
            implementation_id="first_impl",
            inputs=(NodePort("request", "sample_request/v1"),),
            default=True,
            **common,
        )
    )

    with pytest.raises(ValueError, match="contract mismatch"):
        registry.register(
            NodeImplementationSpec(
                implementation_id="second_impl",
                inputs=(NodePort("request", "different_request/v1"),),
                **common,
            )
        )


def test_selection_store_saves_clones_activates_and_resolves(tmp_path: Path) -> None:
    registry = build_default_registry()
    path = tmp_path / "workflow_nodes.json"
    store = WorkflowSelectionStore(path, registry)

    initial = store.load()
    assert initial.revision == 0
    assert store.resolve("tts") == "edge"

    preview = dict(initial.active.selections)
    preview["tts"] = "gpt_sovits"
    saved = store.save_profile(
        "preview",
        preview,
        description="preview profile",
        activate=True,
        expected_revision=0,
    )
    assert saved.revision == 1
    assert saved.active_profile == "preview"
    assert store.resolve("tts") == "gpt_sovits"
    assert store.resolve("tts", "edge") == "edge"

    cloned = store.clone_profile(
        "preview",
        "preview_copy",
        expected_revision=1,
    )
    assert cloned.profiles["preview_copy"].selections == preview
    activated = store.activate("preview_copy", expected_revision=2)
    assert activated.active_profile == "preview_copy"

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["revision"] == 3


def test_selection_store_rejects_stale_or_invalid_updates(tmp_path: Path) -> None:
    registry = build_default_registry()
    path = tmp_path / "workflow_nodes.json"
    store = WorkflowSelectionStore(path, registry)
    selections = registry.default_selections()

    store.save_profile("production", selections, expected_revision=0)
    with pytest.raises(WorkflowSelectionConflict):
        store.save_profile("production", selections, expected_revision=0)

    invalid = dict(selections)
    invalid["tts"] = "not_a_provider"
    with pytest.raises(KeyError):
        store.save_profile("broken", invalid)


def test_selection_store_does_not_silently_replace_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "workflow_nodes.json"
    path.write_text("{broken", encoding="utf-8")
    store = WorkflowSelectionStore(path, build_default_registry())

    with pytest.raises(WorkflowSelectionError, match="cannot read"):
        store.load()
    assert path.read_text(encoding="utf-8") == "{broken"


def test_tts_engine_uses_active_selection_when_provider_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.content_factory import tts_engine
    from src.workflow import runtime

    class FakeProvider:
        def generate_audio(self, *args, **kwargs):
            return True

        def list_voices(self):
            return []

    monkeypatch.setattr(
        runtime,
        "resolve_node_implementation",
        lambda stage, requested=None: "gpt_sovits",
    )
    monkeypatch.setattr(tts_engine, "GPTSoVITSProvider", FakeProvider)

    engine = tts_engine.TTSEngine(output_dir=str(tmp_path), provider_type=None)

    assert engine.provider_type == "gpt_sovits"
    assert isinstance(engine.provider, FakeProvider)


def test_auto_publish_resolves_three_hot_switch_nodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.services.auto_publish_service import AutoPublishRequest, AutoPublishService
    from src.workflow import runtime

    selected = {
        "tts": "gpt_sovits",
        "video_pipeline": "disabled_pending_redesign",
        "background": "disabled_pending_redesign",
    }
    monkeypatch.setattr(
        runtime,
        "resolve_node_implementation",
        lambda stage, requested=None: selected[stage],
    )
    request = AutoPublishRequest()

    AutoPublishService._apply_workflow_selections(request)

    assert request.tts_provider == "gpt_sovits"
    assert request.video_mode == "disabled_pending_redesign"
    assert request.background_provider == "disabled_pending_redesign"


def test_retired_workflow_node_fails_closed_without_side_effects() -> None:
    from src.workflow.contracts import NodeExecutionRequest
    from src.workflow.disabled import reject_execution

    result = reject_execution(
        NodeExecutionRequest(
            run_id="reset-test",
            node_id="shot-1",
            stage="video_generation",
            implementation_id="disabled_pending_redesign",
            inputs={},
        )
    )

    assert result.success is False
    assert result.error_code == "VIDEO_PIPELINE_DISABLED"
    assert result.retryable is False


def test_auto_publish_stops_before_account_or_generation_when_video_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.services.auto_publish_service import AutoPublishRequest, AutoPublishService

    service = AutoPublishService()
    monkeypatch.setattr(
        service,
        "_apply_workflow_selections",
        lambda request: setattr(request, "video_mode", "disabled_pending_redesign"),
    )
    monkeypatch.setattr(
        service,
        "_init_adapter",
        lambda request: pytest.fail("disabled video flow must stop before account access"),
    )

    result = service.publish(AutoPublishRequest(account_key="account01"))

    assert result.success is False
    assert "已重置" in result.message
