"""Temporary synthetic certificates/HTTP MockTransport only; zero real media calls."""
from copy import deepcopy
import json
from pathlib import Path
import socket

import httpx
import pytest
from scripts import creative_world_scene_video_submit_v1 as m


def put(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), "utf-8"); return path


class Counter:
    stopped = False
    def assert_dispatch_allowed(self, key):
        assert key == "offline_round"
        if self.stopped: raise ValueError("offline round completed after claim")


@pytest.fixture
def factory(tmp_path, monkeypatch):
    def deny(*a, **kw): raise AssertionError("no network or real GPU calls in these tests")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    project = tmp_path / "project"; project.mkdir()
    marker = project / "synthetic_submitter_source.py"; marker.write_text("OFFLINE SYNTHETIC SOURCE MARKER", "utf-8")
    monkeypatch.setattr(m, "__file__", str(marker))
    calls = []; response_mode = {"value": "success"}; current = {}
    def handler(request):
        path = request.url.path; calls.append((request.method, path))
        if path == "/system_stats":
            return httpx.Response(200, json={"system": {"argv": ["--offline", "--preview-method", "none",
                "--output-directory", str(project / "service/output"), "--input-directory", str(project / "service/input")]}})
        if path == "/queue": return httpx.Response(200, json={"queue_running": [], "queue_pending": []})
        if request.method == "POST":
            current["payload"] = json.loads(request.content)
            if response_mode["value"] == "timeout": raise httpx.ReadTimeout("synthetic unknown response", request=request)
            if response_mode["value"] == "rejected": return httpx.Response(400, json={"error": "synthetic node rejection"})
            return httpx.Response(200, json={"prompt_id": "offline-original-id", "number": 1, "node_errors": {}})
        assert path == "/history/offline-original-id"
        return httpx.Response(200, json={"offline-original-id": deepcopy(current["history"])})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    def build(name="prepared", production_sha="c" * 64):
        root = project / name; root.mkdir()
        graph = {"condition": {"class_type": "OFFLINE_NOT_A_REAL_GRAPH", "inputs": {"prompt": "SYNTHETIC PROMPT"}}}
        put(root / "workflow_api.json", graph); (root / "PROMPT.txt").write_text("SYNTHETIC PROMPT", "utf-8")
        put(root / "REFERENCE_MAP.json", [])
        for f in ("TEXT_VERIFIED.json", "PRODUCTION_VERIFIED.json", "SERVICE_READONLY.json"): put(root / f, {"OFFLINE": True})
        ledger = put(root / "inherited_ledger.json", {"schema": "same_story_local_h3_video_failure_ledger/v1", "story_id": "same-story",
            "failure_limit": 10, "failures_used": 1, "known_rejections": 1, "technical_failures": 0,
            "observed_local_video_submissions": 2, "not_a_new_story_reset": True, "old_receipts_and_unknowns_retained": True, "events": []})
        base = {"schema": "creative_world_scene_media_probe/v1/prepared", "synthetic": False,
            "eligible_for_root_single_submit_review": True, "graph_sha256": m.sha(root / "workflow_api.json"),
            "prompt_sha256": m.sha(root / "PROMPT.txt"), "reference_map_sha256": m.sha(root / "REFERENCE_MAP.json"),
            "text_handoff_sha256": "b" * 64, "production_handoff_sha256": production_sha,
            "timing": {"native_encoding": {"OFFLINE": True}, "encoded_duration_seconds": 8, "fps": 24, "length": 192},
            "failure_ledger": {"path": str(ledger), "file_sha256": m.sha(ledger), "story_id": "same-story"},
            "output_root": str(project / "service/output"), "output_prefix": "world_scene_live/" + name,
            "width": 1280, "height": 704}
        put(root / "PREPARED.json", base)
        put(root / "PREPARED_V2.json", {"schema": "creative_world_scene_media_probe/v2/prepared", "synthetic": False,
            "eligible_for_root_single_submit_review": True, "base_prepared_path": str(root / "PREPARED.json"),
            "base_prepared_sha256": m.sha(root / "PREPARED.json"), "native_encoding": base["timing"]["native_encoding"],
            **{k: base[k] for k in ("graph_sha256", "text_handoff_sha256", "production_handoff_sha256")}})
        put(root / "OBJECT_INFO.json", {"OFFLINE": "not real node descriptors"})
        put(root / "NATIVE_VALIDATION.json", {"schema": m.VERSION + "/native_validation", "valid": True, "node_errors": {},
            "graph_sha256": base["graph_sha256"], "validator_code_sha256": m.sha(marker), "node_execution_performed": False,
            "server_native_validation_performed": False, "object_info_sha256": m.sha(root / "OBJECT_INFO.json")})
        config = m.Config(str(root), str(root / "AUTHORIZATION.json"), str(project / "counter"), "offline_round")
        counter = Counter()
        session = m.Submitter(config, verifier=lambda path: {"valid": True, "accepted": True,
            "source_files": {str(marker): m.sha(marker)}}, client=client, counter=counter, project=project,
            metadata_probe=lambda path, **kw: {"valid": True, "OFFLINE": "synthetic metadata; not real container verification"})
        put(config.authorization_path, session.authorization_template())
        return session, base, graph, counter
    yield build, calls, response_mode, current
    client.close()


