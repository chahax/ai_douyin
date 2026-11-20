"""Explicit resumed protocol run; immutable old failure and offline request guards."""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

from scripts import run_selected_script_continuation_v8 as trial
from src.content_factory.creative_workflow_roles import RoleResult
from tests.test_creative_continuation_probe_contract_v7 import wire as new_native

CODE_PROJECT = trial.PROJECT


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("resumed protocol tests must remain offline")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def test_real509_spend_and_exhausted_old_run_are_retained_without_adoption():
    paths = [trial.PARENT / n for n in ["CALL_LEDGER.json", "CONTENT_REVISION_BINDING.json",
        "call_509_continuation_performance.json", "PRODUCTION_RESULT.json"]]
    before = [p.read_bytes() for p in paths]
    inherited, binding, seed = trial.recovery_parent()
    assert inherited["calls_started"] == 509 and inherited["reported_tokens"] == 7772480
    assert inherited["calls_with_known_usage"] == 507
    assert inherited["unknown_token_reservations"] == 93117 and inherited["pending_ordinals"] == [70, 160]
    assert seed["status"] == "contract_rejected" and seed["ordinal"] == 509
    assert binding["historical_current_segment_content_revision_index"] == 2
    assert binding["historical_complete_content_revisions_remaining"] == 0
    assert binding["resumed_run_revision_index"] == 0
    assert binding["format_recovery_attempts_remaining"] == 0
    assert binding["old_native_adopted"] is False and binding["budget_reset"] is False
    assert binding["user_statement"] == trial.USER_RESUMPTION
    assert binding["new_contract_sha256"] == trial.control.sha_file(Path(trial.contract.__file__))
    assert trial.approved_frame()["sha256"] == "a980fb18daa9d8f421102f0e989d05ba1de10e7cb2c92b326c7a1c1e4a9c07bc"
    x = trial.control.read(trial.PARENT / "INPUT.json")
    raw = trial.control.strict_json(seed["output"]["payload_json"])
    original = deepcopy(raw)
    ctx = trial.contract.build_scene_continuity_context(x["full_current_script"],
        x["scene_and_character_context"], trial.approved_frame())
    with pytest.raises(ValueError):
        trial.contract.compile_continuation_probe(raw, x["full_current_script"], trial.COMPLETED, trial.REFS, ctx)
    assert raw == original and [p.read_bytes() for p in paths] == before


@pytest.mark.parametrize("field,value", [
    ("total_tokens", None), ("response_body_complete", False),
    ("finish_reason", "length"), ("total_tokens", -1)])
def test_unknown_or_incomplete509_cannot_open_resumed_run(monkeypatch, field, value):
    original = trial.control.read
    path = (trial.PARENT / "call_509_continuation_performance.json").resolve()
    def read(p):
        result = original(p)
        if Path(p).resolve() == path:
            result = deepcopy(result); result["response_metadata"][field] = value
        return result
    monkeypatch.setattr(trial.control, "read", read)
    with pytest.raises(ValueError, match="unknown or incomplete"):
        trial.recovery_parent()


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    monkeypatch.setattr(trial, "PROJECT", tmp_path)
    monkeypatch.setattr(trial, "ROOT", tmp_path / "resumed1")
    monkeypatch.setattr(trial, "runtime", lambda: SimpleNamespace(prepare=lambda: {"offline_only": True}))
    assert trial.prepare() == {"offline_only": True}
    return SimpleNamespace(root=trial.ROOT, project=tmp_path, x=trial.control.read(trial.ROOT / "INPUT.json"))


