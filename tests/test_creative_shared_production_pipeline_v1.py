"""Whole production integration regression: frozen sources and synthetic media only.

No request is dispatched. Synthetic casting/provenance fixtures are explicitly
offline and never write approval into historical production records.
"""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

from src.content_factory import creative_shared_production_contract_v1 as shared
from src.content_factory import creative_video_trial_contract_v1 as source
from src.content_factory import creative_complete_production_pipeline_v1 as complete
from src.content_factory.seedance_client import (
    ARK_BASE_URL, ARK_MINI_MODEL, SeedanceClient, SeedanceConfig, SeedanceReference,
)
from tests.test_creative_shared_production_contract_v1 import production_fixture
from tests.test_creative_complete_production_pipeline_v1 import complete_fixture
from scripts import run_creative_shared_full_production_v1 as full_run
from src.content_factory.creative_workflow_roles import RoleResult


PROJECT = Path(__file__).resolve().parents[1]
TRIALS = PROJECT / "data/production_revisions/selected_script_video_trial_20261011"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("whole production regression is offline")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def actual_input():
    return json.loads((TRIALS / "script487_continuation_v8/INPUT.json").read_text(encoding="utf-8"))


def actual_script():
    return actual_input()["full_current_script"]


def unknown_policy():
    return {"status": "unknown", "provider_id": "ark_api",
        "model": "doubao-seedance-2-0-mini-260615",
        "identity_reference_mode": "unverified", "allows_actor_asset_mapping": None,
        "sources": [], "reason": "离线回归未声明平台参考许可"}


def provider_fixture(tmp_path, base_fixture=None):
    script, manifest, state = base_fixture or production_fixture()
    policy = manifest["provider_policy"]
    policy.update(provider_id="ark_api", model=ARK_MINI_MODEL)
    doc = next(x for x in manifest["provenance_catalog"] if x["source_id"] == "policy")
    doc["text"] = "离线平台夹具：ark_api " + ARK_MINI_MODEL + " 支持 reference_image、first_frame、text_to_video_bootstrap。"
    doc["sha256"] = shared.text_sha256(doc["text"])
    policy["sources"] = [{"source_id": doc["source_id"], "quote": doc["text"]}]
    image = tmp_path / "offline_identity_bytes.png"
    image.write_bytes(b"OFFLINE_REFERENCE_BYTES_NOT_A_GENERATED_IMAGE")
    asset = manifest["asset_catalog"][0]
    asset.update(path=str(image), sha256=hashlib.sha256(image.read_bytes()).hexdigest())
    state["global_manifest_sha256"] = shared.digest(manifest)
    return script, manifest, state


def payload_without_http(prompt, duration, assets, mode):
    # Do not construct the HTTP client or any real credentials/ledger.
    client = object.__new__(SeedanceClient)
    client.config = SeedanceConfig(api_key="offline-placeholder", base_url=ARK_BASE_URL,
        model=ARK_MINI_MODEL, provider="ark_api")
    refs = []
    for asset in assets:
        encoded = base64.b64encode(Path(asset["path"]).read_bytes()).decode("ascii")
        refs.append(SeedanceReference("image", "data:image/png;base64," + encoded, mode))
    return client.build_task_payload(prompt, duration=duration, references=refs,
        task_type="text" if mode == "text_to_video_bootstrap" else "auto", resolution="480p")


def attachments_from_payload(payload, compiled):
    images = [x for x in payload["content"] if x["type"] == "image_url"]
    assert len(images) == len(compiled["media_binding"]["assets"])
    return [{"asset_id": asset["asset_id"],
        "sha256": hashlib.sha256(base64.b64decode(item["image_url"]["url"].split(",", 1)[1])).hexdigest(),
        "reference_mode": item["role"]}
        for item, asset in zip(images, compiled["media_binding"]["assets"])]


def test_actual_frozen_context_cannot_infer_identity_or_asset_subject_mapping():
    x = actual_input(); script = x["full_current_script"]
    manifest = shared.build_pending_manifest(script, x["scene_and_character_context"], unknown_policy())
    before = deepcopy(manifest)
    result = shared.production_gate(manifest, script)
    assert result["status"] == "shared_pending"
    assert manifest == before
    assert {a["id"] for a in manifest["actors"]} == {"zhou", "xiaolin"}
    for actor in manifest["actors"]:
        for key in shared.PROFILE_FIELDS:
            assert actor["profile"][key]["status"] == "unknown"
            assert actor["profile"][key]["value"] is None
        assert actor["asset_binding"]["status"] == "unknown"
    assert result["voice_identity_guaranteed"] is False
    assert result["pixel_identity_verified"] is False
    assert result["calls_authorized"] is False


