from copy import deepcopy
import json

import pytest

from src.content_factory import corpus_scope_v9 as scope


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def fixture_run(tmp_path, ancestor_denial=True):
    prior = tmp_path / "old"
    put(prior / "STATE.json", {"status": "materials_ready", "pending": None})
    put(prior / "PLAN.json", {"version": "old-frozen-plan"})
    if ancestor_denial:
        put(prior / "APPROVAL_REQUIRED.json", {"status": "denied", "reason": "old specific scope"})
    run = tmp_path / "new"
    source = {"manifest": {"book_id": "fixture-book", "book_name": "隔离书籍"},
              "chapters": [{"index": 1, "text": "原文一"}, {"index": 2, "text": "原文二"}]}
    models = {"writer": {"provider": "minimax", "model": "test-writer", "base_url": "https://fixture.invalid/v1"},
              "director": {"provider": "deepseek", "model": "test-reviewer", "base_url": "https://review.invalid/v1"}}
    plan = {"version": scope.PIPELINE_VERSION, "source_sha256": scope._digest(source),
            "source_chapters": [1, 2], "cloud_models": models,
            "previous_status_path": str(prior / "STATE.json")}
    put(run / "SOURCE.json", source)
    put(run / "PLAN.json", plan)
    put(run / "AUTHORIZATION.json", {"user_statement": "先开发本机流程"})
    return run, plan, prior


def approve(run, plan, text="已明确批准的问题与本次答复，测试调用方负责确认其授权含义。"):
    return scope.record_cloud_authorization(run, text,
        approved_source_sha256=plan["source_sha256"], approved_destinations=plan["cloud_models"])


def test_implementation_pin_is_exact_and_read_only():
    pin = scope.implementation_pin()
    assert set(pin["files"]) == set(scope.PIN_FILES)
    assert all(len(value) == 64 for value in pin["files"].values())
    assert scope.validate_implementation_pin(pin) is True
    assert {'corpus_production_v9.py', 'corpus_scope_v9.py', 'corpus_reference_view_v1.py', 'corpus_temporal_policy_v1.py', 'minimax_production_client_v1.py', 'corpus_chapter_materials_v6.py',
            'corpus_episode_state_v6.py', 'corpus_production_contract_v6.py'} <= set(pin['files'])


@pytest.mark.parametrize("mutation", [
    lambda pin: pin["files"].update({"corpus_chapter_materials_v6.py": "0" * 64}),
    lambda pin: pin["files"].pop("corpus_parallel_calls_v2.py"),
    lambda pin: pin["files"].update({"unapproved_module.py": "0" * 64}),
    lambda pin: pin.update(version="old"),
])
def test_changed_or_incomplete_implementation_pin_rejected(mutation):
    pin = scope.implementation_pin()
    mutation(pin)
    with pytest.raises(ValueError, match="implementation_pin_changed"):
        scope.validate_implementation_pin(pin)


def test_no_cloud_authorization_is_created_from_old_generic_scope(tmp_path):
    run, plan, _ = fixture_run(tmp_path)
    with pytest.raises(ValueError, match="explicit_cloud_authorization_required"):
        scope.require_cloud_authorization(run, plan)
    assert not (run / "CLOUD_AUTHORIZATION.json").exists()


def test_explicit_scope_binds_plan_source_chapters_destinations_and_old_denial(tmp_path):
    run, plan, prior = fixture_run(tmp_path)
    denial_bytes = (prior / "APPROVAL_REQUIRED.json").read_bytes()
    evidence = approve(run, plan)
    assert evidence["plan_sha256"] == scope._digest(plan)
    assert evidence["source_sha256"] == plan["source_sha256"]
    assert evidence["source_book_id"] == "fixture-book"
    assert evidence["approved_chapter_indices"] == [1, 2]
    assert evidence["approved_destinations"] == plan["cloud_models"]
    assert evidence["ancestry"]["denial_records"] == [{
        "path": str((prior / "APPROVAL_REQUIRED.json").resolve()),
        "sha256": scope._file_sha(prior / "APPROVAL_REQUIRED.json")}]
    assert scope.require_cloud_authorization(run, plan) == evidence
    assert (prior / "APPROVAL_REQUIRED.json").read_bytes() == denial_bytes


