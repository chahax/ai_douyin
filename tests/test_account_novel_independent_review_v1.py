"""Independent fault probes at freezing and provider-result boundaries."""
import hashlib
import json

import pytest

from src.content_factory import account_novel_creation_v1 as creation
from src.content_factory.account_novel_selection_v1 import discover_books
from src.content_factory.account_novel_workflow_v1 import AccountNovelWorkflow
from src.content_factory.creative_workflow_roles import RoleResult
from tests import test_account_novel_selection_v1 as selection_fixtures
from tests.test_account_novel_selection_v1 import book, NOW
from tests.test_creative_workflow import SOURCE, FakeClients, _answers

profile = selection_fixtures.profile
opportunity = selection_fixtures.opportunity


def test_original_change_between_selection_and_freeze_blocks_preview(tmp_path, profile, opportunity, monkeypatch):
    folder = book(tmp_path / "books", body=SOURCE)
    candidates = discover_books(tmp_path / "books")
    original_select = creation.select_target_novel

    def change_after_select(*args, **kwargs):
        result = original_select(*args, **kwargs)
        with (folder / "material.txt").open("ab") as stream:
            stream.write(b"\nchanged-after-selection")
        return result

    monkeypatch.setattr(creation, "select_target_novel", change_after_select)
    run = tmp_path / "run"
    try:
        creation.prepare_account_novel_run(profile, opportunity, candidates, run, now=NOW,
                                          task_registry=tmp_path / "registry")
    except (ValueError, RuntimeError):
        return  # Detecting the changed identity during preparation is preferable.
    monkeypatch.setattr(creation, "select_target_novel", original_select)
    with pytest.raises((ValueError, RuntimeError)):
        creation.preview_account_novel_run(run, now=NOW)


def test_frozen_source_preserves_crlf_and_derived_hash(tmp_path, profile, opportunity):
    source = SOURCE.replace("\r\n", "\n").replace("\n", "\r\n")
    folder = book(tmp_path / "books", body=source)
    run = tmp_path / "run"
    creation.prepare_account_novel_run(profile, opportunity, discover_books(tmp_path / "books"), run,
                                      now=NOW, task_registry=tmp_path / "registry")
    selection = json.loads((run / "SELECTION.json").read_text(encoding="utf-8"))
    expected = selection["selected_book"]["source_span"]["sha256"]
    frozen = (run / "frozen/story_source.txt").read_bytes()
    assert hashlib.sha256(frozen).hexdigest() == expected
    assert frozen == (folder / "material.txt").read_bytes()


def test_unknown_usage_retains_original_received_envelope(tmp_path, profile, opportunity):
    book(tmp_path / "books", body=SOURCE)
    run = tmp_path / "run"
    creation.prepare_account_novel_run(profile, opportunity, discover_books(tmp_path / "books"), run,
                                      now=NOW, task_registry=tmp_path / "registry", duration_seconds=[10, 30])
    envelope = {"id": "unknown-usage-original", "choices": [{"finish_reason": "stop"}], "usage": None}

    class Unknown(FakeClients):
        def call(self, role, messages, **kwargs):
            result = super().call(role, messages, **kwargs)
            return RoleResult(result.text, {**result.metadata, "total_tokens": None}, response_payload=envelope)

    clients = Unknown(_answers())

    def runner(*, run_dir, bundle, workflow_kwargs):
        return AccountNovelWorkflow(run_dir, clients=clients, **workflow_kwargs).run(bundle)

    with pytest.raises(Exception):
        creation.execute_account_novel_run(run, now=NOW, runner=runner)
    receipt = json.loads((run / "creative/writer_analysis.json").read_text(encoding="utf-8"))
    assert receipt["failure"]["code"] == "USAGE_UNKNOWN"
    assert receipt["response_payload"] == envelope
    assert len(clients.calls) == 1


@pytest.mark.parametrize("finish_reason", [None, "", "length"])
def test_unfinished_response_stops_without_new_dispatch_on_resume(tmp_path, profile, opportunity, finish_reason):
    book(tmp_path / "books", body=SOURCE)
    run = tmp_path / "run"
    creation.prepare_account_novel_run(profile, opportunity, discover_books(tmp_path / "books"), run,
                                      now=NOW, task_registry=tmp_path / "registry", duration_seconds=[10, 30])

    class Unfinished(FakeClients):
        def call(self, role, messages, **kwargs):
            result = super().call(role, messages, **kwargs)
            return RoleResult(result.text, {**result.metadata, "finish_reason": finish_reason},
                              response_payload={"id": "unfinished", "finish_reason": finish_reason})

    clients = Unfinished(_answers())

    def runner(*, run_dir, bundle, workflow_kwargs):
        return AccountNovelWorkflow(run_dir, clients=clients, **workflow_kwargs).run(bundle)

    with pytest.raises(Exception):
        creation.execute_account_novel_run(run, now=NOW, runner=runner)
    receipt = json.loads((run / "creative/writer_analysis.json").read_text(encoding="utf-8"))
    assert receipt["response_payload"]["id"] == "unfinished"
    assert receipt["failure"]["automatic_retry"] is False
    with pytest.raises(Exception):
        creation.execute_account_novel_run(run, now=NOW, runner=runner)
    assert len(clients.calls) == 1