def test_old_complete_transport_and_opening_review_are_not_whole_production_acceptance():
    whole = json.loads((TRIALS / "script487_v4/call_495_whole_direction.json").read_text(encoding="utf-8"))
    opening = json.loads((TRIALS / "script487_v6/call_498_production_text_review.json").read_text(encoding="utf-8"))
    assert whole["status"] == "contract_rejected"
    assert whole["response_metadata"]["response_body_complete"] is True
    assert whole["response_metadata"]["total_tokens"] == 8018
    assert opening["status"] == "contract_valid"
    assert opening["response_metadata"]["total_tokens"] == 10697
    # Source and historical transport records stay byte-for-byte untouched.
    input_path = TRIALS / "script487_continuation_v8/INPUT.json"
    original = input_path.read_bytes()
    assert source.digest(actual_script()) == "cbb125ea23dbefca1c314d53bc26ce7c231d1b3ab39b256b1b20d8dcde520d0d"
    assert hashlib.sha256(input_path.read_bytes()).digest() == hashlib.sha256(original).digest()


def test_shared_identity_reaches_exact_seedance_payload_without_quality_or_voice_claim(tmp_path):
    script, manifest, state = provider_fixture(tmp_path)
    compiled = shared.compile_segment_context(manifest, script, state, ["B1.S01"])
    fragment = shared.render_shared_context(compiled, manifest, script, state, ["B1.S01"])
    prompt = fragment + "\n当前表演：两人接收当前信息，保持自然呼吸。"
    payload = payload_without_http(prompt, 4, compiled["media_binding"]["assets"], "reference_image")
    actual_text = next(item["text"] for item in payload["content"] if item["type"] == "text")
    result = shared.validate_provider_request_coverage(compiled, actual_text,
        attachments_from_payload(payload, compiled), "ark_api", payload["model"])
    assert actual_text == prompt
    assert result["status"] == "shared_request_coverage_valid"
    assert result["global_manifest_sha256"] == shared.digest(manifest)
    assert result["media_status"] == "awaiting_human_review"
    assert result["pixel_subject_mapping_verified"] is False
    assert result["voice_identity_guaranteed"] is False
    for actor in manifest["actors"]:
        assert actor["id"] + "=" + actor["name"] in actual_text
        for fact in actor["profile"].values():
            assert fact["value"] in actual_text
    with pytest.raises(ValueError, match="complete shared projection"):
        shared.validate_provider_request_coverage(compiled, actual_text + "\n" + fragment,
            attachments_from_payload(payload, compiled), "ark_api", payload["model"])


def test_continuation_uses_actual_tail_bytes_with_same_global_manifest_and_separate_media_binding(tmp_path):
    script, manifest, state = provider_fixture(tmp_path)
    first = shared.compile_segment_context(manifest, script, state, ["B1.S01"])
    state.update(completed_source_refs=["B1.S01"], previous_scene_id="meeting_room")
    tail_path = tmp_path / "offline_original_tail.png"
    tail_path.write_bytes(b"OFFLINE_APPROVED_ORIGINAL_TAIL_BYTES_DISTINCT_FROM_MASTER")
    tail_sha = hashlib.sha256(tail_path.read_bytes()).hexdigest()
    tail = {"path": str(tail_path), "sha256": tail_sha, "role": "first_frame",
        "source": "generation_service_original", "source_task_id": "offline-task",
        "source_segment_id": "M001", "source_video_sha256": "c" * 64,
        "human_review_path": str(tmp_path / "offline_review.json"), "human_review_sha256": "d" * 64,
        "human_review_decision": "approved", "global_manifest_sha256": shared.digest(manifest),
        "actor_ids": [actor["id"] for actor in manifest["actors"]]}
    binding = {"role": "first_frame", "assets": [{"asset_id": "offline_original_tail_M001",
        "sha256": tail_sha, "path": str(tail_path), "kind": "image"}], "tail_evidence": tail}
    second = shared.compile_segment_context(manifest, script, state, ["B1.S02"], media_binding=binding)
    fragment = shared.render_shared_context(second, manifest, script, state, ["B1.S02"], media_binding=binding)
    payload = payload_without_http(fragment + "\n周姐向小林提出当前要求。", 4, binding["assets"], "first_frame")
    attached = attachments_from_payload(payload, second)
    result = shared.validate_provider_request_coverage(second, payload["content"][0]["text"], attached,
        "ark_api", payload["model"])
    assert first["global_manifest_sha256"] == second["global_manifest_sha256"]
    assert first["media_binding_sha256"] != second["media_binding_sha256"]
    assert attached[0]["sha256"] == tail_sha != manifest["asset_catalog"][0]["sha256"]
    assert result["pixel_subject_mapping_verified"] is False
    assert second["tail_approval_verification_is_runner_owned"] is True
    wrong = deepcopy(attached); wrong[0]["sha256"] = manifest["asset_catalog"][0]["sha256"]
    with pytest.raises(ValueError, match="actual attachments"):
        shared.validate_provider_request_coverage(second, fragment, wrong, "ark_api", payload["model"])
    with pytest.raises(ValueError, match="without mixed references"):
        client = object.__new__(SeedanceClient)
        client.config = SeedanceConfig(api_key="offline", base_url=ARK_BASE_URL, model=ARK_MINI_MODEL, provider="ark_api")
        client.build_task_payload(fragment, duration=4, references=[
            SeedanceReference("image", "data:image/png;base64,YQ==", "first_frame"),
            SeedanceReference("image", "data:image/png;base64,Yg==", "reference_image")])


