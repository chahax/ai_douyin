"""Full v9 coordinator/ledger/contracts with synthetic native model envelopes.

Only provider discovery and model responses are faked. No production contract,
source validator, episode validator, ledger or final review gate is replaced.
"""
from copy import deepcopy
import json
from types import SimpleNamespace

from src.content_factory import corpus_chapter_materials_v6 as materials
from src.content_factory import corpus_production_v9 as pipeline
from src.content_factory.corpus_scope_v9 import record_cloud_authorization
from tests.test_corpus_episode_state_v6 import episode_fixture
from tests.test_corpus_production_contract_v6 import Fake, DRAFT


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def response(value, identifier, model):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    usage = {"prompt_tokens": 80, "completion_tokens": 20, "total_tokens": 100}
    return SimpleNamespace(
        text=text,
        metadata={**usage, "response_id": identifier, "response_model": model, "finish_reason": "stop"},
        response_payload={"id": identifier, "model": model, "fixture": True,
            "choices": [{"finish_reason": "stop", "message": {"content": text}}], "usage": usage},
    )


def test_full_native_envelope_pipeline_produces_bound_draft_and_reentry_is_read_only(tmp_path, monkeypatch):
    original_chapters, original_library, snapshot = episode_fixture()
    routes = {
        "writer": {"provider": "minimax", "model": "MiniMax-M3.1-Flash", "base_url": "https://fixture.invalid"},
        "director": {"provider": "deepseek", "model": "deepseek-flash", "base_url": "https://fixture.invalid"},
    }
    monkeypatch.setattr(pipeline, "_cloud_routes", lambda: deepcopy(routes))
    monkeypatch.setattr(pipeline, "preflight", lambda route: {**route, "digest": "synthetic-model-digest"})
    entries = []
    for chapter in original_chapters:
        path = put(tmp_path / "source" / f"CH{chapter['index']:03d}.json", {**chapter, "book_id": "synthetic"})
        entries.append({"index": chapter["index"], "path": str(path), "sha256": chapter["sha256"]})
    manifest = put(tmp_path / "source" / "MANIFEST.json", {
        "book_id": "synthetic", "book_name": original_library["book_name"],
        "status": "accessible_catalogue_complete", "chapters": entries,
    })
    history = put(tmp_path / "prior" / "STATE.json", {"calls_started": 7, "reported_tokens": 700, "pending": None})
    run = tmp_path / "run"
    plan = pipeline.prepare(manifest, run, user_statement="Offline native-envelope integration only",
                            previous_status=history, target_seconds=10, workers=1)
    raw_by_chapter = {row["chapter_index"]: materials.raw_candidate(row) for row in original_library["analyses"]}

    class MaterialResponses:
        def __init__(self):
            self.requests = []

        def call(self, role, messages, **kwargs):
            payload = json.loads(messages[-1]["content"])
            assert role == "writer"
            assert kwargs["max_tokens"] == 16384
            self.requests.append(deepcopy(messages))
            index = payload["chapter_index"]
            assert payload["core_chapter"]["text"] == original_chapters[index - 1]["text"]
            for context in payload["context_chapters"]:
                assert context["text"] == original_chapters[context["index"] - 1]["text"]
            return response(raw_by_chapter[index], f"local-{index}", "synthetic-qwen")

    local = MaterialResponses()
    local_clients = pipeline.StageClients(plan["local_route"], routes, minimax_client=local)
    record_cloud_authorization(run, "Synthetic offline classification authorization",
        approved_source_sha256=plan["source_sha256"], approved_destinations=plan["cloud_models"])
    state = pipeline.execute_local(run, local_clients)
    assert state["status"] == "materials_ready" and state["pending"] is None
    assert len(local.requests) == 3
    source = pipeline.read(run / "SOURCE.json")
    analyses = pipeline.read(run / "CHAPTER_MATERIALS.json")
    pack = pipeline.read(run / "CLOUD_SOURCE_PACK.json")
    fake = Fake(source, analyses, pack, snapshot)

    class ProductionResponses:
        def __init__(self):
            self.requests = []

        def call(self, role, messages, **kwargs):
            current = pipeline.read(run / "cloud" / "STATE.json")
            assert len(current["pending_calls"]) == 1
            claim_path, pending = next(iter(current["pending_calls"].items()))
            claim = pipeline.read(claim_path)
            assert claim["messages"] == messages
            expected_provider_role = "director" if claim["role"] == "local" else claim["role"]
            assert role == expected_provider_role
            if claim["role"] == "writer":
                assert kwargs["max_tokens"] == 16384
            elif claim["role"] == "local":
                assert kwargs["max_tokens"] == plan["local_route"]["max_tokens"]
            from src.content_factory import corpus_temporal_policy_v1 as temporal
            assert temporal.VERSION in messages[0]['content']
            if pending['name'].startswith('MATERIAL_REVIEW'):
                assert temporal.REVIEW_RULES in messages[0]['content']
            else:
                assert temporal.RULES not in messages[0]['content']
            payload = json.loads(messages[-1]["content"])
            value = fake(pending["name"], claim["role"], messages[0]["content"], payload, claim["json_output"])
            self.requests.append((pending["name"], claim["role"]))
            return response(value, f"cloud-{pending['ordinal']}", "synthetic-" + claim["role"])

    provider = ProductionResponses()
    clients = pipeline.StageClients(plan["local_route"], routes, local_client=provider, cloud_client=provider, minimax_client=provider)
    state = pipeline.execute_cloud(run, clients)
    assert state["status"] == "reviewed_draft_ready"
    assert state["pending"] is None and state["media_generated"] is False
    assert state["content_acceptance"] == "machine_review_passed_awaiting_independent_review"
    assert (run / "剧本_章节材料与本集状态.md").read_text(encoding="utf-8") == DRAFT.strip()
    binding = pipeline.read(run / "REVIEW_BINDING.json")
    assert binding["artifact_hashes"]["snapshot"]
    assert binding["final_content_sha256"] and binding["final_timing_sha256"]
    assert binding["chapter_material_reviews_sha256"]
    assert binding["media_acceptance"] is False
    names = [name for name, _ in provider.requests]
    assert all(any(name.startswith(stage) for name in names) for stage in (
        "MATERIAL_REVIEW", "FRAMEWORK_", "FRAMEWORK_LOCAL", "FRAMEWORK_CONSISTENCY",
        "EPISODE_SNAPSHOT", "SNAPSHOT_LOCAL", "VISUAL_DESIGN", "DESIGN_LOCAL", "FACTS_",
        "SCREENPLAY", "FINAL_CONTENT", "FINAL_TIMING",
    ))
    assert {name for name, role in provider.requests if role == "director"} == {"FINAL_CONTENT_00", "FINAL_TIMING_00"}
    assert all(role == "local" for name, role in provider.requests if name.startswith("MATERIAL_REVIEW_"))
    total_calls = 0
    for phase in ("materials", "cloud"):
        phase_state = pipeline.read(run / phase / "STATE.json")
        assert phase_state["status"] == "completed"
        assert phase_state["pending"] is None and phase_state["pending_calls"] == {}
        requests = sorted((run / phase).glob("CALL_[0-9][0-9][0-9].json"))
        responses = sorted((run / phase).glob("RESPONSE_[0-9][0-9][0-9].json"))
        assert len(requests) == len(responses) == phase_state["calls_started"]
        assert phase_state["reported_tokens"] == 100 * len(requests)
        total_calls += len(requests)
        for request_path, response_path in zip(requests, responses):
            claim = pipeline.read(request_path)
            native = pipeline.read(response_path)
            call_binding = pipeline.read(run / phase / "CALL_BINDINGS" / (claim["name"] + ".json"))
            request = {key: value for key, value in claim.items() if key not in ("reserved_tokens", "admitted_at")}
            assert call_binding["request_sha256"] == pipeline.digest(request)
            assert call_binding["response_file"] == response_path.name
            assert native["response_payload"]["choices"][0]["message"]["content"] == native["text"]
            assert native["response_payload"]["usage"]["total_tokens"] == 100
            assert native["metadata"]["finish_reason"] == "stop"
    assert state["calls_started"] == total_calls
    assert state["total_calls_with_history"] == total_calls + 7
    assert state["reported_tokens"] == total_calls * 100
    before = {str(path.relative_to(run)): path.read_bytes() for path in run.rglob("*") if path.is_file()}
    observed = (len(local.requests), len(provider.requests))
    assert pipeline.execute_local(run, local_clients) == state
    assert pipeline.execute_cloud(run, clients) == state
    assert (len(local.requests), len(provider.requests)) == observed
    assert {str(path.relative_to(run)): path.read_bytes() for path in run.rglob("*") if path.is_file()} == before