def test_single_post_original_history_four_byte_identical_files_no_content_review(factory):
    build, calls, mode, current = factory; s, base, graph, _ = build()
    before = s.preview(); assert not calls and not (s.root / "RUN_CLAIM.json").exists()
    assert s.submit()["prompt_id"] == "offline-original-id"
    assert [c for c in calls if c[0] == "POST"] == [("POST", "/prompt")]
    assert m.read(s.root / "MEDIA_CALL_LEDGER.json")["inherited_media_submissions"] == 2
    output = Path(base["output_root"]) / base["output_prefix"]; output.mkdir(parents=True)
    outputs = {}
    for node, (field, suffix, _) in m.SAVES.items():
        path = output / (node + suffix); path.write_bytes(("OFFLINE SYNTHETIC FILE " + node).encode())
        outputs[node] = {field: [{"filename": path.name, "subfolder": base["output_prefix"], "type": "output"}]}
    current["history"] = {"prompt": [1, "offline-original-id", graph, {"client_id": current["payload"]["client_id"]}],
        "status": {"completed": True, "status_str": "success"}, "outputs": outputs}
    assert s.poll()["state"] == "success"
    result = s.finalize()
    assert result["status"] == "awaiting_human_review" and result["content_review"] is None
    assert not result["generated_media_opened_or_listened"] and not result["frame_extraction_performed"]
    assert all(m.sha(row["path"]) == m.sha(row["original_service_path"]) for row in result["files"].values())
    with pytest.raises(m.Blocked, match="already claimed"): s.submit()
    assert len([c for c in calls if c[0] == "POST"]) == 1


@pytest.mark.parametrize("mode_name", ["timeout", "rejected"])
def test_unknown_or_known_http_failure_preserves_one_claim_and_never_reposts(factory, mode_name):
    build, calls, mode, _ = factory; s, *_ = build(); mode["value"] = mode_name
    if mode_name == "timeout":
        with pytest.raises(httpx.ReadTimeout): s.submit()
        assert m.read(s.root / "SUBMISSION_UNKNOWN.json")["do_not_resubmit"]
        assert not (s.root / "SUBMISSION_RECEIPT.json").exists()
    else:
        assert s.submit()["state"] == "submission_http_rejected"
        assert not (s.root / "SUBMISSION_UNKNOWN.json").exists()
    with pytest.raises(m.Blocked, match="already claimed"): s.submit()
    assert len([c for c in calls if c[0] == "POST"]) == 1 and (s.root / "RUN_CLAIM.json").exists()


