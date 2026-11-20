"""Integration uses actual frozen source and synthetic asset evidence, no network."""
from copy import deepcopy
import hashlib
import json
import socket
from pathlib import Path
import pytest
from scripts import run_creative_studio_v1 as studio
from src.content_factory import creative_reference_intake_v5 as intake
from tests.test_creative_reference_intake_v5 import fixture as asset_fixture, save, NOW, ACCOUNT, MODEL
from tests.test_creative_studio_provider_bridge_v1 import fixture as provider_fixture


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("No network in studio integration")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture(scope="module")
def source():
    return studio.inspect_source()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(studio, "WORKSPACES", tmp_path)
    return tmp_path / "studio_run"


def prepare(workspace, source, **kwargs):
    return studio.prepare_workspace(workspace, source_loader=lambda: deepcopy(source), **kwargs)


def reference_bundle(tmp_path, source):
    candidate, raw, approval = asset_fixture(tmp_path)
    manifest = source["input"]["manifest"]
    profiles = {a["id"]: {k: v["value"] for k, v in a["profile"].items()} for a in manifest["actors"]}
    scene = manifest["scenes"][0]
    spec = {k: scene[k]["value"] for k in ("setting", "appearance")}
    for row in approval["subject_mappings"]:
        if row["entity_type"] == "actor":
            row["profile"] = profiles[row["entity_id"]]
        else:
            row["scene_spec"] = spec
    candidate["adoption"] = save(Path(candidate["adoption"]["path"]), approval)
    binding = intake.build_binding_contract([candidate], manifest, selected_asset_ids=["tail"],
        output_dir=tmp_path / "normalized", allowed_roots=[tmp_path], provider_id="ark_api", model=MODEL,
        input_account_binding_sha256=ACCOUNT, now=NOW)
    get_path = tmp_path / "original_get.json"
    get_binding = save(get_path, raw["final"])
    get = {"method": "GET", "http_status": 200, "requested_task_id": raw["task_id"],
        "provider_id": "ark_api", "account_binding_sha256": ACCOUNT,
        "received_at": NOW.isoformat(), "response_body": get_binding}
    return {"binding_contract": binding, "selected_asset_ids": ["tail"], "mode": "multimodal_reference",
        "messages": deepcopy(source["request"]["messages"]), "now": NOW.isoformat(),
        "expected_account_binding_sha256": ACCOUNT, "provider_get_evidence": {"tail": get}}


def test_actual_source_import_has_no_claims_and_keeps_exhausted_capacity(workspace, source):
    result = prepare(workspace, source)
    assert result["director_capacity"]["remaining"] == 0
    assert result["director_capacity"]["attempts_including_claims"] == 7
    assert result["tasks"]["attempts"] == []
    assert result["tasks"]["authorizations"][0]["remaining_attempts"] == 0
    assert result["provider_gate"]["dispatch_enabled"] is False
    assert studio.read(workspace / "SOURCE_SNAPSHOT.json") == source["input"]
    assert result["new_paid_calls"] == result["new_media_calls"] == 0


def test_previs_reaches_full_request_and_restarts_without_repeating_compile(workspace, source):
    example = studio.spatial.build_offline_previs_example(source["input"]["manifest"])
    result = prepare(workspace, source, scene_sequence=example["scenes"])
    request = studio.read(workspace / "FULL_MODEL_REQUEST_PREVIEW.json")
    payload = json.loads(request["messages"][1]["content"])
    original = json.loads(source["request"]["messages"][1]["content"])
    assert all(payload[k] == value for k, value in original.items())
    assert len(payload["studio_spatial_previs"]["scene_sequence"]) == 2
    assert payload["studio_spatial_previs"]["geometry_is_provisional"] is True
    assert studio.read(workspace / "SDK_WIRE_BODY_PREVIEW.json")["messages"] == request["messages"]
    assert [a["provider_id"] for a in result["tasks"]["attempts"]] == ["local_compiler"]
    assert result["tasks"]["usage_totals"] == {"provider_units": 0}
    assert studio.status_workspace(workspace)["tasks"]["attempts"] == result["tasks"]["attempts"]
    assert not result["quality"]["usable_full_director"]


