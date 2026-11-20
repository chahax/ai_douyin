"""Offline-only acceptance and adversarial production continuation checks."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from src.content_factory import novel_adaptation_pipeline_v1 as core
from src.content_factory import novel_adaptation_production_v2 as production

_spec = importlib.util.spec_from_file_location("production_fake_fixtures", Path(__file__).with_name("test_novel_adaptation_pipeline_v1.py"))
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)


@pytest.fixture
def authorized(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(core, "ROOT", project)
    monkeypatch.setattr(production, "CANONICAL_REGISTRY", project / "registry")
    # Production ROOT remains the real code root solely for immutable code files.
    original_code_bindings = core._code_bindings
    monkeypatch.setattr(core, "_code_bindings", lambda: [core._binding(core.__file__)])
    assert original_code_bindings is not None
    old_dir = project / "data/novel_platform_trials/old"
    old_dir.mkdir(parents=True)
    chapter = tmp_path / "chapter.txt"
    chapter.write_bytes(_fixtures._fixtures.example_context()["source"]["text"].encode("utf-8"))
    acquisition = tmp_path / "acquired.json"
    core._write(acquisition, {"status": "source_saved", "source": {"book_name": "离线小说", "book_id": "fake-book",
                  "chapters": [{"path": str(chapter), "title": "第1章"}]}})
    source = core._source(None, acquisition, None, "fake-book", None)[0]
    responses, records = [], []
    for ordinal in range(1, 12):
        tokens = 12000 if ordinal < 11 else 60079
        result = _fixtures.FakeClients.envelope("writer", {}, ordinal)
        metadata, native = deepcopy(result.metadata), deepcopy(result.response_payload)
        metadata.update(prompt_tokens=tokens - 9, completion_tokens=9, total_tokens=tokens)
        native["usage"] = {key: metadata[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
        if ordinal == 11:
            metadata.update(finish_reason="length", response_fault_code="RESPONSE_TRUNCATED")
            native["choices"][0]["finish_reason"] = "length"
        path = old_dir / f"old_{ordinal:03}.json"
        core._write(path, {"response_metadata": metadata, "response_payload": native})
        binding = core._binding(path)
        responses.append(binding)
        records.append({"ordinal": ordinal, "path": binding["path"], "sha256": binding["sha256"],
                        "finish_reason": metadata["finish_reason"], "reported_tokens": tokens})
    checkpoint = old_dir / "FINAL_TRIAL_CHECKPOINT.json"
    core._write(checkpoint, {"book_id": "fake-book", "book_name": "离线小说", "status": "stopped_response_truncated",
                            "calls_started": 11, "known_reported_tokens": 180079,
                            "new_writer_requests_allowed_without_new_scope": False, "records": records})
    run = tmp_path / "run"
    auth_path = tmp_path / "AUTHORIZATION.json"
    auth = {"schema": production.AUTH_SCHEMA, "user_instruction": "生成环境真实生成验收",
            "run_dir": str(run), "book_id": "fake-book", "acquisition_receipt": str(acquisition), "scope": None,
            "source_identity": {key: source[key] for key in ("full_source_sha256", "excerpt_sha256", "binding_id")},
            "legacy_checkpoint": core._binding(checkpoint), "legacy_responses": responses,
            "legacy_totals": {"calls_started": 11, "reported_tokens": 180079},
            "original_budget": {"max_calls": 20, "max_total_tokens": 500000},
            "new_budget": {"max_calls": 9, "max_total_tokens": 319921, "max_revisions": 2},
            "allowed_stages": [*core.contracts.STAGES, "review"], "automatic_media_submit": False}
    core._write(auth_path, auth)
    return run, auth_path, auth, source


def test_full_native_route_inherits_legacy_and_no_duplicate_dispatch(authorized):
    run, auth_path, _, _ = authorized
    assert production.prepare(run, authorization=auth_path)["status"] == "prepared"
    clients = _fixtures.FakeClients()
    result = production.execute(run, clients=clients)
    assert result["status"] == "text_ready_for_director"
    assert result["combined_calls_started"] == 15
    assert result["combined_known_reported_tokens"] == 180159
    assert result["human_approved"] is False
    assert len(result["artifacts"]) == 6
    production.execute(run, clients=clients)
    assert len(clients.calls) == 4
    assert production.preview(run)["remaining_calls"] == 5


def test_no_global_mutation_and_old_entry_remains_blocked(authorized):
    run, auth_path, _, source = authorized
    before = core._verify, core._legacy_blocks, core.VERSION, core._lock
    production.prepare(run, authorization=auth_path)
    assert before == (core._verify, core._legacy_blocks, core.VERSION, core._lock)
    assert core._legacy_blocks(source, [])


@pytest.mark.parametrize("field", ["authorization", "response", "source", "checkpoint"])
def test_changes_stop_before_dispatch(authorized, field):
    run, auth_path, auth, _ = authorized
    production.prepare(run, authorization=auth_path)
    target = {"authorization": auth_path, "response": Path(auth["legacy_responses"][0]["path"]),
              "source": run.parent / "chapter.txt", "checkpoint": Path(auth["legacy_checkpoint"]["path"])}[field]
    target.write_bytes(target.read_bytes() + b" ")
    clients = _fixtures.FakeClients()
    with pytest.raises((ValueError, RuntimeError)):
        production.execute(run, clients=clients)
    assert clients.calls == []


def test_new_unrelated_matching_legacy_stop_is_not_exempted(authorized):
    run, auth_path, auth, _ = authorized
    production.prepare(run, authorization=auth_path)
    old = core._read(auth["legacy_checkpoint"]["path"])
    core._write(core.ROOT / "data/novel_platform_trials/other/FINAL_TRIAL_CHECKPOINT.json", old)
    clients = _fixtures.FakeClients()
    with pytest.raises(RuntimeError, match="历史停止"):
        production.execute(run, clients=clients)
    assert clients.calls == []


def test_registry_cannot_be_changed_to_reclaim_budget(authorized):
    run, auth_path, auth, _ = authorized
    production.prepare(run, authorization=auth_path)
    other = run.parent / "run2"
    auth["run_dir"] = str(other)
    other_auth = run.parent / "AUTH2.json"
    core._write(other_auth, auth)
    with pytest.raises(RuntimeError, match="已有登记"):
        production.prepare(other, authorization=other_auth)


@pytest.mark.parametrize("mutation", ["usage", "finish", "budget", "missing_record"])
def test_invalid_authority_or_unknown_legacy_never_prepares(authorized, mutation):
    run, auth_path, auth, _ = authorized
    if mutation in {"usage", "finish"}:
        row = auth["legacy_responses"][0]
        response = core._read(row["path"])
        if mutation == "usage":
            response["response_payload"]["usage"]["total_tokens"] = None
        else:
            response["response_payload"]["choices"][0]["finish_reason"] = None
        Path(row["path"]).write_text(json.dumps(response), encoding="utf-8")
        auth["legacy_responses"][0] = core._binding(row["path"])
        checkpoint = core._read(auth["legacy_checkpoint"]["path"])
        checkpoint["records"][0]["sha256"] = auth["legacy_responses"][0]["sha256"]
        Path(auth["legacy_checkpoint"]["path"]).write_text(json.dumps(checkpoint), encoding="utf-8")
        auth["legacy_checkpoint"] = core._binding(auth["legacy_checkpoint"]["path"])
    elif mutation == "budget":
        auth["new_budget"]["max_calls"] = 20
    else:
        auth["legacy_responses"].pop()
    auth_path.write_text(json.dumps(auth), encoding="utf-8")
    with pytest.raises(ValueError):
        production.prepare(run, authorization=auth_path)
    assert not (run / "BINDING.json").exists()


def test_new_response_truncation_preserves_pending_and_never_retries(authorized):
    run, auth_path, _, _ = authorized
    production.prepare(run, authorization=auth_path)

    class Truncated(_fixtures.FakeClients):
        def call(self, *args, **kwargs):
            result = super().call(*args, **kwargs)
            result.metadata["finish_reason"] = "length"
            result.response_payload["choices"][0]["finish_reason"] = "length"
            return result

    clients = Truncated()
    with pytest.raises(RuntimeError):
        production.execute(run, clients=clients)
    assert (run / "RESPONSE_001.json").exists()
    result = production.execute(run, clients=clients)
    assert result["status"] == "needs_attention" and len(clients.calls) == 1
    assert result["state"]["pending_call"] == 1