def test_confirmation_evidence_text_is_not_guessed_by_keyword_heuristics(tmp_path):
    run, plan, _ = fixture_run(tmp_path)
    # A caller may bind an unambiguous yes to the actual displayed question.
    statement = "当前明确确认问题与答复的完整证据：可以。"
    record = approve(run, plan, statement)
    assert record["approval_evidence_text"] == statement
    assert scope.require_cloud_authorization(run, plan)["approval_evidence_text"] == statement


@pytest.mark.parametrize("statement", [None, "", " \n ", 7])
def test_missing_current_approval_evidence_is_rejected(tmp_path, statement):
    run, plan, _ = fixture_run(tmp_path)
    with pytest.raises(ValueError, match="explicit_cloud_approval_evidence_required"):
        approve(run, plan, statement)
    assert not (run / "CLOUD_AUTHORIZATION.json").exists()


def test_wrong_source_destination_or_chapters_cannot_be_recorded(tmp_path):
    run, plan, _ = fixture_run(tmp_path)
    with pytest.raises(ValueError, match="approved_source_scope_mismatch"):
        scope.record_cloud_authorization(run, "批准证据", approved_source_sha256="wrong",
                                         approved_destinations=plan["cloud_models"])
    changed = deepcopy(plan["cloud_models"])
    changed["writer"]["model"] = "different-model"
    with pytest.raises(ValueError, match="approved_destinations_mismatch"):
        scope.record_cloud_authorization(run, "批准证据", approved_source_sha256=plan["source_sha256"],
                                         approved_destinations=changed)
    with pytest.raises(ValueError, match="approved_chapters_mismatch"):
        scope.record_cloud_authorization(run, "批准证据", approved_source_sha256=plan["source_sha256"],
                                         approved_destinations=plan["cloud_models"], approved_chapter_indices=[1])
    assert not (run / "CLOUD_AUTHORIZATION.json").exists()


def test_exact_explicit_chapter_list_is_accepted(tmp_path):
    run, plan, _ = fixture_run(tmp_path)
    record = scope.record_cloud_authorization(run, "批准证据", approved_source_sha256=plan["source_sha256"],
                                             approved_destinations=plan["cloud_models"], approved_chapter_indices=[1, 2])
    assert record["approved_chapter_indices"] == [1, 2]


def test_existing_record_is_idempotent_and_never_overwritten(tmp_path):
    run, plan, _ = fixture_run(tmp_path)
    first = approve(run, plan)
    original_bytes = (run / "CLOUD_AUTHORIZATION.json").read_bytes()
    assert approve(run, plan) == first
    with pytest.raises(ValueError, match="already_frozen"):
        approve(run, plan, "另一份范围批准证据")
    assert (run / "CLOUD_AUTHORIZATION.json").read_bytes() == original_bytes


@pytest.mark.parametrize("mutation", [
    lambda record: record.update(source_sha256="bad"),
    lambda record: record.update(plan_sha256="bad"),
    lambda record: record.update(approved_chapter_indices=[1]),
    lambda record: record.update(approved_destinations={}),
    lambda record: record.update(approval_evidence_text=""),
    lambda record: record.update(old_denials_preserved=False),
    lambda record: record.update(ancestry={"denial_records": [], "previous_status_links": []}),
])
def test_tampered_authorization_rejected_at_dispatch(tmp_path, mutation):
    run, plan, _ = fixture_run(tmp_path)
    record = approve(run, plan)
    mutation(record)
    put(run / "CLOUD_AUTHORIZATION.json", record)
    with pytest.raises(ValueError):
        scope.require_cloud_authorization(run, plan)


@pytest.mark.parametrize("operation", ["delete", "change", "new_denial"])
def test_denial_ancestry_changes_are_not_silently_ignored(tmp_path, operation):
    run, plan, prior = fixture_run(tmp_path, ancestor_denial=operation != "new_denial")
    approve(run, plan)
    path = prior / "APPROVAL_REQUIRED.json"
    if operation == "delete":
        path.unlink()
    else:
        put(path, {"new": "denial evidence"})
    with pytest.raises(ValueError, match="scope_or_ancestry_changed"):
        scope.require_cloud_authorization(run, plan)


