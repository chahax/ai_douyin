from copy import deepcopy
import json
import threading

import pytest
from jsonschema import Draft202012Validator, ValidationError

from src.content_factory import corpus_analysis_contract_v2 as contract
from src.content_factory import corpus_analysis_parallel_v2 as scheduler


def specimen(count=4, workers=2):
    source = {"book_name": "隔离测试故事", "chapters": [
        {"index": i, "text": f"第{i}章社区服务中心每天九点开门。"} for i in range(1, count + 1)]}
    groups = contract.plan_groups(source["chapters"], max_chars=1, context_chars=4)
    config = {**contract.policy(), "groups": groups, "workers": workers,
              "max_chars": 1, "context_chars": 4}
    return source, config


def response(context):
    if "core_chapters" in context:
        passages = {c["index"]: next(p for p in context["source_passages"]
                                    if p["chapter_index"] == c["index"]
                                    and p["chapter_index"] in context["chapter_indices"])
                    for c in context["core_chapters"]}
        return {"group_id": context["group_id"], "chapter_indices": context["chapter_indices"],
                "claims": [{"id": f"{context['group_id']}-C{c['index']:03d}", "kind": "world",
                            "subject": "社区服务中心", "statement": passages[c["index"]]["text"],
                            "chapter_index": c["index"], "temporal_status": "established",
                            "evidence_ids": [passages[c["index"]]["id"]], "entities": []}
                           for c in context["core_chapters"]], "conflicts": []}
    claims = context["claims"]
    if "summary" in context:
        return {"decision": "pass", "checked_claim_ids": [c["id"] for c in claims], "issues": []}
    return {"world": [{"statement": c["statement"], "claim_ids": [c["id"]]} for c in claims],
            "characters": [], "locations": [], "timeline": [], "conflicts": [],
            "omitted_claims": [], "design_proposals": []}


class FakeCall:
    def __init__(self, hook=None):
        self.names = []
        self.hook = hook
        self.lock = threading.Lock()

    def __call__(self, name, role, prompt, context, json_output=True):
        with self.lock:
            self.names.append(name)
        assert name.startswith("PARALLEL_") and role == "director" and json_output is True
        assert context["output_schema"]["type"] == "object"
        if self.hook:
            result = self.hook(name, context)
            if result is not None:
                return result
        return response(context)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_bounded_parallel_groups_then_single_reviewed_merge(tmp_path):
    source, config = specimen()
    first_two = threading.Barrier(2)
    lock = threading.Lock()
    active = maximum = completed = 0

    def hook(name, context):
        nonlocal active, maximum, completed
        if "core_chapters" not in context:
            assert completed == 4
            return None
        with lock:
            active += 1
            maximum = max(maximum, active)
        if context["group_id"] in {"G001", "G002"}:
            first_two.wait(timeout=5)
        with lock:
            active -= 1
            completed += 1

    client = FakeCall(hook)
    result = scheduler.run_analysis(tmp_path, source, config, client)
    assert maximum == 2
    assert len(result["analyses"]) == 4
    assert result["global_analysis"]["validation"]["downstream_ready"] is True
    assert client.names[-2:] == ["PARALLEL_GLOBAL_MERGE", "PARALLEL_GLOBAL_REVIEW"]
    assert read(tmp_path / scheduler.ROOT / "STATE.json")["status"] == "complete"


def test_accepted_cache_reuses_all_results_without_model_calls(tmp_path):
    source, config = specimen(2)
    first = scheduler.run_analysis(tmp_path, source, config, FakeCall())
    called = FakeCall()
    second = scheduler.run_analysis(tmp_path, source, config, called)
    assert first == second
    assert called.names == []


@pytest.mark.parametrize("change", ["source", "config", "output"])
def test_changed_source_config_or_accepted_output_never_reused(tmp_path, change):
    source, config = specimen(2)
    scheduler.run_analysis(tmp_path, source, config, FakeCall())
    if change == "source":
        source["chapters"][0]["text"] += "正文已变更。"
    elif change == "config":
        config["workers"] = 1
    else:
        path = tmp_path / scheduler.ROOT / "groups/G001/attempt_001/INITIAL.json"
        value = read(path)
        value["claims"][0]["statement"] = "伪造修改"
        path.write_text(json.dumps(value), encoding="utf-8")
    client = FakeCall()
    with pytest.raises(scheduler.AnalysisStopped):
        scheduler.run_analysis(tmp_path, source, config, client)
    assert client.names == []


