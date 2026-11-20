"""Independent offline studio: source inspection, workspace, request preview and recovery.

No live provider dispatch or ledger/candidate grant is exposed by this CLI.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import preview_creative_endpoint_feedback_v6 as endpoint_preview
from scripts import run_creative_capability_production_v5 as frozen
from src.content_factory import creative_studio_reference_previs_v1 as spatial
from src.content_factory import creative_studio_task_store_v1 as tasks
from src.content_factory import creative_studio_provider_bridge_v1 as providers
from src.content_factory import creative_reference_intake_v5 as intake

VERSION = "creative_studio/v1"
WORKSPACES = PROJECT / "data/creative_studio_workspaces"
DEFAULT_WORKSPACE = WORKSPACES / "legal_scene_20261012_v1"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def save(path, obj):
    with Path(path).open("x", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def inspect_source():
    report, feedback, request, wire = endpoint_preview.build_preview()
    # This verifies originals and current inherited scope, without claiming work.
    original = read(frozen.ROOT / "INPUT.json")
    return {"report": report, "input": original, "feedback": feedback,
        "request": request, "wire": wire,
        "input_binding": {"path": str(frozen.ROOT / "INPUT.json"), "sha256": sha(frozen.ROOT / "INPUT.json")}}


def graph_for(workspace, verified):
    script, manifest = verified["input"]["script"], verified["input"]["manifest"]
    capacity = verified["report"]["director_capacity"]
    return {"schema_version": "creative_studio_dag/v1", "graph_id": workspace.name,
        "provenance": {"input_binding": verified["input_binding"],
            "script_sha256": digest(script), "manifest_sha256": digest(manifest),
            "original_candidate_capacity": capacity, "authorization_is_inherited_not_created": True,
            "paid_dispatch_exposed": False, "original_failed_plan_adopted": False},
        "nodes": [
            {"node_id": "source", "kind": "source", "input": {"input_binding": verified["input_binding"],
                "script_sha256": digest(script), "manifest_sha256": digest(manifest), "review_ordinal": 513}, "depends_on": []},
            {"node_id": "space", "kind": "compile", "input": {"scene_path": "SCENE.json",
                "missing_geometry_is_not_inferred": True}, "depends_on": ["source"]},
            {"node_id": "references", "kind": "compile", "input": {"asset_binding": "unbound",
                "voice_binding": "unbound", "require_actual_compiler": True}, "depends_on": ["source"]},
            {"node_id": "direction", "kind": "text", "input": {"request_path": "FULL_MODEL_REQUEST_PREVIEW.json",
                "capacity": capacity, "execution_block_reason": verified["report"]["block_reason"]},
                "depends_on": ["source", "space", "references"]},
            {"node_id": "performance", "kind": "text", "input": {"requires_accepted_native_direction": True}, "depends_on": ["direction"]},
            {"node_id": "compile", "kind": "compile", "input": {"requires_full_native_performance": True}, "depends_on": ["performance", "references"]},
            {"node_id": "full_review", "kind": "review", "input": {"model_role": "DeepSeek_limited_fulltext"}, "depends_on": ["compile"]},
            {"node_id": "video", "kind": "media", "input": {"service": "existing_ark_adapter",
                "requires_verified_model_references": True, "content_status_on_save": "awaiting_human_review"}, "depends_on": ["full_review"]},
            {"node_id": "human_review", "kind": "review", "input": {"authority": "user", "no_assistant_av_inspection": True}, "depends_on": ["video"]}
        ]}


def validate_reference_source(bundle, manifest):
    """Recheck current cast from original intake evidence, not asset names."""
    contract = bundle["binding_contract"]
    required = {("actor", a["id"]) for a in manifest["actors"]} | {("scene", s["id"]) for s in manifest["scenes"]}
    declared = {(r["entity_type"], r["entity_id"]) for r in contract["required_entities"] if r["entity_type"] != "voice"}
    if declared != required:
        raise ValueError("STUDIO_REFERENCE_CURRENT_CAST_COVERAGE_CHANGED")
    if contract["mode"] == "first_frame":
        expected = bundle.get("expected_continuation") or {}
        if expected.get("script_sha256") != manifest["script_sha256"] or expected.get("fixed_identity_sha256") != digest(manifest):
            raise ValueError("STUDIO_REFERENCE_CURRENT_CONTINUATION_MISSING")
        return
    if contract.get("intake", {}).get("fixed_manifest_sha256") != digest(manifest):
        raise ValueError("STUDIO_REFERENCE_CURRENT_MANIFEST_BINDING_MISSING")
    assets = {a["asset_id"]: a for a in contract["assets"]}
    for aid in bundle["selected_asset_ids"]:
        asset = assets[aid]
        approval_path = Path(asset["approval"]["path"])
        if sha(approval_path) != asset["approval"]["sha256"]:
            raise ValueError("STUDIO_REFERENCE_ADOPTION_BYTES_CHANGED")
        provenance = read(approval_path).get("intake_provenance", {})
        if "original_receipt" not in provenance or "original_adoption" not in provenance:
            raise ValueError("STUDIO_REFERENCE_ORIGINAL_CURRENT_CAST_PROOF_MISSING")
        candidate = {"asset_id": aid, "local_path": asset["local_path"], "sha256": asset["sha256"],
            "receipt": provenance["original_receipt"], "adoption": provenance["original_adoption"],
            "artifact_key": asset["original"]["artifact_key"]}
        check = intake.inspect_candidate(candidate, manifest, allowed_roots=[PROJECT], now=bundle["now"])
        if check["status"] != "metadata_ready_for_compiler":
            raise ValueError("STUDIO_REFERENCE_CURRENT_CAST_NOT_READY: " + ",".join(check["reasons"]))


def append_spatial_preview(request, previs):
    """Expose explicit proxy geometry to director input without changing source."""
    request = deepcopy(request)
    original = json.loads(request["messages"][1]["content"])
    original["studio_spatial_previs"] = {"scene": deepcopy(previs["scene"]),
        "validation": deepcopy(previs["validation"]),
        "purpose": "Use these explicit proposed positions/camera and stable IDs in planning; preserve full script and reference.",
        "source_is_native_frame": False, "production_adopted": False,
        "geometry_is_provisional": previs["validation"]["provisional"],
        "physics_or_visual_identity_proven": False}
    request["messages"][1]["content"] = json.dumps(original, ensure_ascii=False, sort_keys=True)
    return request


def prepare_workspace(workspace=DEFAULT_WORKSPACE, *, scene=None, scene_sequence=None, reference_bundle=None,
                      mcp_snapshot=None, provider_declaration=None, source_loader=inspect_source):
    workspace = Path(workspace).resolve()
    if not workspace.is_relative_to(WORKSPACES.resolve()) or workspace == WORKSPACES.resolve():
        raise ValueError("STUDIO_WORKSPACE_OUTSIDE_INDEPENDENT_ROOT")
    if workspace.exists():
        raise ValueError("STUDIO_WORKSPACE_ALREADY_EXISTS_USE_STATUS")
    verified = source_loader()
    if verified["report"].get("new_calls") != 0 or verified["report"].get("native_plan_adopted") is not False:
        raise ValueError("STUDIO_SOURCE_MUST_BE_VERIFIED_READ_ONLY")
    manifest = verified["input"]["manifest"]
    # Validate every optional input before creating a workspace.
    sequence = None
    if scene_sequence is not None:
        if scene is not None:
            raise ValueError("STUDIO_SCENE_AND_SEQUENCE_MUTUALLY_EXCLUSIVE")
        sequence = spatial.build_previs_sequence(scene_sequence, manifest)
        scene = scene_sequence[0]
    previs = spatial.build_previs_bundle(scene, manifest) if scene is not None else None
    reference = None
    request, wire = deepcopy(verified["request"]), deepcopy(verified["wire"])
    if previs is not None:
        request = append_spatial_preview(request, previs)
        if sequence is not None:
            original = json.loads(request["messages"][1]["content"])
            original["studio_spatial_previs"]["scene_sequence"] = deepcopy(scene_sequence)
            original["studio_spatial_previs"]["sequence_validation"] = deepcopy(sequence["validation"])
            request["messages"][1]["content"] = json.dumps(original, ensure_ascii=False, sort_keys=True)
        wire = providers.preview_text_request(request)["expected_wire_body"]
    if reference_bundle is not None:
        b = deepcopy(reference_bundle)
        validate_reference_source(b, manifest)
        if b.get("messages") is not None:
            if b["messages"] != verified["request"]["messages"]:
                raise ValueError("STUDIO_DIRECTOR_REFERENCE_SOURCE_MESSAGES_CHANGED")
            b["messages"] = deepcopy(request["messages"])
        reference = spatial.compile_reference_projection(b["binding_contract"], b["selected_asset_ids"],
            mode=b["mode"], payload=b.get("payload"), messages=b.get("messages"), now=b["now"],
            expected_account_binding_sha256=b.get("expected_account_binding_sha256"),
            provider_get_evidence=b.get("provider_get_evidence"),
            expected_continuation=b.get("expected_continuation"), required_entities=b.get("required_entities"))
        if reference["channel"] == "director_messages":
            # The images must augment THIS full source request, never replace
            # it with unrelated user-provided messages or filenames.
            request["messages"] = deepcopy(reference["compiler_result"]["messages"])
            wire = providers.preview_text_request(request)["expected_wire_body"]
    provider_gate = providers.inspect_provider_gate(mcp_snapshot, provider_declaration)
    graph = graph_for(workspace, verified)
    if scene is not None:
        graph["nodes"][1]["input"]["scene_sha256"] = digest(scene)
        graph["nodes"][3]["input"].update(spatial_previs_in_request=True, request_sha256=digest(request))
    if reference_bundle is not None:
        director_bound = reference["channel"] == "director_messages"
        graph["nodes"][2]["input"].update(
            asset_binding="metadata_compiled" if director_bound else "media_payload_compiled_director_unbound",
            reference_channel=reference["channel"], director_images_in_request=director_bound,
            reference_bundle_sha256=digest(reference_bundle))
    workspace.mkdir(parents=True, exist_ok=False)
    for name, obj in (("SOURCE_SNAPSHOT.json", verified["input"]), ("SOURCE_PROOF.json", verified["report"]),
        ("DAG.json", graph), ("FULL_MODEL_REQUEST_PREVIEW.json", request),
        ("SDK_WIRE_BODY_PREVIEW.json", wire), ("ENDPOINT_FEEDBACK_PREVIEW.json", verified["feedback"]),
        ("PROVIDER_GATE.json", provider_gate)):
        save(workspace / name, obj)
    if previs is not None:
        save(workspace / "SCENE.json", scene)
        save(workspace / "PREVIS_BUNDLE.json", previs)
        (workspace / "PREVIS_BLENDER.py").write_text(previs["blender_python"], encoding="utf-8")
    if sequence is not None:
        save(workspace / "SCENE_SEQUENCE.json", scene_sequence)
        save(workspace / "PREVIS_SEQUENCE.json", sequence)
    if mcp_snapshot is not None:
        save(workspace / "MCP_SCHEMA_SNAPSHOT.json", mcp_snapshot)
    if provider_declaration is not None:
        save(workspace / "PROVIDER_DECLARATION.json", provider_declaration)
    if reference is not None:
        save(workspace / "REFERENCE_PROJECTION.json", reference)
        save(workspace / "REFERENCE_BUNDLE.json", reference_bundle)
    store = tasks.TaskStore(workspace / "TASKS.sqlite3")
    store.register_graph(graph)
    record_local_preparation(store, graph["graph_id"], workspace, previs, reference)
    scope = verified["report"]["director_capacity"]
    store.register_authorization({"schema_version": "creative_studio_authorization/v1",
        "authorization_id": graph["graph_id"] + ":inherited_direction_scope", "graph_id": graph["graph_id"],
        "node_ids": ["direction"], "scope": "text", "purpose": "dispatch",
        "source_sha256": store.snapshot(graph["graph_id"])["source_sha256"],
        "max_attempts": scope["candidate_limit"], "prior_attempts": scope["attempts_including_claims"],
        "allows_content_revision": True, "evidence_ref": str(frozen.ROOT / "USER_SCOPE.json"),
        "evidence_sha256": sha(frozen.ROOT / "USER_SCOPE.json")})
    fixed = {p.name: sha(p) for p in workspace.iterdir() if p.is_file() and p.suffix in (".json", ".py")}
    initial_attempts = store.snapshot(graph["graph_id"])["attempts"]
    save(workspace / "WORKSPACE_MANIFEST.json", {"schema": VERSION + "/workspace_manifest",
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "fixed_files": fixed,
        "original_files": verified["report"]["original_file_hashes"],
        "runtime_sources": {str(PROJECT / p): sha(PROJECT / p) for p in (
            "scripts/run_creative_studio_v1.py", "src/content_factory/creative_studio_reference_previs_v1.py",
            "src/content_factory/creative_studio_task_store_v1.py", "src/content_factory/creative_studio_provider_bridge_v1.py")},
        "production_ledger_updated": False,
        "claims_created": len(initial_attempts),
        "local_claims_created": sum(a["provider_id"] == "local_compiler" for a in initial_attempts),
        "paid_claims_created": 0})
    result = status_workspace(workspace)
    save(workspace / "INITIAL_STUDIO_STATUS.json", result)
    return result


def record_local_preparation(store, graph_id, workspace, previs, reference):
    """Record actual local compilation separately from paid model execution."""
    scope = {"schema": VERSION + "/development_scope", "graph_id": graph_id,
        "user_instruction": "先保存目前的内容，可以持久记忆然后按你的建议组合开始开发；子agent开发，我审查直到开发完毕。",
        "operations": "Only local preparation of the supplied scene/reference projections.",
        "new_paid_calls": 0, "paid_dispatch_authorized": False, "production_content_adopted": False}
    scope_path = workspace / "LOCAL_DEVELOPMENT_SCOPE.json"
    save(scope_path, scope)
    auth = {"schema_version": "creative_studio_authorization/v1",
        "authorization_id": graph_id + ":local_preparation", "graph_id": graph_id,
        "node_ids": ["space", "references"], "scope": "offline", "purpose": "dispatch",
        "source_sha256": store.snapshot(graph_id)["source_sha256"], "max_attempts": 2, "prior_attempts": 0,
        "allows_content_revision": False, "evidence_ref": str(scope_path), "evidence_sha256": sha(scope_path)}
    for node, name, material in (("space", "PREVIS_BUNDLE.json", previs),
            ("references", "REFERENCE_PROJECTION.json", reference)):
        if material is None:
            continue
        if node == "references" and material["channel"] != "director_messages":
            # A media payload is retained for its later stage, but this node
            # gates the director's actual image input and must remain blocked.
            continue
        attempt = store.claim(graph_id, node, {"provider_id": "local_compiler",
            "payload": {"operation": node, "artifact_sha256": sha(workspace / name)}}, auth)
        output = {"artifact": {"path": str(workspace / name), "sha256": sha(workspace / name)},
            "local_contract_validated": True, "production_adopted": False,
            "new_paid_calls": 0, "human_content_approval": None}
        raw = json.dumps({"local_compiler": node, "output": output}, ensure_ascii=False, sort_keys=True)
        store.accept_result(attempt["claim_id"], {"schema_version": "creative_studio_result/v1",
            "claim_id": attempt["claim_id"], "request_sha256": attempt["request_sha256"], "service_task_id": None,
            "outcome": "completed", "result_known": True, "usage_known": True,
            "usage": {"unit": "provider_units", "amount": 0}, "complete": True, "complete_end": True,
            "schema_tool_status": "not_applicable", "contract_valid": True,
            "raw_receipt": {"encoding": "utf-8", "body": raw,
                "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(), "http_status": None}, "output": output})


def verify_workspace(workspace):
    workspace = Path(workspace).resolve()
    if not workspace.is_relative_to(WORKSPACES.resolve()):
        raise ValueError("STUDIO_WORKSPACE_OUTSIDE_INDEPENDENT_ROOT")
    m = read(workspace / "WORKSPACE_MANIFEST.json")
    for name, expected in m["fixed_files"].items():
        p = (workspace / name).resolve()
        if not p.is_relative_to(workspace) or sha(p) != expected:
            raise ValueError("STUDIO_FIXED_INPUT_CHANGED")
    for path, expected in {**m["original_files"], **m["runtime_sources"]}.items():
        if sha(path) != expected:
            raise ValueError("STUDIO_SOURCE_OR_RUNTIME_CHANGED")
    rt = frozen.runtime()
    rt.check(read(rt.ledger))
    frozen.verify_loop_history(rt)
    return workspace


def status_workspace(workspace=DEFAULT_WORKSPACE):
    workspace = verify_workspace(workspace)
    graph, source, proof = read(workspace / "DAG.json"), read(workspace / "SOURCE_SNAPSHOT.json"), read(workspace / "SOURCE_PROOF.json")
    store = tasks.TaskStore(workspace / "TASKS.sqlite3")
    snapshot = store.snapshot(graph["graph_id"])
    if snapshot["graph_definition"] != graph or snapshot["graph_sha256"] != digest(graph):
        raise ValueError("STUDIO_DATABASE_GRAPH_BINDING_CHANGED")
    originals = {n["node_id"]: n for n in graph["nodes"]}
    if {n["node_id"] for n in snapshot["nodes"]} != set(originals):
        raise ValueError("STUDIO_DATABASE_NODE_BINDING_CHANGED")
    for node in snapshot["nodes"]:
        if node["kind"] != originals[node["node_id"]]["kind"] or node["dependencies"] != originals[node["node_id"]]["depends_on"]:
            raise ValueError("STUDIO_DATABASE_NODE_BINDING_CHANGED")
        if node["kind"] == "source" and (node["input"] != originals[node["node_id"]]["input"]
                or node["input_sha256"] != digest(originals[node["node_id"]]["input"])):
            raise ValueError("STUDIO_DATABASE_SOURCE_BINDING_CHANGED")
    projection = read(workspace / "REFERENCE_PROJECTION.json") if (workspace / "REFERENCE_PROJECTION.json").exists() else None
    reference_state = "cast_and_environment_assets_unbound"
    if projection is not None:
        reference_state = ("metadata_compiled_not_content_approval" if projection["channel"] == "director_messages"
            else "media_payload_compiled_director_images_missing")
    return {"schema": VERSION, "workspace": str(workspace), "status": "offline_workspace_prepared_production_blocked",
        "source_title": source["script"]["title"], "script_sha256": proof["script_sha256"],
        "director_capacity": proof["director_capacity"], "block_reason": proof["block_reason"],
        "story_changed": False, "failed_director_adopted": False, "live_dispatch_exposed": False,
        "new_paid_calls": 0, "new_media_calls": 0, "old_budget_reset": False,
        "space": "provisional_local_previs_available" if (workspace / "PREVIS_BUNDLE.json").exists() else "explicit_geometry_missing",
        "references": reference_state,
        "director_images_in_request": projection is not None and projection["channel"] == "director_messages",
        "local_claims_created": sum(a["provider_id"] == "local_compiler" for a in snapshot["attempts"]),
        "paid_claims_created": sum(a["provider_id"] != "local_compiler" for a in snapshot["attempts"]),
        "provider_gate": read(workspace / "PROVIDER_GATE.json"),
        "tasks": snapshot, "recovery": store.recover(graph["graph_id"]),
        "quality": {"interface_passed": False, "usable_full_director": False,
            "performance_available": False, "production_handoff_available": False, "human_video_approval": None},
        "restore_reminder": "如组合后的内容不满意，可恢复已保存的基线副本或选择旧入口；旧账本与冻结历史完整保留。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "prepare", "preview", "status", "recover", "provider-preview"))
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--scene", type=Path)
    parser.add_argument("--offline-space-example", action="store_true",
        help="Use an assistant-authored two-person proxy layout, never native/user-approved geometry.")
    parser.add_argument("--reference-bundle", type=Path)
    parser.add_argument("--mcp-tools-list", type=Path)
    parser.add_argument("--mcp-capture", type=Path)
    parser.add_argument("--provider-declaration", type=Path)
    parser.add_argument("--media-request", type=Path)
    args = parser.parse_args()
    snapshot, declaration = None, None
    if args.mcp_tools_list is not None:
        if args.mcp_capture is None:
            parser.error("--mcp-tools-list requires original capture metadata in --mcp-capture")
        snapshot = providers.import_mcp_snapshot(args.mcp_tools_list.read_bytes(), capture=read(args.mcp_capture))
    if args.provider_declaration is not None:
        declaration = read(args.provider_declaration)
    if args.command == "inspect":
        verified = inspect_source()
        result = {"source_title": verified["input"]["script"]["title"], "source_proof": verified["report"],
            "libtv_gate": providers.inspect_provider_gate(), "new_paid_calls": 0}
    elif args.command == "prepare":
        scene = read(args.scene) if args.scene else None
        scene_sequence = None
        source_loader = inspect_source
        if args.offline_space_example:
            if scene is not None:
                parser.error("--scene and --offline-space-example are mutually exclusive")
            verified = inspect_source()
            example = spatial.build_offline_previs_example(verified["input"]["manifest"])
            scene_sequence = example["scenes"]
            source_loader = lambda: verified
        result = prepare_workspace(args.workspace, scene=scene, scene_sequence=scene_sequence,
            reference_bundle=read(args.reference_bundle) if args.reference_bundle else None,
            mcp_snapshot=snapshot, provider_declaration=declaration, source_loader=source_loader)
    elif args.command == "provider-preview":
        if snapshot is not None and declaration is not None and args.media_request is not None:
            result = providers.build_media_request_preview(snapshot, declaration, read(args.media_request))
        else:
            result = providers.inspect_provider_gate(snapshot, declaration)
    else:
        result = status_workspace(args.workspace)
        if args.command == "preview":
            result = {"status": result, "logical_request": read(args.workspace / "FULL_MODEL_REQUEST_PREVIEW.json"),
                "sdk_body": read(args.workspace / "SDK_WIRE_BODY_PREVIEW.json"), "dispatched": False}
        elif args.command == "recover":
            result = {"recovery": result["recovery"], "no_requests_dispatched": True}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