def test_new_casting_bootstrap_is_one_initial_text_video_without_false_old_asset_adoption(tmp_path):
    script, manifest, state = provider_fixture(tmp_path)
    for entity in [*manifest["actors"], *manifest["scenes"]]:
        entity["asset_binding"] = shared.unknown("离线新选角的实际人物对应尚未人工确认")
    manifest["asset_catalog"] = []
    state["global_manifest_sha256"] = shared.digest(manifest)
    assert shared.production_gate(manifest, script)["status"] == "shared_pending"
    result = shared.validate_casting_bootstrap(manifest, script)
    assert result["status"] == "casting_bootstrap_ready"
    assert result["visual_cast_approved"] is False
    assert result["formal_continuation_allowed"] is False
    first = shared.compile_segment_context(manifest, script, state, ["B1.S01"], bootstrap=True)
    payload = payload_without_http(first["prompt_fragment"], 4, [], "text_to_video_bootstrap")
    assert payload["content"] == [{"type": "text", "text": first["prompt_fragment"]}]
    assert shared.validate_provider_request_coverage(first, payload["content"][0]["text"], [],
        "ark_api", payload["model"])["media_status"] == "awaiting_human_review"
    state["completed_source_refs"] = ["B1.S01"]
    with pytest.raises(ValueError, match="first segment"):
        shared.compile_segment_context(manifest, script, state, ["B1.S02"], bootstrap=True)


def test_whole_director_all_performances_compile_and_actual_requests_share_one_identity(tmp_path):
    fixture_script, fixture_manifest, initial, fixture_direction, fixture_performances = complete_fixture()
    _, _, dynamic = production_fixture()
    script, manifest, dynamic = provider_fixture(tmp_path, (fixture_script, fixture_manifest, dynamic))
    assert script == fixture_script
    native_before = deepcopy([p["native"] for p in fixture_performances])
    direction = complete.compile_direction(fixture_direction["native"], script, manifest)
    performances, completed_refs, previous = [], [], deepcopy(initial)
    for segment, native in zip(direction["segments"], native_before):
        row = complete.compile_performance(native, script, manifest, segment, previous, completed_refs)
        performances.append(row)
        previous = row["planned_ending_state"]
        completed_refs += segment["source_refs"]
    whole = complete.compile_complete(direction, performances, script, manifest, initial)
    assert whole["source_refs"] == list(source.catalog(script))
    assert whole["whole_film_performance_complete"] is True
    assert whole["planned_state_chain_complete"] is True
    assert whole["machine_script_quality"] is False
    assert whole["source_state_semantic_review_complete"] is False
    assert whole["actual_media_quality_passed"] is False
    assert whole["human_approved"] is False
    for row, native in zip(performances, native_before):
        assert row["native"] == native
        assert row["global_manifest_sha256"] == whole["global_manifest_sha256"] == shared.digest(manifest)
        assert row["normal_spoken_characters_per_second"] == 3.3
        assert row["fit_scaled"] is False

    first = performances[0]
    projection = shared.compile_segment_context(manifest, script, dynamic, first["source_refs"])
    prompt = complete.render_prompt(first, script, manifest, projection)
    payload = payload_without_http(prompt, first["duration_seconds"], projection["media_binding"]["assets"], "reference_image")
    assert payload["content"][0]["text"].count("请看这张纸。") == 1
    assert "我先看一下。" not in payload["content"][0]["text"]
    coverage = shared.validate_provider_request_coverage(projection, payload["content"][0]["text"],
        attachments_from_payload(payload, projection), "ark_api", payload["model"])
    assert coverage["global_manifest_sha256"] == whole["global_manifest_sha256"]
    action, speech = first["schedule"]
    assert action["start_seconds"] == speech["start_seconds"]
    assert action["overlap_with"] == speech["source_ref"]
    assert first["post_reaction_seconds"] >= first["segment"]["reaction_reserve_seconds"]
    changed = deepcopy(performances)
    changed[1]["planned_initial_state"]["props"][0]["holder"] = "zhou"
    with pytest.raises(ValueError, match="state chain changed"):
        complete.compile_complete(direction, changed, script, manifest, initial)
    changed_manifest = deepcopy(manifest)
    changed_manifest["actors"][0]["profile"]["gender_presentation"] = shared.unknown("旧断言不得人工迁就")
    with pytest.raises(ValueError):
        complete.compile_complete(direction, performances, script, changed_manifest, initial)