def test_one_completed_bad_response_can_repair_once(tmp_path):
    source, config = specimen(1, 1)
    client = FakeCall(lambda name, context: {"parse_error": "bad_json"}
                      if name == "PARALLEL_G001_ATTEMPT_001" else None)
    result = scheduler.run_analysis(tmp_path, source, config, client)
    assert result["global_analysis"]["validation"]["downstream_ready"]
    assert client.names[:2] == ["PARALLEL_G001_ATTEMPT_001", "PARALLEL_G001_ATTEMPT_001_REPAIR"]
    folder = tmp_path / scheduler.ROOT / "groups/G001/attempt_001"
    assert (folder / "INITIAL_REJECTED.json").exists()
    assert read(folder / "ACCEPTED.json")["output_file"] == "REPAIR.json"


def test_failure_stops_new_groups_and_waits_for_in_flight_success(tmp_path, monkeypatch):
    source, config = specimen(4, 2)
    started = threading.Barrier(2)
    failed = threading.Event()
    original_record = scheduler._record_group

    def record_after_failure(root, group, value):
        original_record(root, group, value)
        # Release the successful sibling only after the runner has actually
        # observed and persisted the failed validation (not before hook return).
        if group["id"] == "G001" and value["status"] == "protocol_failed":
            failed.set()

    monkeypatch.setattr(scheduler, "_record_group", record_after_failure)

    def hook(name, context):
        if name == "PARALLEL_G001_ATTEMPT_001":
            started.wait(timeout=5)
            return {"parse_error": "bad_json"}
        if name == "PARALLEL_G001_ATTEMPT_001_REPAIR":
            return {"parse_error": "still_bad"}
        if name == "PARALLEL_G002_ATTEMPT_001":
            started.wait(timeout=5)
            assert failed.wait(timeout=5)

    client = FakeCall(hook)
    with pytest.raises(scheduler.AnalysisStopped, match="groups_incomplete"):
        scheduler.run_analysis(tmp_path, source, config, client)
    assert all("G003" not in name and "G004" not in name and "GLOBAL" not in name for name in client.names)
    assert read(tmp_path / scheduler.ROOT / "groups/G002/STATE.json")["status"] == "accepted"


@pytest.mark.parametrize("error", [RuntimeError("unknown"), RuntimeError("length"), ValueError("budget_exhausted")])
def test_call_exceptions_are_never_protocol_retried(tmp_path, error):
    source, config = specimen(1, 1)

    def hook(name, context):
        raise error

    client = FakeCall(hook)
    with pytest.raises(scheduler.AnalysisStopped):
        scheduler.run_analysis(tmp_path, source, config, client)
    assert client.names == ["PARALLEL_G001_ATTEMPT_001"]
    with pytest.raises(scheduler.AnalysisStopped):
        scheduler.prepare_retry(tmp_path, source, config, ["G001"], "明确格式修复")
    again = FakeCall()
    with pytest.raises(scheduler.AnalysisStopped):
        scheduler.run_analysis(tmp_path, source, config, again)
    assert not again.names


def test_explicit_retry_preserves_success_and_failed_attempt_artifacts(tmp_path):
    source, config = specimen(3, 1)
    bad = FakeCall(lambda name, context: {"parse_error": "bad"} if "G002" in name else None)
    with pytest.raises(scheduler.AnalysisStopped):
        scheduler.run_analysis(tmp_path, source, config, bad)
    failed_path = tmp_path / scheduler.ROOT / "groups/G002/attempt_001/INITIAL.json"
    old = failed_path.read_bytes()
    again = FakeCall()
    with pytest.raises(scheduler.AnalysisStopped, match="explicit_retry"):
        scheduler.run_analysis(tmp_path, source, config, again)
    assert not again.names
    record = scheduler.prepare_retry(tmp_path, source, config, ["G002"], "已修复通用提示词协议；原消耗保留")
    assert record[0]["additional_budget"] == 0 and record[0]["attempt"] == 2
    result = scheduler.run_analysis(tmp_path, source, config, again)
    assert result["global_analysis"]["validation"]["downstream_ready"]
    assert not any("G001" in name for name in again.names)
    assert "PARALLEL_G002_ATTEMPT_002" in again.names
    assert failed_path.read_bytes() == old