def test_existing_workspace_does_not_call_source_loader_again(workspace, source):
    prepare(workspace, source)
    def fail():
        raise AssertionError("no re-preparation")
    with pytest.raises(ValueError, match="ALREADY_EXISTS"):
        studio.prepare_workspace(workspace, source_loader=fail)


def test_tampered_fixed_source_blocks_status(workspace, source):
    prepare(workspace, source)
    (workspace / "SOURCE_SNAPSHOT.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="FIXED_INPUT_CHANGED"):
        studio.status_workspace(workspace)


def test_wrong_closed_cast_is_rejected_before_creating_workspace(workspace, source, tmp_path):
    bundle = reference_bundle(tmp_path, source)
    bundle["binding_contract"]["required_entities"] = [{"entity_type": "actor", "entity_id": "xiaolin"}]
    with pytest.raises(ValueError, match="CURRENT_CAST_COVERAGE_CHANGED"):
        prepare(workspace, source, reference_bundle=bundle)
    assert not workspace.exists()


def test_current_cast_original_adoption_is_rechecked(workspace, source, tmp_path):
    bundle = reference_bundle(tmp_path, source)
    normalized = studio.read(bundle["binding_contract"]["assets"][0]["approval"]["path"])
    original_binding = normalized["intake_provenance"]["original_adoption"]
    original = studio.read(original_binding["path"])
    original["subject_mappings"][0]["profile"]["gender_presentation"] = "旧角色性别错误"
    save(Path(original_binding["path"]), original)
    with pytest.raises(ValueError, match="CURRENT_CAST_NOT_READY"):
        prepare(workspace, source, reference_bundle=bundle)
    assert not workspace.exists()


def test_current_reference_pixels_reach_exact_source_and_sdk_preview(workspace, source, tmp_path):
    bundle = reference_bundle(tmp_path, source)
    result = prepare(workspace, source, reference_bundle=bundle)
    request = studio.read(workspace / "FULL_MODEL_REQUEST_PREVIEW.json")
    assert request["messages"][:-1] == source["request"]["messages"]
    assert request["messages"][-1]["content"][1]["type"] == "image_url"
    assert request["messages"][-1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert studio.read(workspace / "SDK_WIRE_BODY_PREVIEW.json")["messages"] == request["messages"]
    assert result["references"] == "metadata_compiled_not_content_approval"
    assert result["tasks"]["attempts"][0]["node_id"] == "references"
    assert result["new_paid_calls"] == 0


def test_original_mcp_schema_and_declaration_are_preserved(workspace, source):
    snapshot, declaration = provider_fixture()
    result = prepare(workspace, source, mcp_snapshot=snapshot, provider_declaration=declaration)
    assert studio.read(workspace / "MCP_SCHEMA_SNAPSHOT.json") == snapshot
    assert studio.read(workspace / "PROVIDER_DECLARATION.json") == declaration
    assert result["provider_gate"]["schema_source_kind"] == "offline_fixture"
    assert result["provider_gate"]["schema_contract_eligible"] is True
    assert result["provider_gate"]["dispatch_enabled"] is False


def test_workspace_must_be_independent_child(source, tmp_path, monkeypatch):
    monkeypatch.setattr(studio, "WORKSPACES", tmp_path / "allowed")
    with pytest.raises(ValueError, match="OUTSIDE_INDEPENDENT_ROOT"):
        prepare(tmp_path / "elsewhere", source)


def test_two_scene_sources_cannot_silently_conflict(workspace, source):
    scenes = studio.spatial.build_offline_previs_example(source["input"]["manifest"])["scenes"]
    with pytest.raises(ValueError, match="MUTUALLY_EXCLUSIVE"):
        prepare(workspace, source, scene=scenes[0], scene_sequence=scenes)
    assert not workspace.exists()