@pytest.fixture
def prepared_whole_run(monkeypatch, tmp_path):
    old_paths = [full_run.parent.ROOT / "CALL_LEDGER.json", full_run.parent.OUT / "receipt.json",
        full_run.parent.OUT / "receipt.human_review.json", full_run.OLD_SCRIPT, full_run.OLD_DECISION]
    before = [p.read_bytes() for p in old_paths]
    monkeypatch.setattr(full_run, "PROJECT", tmp_path)
    monkeypatch.setattr(full_run, "ROOT", tmp_path / "whole_run1")
    monkeypatch.setattr(full_run, "OUT", tmp_path / "media")
    monkeypatch.setattr(full_run, "runtime", lambda: SimpleNamespace(prepare=lambda: {"offline_only": True}))
    assert full_run.prepare() == {"offline_only": True}
    result = SimpleNamespace(project=tmp_path, root=full_run.ROOT,
        input=full_run.control.read(full_run.ROOT / "INPUT.json"),
        anchor=full_run.control.read(full_run.ROOT / "ANCHOR.json"))
    yield result
    assert [p.read_bytes() for p in old_paths] == before


def test_real511_lineage_one_opening_claim_and_frozen_initial_state_keep_history(prepared_whole_run, monkeypatch):
    env = prepared_whole_run
    inherited = env.anchor["inherited"]
    assert inherited["calls_started"] == 511 and inherited["reported_tokens"] == 7798340
    assert inherited["calls_with_known_usage"] == 509
    assert inherited["unknown_token_reservations"] == 93117 and inherited["pending_ordinals"] == [70, 160]
    scope = full_run.control.read(env.root / "USER_SCOPE.json")
    assert scope["max_script_content_revisions"] == 2
    assert scope["max_new_video_submissions"] == 1
    assert scope["batch_authorized"] is False and scope["budget_reset"] is False
    assert scope["old_unknown_and_failure_history_preserved"] is True
    script = env.input["old_script"]
    manifest = full_run.build_manifest(script, env.input)
    initial_context = {k: deepcopy(env.input["brief"][k]) for k in ["characters", "scenes", "initial_state"]}
    initial = complete.build_initial_state(initial_context, manifest)
    old_actor_states = {r["id"]: r for r in initial_context["initial_state"]["character_states"]}
    for actor in initial["actors"]:
        assert actor["posture"] == old_actor_states[actor["id"]]["expected_state"]
        assert actor["gaze"] is None and actor["emotion"] is None
    assert shared.production_gate(manifest, script)["status"] == "shared_pending"
    assert shared.validate_casting_bootstrap(manifest, script)["status"] == "casting_bootstrap_ready"
    monkeypatch.setattr(full_run, "ROOT", env.project / "whole_run2")
    with pytest.raises(RuntimeError, match="immutable artifact changed"):
        full_run.prepare()
    assert len(list((env.project / "data/creative_continuation_stages").glob("*/CLAIM.json"))) == 1