def test_semantic_rejection_blocks_writer_without_auto_rewrite(tmp_path):
    source, config = specimen(2, 1)

    def hook(name, context):
        if name == "PARALLEL_GLOBAL_REVIEW":
            value = response(context)
            claim = context["claims"][0]
            evidence = next(row for row in context["evidence_catalog"]
                            if row["id"] == claim["evidence_ids"][0])
            passage = next(row for row in context["source_contexts"]
                           if row["id"] == evidence["source_context_id"])
            start = evidence["start_offset"] - passage["start_offset"]
            end = evidence["end_offset"] - passage["start_offset"]
            value.update(decision="revise", issues=[{"claim_ids": [claim["id"]],
                         "reason": "事实概括不充分", "evidence": [
                             {"chapter_index": evidence["chapter_index"], "quote": passage["text"][start:end]}]}])
            return value

    client = FakeCall(hook)
    with pytest.raises(scheduler.AnalysisStopped, match="semantic"):
        scheduler.run_analysis(tmp_path, source, config, client)
    assert len(client.names) == 4
    assert read(tmp_path / scheduler.ROOT / "GLOBAL_REVIEWED.json")["semantic_status"] == "machine_review_revise"
    retry = FakeCall()
    with pytest.raises(scheduler.AnalysisStopped, match="semantic"):
        scheduler.run_analysis(tmp_path, source, config, retry)
    assert not retry.names


def test_unresolved_conflict_blocks_even_passing_independent_review(tmp_path):
    source, config = specimen(2, 1)

    def hook(name, context):
        if name == "PARALLEL_GLOBAL_MERGE":
            value = response(context)
            value["conflicts"] = [{"claim_ids": [row["claim_ids"][0] for row in value["world"]],
                                   "reason": "来源含未解决矛盾"}]
            return value

    with pytest.raises(scheduler.AnalysisStopped, match="conflict"):
        scheduler.run_analysis(tmp_path, source, config, FakeCall(hook))
    assert read(tmp_path / scheduler.ROOT / "GLOBAL_REVIEWED.json")["validation"]["downstream_ready"] is False


def test_only_one_merge_protocol_repair_and_no_review_after_bad_merge(tmp_path):
    source, config = specimen(1, 1)
    client = FakeCall(lambda name, context: {"parse_error": "bad"} if "GLOBAL_MERGE" in name else None)
    with pytest.raises(scheduler.AnalysisStopped, match="protocol_failed"):
        scheduler.run_analysis(tmp_path, source, config, client)
    assert client.names == ["PARALLEL_G001_ATTEMPT_001", "PARALLEL_GLOBAL_MERGE", "PARALLEL_GLOBAL_MERGE_REPAIR"]


@pytest.mark.parametrize("change", ["duplicate", "missing", "unsafe", "workers"])
def test_invalid_group_plan_stops_before_any_call(tmp_path, change):
    source, config = specimen(2)
    if change == "duplicate":
        config["groups"].append(deepcopy(config["groups"][0]))
    elif change == "missing":
        config["groups"].pop()
    elif change == "unsafe":
        config["groups"][0]["id"] = "../G001"
    else:
        config["workers"] = 0
    client = FakeCall()
    with pytest.raises(ValueError):
        scheduler.run_analysis(tmp_path, source, config, client)
    assert not client.names


def test_crash_after_parent_receipt_can_recover_without_new_dispatch(tmp_path):
    source, config = specimen(1, 1)
    client = FakeCall()
    scheduler.run_analysis(tmp_path, source, config, client)
    root = tmp_path / scheduler.ROOT
    folder = root / "groups/G001/attempt_001"
    value = read(folder / "INITIAL.json")
    (tmp_path / "PARALLEL_G001_ATTEMPT_001.json").write_text(json.dumps(value), encoding="utf-8")
    for name in ("ACCEPTED.json", "INITIAL.json"):
        (folder / name).unlink()
    (folder / "STATE.json").write_text(json.dumps({"status": "in_flight", "name": "PARALLEL_G001_ATTEMPT_001"}), encoding="utf-8")
    (root / "groups/G001/STATE.json").write_text(json.dumps({"status": "running", "group_id": "G001", "attempt": 1}), encoding="utf-8")
    cached = []

    def parent_call(name, *args, **kwargs):
        cached.append(name)
        return read(tmp_path / (name + ".json"))

    result = scheduler.run_analysis(tmp_path, source, config, parent_call)
    assert result["global_analysis"]["validation"]["downstream_ready"]
    assert cached == ["PARALLEL_G001_ATTEMPT_001"]


