"""Concurrency and crash-accounting checks; no remote models are contacted."""
import hashlib
import json
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from types import SimpleNamespace

import pytest

from src.content_factory.corpus_parallel_calls_v2 import ParallelCalls
from src.content_factory.creative_workflow_roles import RoleResponseError


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def freeze(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def result(value=None, *, finish="stop", usage=None):
    usage = usage if usage is not None else {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
    return SimpleNamespace(
        text=json.dumps(value if value is not None else {"accepted": True}),
        metadata={**usage, "finish_reason": finish, "response_id": "native-1"},
        response_payload={"id": "native-1", "usage": dict(usage), "choices": [{"finish_reason": finish}]},
    )


def ledger(tmp_path, client, *, calls=20, tokens=1000000):
    run = tmp_path / "run"
    run.mkdir()
    plan = {"source_sha256": "frozen-source", "new_call_limit": calls, "new_token_limit": tokens,
            "analysis_route": {"max_tokens": 64}}
    state = {"calls_started": 0, "reported_tokens": 0, "status": "prepared", "pending": None,
             "pending_calls": {}}
    return ParallelCalls(run, plan, state, client, read, freeze, digest)


def invoke(calls, name, context=None):
    return calls(name, "director", "Return JSON", context or {"name": name})


class Success:
    def __init__(self):
        self.calls = 0

    def call(self, *args, **kwargs):
        self.calls += 1
        return result()


def test_claim_and_reservation_exist_before_provider_dispatch(tmp_path):
    class Inspect:
        def call(self, *args, **kwargs):
            state = read(calls.run / "STATE.json")
            assert state["calls_started"] == 1
            assert len(state["pending_calls"]) == 1
            path = next(iter(state["pending_calls"]))
            assert read(calls.run / "CALL_001.json")["reserved_tokens"] > kwargs["max_tokens"]
            assert state["pending"] == [path]
            return result()

    calls = ledger(tmp_path, Inspect())
    invoke(calls, "GROUP_1")
    assert read(calls.run / "STATE.json")["pending"] is None


def test_unknown_then_other_success_keeps_unknown_claim(tmp_path):
    barrier, release = threading.Barrier(2), threading.Event()

    class Controlled:
        def call(self, role, messages, **kwargs):
            name = json.loads(messages[-1]["content"])["name"]
            barrier.wait(timeout=5)
            if name == "UNKNOWN":
                raise TimeoutError("native outcome missing")
            assert release.wait(timeout=5)
            return result()

    calls = ledger(tmp_path, Controlled())
    with ThreadPoolExecutor(max_workers=2) as pool:
        unknown = pool.submit(invoke, calls, "UNKNOWN")
        success = pool.submit(invoke, calls, "SUCCESS")
        try:
            with pytest.raises(TimeoutError):
                unknown.result(timeout=5)
            assert calls.state["status"] == "outcome_unknown"
        finally:
            release.set()
        assert success.result(timeout=5) == {"accepted": True}
    saved = read(calls.run / "STATE.json")
    assert saved["status"] == "outcome_unknown" and saved["reported_tokens"] == 10
    assert [item["name"] for item in saved["pending_calls"].values()] == ["UNKNOWN"]
    assert (calls.run / "SUCCESS.json").exists()
    with pytest.raises(RuntimeError, match="stopped"):
        invoke(calls, "NEW")
    assert saved["calls_started"] == calls.state["calls_started"] == 2


@pytest.mark.parametrize("limit_kind", ["tokens", "calls"])
def test_concurrent_admission_reserves_budget_before_either_completes(tmp_path, limit_kind):
    start, release = threading.Barrier(3), threading.Event()
    entered = []

    class Blocked:
        def call(self, *args, **kwargs):
            entered.append(True)
            assert release.wait(timeout=5)
            return result()

    calls = ledger(tmp_path, Blocked(), calls=1 if limit_kind == "calls" else 20,
                   tokens=2000 if limit_kind == "tokens" else 1000000)

    def worker(name):
        start.wait(timeout=5)
        return invoke(calls, name)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, name) for name in ("ONE", "TWO")]
        start.wait(timeout=5)
        try:
            done, pending = wait(futures, timeout=5, return_when=FIRST_COMPLETED)
            assert len(done) == 1 and len(pending) == 1
            with pytest.raises(ValueError, match="budget_exhausted"):
                next(iter(done)).result()
            assert calls.state["calls_started"] == 1
        finally:
            release.set()
        assert next(iter(pending)).result(timeout=5) == {"accepted": True}
    assert len(entered) == 1 and calls.state["reported_tokens"] == 10