def test_current_run_denial_requires_separate_disposition_and_is_never_removed(tmp_path):
    run, plan, _ = fixture_run(tmp_path)
    path = put(run / "APPROVAL_REQUIRED.json", {"status": "denied-current-run"})
    original = path.read_bytes()
    approve(run, plan)
    with pytest.raises(ValueError, match="separate_disposition"):
        scope.require_cloud_authorization(run, plan)
    assert path.read_bytes() == original


def test_source_or_plan_change_invalidates_record(tmp_path):
    run, plan, _ = fixture_run(tmp_path)
    approve(run, plan)
    changed = deepcopy(plan)
    changed["source_chapters"] = [1]
    with pytest.raises(ValueError, match="plan_changed"):
        scope.require_cloud_authorization(run, changed)
    source = scope._read(run / "SOURCE.json")
    source["chapters"][0]["text"] = "被改过的正文"
    put(run / "SOURCE.json", source)
    with pytest.raises(ValueError, match="source_changed"):
        scope.require_cloud_authorization(run, plan)


def test_follows_multiple_explicit_previous_status_links(tmp_path):
    run, plan, prior = fixture_run(tmp_path)
    oldest = tmp_path / "oldest"
    put(oldest / "STATE.json", {"pending": None})
    put(oldest / "PLAN.json", {"version": "original"})
    put(oldest / "APPROVAL_REQUIRED.json", {"status": "oldest-denied"})
    put(prior / "PLAN.json", {"previous_status_path": str(oldest / "STATE.json")})
    record = approve(run, plan)
    assert len(record["ancestry"]["denial_records"]) == 2
    assert scope.require_cloud_authorization(run, plan) == record


def test_previous_phase_plan_is_bound_to_outer_run_and_its_denial(tmp_path):
    run, plan, prior = fixture_run(tmp_path)
    outer = scope._read(prior / "PLAN.json")
    phase = prior / "local"
    put(phase / "STATE.json", {"pending": None})
    put(phase / "PLAN.json", {"parent_plan_sha256": scope._digest(outer)})
    plan["previous_status_path"] = str(phase / "STATE.json")
    put(run / "PLAN.json", plan)
    record = approve(run, plan)
    assert record["ancestry"]["denial_records"][0]["path"] == str((prior / "APPROVAL_REQUIRED.json").resolve())
    assert len(record["ancestry"]["previous_status_links"]) == 2


def test_cycle_and_missing_ancestry_evidence_fail_closed(tmp_path):
    run, plan, prior = fixture_run(tmp_path)
    put(prior / "PLAN.json", {"previous_status_path": str(run / "STATE.json")})
    put(run / "STATE.json", {"pending": None})
    with pytest.raises(ValueError, match="ancestry_cycle"):
        approve(run, plan)
    put(prior / "PLAN.json", {"previous_status_path": str(tmp_path / "gone" / "STATE.json")})
    with pytest.raises(ValueError, match="previous_status_evidence_missing"):
        approve(run, plan)


@pytest.mark.parametrize("endpoint", ["https://user:secret@fixture.invalid/v1", "https://fixture.invalid/v1?key=secret"])
def test_destination_urls_cannot_store_embedded_credentials(tmp_path, endpoint):
    run, plan, _ = fixture_run(tmp_path)
    plan["cloud_models"]["writer"]["base_url"] = endpoint
    put(run / "PLAN.json", plan)
    with pytest.raises(ValueError, match="exclude_credentials"):
        approve(run, plan)


def test_generic_old_prepare_statement_never_replaces_explicit_evidence(tmp_path):
    run, plan, _ = fixture_run(tmp_path)
    approve(run, plan, "完整当前批准证据")
    assert scope.require_cloud_authorization(run, plan)["approval_evidence_text"] == "完整当前批准证据"
    assert scope._read(run / "AUTHORIZATION.json")["user_statement"] == "先开发本机流程"
