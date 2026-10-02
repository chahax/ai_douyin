"""Independent offline regression for the B+D runner; no provider traffic."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_modular_bd_probe as runner
from src.content_factory.creative_full_script_revision import accept_full_script
from src.content_factory.creative_workflow_roles import RoleConfig, RoleResult, RoleResponseError


PROJECT = Path(__file__).resolve().parents[1]
REAL_CONTEXT = PROJECT / "data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/CONTEXT.json"


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    diagnostic = tmp_path / "shared"
    diagnostic.mkdir()
    prior = diagnostic / "matrix_v3"
    prior.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    source = project / "fixture_source.py"
    source.write_text("fixture_source = 1\n", encoding="utf-8")
    root = diagnostic / "modular"
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "LEDGER", root / "CALL_LEDGER.json")
    monkeypatch.setattr(runner, "PROJECT", project)
    monkeypatch.setattr(runner.previous, "ROOT", prior)
    monkeypatch.setattr(runner.previous, "LEDGER", prior / "CALL_LEDGER.json")
    monkeypatch.setattr(runner.previous.definition, "DIAGNOSTIC", diagnostic)
    monkeypatch.setattr(runner.previous, "check", lambda ledger: None)
    monkeypatch.setattr(runner, "source_manifest", lambda: {
        "fixture_source.py": runner.file_hash(source)})
    def config(role):
        return RoleConfig("minimax" if role == "writer" else "deepseek",
            "MiniMax-M3" if role == "writer" else "deepseek-flash",
            "https://fixture.invalid/v1", "offline-placeholder")
    monkeypatch.setattr(runner, "role_config", config)
    context = json.loads(REAL_CONTEXT.read_text(encoding="utf-8"))
    runner.write(diagnostic / "CONTEXT.json", context, True)
    runner.write(prior / "CALL_LEDGER.json",
        {"parent_run": str(tmp_path / "frozen_parent"), "calls": []}, True)
    runner.write(prior / "RESULT.json", {"effective_calls_started": 42,
        "effective_reported_tokens": 398343, "unknown_token_reservations": 0,
        "max_total_tokens": 500000}, True)
    runner.write(prior / "AUTHORIZATION.json", {"fixture": True}, True)
    provider = SimpleNamespace(calls=[], handler=None)
    def call(*args, **kwargs):
        provider.calls.append((args, kwargs))
        if provider.handler is None:
            raise AssertionError("offline provider handler was not configured")
        return provider.handler(*args, **kwargs)
    monkeypatch.setattr(runner, "CreativeRoleClients",
        lambda: SimpleNamespace(call=call))
    runner.prepare()
    return SimpleNamespace(root=root, diagnostic=diagnostic, prior=prior,
        source=source, context=context, provider=provider)


def result(value, *, tokens=100, response_id="fixture-response"):
    metadata = {"finish_reason": "tool_calls", "output_mode": "tool_call",
                "response_id": response_id}
    if tokens is not None:
        metadata["total_tokens"] = tokens
    return RoleResult(json.dumps(value, ensure_ascii=False), metadata,
        {"id": response_id, "choices": [], "usage": metadata})


def wire(max_tokens=32, schema=None, text="offline request"):
    return runner.request("writer", [{"role": "user", "content": text}],
        schema, max_tokens)


def valid_complete_script(context):
    old = context["script"]
    value = {k: deepcopy(old[k]) for k in
        ("title", "premise", "selected_candidate_id", "duration_seconds", "beats")}
    value["title"] = "完整新稿离线测试"
    value["premise"] = "用独立的新起点与新结尾替换完整旧稿，内容质量不在此测试判定。"
    value["beats"] = [deepcopy(old["beats"][0]), deepcopy(old["beats"][-1])]
    value["beats"][0]["id"] = "NEW_START"
    value["beats"][1]["id"] = "NEW_END"
    value["beats"][0]["before"] = "方澄将杯子从桌沿拿起，平稳放回桌面中央。"
    value["beats"][1]["after"] = "林屿将结算单从文件叠中取出，开始自己核对。"
    value["duration_seconds"] = sum(beat["duration_seconds"] for beat in value["beats"])
    return value


def create_draft(runtime):
    value = valid_complete_script(runtime.context)
    runtime.provider.handler = lambda *args, **kwargs: result(value)
    record = runner.draft(1)
    assert record["status"] == "contract_valid"
    return value, record


def record_review(runtime, value):
    runtime.provider.handler = lambda *args, **kwargs: result(value,
        response_id="fixture-review")
    return runner.dispatch("script_review_v1", wire(),
        lambda output: {"evidence_valid": True})


def test_prepare_inherits_actual_spend_without_reset(runtime):
    ledger = runner.read(runner.LEDGER)
    assert ledger["starting_spend"] == {
        "calls_started": 42, "reported_tokens": 398343, "max_total_tokens": 500000}
    summary = runner.summary()
    assert summary["effective_calls_started"] == 42
    assert summary["effective_reported_tokens"] == 398343
    assert summary["remaining_tokens"] == 101657
    assert summary["new_calls"] == 0
    assert summary["old_budget_reset"] is False
    assert summary["old_governance_migrated"] is False
    assert runtime.provider.calls == []


def test_pending_receipt_and_reservation_saved_before_provider(runtime):
    def inspect(*args, **kwargs):
        ledger = runner.read(runner.LEDGER)
        assert len(ledger["calls"]) == 1
        call = ledger["calls"][0]
        assert call["ordinal"] == 43
        record = runner.read(runtime.root / call["receipt"])
        assert record["status"] == "pending_response"
        assert record["token_reservation"] == call["token_reservation"] > 0
        assert (runtime.diagnostic / "DISPATCH.lock").is_file()
        return result({"accepted": True}, tokens=99)
    runtime.provider.handler = inspect
    record = runner.dispatch("micro", wire(), lambda output: {"valid": True})
    assert record["status"] == "contract_valid"
    summary = runner.summary()
    assert summary["effective_calls_started"] == 43
    assert summary["effective_reported_tokens"] == 398442
    assert summary["unknown_token_reservations"] == 0
    assert not (runtime.diagnostic / "DISPATCH.lock").exists()


def test_unknown_outcome_reserves_budget_and_blocks_next_dispatch(runtime):
    def unknown(*args, **kwargs):
        raise RuntimeError("APIConnectionError; request_id=unknown")
    runtime.provider.handler = unknown
    request = wire()
    first = runner.dispatch("unknown", request, lambda output: None)
    assert first["status"] == "outcome_unknown"
    summary = runner.summary()
    assert summary["new_reported_tokens"] == 0
    assert summary["unknown_token_reservations"] == first["token_reservation"] > 0
    assert summary["effective_calls_started"] == 43
    assert runner.dispatch("unknown", request, lambda output: None) == first
    with pytest.raises(RuntimeError, match="unknown outcome"):
        runner.dispatch("dependent", wire(text="second request"), lambda output: None)
    assert len(runtime.provider.calls) == 1


def test_missing_usage_is_not_assumed_zero_even_after_valid_response(runtime):
    runtime.provider.handler = lambda *args, **kwargs: result({}, tokens=None)
    first = runner.dispatch("missing_usage", wire(), lambda output: {})
    assert first["status"] == "contract_valid"
    assert runner.summary()["unknown_token_reservations"] == first["token_reservation"]
    with pytest.raises(RuntimeError, match="unknown outcome/usage"):
        runner.dispatch("next", wire(), lambda output: {})
    assert len(runtime.provider.calls) == 1


def test_identical_request_key_reuses_known_receipt_without_dispatch(runtime):
    runtime.provider.handler = lambda *args, **kwargs: result({"accepted": True})
    request = wire()
    first = runner.dispatch("same", request, lambda output: {"checked": True})
    original = runner.read(runner.LEDGER)
    second = runner.dispatch("same", deepcopy(request),
        lambda output: pytest.fail("cached receipt must not be revalidated"))
    assert first == second
    assert runner.read(runner.LEDGER) == original
    assert len(runtime.provider.calls) == 1


@pytest.mark.parametrize("response_id,expected", [("same-id", 100), ("", 200)])
def test_usage_deduplicates_response_identity_or_uses_each_ordinal(runtime, response_id, expected):
    runtime.provider.handler = lambda *args, **kwargs: result({}, response_id=response_id)
    runner.dispatch("first", wire(), lambda output: {})
    runner.dispatch("second", wire(text="different"), lambda output: {})
    assert len(runtime.provider.calls) == 2
    assert runner.summary()["new_reported_tokens"] == expected


@pytest.mark.parametrize("maximum,retained", [(102000, 0), (90000, 14000)])
def test_insufficient_total_budget_has_no_receipt_or_provider_dispatch(runtime, maximum, retained):
    before = runner.read(runner.LEDGER)
    with pytest.raises(RuntimeError, match="500000 token budget insufficient"):
        runner.dispatch("too_large", wire(max_tokens=maximum),
            lambda output: {}, retain_review_tokens=retained)
    assert runner.read(runner.LEDGER) == before
    assert list(runtime.root.glob("call_[0-9][0-9][0-9]_*.json")) == []
    assert runtime.provider.calls == []


def test_batch_call_guard_stops_without_provider_dispatch(runtime):
    ledger = runner.read(runner.LEDGER)
    ledger["assistant_batch_call_ceiling"] = 0
    runner.write(runner.LEDGER, ledger)
    with pytest.raises(RuntimeError, match="local batch call ceiling"):
        runner.dispatch("blocked", wire(), lambda output: {})
    assert runtime.provider.calls == []


@pytest.mark.parametrize("change", ["source", "prior_evidence", "context"])
def test_binding_changes_block_before_dispatch(runtime, change):
    if change == "source":
        runtime.source.write_text("fixture_source = 2\n", encoding="utf-8")
    elif change == "prior_evidence":
        runner.write(runtime.prior / "AUTHORIZATION.json", {"fixture": False})
    else:
        context = runner.read(runtime.root / "ORIGINAL_CONTEXT.json")
        context["script"]["title"] += " altered"
        runner.write(runtime.root / "ORIGINAL_CONTEXT.json", context)
    with pytest.raises(RuntimeError, match="changed"):
        runner.dispatch("blocked", wire(), lambda output: {})
    assert runtime.provider.calls == []
    assert runner.read(runner.LEDGER)["calls"] == []


def test_orphan_receipt_blocks_before_dispatch(runtime):
    runner.write(runtime.root / "call_043_orphan.json", {"status": "pending_response"})
    with pytest.raises(RuntimeError, match="orphan/missing"):
        runner.dispatch("blocked", wire(), lambda output: {})
    assert runtime.provider.calls == []


def test_held_parent_lock_blocks_before_provider_dispatch(runtime):
    path = runtime.diagnostic / "DISPATCH.lock"
    path.write_text("another offline dispatch", encoding="utf-8")
    with pytest.raises(FileExistsError):
        runner.dispatch("blocked", wire(), lambda output: {})
    assert runtime.provider.calls == []
    assert path.read_text(encoding="utf-8") == "another offline dispatch"


def test_interface_rejection_preserves_usage_and_never_blindly_retries(runtime):
    def rejected(*args, **kwargs):
        raise RoleResponseError("required tool missing", {
            "response_id": "rejected-id", "finish_reason": "stop",
            "response_fault_code": "REQUIRED_TOOL_MISSING", "total_tokens": 73},
            response_text="body prose", response_payload={"content": "body prose"})
    runtime.provider.handler = rejected
    request = wire()
    first = runner.dispatch("interface_failure", request, lambda output: {})
    assert first["status"] == "interface_rejected"
    assert first["failure"]["automatic_retry"] is False
    assert first["response_text"] == "body prose"
    assert runner.summary()["new_reported_tokens"] == 73
    assert runner.summary()["unknown_token_reservations"] == 0
    assert runner.dispatch("interface_failure", request, lambda output: {}) == first
    assert len(runtime.provider.calls) == 1


def test_complete_new_draft_is_adopted_whole_without_old_beat_projection(runtime):
    original_bytes = (runtime.root / "ORIGINAL_CONTEXT.json").read_bytes()
    generated, record = create_draft(runtime)
    context = runner.revised_context(1)
    assert context["script"] == accept_full_script(runtime.context["script"], generated)
    assert [beat["id"] for beat in context["script"]["beats"]] == ["NEW_START", "NEW_END"]
    assert not {beat["id"] for beat in runtime.context["script"]["beats"]}.intersection(
        beat["id"] for beat in context["script"]["beats"])
    assert record["output"] == generated
    assert context["script_revision_source"]["complete_model_authored"] is True
    assert (runtime.root / "ORIGINAL_CONTEXT.json").read_bytes() == original_bytes


def test_partial_replacement_is_rejected_without_splicing_old_draft(runtime):
    original_bytes = (runtime.root / "ORIGINAL_CONTEXT.json").read_bytes()
    runtime.provider.handler = lambda *args, **kwargs: result({"replace_beats": []})
    record = runner.draft(1)
    assert record["status"] == "contract_rejected"
    with pytest.raises(RuntimeError, match="upstream not validated"):
        runner.revised_context(1)
    assert (runtime.root / "ORIGINAL_CONTEXT.json").read_bytes() == original_bytes
    assert len(runtime.provider.calls) == 1


def test_no_review_decision_blocks_direction_without_dispatch(runtime):
    create_draft(runtime)
    record_review(runtime, {"issues": [], "story_preserved": True})
    count = len(runtime.provider.calls)
    with pytest.raises(FileNotFoundError):
        runner.direction(1, 1)
    assert len(runtime.provider.calls) == count


def test_unresolved_review_cannot_be_approved_or_advance_to_direction(runtime):
    create_draft(runtime)
    record_review(runtime, {"issues": [{"id": "remaining_content_issue"}],
                            "story_preserved": False})
    count = len(runtime.provider.calls)
    with pytest.raises(RuntimeError, match="cannot approve unresolved"):
        runner.evidence_decision(1, True, [{"source": "offline"}])
    runner.evidence_decision(1, False, [{"source": "offline"}])
    with pytest.raises(RuntimeError, match="full script review not verified"):
        runner.direction(1, 1)
    assert len(runtime.provider.calls) == count

def test_pending_and_terminal_receipts_are_hash_bound(runtime):
    def inspect(*args, **kwargs):
        ledger = runner.read(runner.LEDGER)
        entry = ledger["calls"][0]
        assert runner.file_hash(runtime.root / entry["receipt"]) == entry["receipt_sha256"]
        return result({})
    runtime.provider.handler = inspect
    runner.dispatch("sha", wire(), lambda output: {})
    ledger = runner.read(runner.LEDGER)
    entry = ledger["calls"][0]
    assert runner.file_hash(runtime.root / entry["receipt"]) == entry["receipt_sha256"]


def test_changed_new_receipt_blocks_next_dispatch(runtime):
    runtime.provider.handler = lambda *args, **kwargs: result({})
    runner.dispatch("first", wire(), lambda output: {})
    ledger = runner.read(runner.LEDGER)
    path = runtime.root / ledger["calls"][0]["receipt"]
    receipt = runner.read(path)
    receipt["response_metadata"]["total_tokens"] = 0
    runner.write(path, receipt)
    with pytest.raises(RuntimeError, match="receipt changed"):
        runner.dispatch("next", wire(text="new"), lambda output: {})
    assert len(runtime.provider.calls) == 1


def test_known_interface_rejection_blocks_other_requests(runtime):
    def rejected(*args, **kwargs):
        raise RoleResponseError("tool missing", {
            "response_id": "known-failure", "total_tokens": 30,
            "response_fault_code": "REQUIRED_TOOL_MISSING"})
    runtime.provider.handler = rejected
    runner.dispatch("rejected", wire(), lambda output: {})
    with pytest.raises(RuntimeError, match="unknown outcome/usage"):
        runner.dispatch("different", wire(text="different"), lambda output: {})
    assert len(runtime.provider.calls) == 1


def test_altered_complete_compilation_cannot_enter_final_review(runtime, monkeypatch):
    from tests.test_creative_modular_contract import fixture
    context, direction, locals_ = fixture()
    complete = runner.compile_complete(context, direction, locals_)
    forged = deepcopy(complete)
    forged["derived_timing_script"]["beats"][0]["before"] = "unbound derived action"
    runner.write(runtime.root / f"COMPLETE_s1_d1_{runner.digest(complete)[:12]}.json", forged, True)
    monkeypatch.setattr(runner, "revised_context", lambda index: deepcopy(context))
    def upstream(label):
        if label == "direction_s1_v1":
            return {"output": deepcopy(direction)}
        for index, local in enumerate(locals_, 1):
            if label == f"local_s1_d1_b{index}":
                return {"output": deepcopy(local)}
        raise RuntimeError("unexpected fixture upstream " + label)
    monkeypatch.setattr(runner, "get_call", upstream)
    monkeypatch.setattr(runner, "get_local", lambda index, version, beat_number: {"output": deepcopy(locals_[beat_number - 1])})
    monkeypatch.setattr(runner, "build_review_prompt", lambda context: "offline review")
    monkeypatch.setattr(runner, "validate_review_v6", lambda value, context: None)
    runtime.provider.handler = lambda *args, **kwargs: result({
        "issues": [], "story_preserved": True})
    with pytest.raises(RuntimeError, match="complete|compilation|derived"):
        runner.final_review(1, 1)
    assert runtime.provider.calls == []

def test_schema_type_failure_is_state_contract_and_does_not_patch(runtime):
    runtime.provider.handler = lambda *args, **kwargs: result({"rows": {"item": []}})
    request = wire(schema={"type": "object", "required": ["rows"],
        "properties": {"rows": {"type": "array"}}})
    record = runner.dispatch("boxed_array", request, lambda output: {})
    assert record["status"] == "contract_rejected"
    assert record["failure"]["code"] == "MODULE_SCHEMA_INVALID"
    assert record["failure"]["category"] == "state_contract"
    assert record["failure"]["next_action"] == "complete_new_draft_then_full_review"
    assert record["failure"]["automatic_retry"] is False
    assert record["output"] == {"rows": {"item": []}}
    assert len(runtime.provider.calls) == 1


def test_newest_rejected_local_cannot_fall_back_to_prior_valid_attempt(runtime):
    runtime.provider.handler = lambda *args, **kwargs: result({"attempt": 1})
    runner.dispatch("local_s1_d1_b1", wire(text="first"), lambda output: {})
    runtime.provider.handler = lambda *args, **kwargs: result({"attempt": 2},
        response_id="revision-failed")
    def reject(output):
        raise RuntimeError("fixture invalid latest local")
    runner.dispatch("local_s1_d1_b1_v2", wire(text="second"), reject)
    with pytest.raises(RuntimeError, match="upstream not validated"):
        runner.get_local(1, 1, 1)
    assert len(runtime.provider.calls) == 2


def test_local_revision_submits_a_complete_replacement_and_preserves_rejected_receipt(runtime, monkeypatch):
    from tests.test_creative_modular_contract import fixture
    context, direction, locals_ = fixture()
    original_get_call = runner.get_call
    monkeypatch.setattr(runner, "revised_context", lambda index: deepcopy(context))
    monkeypatch.setattr(runner, "get_call", lambda label:
        {"output": deepcopy(direction)} if label == "direction_s1_v1" else original_get_call(label))
    bad = deepcopy(locals_[0])
    bad["groups"] = {"item": bad["groups"]}
    runtime.provider.handler = lambda *args, **kwargs: result(bad, response_id="local-bad")
    rejected = runner.local(1, 1, 1)
    assert rejected["status"] == "contract_rejected"
    ledger = runner.read(runner.LEDGER)
    old_path = runtime.root / ledger["calls"][0]["receipt"]
    old_bytes = old_path.read_bytes()
    replacement = deepcopy(locals_[0])
    replacement["groups"][0]["performance"] = "完整新稿中的新表演描述"
    runtime.provider.handler = lambda *args, **kwargs: result(replacement, response_id="local-new")
    revised = runner.local(1, 1, 1, revision=2)
    assert revised["status"] == "contract_valid"
    assert revised["output"] == replacement
    assert runner.get_local(1, 1, 1)["output"] == replacement
    assert old_path.read_bytes() == old_bytes
    assert len(runtime.provider.calls) == 2
    arguments, keywords = runtime.provider.calls[-1]
    revision_messages = arguments[1]
    feedback = json.loads(revision_messages[-1]["content"])["revision_feedback"]
    assert bad == feedback["previous_complete_local"]
    assert "补丁" in feedback["instruction"]


def test_valid_complete_artifact_reaches_final_review_with_verified_sources(runtime, monkeypatch):
    from tests.test_creative_modular_contract import fixture
    context, direction, locals_ = fixture()
    complete = runner.compile_complete(context, direction, locals_)
    runner.write(runtime.root / f"COMPLETE_s1_d1_{runner.digest(complete)[:12]}.json", complete, True)
    monkeypatch.setattr(runner, "revised_context", lambda index: deepcopy(context))
    monkeypatch.setattr(runner, "get_call", lambda label: {"output": deepcopy(direction)})
    monkeypatch.setattr(runner, "get_local", lambda index, version, beat_number:
        {"output": deepcopy(locals_[beat_number - 1])})
    monkeypatch.setattr(runner, "build_review_prompt", lambda context: "offline review")
    monkeypatch.setattr(runner, "validate_review_v6", lambda value, context: None)
    runtime.provider.handler = lambda *args, **kwargs: result({
        "issues": [], "story_preserved": True})
    record = runner.final_review(1, 1)
    assert record["status"] == "contract_valid"
    assert len(runtime.provider.calls) == 1
    arguments, keywords = runtime.provider.calls[0]
    submitted = json.loads(arguments[1][1]["content"])
    assert submitted["script"] == complete["derived_timing_script"]
    assert submitted["state_plan"] == complete["derived_action_plan"]