def test_scope_claim_is_explicit_one_run_and_directory_change_does_not_renew(prepared, monkeypatch):
    x = prepared.x; scope = trial.control.read(prepared.root / "USER_SCOPE.json")
    assert trial.USER_RESUMPTION in scope["user_statements"]
    assert scope["production_authorized_by"] == "explicit_user_resumption_not_contract"
    assert [scope[k] for k in ["max_new_writer_requests", "max_new_review_requests", "max_new_video_submissions"]] == [1, 1, 1]
    assert scope["resumed_run_revision_index"] == 0 and scope["historical_complete_content_revisions_remaining"] == 0
    assert scope["format_recovery_attempts_remaining"] == 0 and scope["budget_reset"] is False
    assert x["prior_current_content_revision"]["prior_native_status"] == "contract_rejected_unaccepted_counterexample"
    seed = trial.control.read(trial.PARENT / "call_509_continuation_performance.json")
    assert x["prior_current_content_revision"]["complete_prior_native"] == trial.control.strict_json(seed["output"]["payload_json"])
    claim_path = Path(x["content_revision"]["claim_path"])
    claim = trial.control.read(claim_path)
    assert claim["seed_ordinal"] == 509 and claim["user_statement"] == trial.USER_RESUMPTION
    assert claim["old_exhausted_run_retained"] is True and claim["old_budget_reset"] is False
    assert claim["new_contract_sha256"] == trial.control.sha_file(Path(trial.contract.__file__))
    monkeypatch.setattr(trial, "ROOT", prepared.project / "resumed2")
    with pytest.raises(RuntimeError, match="immutable artifact changed"):
        trial.prepare()
    assert len(list((prepared.project / "data/creative_continuation_stages").glob("*/CLAIM.json"))) == 1


def exercise_text(prepared, monkeypatch, *, writer_mode="new", review_status="pass"):
    x = prepared.x; native = new_native(x["full_current_script"]); calls = []
    def review():
        result = {"script_sha256": trial.SOURCE_SHA,
            "checks": [{"check": name, "status": "pass", "source_refs": trial.REFS,
                        "reason": "offline source-bound review"} for name in trial.REVIEW_CHECKS],
            "revision_requirements": [], "review_limitations": ["Video remains subject to human review."]}
        result["checks"][-1]["status"] = review_status
        return result
    class Clients:
        def call(self, role, messages, **kwargs):
            calls.append((role, deepcopy(messages), deepcopy(kwargs["structured_schema"])))
            if role == "writer":
                if writer_mode == "unknown": raise TimeoutError("offline outcome unknown")
                if writer_mode == "old509":
                    text = json.dumps({"payload_json": trial.control.read(trial.PARENT /
                        "call_509_continuation_performance.json")["output"]["payload_json"]}, ensure_ascii=False)
                else:
                    text = trial.transport.encode_envelope(native, trial.contract.continuation_probe_schema(
                        x["full_current_script"], trial.COMPLETED, trial.REFS, x["scene_continuity_context"]))
            else: text = json.dumps(review(), ensure_ascii=False)
            return RoleResult(text=text, metadata={"output_mode": "tool_call", "finish_reason": "tool_calls",
                "total_tokens": 20, "response_id": "offline-v8-" + role, "response_body_complete": True})
    inherited = trial.control.read(prepared.root / "ANCHOR.json")["inherited"]
    runtime = trial.control.ContinuationRuntime(prepared.project, prepared.root,
        [prepared.root / "INPUT.json", prepared.root / "CONTENT_REVISION_BINDING.json"], inherited,
        {"writer": {"model": "MiniMax-M3"}, "director": {"model": "deepseek-flash"}},
        client_factory=Clients, quota_state=None)
    runtime.prepare()
    monkeypatch.setattr(trial, "PROJECT", CODE_PROJECT)
    monkeypatch.setattr(trial, "prepare", lambda: None)
    monkeypatch.setattr(trial, "runtime", lambda: runtime)
    first, second = trial.text(), trial.text()
    assert first["status"] == second["status"]
    assert len(calls) == (2 if writer_mode == "new" else 1)
    ledger = trial.control.read(runtime.ledger)
    assert ledger["starting_spend"] == inherited and inherited["calls_started"] == 509
    assert ledger["automatic_retry"] is False and ledger["old_budget_reset"] is False
    assert [q["ordinal"] for q in ledger["calls"]] == ([510, 511] if writer_mode == "new" else [510])
    request = trial.control.read(prepared.root / ledger["calls"][0]["receipt"])["request"]
    assert request["content_revision_policy"]["resumed_run_revision_index"] == 0
    assert request["content_revision_policy"]["historical_current_segment_content_revision_index"] == 2
    assert request["content_revision_policy"]["format_recovery_attempts_remaining"] == 0
    assert trial.PRODUCTION_RULE in request["messages"][0]["content"]
    return first, native, calls


