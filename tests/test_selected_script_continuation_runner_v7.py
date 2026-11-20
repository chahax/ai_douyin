"""Second bounded content revision and review semantics; no API or media inspection."""
from copy import deepcopy
import json
from pathlib import Path
import socket
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from scripts import run_selected_script_continuation_v7 as trial
from src.content_factory.creative_workflow_roles import RoleResult
from tests.test_creative_continuation_probe_contract_v5 import wire as valid_native


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("bounded continuation tests must remain offline")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def current_input():
    x = deepcopy(trial.control.read(trial.PARENT / "INPUT.json"))
    x["scene_continuity_context"] = trial.contract.build_scene_continuity_context(
        x["full_current_script"], x["scene_and_character_context"], x["approved_first_frame"])
    prior = trial.control.read(trial.PARENT / "call_507_continuation_performance.json")
    x["prior_current_content_revision"] = {
        "ordinal": 507, "complete_prior_native": trial.previous.received_document(prior),
        "complete_prior_review": trial.control.read(trial.PARENT / "call_508_production_text_review.json")["output"],
        "required_repairs": ["Remove unsupported screen layout from the complete new native document."],
        "current_segment_new_scope": False}
    x["content_revision"].update(current_segment_content_revision_index=2,
        max_current_segment_complete_content_revisions=2, max_new_writer_requests=1,
        format_recovery_attempts_remaining=0, budget_reset=False)
    return x


def review_document(status="pass", requirements=None):
    result = {"script_sha256": trial.SOURCE_SHA,
        "checks": [{"check": name, "status": "pass", "source_refs": trial.REFS,
                    "reason": "offline source-bound review"} for name in trial.REVIEW_CHECKS],
        "revision_requirements": [] if requirements is None else requirements,
        "review_limitations": ["Actual video quality remains subject to explicit user review."]}
    result["checks"][-1]["status"] = status
    return result


def test_actual508_parent_spend_rejection_and_original_native_are_retained():
    paths = [trial.PARENT / n for n in ["CALL_LEDGER.json", "CONTENT_REVISION_BINDING.json",
        "call_507_continuation_performance.json", "call_508_production_text_review.json"]]
    before = [p.read_bytes() for p in paths]
    inherited, binding, receipt = trial.recovery_parent()
    assert inherited["calls_started"] == 508 and inherited["reported_tokens"] == 7760051
    assert inherited["calls_with_known_usage"] == 506
    assert inherited["unknown_token_reservations"] == 93117 and inherited["pending_ordinals"] == [70, 160]
    assert receipt["ordinal"] == 507 and receipt["status"] == "contract_valid"
    assert binding["current_segment_content_revision_index"] == 2
    assert binding["max_current_segment_complete_content_revisions"] == 2
    assert binding["max_new_writer_requests"] == 1 and binding["format_recovery_attempts_remaining"] == 0
    assert binding["budget_reset"] is False
    assert binding["previous_content_revision_binding_sha256"] == trial.control.sha_file(paths[1])
    assert binding["previous_content_revision_claim_sha256"] == trial.control.sha_file(
        Path(binding["previous_content_revision_claim_path"]))
    old = trial.control.read(paths[-1])
    assert old["validation"]["needs_revision"] is True
    assert all(q["status"] == "pass" for q in old["output"]["checks"])
    assert old["output"]["revision_requirements"]  # Never deleted to force adoption.
    assert before == [p.read_bytes() for p in paths]


@pytest.mark.parametrize("key,value", [
    ("current_segment_content_revision_index", 0),
    ("current_segment_content_revision_index", 2),
    ("max_new_writer_requests", 2),
    ("format_recovery_attempts_remaining", 1)])
def test_parent_lineage_cannot_renew_content_or_format_allowance(monkeypatch, key, value):
    original = trial.control.read
    binding_path = (trial.PARENT / "CONTENT_REVISION_BINDING.json").resolve()
    def read(path):
        result = original(path)
        if Path(path).resolve() == binding_path:
            result = deepcopy(result); result[key] = value
        return result
    monkeypatch.setattr(trial.control, "read", read)
    with pytest.raises(ValueError):
        trial.recovery_parent()


def test_prepare_claim_is_second_revision_only_and_cannot_be_relocated(monkeypatch, tmp_path):
    monkeypatch.setattr(trial, "PROJECT", tmp_path)
    monkeypatch.setattr(trial, "ROOT", tmp_path / "route1")
    monkeypatch.setattr(trial, "runtime", lambda: SimpleNamespace(prepare=lambda: {"offline_only": True}))
    assert trial.prepare() == {"offline_only": True}
    x = trial.control.read(trial.ROOT / "INPUT.json")
    claim_path = Path(x["content_revision"]["claim_path"])
    claim = trial.control.read(claim_path)
    assert claim["content_revision_index"] == 2 and claim["max_current_segment_complete_content_revisions"] == 2
    assert claim["format_recovery_attempts_remaining"] == 0 and claim["old_budget_reset"] is False
    assert claim["previous_content_revision_binding_sha256"] == trial.control.sha_file(
        trial.PARENT / "CONTENT_REVISION_BINDING.json")
    assert x["prior_current_content_revision"]["complete_prior_native"] == trial.previous.received_document(
        trial.control.read(trial.PARENT / "call_507_continuation_performance.json"))
    assert trial.control.read(trial.ROOT / "USER_SCOPE.json")["max_new_video_submissions"] == 1
    monkeypatch.setattr(trial, "ROOT", tmp_path / "route2")
    with pytest.raises(RuntimeError, match="immutable artifact changed"):
        trial.prepare()
    assert len(list((tmp_path / "data/creative_continuation_stages").glob("*/CLAIM.json"))) == 1


