"""No network/dispatch: one saved metadata result and authoritative log proof."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.content_factory import creative_collection_cli_result_v1 as reconcile


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("network forbidden"))
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network forbidden"))


@pytest.fixture
def case(tmp_path):
    project = tmp_path / "project"
    root = project / "data/production_trials/fixture/collection_live_01"
    root.mkdir(parents=True)
    workflow = "research:" + "1" * 32
    plan_path = project / "data/production_trials/fixture/LEGAL_CORE_PLAN.json"
    plan = {"schema": "legal_core_topic_plan/v1", "plan_id": "legal-core:fixture",
            "account_uuid": "account:fixture", "account_key": "account01",
            "profile_version": 1, "core_tag": "劳动争议",
            "related_tags": ["劳动仲裁"], "estimated_pages": 6}
    save(plan_path, plan)
    plan_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    claim = {"at_utc": "2026-10-12T13:00:00+00:00", "account_key": "account01",
             "plan_path": str(plan_path), "plan_sha256": plan_sha, "metadata_only": True,
             "no_model_calls": True, "no_media_calls": True, "automatic_retry": False}
    identity = {"healthy": True, "status": "active", "account_key": "account01",
                "profile_version": 1, "expected_public_id": "public-fixture",
                "actual_public_id": "public-fixture", "at_utc": "2026-10-12T13:00:05+00:00"}
    log_path = project / "data/trend_research_runs/research_{}.json".format("1" * 32)
    result = {"workflow_run_id": workflow, "account_uuid": "account:fixture", "account_key": "account01",
              "profile_version": 1, "status": "failed", "started_at": "2026-10-12T13:00:10+00:00",
              "finished_at": "2026-10-12T13:00:20+00:00", "collection_run_id": "",
              **{key: 0 for key in ("collected_observations", "unique_videos", "tag_relations",
                  "tag_traffic_snapshots", "clusters", "briefs", "content_analyses", "opportunities")},
              "stopped_reason": "human_required", "warnings": ["等待安全验证"],
              "stages": [{"stage": "trend_collection", "status": "failed", "message": "human_required"}],
              "log_path": str(log_path.relative_to(project)), "video_records": [],
              "legal_core_plan": {"path": str(plan_path), "file_sha256": plan_sha,
                  "plan_id": plan["plan_id"], "core_tag": plan["core_tag"], "related_tags": plan["related_tags"],
                  "estimated_pages": 6, "metadata_only": True, "script_generation_submitted": False}}
    save(root / "COLLECTION_CLAIM.json", claim)
    save(root / "LIVE_IDENTITY_CHECK.json", identity)
    save(root / "COLLECTION_RESULT.json", {"status": "stopped_exception", "exception_type": "JSONDecodeError"})
    def payload(value):
        save(log_path, value)
        (root / "COLLECTION.stdout.log").write_text(
            "2026-10-12 21:00:21 | INFO | Browser session stopped.\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    payload(result)
    kwargs = {"project_root": project, "collection_root": root,
              "expected_account_key": "account01", "expected_account_uuid": "account:fixture",
              "expected_profile_version": 1, "expected_public_id": "public-fixture",
              "expected_workflow_run_id": workflow, "now": "2026-10-12T13:01:00+00:00",
              "expected_claim_sha256": hashlib.sha256((root / "COLLECTION_CLAIM.json").read_bytes()).hexdigest()}
    return SimpleNamespace(project=project, root=root, plan_path=plan_path, log_path=log_path,
                           claim=claim, identity=identity, result=result, payload=payload, kwargs=kwargs)


def call(case):
    return reconcile.reconcile_collection_cli_result(**case.kwargs)


def test_exact_known_human_required_preserves_every_original_file(case):
    before = {p: p.read_bytes() for p in case.project.rglob("*") if p.is_file()}
    value = call(case)
    assert value["status"] == "human_required" and value["observed_research_status"] == "failed"
    assert value["authoritative_full_result_equal"] is True and value["result"] == case.result
    assert value["original_request_redispatched"] is False and value["new_model_calls"] == 0
    assert value["new_media_calls"] == 0 and value["eligible_for_creative_source"] is False
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert set(before) == {p for p in case.project.rglob("*") if p.is_file()}


def test_known_other_failed_reason_is_failed_and_not_source(case):
    case.result["stopped_reason"] = "platform_known_failure"
    case.payload(case.result)
    assert call(case)["status"] == "failed" and call(case)["eligible_for_creative_source"] is False


@pytest.mark.parametrize("text", ["", '{"half":', '{}\n{}', '[]\n{}', '{"a":1}\nlog\n{}',
    'log {"inline":1}\n{}', 'log [1,2]\n{}', '{}\ntrailing log', '{"x":1,"x":2}', '{"x":NaN}'])
def test_multiple_truncated_unknown_or_ambiguous_stdout_refused(text):
    with pytest.raises(reconcile.CollectionResultReconcileError):
        reconcile.extract_terminal_research_json(text)


@pytest.mark.parametrize("prefix", ["null", "true", "false", "123", "-1.2", '"a JSON string"'])
def test_complete_json_scalar_in_prefix_is_also_multiple_output(prefix):
    with pytest.raises(reconcile.CollectionResultReconcileError, match="MULTIPLE"):
        reconcile.extract_terminal_research_json(prefix + "\n{}")


def test_nested_object_and_array_are_one_terminal_document():
    value = {"nested": [{"a": 1}, {"a": 2}], "object": {"b": 3}}
    text = "plain logger line\n" + json.dumps(value, indent=2) + "\n\n"
    assert reconcile.extract_terminal_research_json(text) == value


@pytest.mark.parametrize("key,value", [("account_uuid", "account:other"), ("account_key", "account02"),
    ("profile_version", 2), ("profile_version", True), ("profile_version", 1.0),
    ("workflow_run_id", "research:" + "2" * 32), ("status", "outcome_unknown"),
    ("status", "completed"), ("stopped_reason", ""), ("unique_videos", True),
    ("unique_videos", "0"), ("unique_videos", -1), ("unique_videos", 1),
    ("started_at", "2026-10-11T13:00:10+00:00"), ("started_at", "2026-10-12T13:00:10"),
    ("finished_at", "2026-10-12T13:00:01+00:00"), ("finished_at", "2026-10-13T13:00:20+00:00"),
    ("log_path", "../outside.json"), ("log_path", "data/trend_research_runs/another.json"),
    ("stages", []), ("video_records", [{}])])
def test_identity_time_result_and_workflow_path_must_match_claim(case, key, value):
    case.result[key] = value
    case.payload(case.result)
    with pytest.raises(reconcile.CollectionResultReconcileError):
        call(case)


@pytest.mark.parametrize("fault", ["authoritative", "cli_only_extra", "log_only_extra", "plan_hash", "plan_fields",
    "plan_identity", "plan_extra", "claim_hash", "identity", "claim_scope", "missing_log", "duplicate_authoritative_key"])
def test_any_extra_difference_or_tampered_evidence_refused(case, fault):
    if fault == "authoritative":
        other = deepcopy(case.result); other["warnings"] = ["different"]
        save(case.log_path, other)
    elif fault == "cli_only_extra":
        (case.root / "COLLECTION.stdout.log").write_text(json.dumps({**case.result, "source_media_acquisition": {}}), encoding="utf-8")
    elif fault == "log_only_extra":
        save(case.log_path, {**case.result, "extra": 1})
    elif fault == "plan_hash":
        case.plan_path.write_text(case.plan_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    elif fault == "plan_fields":
        case.result["legal_core_plan"]["related_tags"] = ["wrong"]; case.payload(case.result)
    elif fault == "plan_identity":
        plan = json.loads(case.plan_path.read_text(encoding="utf-8")); plan["account_uuid"] = "account:other"
        save(case.plan_path, plan)
        digest = hashlib.sha256(case.plan_path.read_bytes()).hexdigest()
        case.claim["plan_sha256"] = digest; save(case.root / "COLLECTION_CLAIM.json", case.claim)
        case.kwargs.pop("expected_claim_sha256")
        case.result["legal_core_plan"]["file_sha256"] = digest; case.payload(case.result)
    elif fault == "plan_extra":
        case.result["legal_core_plan"]["ignored_extra"] = "not ignored"; case.payload(case.result)
    elif fault == "claim_hash":
        save(case.root / "COLLECTION_CLAIM.json", {**case.claim, "changed": True})
    elif fault == "identity":
        save(case.root / "LIVE_IDENTITY_CHECK.json", {**case.identity, "actual_public_id": "other"})
    elif fault == "claim_scope":
        save(case.root / "COLLECTION_CLAIM.json", {**case.claim, "metadata_only": False})
    elif fault == "missing_log":
        case.log_path.unlink()
    else:
        raw = case.log_path.read_text(encoding="utf-8")
        case.log_path.write_text(raw[:-1] + ',"status":"failed"}', encoding="utf-8")
    with pytest.raises(reconcile.CollectionResultReconcileError):
        call(case)


def test_attempt_has_a_bound_window(case):
    case.kwargs["max_elapsed_seconds"] = 10
    with pytest.raises(reconcile.CollectionResultReconcileError, match="BOUND_ATTEMPT"):
        call(case)


def test_actual_saved_failed_cli_reconciles_readonly():
    project = Path(__file__).resolve().parents[1]
    root = project / "data/production_trials/fresh_legal_full_flow_20261012/round_01/collection_live_01"
    paths = [root / "COLLECTION.stdout.log", root / "COLLECTION_CLAIM.json", root / "LIVE_IDENTITY_CHECK.json", root / "COLLECTION_RESULT.json"]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    value = reconcile.reconcile_collection_cli_result(project_root=project, collection_root=root,
        expected_account_key="account01", expected_account_uuid="account:9e5f9e75192fa45becb945bc",
        expected_profile_version=1, expected_public_id="dy4qyzku18yu",
        expected_workflow_run_id="research:a388adda8baf4a8b96e41c8b691183a7",
        expected_claim_sha256=before[root / "COLLECTION_CLAIM.json"])
    assert value["status"] == "human_required" and value["collection_run_id"] == ""
    assert value["result"]["unique_videos"] == 0 and value["authoritative_full_result_equal"] is True
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in before.items())