def test_parallel_claim_ordinals_are_unique_and_all_settle(tmp_path):
    count = 6
    barrier = threading.Barrier(count)

    class Together:
        def call(self, *args, **kwargs):
            barrier.wait(timeout=5)
            return result()

    calls = ledger(tmp_path, Together())
    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [pool.submit(invoke, calls, f"GROUP_{n}") for n in range(count)]
        assert all(future.result(timeout=5) == {"accepted": True} for future in futures)
    assert sorted(path.name for path in calls.run.glob("CALL_*.json")) == [f"CALL_{i:03d}.json" for i in range(1, count + 1)]
    assert len({read(path)["name"] for path in calls.run.glob("CALL_*.json")}) == count
    state = read(calls.run / "STATE.json")
    assert state["calls_started"] == count and state["reported_tokens"] == count * 10
    assert state["pending"] is None and state["pending_calls"] == {}


def test_same_name_cannot_be_dispatched_again_while_pending(tmp_path):
    entered, release = threading.Event(), threading.Event()

    class Blocked:
        def call(self, *args, **kwargs):
            entered.set()
            assert release.wait(timeout=5)
            return result()

    calls = ledger(tmp_path, Blocked())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(invoke, calls, "SAME")
        try:
            assert entered.wait(timeout=5)
            with pytest.raises(RuntimeError, match="already_pending"):
                invoke(calls, "SAME")
        finally:
            release.set()
        assert future.result(timeout=5) == {"accepted": True}
    assert calls.state["calls_started"] == 1


@pytest.mark.parametrize("usage", [
    {"total_tokens": 10},
    {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 11},
    {"prompt_tokens": 7, "completion_tokens": True, "total_tokens": 8},
])
def test_unknown_native_usage_preserves_pending_and_native_response(tmp_path, usage):
    class BadUsage:
        def call(self, *args, **kwargs):
            return result(usage=usage)

    calls = ledger(tmp_path, BadUsage())
    with pytest.raises(ValueError, match="native_usage_unknown"):
        invoke(calls, "BROKEN")
    assert calls.state["status"] == "outcome_unknown"
    assert len(calls.state["pending_calls"]) == 1 and calls.state["reported_tokens"] == 0
    assert (calls.run / "RESPONSE_001.json").exists()
    assert not (calls.run / "BROKEN.json").exists()


@pytest.mark.parametrize("finish", [None, "", "unknown"])
def test_unknown_native_finish_preserves_pending(tmp_path, finish):
    class BadFinish:
        def call(self, *args, **kwargs):
            return result(finish=finish)

    calls = ledger(tmp_path, BadFinish())
    with pytest.raises((ValueError, RuntimeError)):
        invoke(calls, "BROKEN")
    assert calls.state["status"] == "outcome_unknown"
    assert len(calls.state["pending_calls"]) == 1
    assert (calls.run / "RESPONSE_001.json").exists()
    assert not (calls.run / "BROKEN.json").exists()


@pytest.mark.parametrize("known", [True, False])
def test_received_exception_only_settles_verified_native_envelope(tmp_path, known):
    native = result(finish="length")
    if not known:
        native.response_payload["usage"]["total_tokens"] = 99

    class Rejected:
        def call(self, *args, **kwargs):
            raise RoleResponseError("received incomplete output", native.metadata,
                                    response_text=native.text, response_payload=native.response_payload)

    calls = ledger(tmp_path, Rejected())
    with pytest.raises(RoleResponseError):
        invoke(calls, "TRUNCATED")
    assert (calls.run / "ERROR_001.json").exists()
    assert calls.state["status"] == ("needs_attention" if known else "outcome_unknown")
    assert calls.state["reported_tokens"] == (10 if known else 0)
    assert bool(calls.state["pending_calls"]) is (not known)