def test_review_protocol_publicly_separates_limitations_from_required_revisions():
    schema = trial.review_schema(current_input()["full_current_script"])
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(review_document())
    for status in ["fail", "unknown"]:
        validator.validate(review_document(status, ["A specific current-content change is required."]))
    inconsistent = review_document(requirements=["Artificial all-pass but still mandatory change."])
    assert list(validator.iter_errors(inconsistent))
    missing_limitations = review_document(); del missing_limitations["review_limitations"]
    assert list(validator.iter_errors(missing_limitations))


@pytest.mark.parametrize("status,requirements,ready", [
    ("pass", [], True),
    ("fail", ["The current native contains an unsupported layout."], False),
    ("unknown", [], False),
    ("pass", ["All pass cannot contain a required content change."], False)])
def test_same_wire_is_cached_and_review_failure_or_unknown_blocks_handoff(
        monkeypatch, tmp_path, status, requirements, ready):
    x = current_input(); root = tmp_path / "runtime"
    write(root / "INPUT.json", x)
    write(root / "CONTENT_REVISION_BINDING.json", x["content_revision"])
    native = valid_native(x["full_current_script"])
    old_native = deepcopy(x["prior_current_content_revision"]["complete_prior_native"])
    calls = []
    class Clients:
        def call(self, role, messages, **kwargs):
            calls.append((role, deepcopy(messages), deepcopy(kwargs["structured_schema"])))
            if role == "writer":
                text = trial.transport.encode_envelope(native, trial.contract.continuation_probe_schema(
                    x["full_current_script"], trial.COMPLETED, trial.REFS, x["scene_continuity_context"]))
            else:
                text = json.dumps(review_document(status, requirements), ensure_ascii=False)
            return RoleResult(text=text, metadata={"output_mode": "tool_call", "finish_reason": "tool_calls",
                "total_tokens": 20, "response_id": "offline-v7-" + role, "response_body_complete": True})
    inherited = {"calls_started": 508, "reported_tokens": 7760051, "calls_with_known_usage": 506,
        "unknown_token_reservations": 93117, "pending_ordinals": [70, 160]}
    models = {"writer": {"model": "MiniMax-M3"}, "director": {"model": "deepseek-flash"}}
    runtime = trial.control.ContinuationRuntime(tmp_path, root,
        [root / "INPUT.json", root / "CONTENT_REVISION_BINDING.json"], inherited, models,
        client_factory=Clients, quota_state=None)
    runtime.prepare()
    monkeypatch.setattr(trial, "ROOT", root)
    monkeypatch.setattr(trial, "prepare", lambda: None)
    monkeypatch.setattr(trial, "runtime", lambda: runtime)
    first, second = trial.text(), trial.text()
    assert [q[0] for q in calls] == ["writer", "director"]
    ledger = trial.control.read(runtime.ledger)
    assert [row["ordinal"] for row in ledger["calls"]] == [509, 510]
    assert ledger["starting_spend"] == inherited
    assert ledger["automatic_retry"] is False and ledger["old_budget_reset"] is False
    receipt = trial.control.read(root / ledger["calls"][0]["receipt"])
    assert receipt["request"]["content_revision_policy"]["revision_index"] == 2
    assert receipt["request"]["content_revision_policy"]["max_complete_content_revisions"] == 2
    assert receipt["request"]["content_revision_policy"]["format_recovery_attempts_remaining"] == 0
    inp = json.loads(calls[1][1][1]["content"])
    assert inp["current_native_direction_and_performance"] == native
    assert inp["prior_current_content_revision"]["complete_prior_native"] == old_native
    compiled = trial.control.read(root / "PERFORMANCE_COMPILED.json")
    assert inp["actual_video_prompt"] == trial.contract.render_prompt(compiled, x["full_current_script"], x["actor_names"])
    assert x["prior_current_content_revision"]["complete_prior_native"] == old_native
    assert first["status"] == second["status"]
    if ready:
        handoff = trial.control.read(root / "VIDEO_TEXT_HANDOFF.json")
        assert handoff["review_limitations"] == review_document()["review_limitations"]
        assert handoff["production_text_ready_for_single_trial"] is True
        assert handoff["actual_video_quality_passed"] is False and handoff["whole_film_direction_accepted"] is False
    else:
        assert first["status"] == "production_text_needs_attention"
        assert not (root / "VIDEO_TEXT_HANDOFF.json").exists()
        with pytest.raises((FileNotFoundError, ValueError)): trial.make_plan()
