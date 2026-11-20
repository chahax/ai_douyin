"""Current human-rejected segment repair guards; synthetic media, no network."""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

from scripts import run_selected_script_continuation_v6 as trial
from src.content_factory import media_review_policy as policy
from src.content_factory.creative_workflow_roles import RoleResult
from tests.test_creative_continuation_probe_contract_v5 import wire as valid_native


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("spatial repair tests must remain offline")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def synthetic_candidate(folder, *, segment, completed, refs, marker):
    folder.mkdir()
    video, tail = folder / "synthetic.mp4", folder / "synthetic.png"
    video.write_bytes(("OFFLINE video " + marker).encode())
    tail.write_bytes(("OFFLINE tail " + marker).encode())
    request = {"offline_fixture": marker}
    record = {"technical_status": "succeeded", "content_status": "awaiting_human_review",
        "segment_id": segment, "logical_task_id": trial.LOGICAL,
        "provider": "ark_api", "model": trial.MODEL, "task_id": "offline-" + marker,
        "request": request, "request_sha256": trial.control.digest(request),
        "plan_sha256": "offline-plan-" + marker, "source_bindings": {},
        "plan_snapshot": {"script_content_sha256": trial.SOURCE_SHA,
            "source_refs": refs, "completed_source_refs": completed},
        "video_path": str(video), "video_sha256": trial.control.sha_file(video),
        "last_frame": str(tail), "last_frame_sha256": trial.control.sha_file(tail),
        "last_frame_source": "generation_service_original"}
    write(folder / "receipt.json", record)
    write(folder / "PLAN.json", {"offline_fixture": marker})
    (folder / "PROMPT.txt").write_text("offline current prompt", encoding="utf-8")
    return folder / "receipt.json"


@pytest.fixture
def candidate_pair(monkeypatch, tmp_path):
    approved = synthetic_candidate(tmp_path / "previous", segment=trial.PREVIOUS_SID,
        completed=trial.prior_segment.COMPLETED, refs=trial.prior_segment.REFS, marker="approved-second")
    rejected = synthetic_candidate(tmp_path / "rejected", segment=trial.SID,
        completed=trial.COMPLETED, refs=trial.REFS, marker="rejected-third")
    statement = "[OFFLINE FIXTURE] rejected positions and extra person"
    policy._record_user_media_decision(approved, "approved", "[OFFLINE FIXTURE] second approved")
    policy._record_user_media_decision(rejected, "rejected", statement)
    monkeypatch.setattr(trial, "PREVIOUS_MEDIA", approved.parent)
    monkeypatch.setattr(trial.rejected_segment, "OUT", rejected.parent)
    monkeypatch.setattr(trial, "USER_FEEDBACK", statement)
    return SimpleNamespace(approved=approved, rejected=rejected,
        review=rejected.with_name("receipt.human_review.json"))


def test_actual506_known_spend_unknown_history_and_rejection_are_retained():
    ledger = trial.PARENT / "CALL_LEDGER.json"
    rejected = trial.rejected_segment.OUT / "receipt.json"
    before = (ledger.read_bytes(), rejected.read_bytes())
    inherited, binding, receipt = trial.recovery_parent()
    assert inherited["calls_started"] == 506 and inherited["reported_tokens"] == 7739310
    assert inherited["calls_with_known_usage"] == 504
    assert inherited["unknown_token_reservations"] == 93117 and inherited["pending_ordinals"] == [70, 160]
    assert receipt["ordinal"] == 505 and receipt["status"] == "contract_valid"
    assert binding["rejected_candidate"]["decision"] == "rejected"
    assert binding["format_recovery_attempts_remaining"] == 0 and binding["budget_reset"] is False
    assert trial.approved_frame()["sha256"] == "a980fb18daa9d8f421102f0e989d05ba1de10e7cb2c92b326c7a1c1e4a9c07bc"
    assert trial.approved_frame()["source_segment_id"] == trial.PREVIOUS_SID
    assert before == (ledger.read_bytes(), rejected.read_bytes())


@pytest.mark.parametrize("technical,content", [
    ("succeeded", "awaiting_human_review"), ("running", "rejected"), ("unknown", "rejected")])
