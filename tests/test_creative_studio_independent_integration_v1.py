"""Independent integration checks using current originals and isolated fixtures.

Current 512/513 and 518--520 receipts are only read. All workspace, normalized
asset, SQLite and recovery copies live under a fresh pytest temporary directory.
Tiny image bytes and local approval fixtures never prove real media quality.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import pytest

from scripts import run_creative_studio_v1 as cli
from scripts import restore_creative_studio_baseline_v1 as restore
from src.content_factory import creative_reference_intake_v5 as intake
from src.content_factory import creative_studio_task_store_v1 as tasks
from tests.test_creative_reference_intake_v5 import fixture as original_asset_fixture
from tests.test_creative_reference_intake_v5 import NOW, MODEL, ACCOUNT, save as fixture_save
from tests.test_creative_studio_provider_bridge_v1 import fixture as provider_fixture


@pytest.fixture(autouse=True)
def no_service(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("independent studio integration must not contact services")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.fixture(scope="module")
def verified_source():
    return cli.inspect_source()


def isolate_cli(tmp_path, monkeypatch):
    """Allow synthetic assets without weakening production root checks."""
    original_project = cli.PROJECT
    for relative in ("scripts/run_creative_studio_v1.py", "src/content_factory/creative_studio_reference_previs_v1.py",
                     "src/content_factory/creative_studio_task_store_v1.py", "src/content_factory/creative_studio_provider_bridge_v1.py"):
        dest = tmp_path / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((original_project / relative).read_bytes())
    monkeypatch.setattr(cli, "PROJECT", tmp_path)
    monkeypatch.setattr(cli, "WORKSPACES", tmp_path / "studio_workspaces")
    return tmp_path / "studio_workspaces" / "isolated"


def current_reference_bundle(tmp_path, verified):
    """Real intake/compiler execution over labelled synthetic current-cast bytes."""
    candidate, raw, adoption = original_asset_fixture(tmp_path)
    manifest = verified["input"]["manifest"]
    for subject in adoption["subject_mappings"]:
        if subject["entity_type"] == "actor":
            actor = next(actor for actor in manifest["actors"] if actor["id"] == subject["entity_id"])
            subject["profile"] = {key: item["value"] for key, item in actor["profile"].items()}
        else:
            scene = next(scene for scene in manifest["scenes"] if scene["id"] == subject["entity_id"])
            subject["scene_spec"] = {key: scene[key]["value"] for key in ("setting", "appearance")}
    candidate["adoption"] = fixture_save(Path(candidate["adoption"]["path"]), adoption)
    contract = intake.build_binding_contract([candidate], manifest, selected_asset_ids=["tail"],
        output_dir=tmp_path / "normalized", allowed_roots=[tmp_path], provider_id="ark_api", model=MODEL,
        input_account_binding_sha256=ACCOUNT, now=NOW)
    get = {"method": "GET", "http_status": 200, "requested_task_id": raw["task_id"],
        "provider_id": "ark_api", "account_binding_sha256": ACCOUNT, "received_at": NOW.isoformat(),
        "response_body": fixture_save(tmp_path / "original_get.json", raw["final"])}
    return {"binding_contract": contract, "selected_asset_ids": ["tail"], "mode": "multimodal_reference",
        "messages": deepcopy(verified["request"]["messages"]), "now": NOW.isoformat(),
        "expected_account_binding_sha256": ACCOUNT, "provider_get_evidence": {"tail": get}}


def test_current_source_remains_exhausted_full_text_and_reference_preserved(verified_source):
    proof = verified_source["report"]
    assert proof["director_capacity"]["candidate_limit"] == 7
    assert proof["director_capacity"]["attempts_including_claims"] == 7
    assert proof["director_capacity"]["remaining"] == 0
    assert proof["native_plan_adopted"] is False
    assert proof["new_calls"] == 0
    user = json.loads(verified_source["request"]["messages"][1]["content"])
    assert user["full_current_script"] == verified_source["input"]["script"]
    assert user["reference_fulltext"] == verified_source["input"]["original_input"]["reference_fulltext"]
    assert verified_source["wire"]["messages"] == verified_source["request"]["messages"]


def test_same_workspace_really_calls_previs_reference_provider_and_persistent_store(tmp_path, monkeypatch, verified_source):
    workspace = isolate_cli(tmp_path, monkeypatch)
    verified = deepcopy(verified_source)
    original_hashes = {path: cli.sha(path) for path in verified["report"]["original_file_hashes"]}
    scene = cli.spatial.build_offline_previs_example(verified["input"]["manifest"])["scenes"][0]
    bundle = current_reference_bundle(tmp_path, verified)
    before = deepcopy((verified, scene, bundle))
    called = []
    for module, name, label in ((cli.spatial, "build_previs_bundle", "previs"),
                                (cli.spatial, "compile_reference_projection", "references"),
                                (cli.providers, "preview_text_request", "exact_text_wire"),
                                (cli.providers, "inspect_provider_gate", "provider_gate")):
        original = getattr(module, name)
        def wrapped(*args, _original=original, _label=label, **kwargs):
            called.append(_label)
            return _original(*args, **kwargs)
        monkeypatch.setattr(module, name, wrapped)
    result = cli.prepare_workspace(workspace, scene=scene, reference_bundle=bundle,
        source_loader=lambda: deepcopy(verified))
    assert "previs" in called and "references" in called and "provider_gate" in called
    assert called.count("exact_text_wire") == 2
    assert result["director_capacity"]["remaining"] == 0
    assert result["new_paid_calls"] == result["new_media_calls"] == 0
    assert result["quality"]["usable_full_director"] is False
    assert result["provider_gate"]["dispatch_enabled"] is False
    current_request = cli.read(workspace / "FULL_MODEL_REQUEST_PREVIEW.json")
    wire = cli.read(workspace / "SDK_WIRE_BODY_PREVIEW.json")
    actual = json.loads(current_request["messages"][1]["content"])
    assert actual["full_current_script"] == verified["input"]["script"]
    assert actual["reference_fulltext"] == verified["input"]["original_input"]["reference_fulltext"]
    assert actual["studio_spatial_previs"]["scene"] == scene
    assert actual["studio_spatial_previs"]["geometry_is_provisional"] is True
    assert actual["studio_spatial_previs"]["production_adopted"] is False
    assert wire["messages"] == current_request["messages"]
    image_items = [part for message in wire["messages"] if isinstance(message.get("content"), list)
                   for part in message["content"] if part.get("type") == "image_url"]
    assert len(image_items) == 1
    assert image_items[0]["image_url"]["url"].startswith("data:image/png;base64,")
    nodes = {node["node_id"]: node for node in result["tasks"]["nodes"]}
    assert nodes["space"]["status"] == nodes["references"]["status"] == "completed"
    assert nodes["direction"]["status"] == "prepared"
    assert all(attempt["provider_id"] == "local_compiler" for attempt in result["tasks"]["attempts"])
    assert len(result["tasks"]["attempts"]) == 2
    workspace_manifest = cli.read(workspace / "WORKSPACE_MANIFEST.json")
    assert workspace_manifest["claims_created"] == len(result["tasks"]["attempts"]) == 2
    assert workspace_manifest["local_claims_created"] == result["local_claims_created"] == 2
    assert workspace_manifest["paid_claims_created"] == result["paid_claims_created"] == 0
    inherited = [row for row in result["tasks"]["authorizations"] if row["authorization"]["scope"] == "text"][0]
    assert inherited["authorization"]["max_attempts"] == inherited["authorization"]["prior_attempts"] == 7
    assert inherited["remaining_attempts"] == 0
    store = tasks.TaskStore(workspace / "TASKS.sqlite3")
    with pytest.raises(tasks.TaskStoreError) as caught:
        store.claim(workspace.name, "direction", {"provider_id": "minimax", "payload": current_request},
            inherited["authorization"])
    assert caught.value.code == "AUTHORIZATION_EXHAUSTED"
    restart = cli.status_workspace(workspace)
    assert restart["tasks"]["attempts"] == result["tasks"]["attempts"]
    assert restart["new_paid_calls"] == 0
    assert (verified, scene, bundle) == before
    assert {path: cli.sha(path) for path in original_hashes} == original_hashes


def test_media_payload_is_saved_but_cannot_complete_director_image_gate(tmp_path, monkeypatch, verified_source):
    workspace = isolate_cli(tmp_path, monkeypatch)
    verified = deepcopy(verified_source)
    scene = cli.spatial.build_offline_previs_example(verified["input"]["manifest"])["scenes"][0]
    bundle = current_reference_bundle(tmp_path, verified)
    bundle.pop("messages")
    narrative = json.dumps(verified["input"]["script"], ensure_ascii=False, sort_keys=True)
    bundle["binding_contract"]["narrative_text_sha256"] = hashlib.sha256(narrative.encode()).hexdigest()
    bundle["payload"] = {"model": MODEL, "content": [{"type": "text", "text": narrative}],
        "duration": 8, "resolution": "480p", "ratio": "9:16", "generate_audio": True,
        "return_last_frame": True, "watermark": False}
    original_bundle = deepcopy(bundle)
    result = cli.prepare_workspace(workspace, scene=scene, reference_bundle=bundle,
        source_loader=lambda: deepcopy(verified))
    projection = cli.read(workspace / "REFERENCE_PROJECTION.json")
    assert projection["channel"] == "media_payload"
    assert projection["compiler_result"]["payload"]["model"] == MODEL
    assert projection["compiler_result"]["payload"]["content"][0]["text"].startswith(narrative)
    assert any(row["type"] == "image_url" for row in projection["compiler_result"]["payload"]["content"])
    assert cli.read(workspace / "REFERENCE_BUNDLE.json") == original_bundle
    nodes = {node["node_id"]: node for node in result["tasks"]["nodes"]}
    assert nodes["space"]["status"] == "completed"
    assert nodes["references"]["status"] not in {"source_ready", "completed", "passed"}
    assert nodes["references"]["input"]["director_images_in_request"] is False
    assert nodes["references"]["input"]["asset_binding"] == "media_payload_compiled_director_unbound"
    assert nodes["direction"]["status"] == "prepared"
    assert not any(row["node_id"] == "references" for row in result["tasks"]["attempts"])
    assert result["references"] == "media_payload_compiled_director_images_missing"
    assert result["director_images_in_request"] is False
    request = cli.read(workspace / "FULL_MODEL_REQUEST_PREVIEW.json")
    inherited = next(row["authorization"] for row in result["tasks"]["authorizations"]
        if row["authorization"]["scope"] == "text")
    store = tasks.TaskStore(workspace / "TASKS.sqlite3")
    with pytest.raises(tasks.TaskStoreError) as caught:
        store.claim(workspace.name, "direction", {"provider_id": "minimax", "payload": request}, inherited)
    assert caught.value.code == "DEPENDENCY_NOT_READY"
    wire = cli.read(workspace / "SDK_WIRE_BODY_PREVIEW.json")
    assert wire["messages"] == request["messages"]
    assert all(isinstance(message["content"], str) for message in request["messages"])
    current = json.loads(request["messages"][1]["content"])
    assert current["full_current_script"] == verified["input"]["script"]
    assert current["reference_fulltext"] == verified["input"]["original_input"]["reference_fulltext"]
    assert current["studio_spatial_previs"]["scene"] == scene
    workspace_manifest = cli.read(workspace / "WORKSPACE_MANIFEST.json")
    assert workspace_manifest["claims_created"] == len(result["tasks"]["attempts"]) == 1
    assert workspace_manifest["local_claims_created"] == result["local_claims_created"] == 1
    assert workspace_manifest["paid_claims_created"] == result["paid_claims_created"] == 0
    assert result["new_paid_calls"] == result["new_media_calls"] == 0
    assert result["quality"]["usable_full_director"] is False
    restarted = cli.status_workspace(workspace)
    assert restarted["tasks"]["attempts"] == result["tasks"]["attempts"]
    assert restarted["director_images_in_request"] is False
    assert bundle == original_bundle


@pytest.mark.parametrize("change", ["missing_zhou", "foreign_scene", "foreign_actor"])
def test_foreign_or_incomplete_reference_entities_cannot_complete_current_direction(tmp_path, monkeypatch, verified_source, change):
    workspace = isolate_cli(tmp_path, monkeypatch)
    bundle = current_reference_bundle(tmp_path, verified_source)
    required = bundle["binding_contract"]["required_entities"]
    if change == "missing_zhou":
        required[:] = [row for row in required if row["entity_id"] != "zhou"]
    else:
        target = "meeting_room" if change == "foreign_scene" else "xiaolin"
        next(row for row in required if row["entity_id"] == target)["entity_id"] = "foreign_story_entity"
    with pytest.raises(ValueError, match="STUDIO_REFERENCE_CURRENT_CAST_COVERAGE_CHANGED"):
        cli.prepare_workspace(workspace, reference_bundle=bundle, source_loader=lambda: deepcopy(verified_source))
    assert not workspace.exists()


def test_replaced_source_messages_cannot_be_used_as_current_visual_request(tmp_path, monkeypatch, verified_source):
    workspace = isolate_cli(tmp_path, monkeypatch)
    bundle = current_reference_bundle(tmp_path, verified_source)
    bundle["messages"] = [{"role": "user", "content": "unrelated shorter story"}]
    with pytest.raises(ValueError, match="STUDIO_DIRECTOR_REFERENCE_SOURCE_MESSAGES_CHANGED"):
        cli.prepare_workspace(workspace, reference_bundle=bundle, source_loader=lambda: deepcopy(verified_source))
    assert not workspace.exists()


def test_original_mcp_snapshot_and_declaration_are_saved_and_frozen(tmp_path, monkeypatch, verified_source):
    workspace = isolate_cli(tmp_path, monkeypatch)
    snapshot, declaration = provider_fixture()
    cli.prepare_workspace(workspace, mcp_snapshot=snapshot, provider_declaration=declaration,
        source_loader=lambda: deepcopy(verified_source))
    assert cli.read(workspace / "MCP_SCHEMA_SNAPSHOT.json") == snapshot
    assert cli.read(workspace / "PROVIDER_DECLARATION.json") == declaration
    manifest = cli.read(workspace / "WORKSPACE_MANIFEST.json")
    assert "MCP_SCHEMA_SNAPSHOT.json" in manifest["fixed_files"]
    assert "PROVIDER_DECLARATION.json" in manifest["fixed_files"]
    assert manifest["claims_created"] == manifest["local_claims_created"] == manifest["paid_claims_created"] == 0
    gate = cli.status_workspace(workspace)["provider_gate"]
    assert gate["schema_contract_eligible"] is True
    assert gate["schema_source_kind"] == "offline_fixture"
    assert gate["blocked"] is True
    (workspace / "PROVIDER_DECLARATION.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="STUDIO_FIXED_INPUT_CHANGED"):
        cli.status_workspace(workspace)


@pytest.mark.parametrize("change", ["graph_definition", "source_input", "source_kind"])
def test_database_cannot_replace_frozen_graph_or_source_binding(tmp_path, monkeypatch, verified_source, change):
    import sqlite3
    workspace = isolate_cli(tmp_path, monkeypatch)
    cli.prepare_workspace(workspace, source_loader=lambda: deepcopy(verified_source))
    con = sqlite3.connect(workspace / "TASKS.sqlite3")
    try:
        if change == "graph_definition":
            raw = con.execute("SELECT definition FROM graphs").fetchone()[0]
            graph = json.loads(raw)
            graph["provenance"]["substituted_fixture"] = True
            con.execute("UPDATE graphs SET definition=?,sha=?", (json.dumps(graph), cli.digest(graph)))
        elif change == "source_input":
            raw = con.execute("SELECT input FROM revisions WHERE node_id='source' AND revision=1").fetchone()[0]
            source = json.loads(raw)
            source["script_sha256"] = "e" * 64
            con.execute("UPDATE revisions SET input=?,input_sha=? WHERE node_id='source' AND revision=1",
                (json.dumps(source), cli.digest(source)))
        else:
            con.execute("UPDATE nodes SET kind='text' WHERE node_id='source'")
        con.commit()
    finally:
        con.close()
    with pytest.raises(ValueError, match="STUDIO_DATABASE_(GRAPH|SOURCE|NODE)_BINDING_CHANGED"):
        cli.status_workspace(workspace)


def raw_receipt(body="connection lost after submit", status=None):
    return {"encoding": "utf-8", "body": body, "sha256": hashlib.sha256(body.encode()).hexdigest(), "http_status": status}


def test_sqlite_restart_unknown_retains_original_id_and_cannot_redispatch(tmp_path):
    db = tmp_path / "TASKS.sqlite3"
    store = tasks.TaskStore(db)
    graph = {"schema_version": tasks.GRAPH_SCHEMA, "graph_id": "unknown_fixture", "nodes": [
        {"node_id": "source", "kind": "source", "input": {"script": "fixture-only"}, "depends_on": []},
        {"node_id": "video", "kind": "media", "input": {"segment": "fixture-only"}, "depends_on": ["source"]}]}
    store.register_graph(graph)
    auth = {"schema_version": tasks.AUTH_SCHEMA, "authorization_id": "fixture_not_real_authorization",
        "graph_id": graph["graph_id"], "node_ids": ["video"], "scope": "media", "purpose": "dispatch",
        "source_sha256": store.snapshot(graph["graph_id"])["source_sha256"], "max_attempts": 1, "prior_attempts": 0,
        "allows_content_revision": False, "evidence_ref": "offline-only-fixture", "evidence_sha256": "a" * 64}
    request = {"provider_id": "illustrative_provider_not_called", "payload": {"prompt": "offline fixture"}}
    claim = store.claim(graph["graph_id"], "video", request, auth)
    store.record_submission(claim["claim_id"], "original-service-id", raw_receipt('{"id":"original-service-id"}', 200))
    store.mark_unknown(claim["claim_id"], raw_receipt(), "connection_lost")
    restarted = tasks.TaskStore(db)
    recovery = restarted.recover(graph["graph_id"])
    assert recovery["actions"][0]["service_task_id"] == "original-service-id"
    assert recovery["actions"][0]["action"] == "query_original_task"
    assert recovery["actions"][0]["may_dispatch_new_request"] is False
    with pytest.raises(tasks.TaskStoreError):
        restarted.claim(graph["graph_id"], "video", request, auth)
    assert len(restarted.snapshot(graph["graph_id"])["attempts"]) == 1


def test_restore_leaves_original_frozen_history_bytes_untouched(tmp_path):
    import zipfile
    original = tmp_path / "production" / "CALL_LEDGER.json"
    original.parent.mkdir()
    original.write_text('{"historical_calls":520,"reported_tokens":7964215}', encoding="utf-8")
    original_sha = cli.sha(original)
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    raw = b"# preserved old code\n"
    with zipfile.ZipFile(checkpoint / "BASELINE_CODE_AND_CONTEXT.zip", "w") as archive:
        archive.writestr("scripts/old.py", raw)
    manifest = {"schema": "creative_studio_development_baseline/v1",
        "archive_sha256": cli.sha(checkpoint / "BASELINE_CODE_AND_CONTEXT.zip"),
        "files": [{"path": "scripts/old.py", "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}],
        "protected_production_files": [{"path": "production/CALL_LEDGER.json", "sha256": original_sha}]}
    (checkpoint / "BASELINE_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    restore.verify_checkpoint(checkpoint, check_protected=True, project=tmp_path)
    target = tmp_path / "isolated_restore"
    result = restore.extract_new(checkpoint, target, project=tmp_path)
    assert result["ledger_reset"] is False
    assert result["original_workspace_overwritten"] is False
    assert cli.sha(original) == original_sha
    with pytest.raises(ValueError, match="RESTORE_TARGET_ALREADY_EXISTS"):
        restore.extract_new(checkpoint, target, project=tmp_path)
    assert cli.sha(original) == original_sha