def test_unresolved_in_flight_claim_is_not_replayed(tmp_path):
    source, config = specimen(1, 1)
    scheduler.run_analysis(tmp_path, source, config, FakeCall())
    root = tmp_path / scheduler.ROOT
    folder = root / "groups/G001/attempt_001"
    for name in ("ACCEPTED.json", "INITIAL.json"):
        (folder / name).unlink()
    (folder / "STATE.json").write_text(json.dumps({"status": "in_flight", "name": "PARALLEL_G001_ATTEMPT_001"}), encoding="utf-8")
    (root / "groups/G001/STATE.json").write_text(json.dumps({"status": "running", "group_id": "G001", "attempt": 1}), encoding="utf-8")
    client = FakeCall()
    with pytest.raises(scheduler.AnalysisStopped):
        scheduler.run_analysis(tmp_path, source, config, client)
    assert not client.names


def test_missing_accepted_checkpoint_does_not_re_dispatch(tmp_path):
    source, config = specimen(1, 1)
    scheduler.run_analysis(tmp_path, source, config, FakeCall())
    directory = tmp_path / scheduler.ROOT / "groups/G001/attempt_001"
    (directory / "ACCEPTED.json").unlink()
    (directory / "INITIAL.json").unlink()
    client = FakeCall()
    with pytest.raises(scheduler.AnalysisStopped, match="accepted_checkpoint_missing"):
        scheduler.run_analysis(tmp_path, source, config, client)
    assert not client.names


@pytest.mark.parametrize("old_version", ["corpus_analysis/v2-experimental", "corpus_analysis/v2.1-experimental"])
def test_old_frozen_policy_is_not_silently_upgraded(tmp_path, old_version):
    source, config = specimen(1, 1)
    config["version"] = old_version
    client = FakeCall()
    with pytest.raises(ValueError, match="analysis_policy_version_mismatch"):
        scheduler.run_analysis(tmp_path, source, config, client)
    assert not client.names
    assert not (tmp_path / scheduler.ROOT).exists()


def test_native_passage_ids_preserved_and_accepted_evidence_bound_to_source(tmp_path):
    source, config = specimen(1, 1)
    result = scheduler.run_analysis(tmp_path, source, config, FakeCall())
    folder = tmp_path / scheduler.ROOT / "groups/G001/attempt_001"
    native = read(folder / "INITIAL.json")
    assert "evidence_ids" in native["claims"][0]
    assert "evidence" not in native["claims"][0]
    bound = result["analyses"][0]["claims"][0]
    assert "evidence_ids" not in bound
    assert len(bound["evidence"]) == 1
    evidence = bound["evidence"][0]
    assert evidence["chapter_index"] == 1
    assert evidence["quote"] == source["chapters"][0]["text"]
    assert evidence["start_offset"] == 0
    assert evidence["end_offset"] == len(source["chapters"][0]["text"])
    assert evidence["passage_id"] == native["claims"][0]["evidence_ids"][0]
    accepted = read(folder / "ACCEPTED.json")
    assert accepted["output_sha256"] == contract.digest(native)
    assert accepted["validated_sha256"] == contract.digest(result["analyses"][0])


def test_merge_request_schema_limits_world_references_to_actual_world_claims(tmp_path):
    source, config = specimen(2, 1)
    source["chapters"][1]["text"] = "小周是社区服务中心的值班员。"
    observed = []

    def hook(name, context):
        if name == "PARALLEL_G002_ATTEMPT_001":
            value = response(context)
            value["claims"][0].update(kind="character", subject="小周",
                                      entities=[{"kind": "character", "name": "小周"}])
            return value
        if name == "PARALLEL_GLOBAL_MERGE":
            value = response(context)
            value["world"] = [row for row in value["world"] if row["claim_ids"] == ["G001-C001"]]
            value["characters"] = [{"id": contract.stable_entity_id("character", "小周"),
                                    "name": "小周", "aliases": [], "claim_ids": ["G002-C002"]}]
            validator = Draft202012Validator(context["output_schema"])
            validator.validate(value)
            wrong = deepcopy(value)
            wrong["world"][0]["claim_ids"] = ["G002-C002"]
            with pytest.raises(ValidationError):
                validator.validate(wrong)
            observed.append(context["output_schema"])
            return value

    result = scheduler.run_analysis(tmp_path, source, config, FakeCall(hook))
    assert len(observed) == 1
    assert result["global_analysis"]["validation"]["downstream_ready"]