def test_unresolved_candidate_cannot_open_current_repair(candidate_pair, technical, content):
    record = trial.control.read(candidate_pair.rejected)
    record.update(technical_status=technical, content_status=content)
    write(candidate_pair.rejected, record)
    with pytest.raises(ValueError, match="exact human rejection"):
        trial.rejected_candidate()


@pytest.mark.parametrize("key,value", [
    ("original_video_sha256", "0" * 64), ("raw_tail_sha256", "0" * 64),
    ("original_video", "D:/offline/another.mp4"), ("raw_tail", "D:/offline/another.png"),
    ("automated_visual_or_voice_verdict", 0)])
def test_rejection_original_media_binding_cannot_be_substituted(candidate_pair, key, value):
    review = trial.control.read(candidate_pair.review)
    review[key] = value
    write(candidate_pair.review, review)
    record = trial.control.read(candidate_pair.rejected)
    record["user_decision_sha256"] = trial.control.sha_file(candidate_pair.review)
    write(candidate_pair.rejected, record)
    with pytest.raises(ValueError, match="exact human rejection"):
        trial.rejected_candidate()


def current_input(candidate_pair):
    x = deepcopy(trial.control.read(trial.PARENT / "INPUT.json"))
    x["approved_first_frame"] = trial.approved_frame()
    x["scene_continuity_context"] = trial.contract.build_scene_continuity_context(
        x["full_current_script"], x["scene_and_character_context"], x["approved_first_frame"])
    old = trial.control.read(trial.PARENT / "call_505_continuation_performance.json")
    x["prior_current_content_revision"] = {"ordinal": 505,
        "complete_prior_native": trial.previous.received_document(old),
        "required_repairs": [trial.USER_FEEDBACK], "current_segment_new_scope": False}
    x["content_revision"] = {"rejected_candidate": trial.rejected_candidate(),
        "current_segment_content_revision_index": 1, "max_new_writer_requests": 1,
        "format_recovery_attempts_remaining": 0, "budget_reset": False}
    return x


@pytest.mark.parametrize("review_status", ["pass", "fail", "unknown"])
def test_new_native_and_ten_item_review_cache_once_and_block_handoff(
        monkeypatch, tmp_path, candidate_pair, review_status):
    root = tmp_path / "text"
    root.mkdir()
    x = current_input(candidate_pair)
    write(root / "INPUT.json", x)
    write(root / "CONTENT_REVISION_BINDING.json", x["content_revision"])
    before = deepcopy(x["prior_current_content_revision"]["complete_prior_native"])
    native = valid_native(x["full_current_script"])
    calls = []
    class Clients:
        def call(self, role, messages, **kwargs):
            calls.append((role, deepcopy(messages), deepcopy(kwargs["structured_schema"])))
            if role == "writer":
                text = trial.transport.encode_envelope(native, trial.contract.continuation_probe_schema(
                    x["full_current_script"], trial.COMPLETED, trial.REFS, x["scene_continuity_context"]))
            else:
                document = {"script_sha256": trial.SOURCE_SHA,
                    "checks": [{"check": name, "status": "pass", "source_refs": trial.REFS,
                        "reason": "offline exact current text"} for name in trial.REVIEW_CHECKS],
                    "revision_requirements": []}
                document["checks"][-1]["status"] = review_status
                text = json.dumps(document, ensure_ascii=False)
            return RoleResult(text=text, metadata={"output_mode": "tool_call", "finish_reason": "tool_calls",
                "total_tokens": 20, "response_id": "offline-" + role, "response_body_complete": True})
    models = {"writer": {"model": "MiniMax-M3"}, "director": {"model": "deepseek-chat"}}
    inherited = {"calls_started": 506, "reported_tokens": 7739310, "calls_with_known_usage": 504,
        "unknown_token_reservations": 93117, "pending_ordinals": [70, 160]}
    runtime = trial.control.ContinuationRuntime(tmp_path, root,
        [root / "INPUT.json", root / "CONTENT_REVISION_BINDING.json"], inherited, models,
        client_factory=Clients, quota_state=None)
    runtime.prepare()
    monkeypatch.setattr(trial, "ROOT", root)
    monkeypatch.setattr(trial, "prepare", lambda: None)
    monkeypatch.setattr(trial, "runtime", lambda: runtime)
    first = trial.text()
    second = trial.text()
    assert len(calls) == 2 and [c["role"] if isinstance(c, dict) else c[0] for c in calls] == ["writer", "director"]
    ledger = trial.control.read(runtime.ledger)
    assert [q["ordinal"] for q in ledger["calls"]] == [507, 508]
    assert ledger["starting_spend"] == inherited
    assert ledger["automatic_retry"] is False and ledger["old_budget_reset"] is False
    assert x["prior_current_content_revision"]["complete_prior_native"] == before
    writer_input = json.loads(calls[0][1][1]["content"])
    review_input = json.loads(calls[1][1][1]["content"])
    assert writer_input["scene_continuity_context"] == review_input["scene_continuity_context"]
    assert writer_input["prior_current_content_revision"]["complete_prior_native"] == before
    assert len(calls[1][2]["properties"]["checks"]["prefixItems"]) == 10
    compiled = trial.control.read(root / "PERFORMANCE_COMPILED.json")
    assert compiled["native"] == native
    assert compiled["requires_independent_current_review_criteria_count"] == 10
    assert review_input["current_native_direction_and_performance"] == native
    assert review_input["actual_video_prompt"] == trial.contract.render_prompt(
        compiled, x["full_current_script"], x["actor_names"])
    if review_status == "pass":
        assert first["status"] == second["status"] == "production_text_ready_for_single_continuation"
        assert (root / "VIDEO_TEXT_HANDOFF.json").exists()
    else:
        assert first["status"] == second["status"] == "production_text_needs_attention"
        assert not (root / "VIDEO_TEXT_HANDOFF.json").exists()
        with pytest.raises(FileNotFoundError): trial.make_plan()