@pytest.mark.parametrize("fault", ["counter_stopped", "graph_changed"])
def test_claim_then_locked_guard_failure_never_reaches_post(factory, monkeypatch, fault):
    build, calls, _, _ = factory; s, *_ = build()
    original = m.create
    def changed(path, value):
        original(path, value)
        if Path(path) == s.root / "RUN_CLAIM.json":
            if fault == "counter_stopped": s.counter.stopped = True
            else: (s.root / "workflow_api.json").write_text("changed after claim", "utf-8")
    monkeypatch.setattr(m, "create", changed)
    with pytest.raises(ValueError): s.submit()
    assert (s.root / "RUN_CLAIM.json").exists() and not any(c[0] == "POST" for c in calls)
    assert not (s.root / "POST_STARTED.json").exists()


def test_same_global_authorization_different_root_and_production_cannot_regrant(factory):
    build, calls, _, _ = factory; first, *_ = build("first")
    first.submit(); second, *_ = build("second", production_sha="d" * 64)
    with pytest.raises(m.Blocked, match="already claimed"): second.submit()
    assert not (second.root / "RUN_CLAIM.json").exists()
    assert len([c for c in calls if c[0] == "POST"]) == 1


def test_original_id_query_checks_graph_and_does_not_require_fresh_source_or_new_authorization(factory):
    build, calls, _, current = factory; s, base, graph, _ = build(); s.submit()
    Path(base["failure_ledger"]["path"]).write_text("later external ledger update", "utf-8")
    s.counter.stopped = True
    current["history"] = {"prompt": [1, "offline-original-id", graph, {"client_id": current["payload"]["client_id"]}],
        "status": {"completed": False, "status_str": "running"}, "outputs": {}}
    result = s.poll(); assert result["source_drift_since_submission"] and result["state"] == "running_or_pending_original_id"
    current["history"]["prompt"][2] = {"wrong": "graph"}
    with pytest.raises(m.Blocked, match="original service graph"): s.poll()
    assert len([c for c in calls if c[0] == "POST"]) == 1


def test_native_validation_and_service_output_contract_must_match_before_claim(factory):
    build, calls, _, _ = factory; s, *_ = build()
    validation = m.read(s.root / "NATIVE_VALIDATION.json"); validation["graph_sha256"] = "0" * 64
    put(s.root / "NATIVE_VALIDATION.json", validation)
    with pytest.raises(m.Blocked, match="local graph/schema validation"): s.submit()
    assert not calls and not (s.root / "RUN_CLAIM.json").exists()


def test_local_object_info_schema_expands_reference_slots_and_rejects_wrong_link_or_enum():
    infos = {"Load": {"input": {"required": {"image": [["reference.png"]]}}, "output": ["IMAGE"]},
        "H3": {"input": {"required": {"length": ["INT", {"min": 5, "max": 362}]}, "optional": {
            "refs": ["COMFY_AUTOGROW_V3", {"template": {"prefix": "image_", "min": 0, "max": 3,
                "input": {"required": {"image": ["IMAGE"]}}}}]}}, "output": []}}
    graph = {"load": {"class_type": "Load", "inputs": {"image": "reference.png"}},
        "h3": {"class_type": "H3", "inputs": {"length": 192, "refs.image_0": ["load", 0]}}}
    assert m.validate_graph_schema(graph, infos)["valid"]
    bad = deepcopy(graph); bad["h3"]["inputs"]["refs.image_0"][1] = 1
    with pytest.raises(m.Blocked, match="output index"): m.validate_graph_schema(bad, infos)
    bad = deepcopy(graph); bad["load"]["inputs"]["image"] = "wrong-reference.png"
    with pytest.raises(m.Blocked, match="enum/model"): m.validate_graph_schema(bad, infos)
    bad = deepcopy(graph); bad["h3"]["inputs"]["refs.image_4"] = ["load", 0]
    with pytest.raises(m.Blocked, match="input slots"): m.validate_graph_schema(bad, infos)