def test_completed_call_reused_without_provider_replay(tmp_path):
    client = Success()
    calls = ledger(tmp_path, client)
    first = invoke(calls, "GOOD")
    second = invoke(calls, "GOOD")
    assert first == second and client.calls == 1
    assert calls.state["calls_started"] == 1


def test_reconstructed_ledger_reuses_complete_bound_artifact(tmp_path):
    client = Success()
    calls = ledger(tmp_path, client)
    expected = invoke(calls, "GOOD")
    restored = ParallelCalls(calls.run, calls.plan, read(calls.run / "STATE.json"), client,
                             read, freeze, digest)
    assert invoke(restored, "GOOD") == expected
    assert client.calls == 1 and restored.state["calls_started"] == 1


def test_received_length_result_settles_usage_but_never_accepts_artifact(tmp_path):
    class Truncated:
        def call(self, *args, **kwargs):
            return result(finish="length")

    calls = ledger(tmp_path, Truncated())
    with pytest.raises(RuntimeError, match="not_completed"):
        invoke(calls, "TRUNCATED")
    assert calls.state["status"] == "needs_attention"
    assert calls.state["reported_tokens"] == 10 and calls.state["pending"] is None
    assert (calls.run / "RESPONSE_001.json").exists()
    assert not (calls.run / "TRUNCATED.json").exists()


@pytest.mark.parametrize("mutate", ["context", "artifact", "route"])
def test_cached_call_rejects_input_or_artifact_tampering(tmp_path, mutate):
    client = Success()
    calls = ledger(tmp_path, client)
    invoke(calls, "GOOD")
    context = {"name": "GOOD"}
    if mutate == "context":
        context["new_instruction"] = "changed"
    elif mutate == "artifact":
        (calls.run / "GOOD.json").write_text('{"accepted": false}', encoding="utf-8")
    else:
        calls.plan["analysis_route"]["max_tokens"] = 128
    with pytest.raises(ValueError, match="cached_call_binding_changed"):
        invoke(calls, "GOOD", context)
    assert client.calls == 1 and calls.state["calls_started"] == 1


def test_group_failure_waits_for_inflight_receipt_and_never_starts_next_group(tmp_path, monkeypatch):
    from src.content_factory import corpus_analysis_parallel_v2 as driver

    barrier, release, unknown_done = threading.Barrier(2), threading.Event(), threading.Event()

    class Controlled:
        def call(self, role, messages, **kwargs):
            name = json.loads(messages[-1]["content"])["name"]
            barrier.wait(timeout=5)
            if name == "G1":
                raise TimeoutError("unknown")
            assert release.wait(timeout=5)
            return result()

    calls = ledger(tmp_path, Controlled())
    root = calls.run / "parallel_analysis"
    root.mkdir()
    groups = [{"id": "G1"}, {"id": "G2"}, {"id": "G3"}]
    monkeypatch.setattr(driver, "_setup", lambda *args: (calls.run, root, groups, 2, {}))
    monkeypatch.setattr(driver, "_validate_cached", lambda *args: {})

    def one_group(run, root, source, group, call, stopped):
        try:
            return invoke(call, group["id"])
        except TimeoutError:
            unknown_done.set()
            raise

    monkeypatch.setattr(driver, "_one_group", one_group)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(driver.run_analysis, calls.run, {}, {}, calls)
        try:
            assert unknown_done.wait(timeout=5)
            assert not future.done(), "driver must preserve the remaining in-flight receipt"
        finally:
            release.set()
        with pytest.raises(driver.AnalysisStopped, match="groups_incomplete"):
            future.result(timeout=5)
    assert calls.state["calls_started"] == 2
    assert (calls.run / "G2.json").exists() and not (calls.run / "G3.json").exists()
    assert read(root / "STATE.json")["accepted_groups"] == ["G2"]
    assert calls.state["status"] == "outcome_unknown" and len(calls.state["pending_calls"]) == 1