def test_new_claim_binds_rejection_and_cannot_be_claimed_from_another_directory(
        monkeypatch, tmp_path, candidate_pair):
    inherited, _, seed = trial.recovery_parent()
    binding = {"rejected_candidate": trial.rejected_candidate(), "format_recovery_attempts_remaining": 0}
    monkeypatch.setattr(trial, "PROJECT", tmp_path)
    monkeypatch.setattr(trial, "ROOT", tmp_path / "route1")
    monkeypatch.setattr(trial, "recovery_parent", lambda: (inherited, binding, seed))
    monkeypatch.setattr(trial, "runtime", lambda: SimpleNamespace(prepare=lambda: {"offline_only": True}))
    assert trial.prepare() == {"offline_only": True}
    x = trial.control.read(trial.ROOT / "INPUT.json")
    claim_path = Path(x["content_revision"]["claim_path"])
    claim = trial.control.read(claim_path)
    assert x["content_revision"]["rejected_candidate"] == binding["rejected_candidate"]
    assert x["content_revision"]["claim_sha256"] == trial.control.sha_file(claim_path)
    assert claim["user_statement"] == trial.USER_FEEDBACK and claim["max_new_writer_requests"] == 1
    assert claim["format_recovery_attempts_remaining"] == 0 and claim["old_budget_reset"] is False
    monkeypatch.setattr(trial, "ROOT", tmp_path / "route2")
    with pytest.raises(RuntimeError, match="immutable artifact changed"):
        trial.prepare()
    assert len(list((tmp_path / "data/creative_continuation_stages").glob("*/CLAIM.json"))) == 1


def test_media_payload_contains_only_original_approved_second_tail(candidate_pair):
    frame = trial.approved_frame()
    assert frame["path"] != trial.control.read(candidate_pair.rejected)["last_frame"]
    class Client:
        config = SimpleNamespace(provider="ark_api", model=trial.MODEL)
        build_task_payload = trial.SeedanceClient.build_task_payload
    payload = trial.build_request(Client(), {"first_frame": frame, "prompt": "offline current prompt", "duration_seconds": 12})
    references = [q for q in payload["content"] if q["type"] != "text"]
    assert len(references) == 1 and references[0]["role"] == "first_frame"
    raw = base64.b64decode(references[0]["image_url"]["url"].split(",", 1)[1], validate=True)
    assert raw == Path(frame["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == frame["sha256"]
    assert payload["model"] == trial.MODEL and payload["resolution"] == "480p"
    assert payload["duration"] == 12 and payload["return_last_frame"] is True