def exercise_complete_script(env, monkeypatch, mode):
    calls = []
    writer_schema = full_run.script_schema(env.input["brief"])
    refs = list(source.catalog(env.input["old_script"]))
    class Clients:
        def call(self, role, messages, **kwargs):
            calls.append((role, deepcopy(messages), deepcopy(kwargs)))
            if role == "writer":
                if mode == "outcome_unknown":
                    raise TimeoutError("offline response outcome unknown")
                native = deepcopy(env.input["old_script"])
                native["title"] = "离线完整模拟新稿 " + str(len(calls))
                text = full_run.transport.encode_envelope(native, writer_schema)
            else:
                q = {"checks": [{"check": key, "status": "pass", "source_refs": refs,
                    "reason": "离线同源全文审查夹具，不构成真实质量证明"} for key in full_run.SCRIPT_CHECKS],
                    "revision_requirements": [], "review_limitations": ["未对任何媒体内容作判断。"]}
                if mode in ("fail", "only_unknown", "fail_and_unknown"):
                    q["checks"][0]["status"] = "unknown" if mode == "only_unknown" else "fail"
                    if mode == "fail_and_unknown": q["checks"][1]["status"] = "unknown"
                    q["revision_requirements"] = ["离线模拟：必须完整生成新稿并全文复审。"]
                text = json.dumps(q, ensure_ascii=False)
            metadata = {"output_mode": "tool_call", "finish_reason": "tool_calls", "total_tokens": 20,
                "response_id": "offline-whole-" + str(len(calls)), "response_body_complete": True}
            if role == "writer" and mode == "required_tool_missing":
                metadata.update(output_mode="content", finish_reason="stop")
            if role == "writer" and mode == "truncated": metadata["finish_reason"] = "length"
            return RoleResult(text=text, metadata=metadata)
    runtime = full_run.control.ContinuationRuntime(env.project, env.root,
        [env.root / p for p in ["INPUT.json", "USER_SCOPE.json", "ANCHOR.json"]], env.anchor["inherited"],
        env.anchor["models"], client_factory=Clients, quota_state=None)
    runtime.prepare()
    monkeypatch.setattr(full_run, "prepare", lambda: None)
    monkeypatch.setattr(full_run, "runtime", lambda: runtime)
    first, second = full_run.draft(), full_run.draft()
    assert first == second
    ledger = full_run.control.read(runtime.ledger)
    assert ledger["starting_spend"] == env.anchor["inherited"]
    assert ledger["automatic_retry"] is False and ledger["old_budget_reset"] is False
    assert len(ledger["calls"]) == len(calls)
    assert [r["ordinal"] for r in ledger["calls"]] == list(range(512, 512 + len(calls)))
    return first, calls, ledger


@pytest.mark.parametrize("mode,call_count", [
    ("pass", 2), ("fail", 6), ("fail_and_unknown", 6), ("only_unknown", 2),
    ("outcome_unknown", 1), ("required_tool_missing", 1), ("truncated", 1)])
def test_full_script_known_content_revision_is_bounded_and_cached_unknown_never_reissued(prepared_whole_run, monkeypatch, mode, call_count):
    env = prepared_whole_run
    result, calls, ledger = exercise_complete_script(env, monkeypatch, mode)
    assert len(calls) == call_count
    assert result.get("actual_media_quality_passed", False) is False
    if mode == "pass":
        assert result["status"] == "complete_source_ready_for_director"
        adopted = full_run.control.read(env.root / "ADOPTED_SOURCE.json")
        assert adopted["user_adopted"] is False and adopted["original487_decision_unchanged"] is True
        assert adopted["actual_media_quality_passed"] is False
    else:
        assert not (env.root / "ADOPTED_SOURCE.json").exists()
        assert not (env.root / "VIDEO_HANDOFF.json").exists()
    if mode == "only_unknown": assert result["status"] == "script_review_unknown_no_redispatch"
    if mode in ("fail", "fail_and_unknown"):
        assert result["status"] == "bounded_complete_script_revision_exhausted"
        last = full_run.control.read(env.root / ledger["calls"][-2]["receipt"])
        original_user = json.loads(last["request"]["messages"][1]["content"])
        # JSON document transport retains the full source user message as index 1.
        assert len(original_user["previous_complete_candidates"]) == 2
        assert all("complete_native_script" in v and "full_review" in v for v in original_user["previous_complete_candidates"])