@pytest.mark.parametrize("mode", ["new", "old509", "unknown"])
def test_new_native_only_and_cached_wire_never_redispatches(prepared, monkeypatch, mode):
    result, native, calls = exercise_text(prepared, monkeypatch, writer_mode=mode)
    if mode != "new":
        assert result["status"] == "current_performance_needs_attention"
        assert not (prepared.root / "VIDEO_TEXT_HANDOFF.json").exists()
        return
    compiled = trial.control.read(prepared.root / "PERFORMANCE_COMPILED.json")
    handoff = trial.control.read(prepared.root / "VIDEO_TEXT_HANDOFF.json")
    inp = json.loads(calls[1][1][1]["content"])
    assert set(native) == {"current_direction", "performance"}
    assert compiled["native"] == native and compiled["creative_fields_rewritten"] is False
    assert compiled["derived_metadata"] == {"script_sha256": trial.SOURCE_SHA,
        "source_refs": trial.REFS, "camera": "retain_approved_frame", "spoken_language": "zh-CN"}
    assert inp["derived_metadata"] == compiled["derived_metadata"]
    assert inp["current_native_direction_and_performance"] == native
    assert inp["actual_video_prompt"] == trial.contract.render_prompt(compiled, prepared.x["full_current_script"], prepared.x["actor_names"])
    assert handoff["derived_metadata_sha256"] == compiled["derived_metadata_sha256"]
    assert handoff["legacy_failed_response_adopted"] is False
    plan = trial.make_plan(); trial.validate_plan(plan)
    assert plan["prompt"] == inp["actual_video_prompt"] and plan["source_run"] is None
    assert plan["logical_task_id"] == trial.LOGICAL and plan["new_submissions"] == 1
    assert plan["first_frame"] == trial.approved_frame()
    assert plan["first_frame"]["path"] != trial.control.read(trial.rejected_segment.OUT / "receipt.json")["last_frame"]
    changed = deepcopy(plan); changed["first_frame"]["sha256"] = "0" * 64
    with pytest.raises(ValueError): trial.validate_plan(changed)
    changed = deepcopy(plan); changed["script_content_sha256"] = "0" * 64
    with pytest.raises(ValueError): trial.validate_plan(changed)


@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_review_failure_or_unknown_blocks_media(prepared, monkeypatch, status):
    result, _, _ = exercise_text(prepared, monkeypatch, review_status=status)
    assert result["status"] == "production_text_needs_attention"
    assert not (prepared.root / "VIDEO_TEXT_HANDOFF.json").exists()
    with pytest.raises((FileNotFoundError, ValueError)): trial.make_plan()


def test_actual_first_frame_bytes_and_unknown_media_submission_are_not_repeated(prepared, monkeypatch):
    exercise_text(prepared, monkeypatch)
    monkeypatch.setattr(trial, "OUT", prepared.project / "media")
    original_client = trial.SeedanceClient
    submitted, reservations = [], []
    class Client:
        def __init__(self, config): self.config = SimpleNamespace(provider="ark_api", model=trial.MODEL)
        def __enter__(self): return self
        def __exit__(self, *args): pass
        build_task_payload = original_client.build_task_payload
        def create_task(self, request):
            submitted.append(deepcopy(request)); raise TimeoutError("offline original result unknown")
    monkeypatch.setattr(trial, "SeedanceClient", Client)
    monkeypatch.setattr(trial.SeedanceConfig, "from_env", lambda *args, **kwargs: None)
    monkeypatch.setattr(trial, "reserve_media_attempt", lambda *args: reservations.append(args))
    assert trial.media("media_prepare")["new_paid_calls"] == 0
    with pytest.raises(TimeoutError): trial.media("media_submit")
    with pytest.raises(ValueError, match="never resubmit"): trial.media("media_submit")
    with pytest.raises(ValueError, match="missing original ID"): trial.media("media_query")
    assert len(submitted) == len(reservations) == 1
    request = submitted[0]; refs = [q for q in request["content"] if q["type"] != "text"]
    assert len(refs) == 1 and refs[0]["role"] == "first_frame"
    image_bytes = base64.b64decode(refs[0]["image_url"]["url"].split(",", 1)[1], validate=True)
    frame = trial.approved_frame()
    assert image_bytes == Path(frame["path"]).read_bytes()
    assert hashlib.sha256(image_bytes).hexdigest() == frame["sha256"]
    plan = reservations[0][1]
    assert plan["source_run"] is None and plan["logical_task_id"] == trial.LOGICAL
    assert plan["budget_reset"] is False and plan["automatic_retry"] is False
    receipt = trial.control.read(trial.OUT / "receipt.json")
    assert receipt["technical_status"] == "unknown" and not receipt.get("task_id")
