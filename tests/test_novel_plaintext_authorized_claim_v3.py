"""Isolated continuation registration tests; all registry files stay in tmp."""
from copy import deepcopy
from pathlib import Path

import pytest

from src.content_factory import novel_plaintext_pipeline_v3 as pipe


@pytest.fixture
def authorized_parent(tmp_path, monkeypatch):
    registry, parent = tmp_path / "registry", tmp_path / "parent"
    source_path = tmp_path / "chapter.txt"
    source_path.write_text("第一章：婚礼现场。新郎苏醒，转头看见旧树刻字。", encoding="utf-8")
    source, evidence, paths = pipe.core._source(source_path, None, "临时测试小说", "tmp-book", None)
    registry.mkdir()
    parent.mkdir()
    parent_claim = {"schema": "novel_adaptation_production/v2", "run_dir": str(parent),
                    "source_binding_id": source["binding_id"], "story_id": "source_" + source["full_source_sha256"]}
    registry_rows = []
    original_bytes = {}
    for alias in pipe._aliases(source):
        path = registry / (alias + ".json")
        pipe.core._write(path, parent_claim)
        registry_rows.append(pipe.core._binding(path))
        original_bytes[path] = path.read_bytes()
    old_auth = tmp_path / "parent_auth.json"
    pipe.core._write(old_auth, {"legacy_checkpoint": {"path": str(tmp_path / "old_checkpoint.json"),
                                                   "sha256": "unused-in-this-registration-test", "bytes": 0}})
    pipe.core._write(parent / "BINDING.json", {"registry": registry_rows,
                                             "production_authorization": pipe.core._binding(old_auth)})
    auth_path = tmp_path / "AUTHORIZATION.json"
    auth = {"schema": "novel_plaintext_authorization/v3", "user_instruction": "修改测试生产测试",
            "run_dir": str(tmp_path / "run"), "parent_run": str(parent),
            "acquisition_receipt": str(tmp_path / "receipt.json"), "book_id": source["book_id"],
            "title": source["title"], "scope": None,
            "source_identity": {key: source[key] for key in ("full_source_sha256", "excerpt_sha256", "binding_id")},
            "legacy_totals": {"calls_started": 14, "reported_tokens": 228513},
            "original_budget": {"max_calls": 20, "max_total_tokens": 500000},
            "new_budget": {"max_calls": 6, "max_total_tokens": 271487, "max_revisions": 2},
            "automatic_media_submit": False}
    pipe.core._write(auth_path, auth)
    monkeypatch.setattr(pipe, "CANONICAL_REGISTRY", registry)
    # History audit itself has a separate read-only real-evidence test. These
    # tests isolate actual locked registration using a fully temporary parent.
    monkeypatch.setattr(pipe, "_audit_authorization", lambda path, run: deepcopy(auth))
    monkeypatch.setattr(pipe.core, "_source", lambda *args, **kwargs: (deepcopy(source), evidence, paths))
    monkeypatch.setattr(pipe.core, "_legacy_blocks", lambda *args, **kwargs: [])
    monkeypatch.setattr(pipe.CreativeRoleClients, "call", lambda *args, **kwargs: pytest.fail("prepare must not call a model"))
    return {"auth": auth, "auth_path": auth_path, "registry": registry, "original_bytes": original_bytes,
            "run": Path(auth["run_dir"]), "tmp_path": tmp_path}


def test_authorized_prepare_owns_one_continuation_without_changing_parent_registry(authorized_parent):
    item = authorized_parent
    view = pipe.prepare(item["run"], authorization=item["auth_path"])
    assert view["status"] == "prepared"
    assert view["calls_started"] == 0 and view["combined_calls_started"] == 14
    assert view["combined_known_reported_tokens"] == 228513
    continuation_paths = list((item["registry"] / "_plaintext_continuations").glob("*.json"))
    assert len(continuation_paths) == 1
    claim = pipe.core._read(continuation_paths[0])
    assert claim["run_dir"] == str(item["run"])
    assert claim["parent_run"] == item["auth"]["parent_run"]
    assert claim["authorization"] == pipe.core._binding(item["auth_path"])
    assert all(path.read_bytes() == raw for path, raw in item["original_bytes"].items())
    assert not list(item["run"].glob("REQUEST_*.json"))
    assert pipe.prepare(item["run"], authorization=item["auth_path"])["calls_started"] == 0
    assert len(list((item["registry"] / "_plaintext_continuations").glob("*.json"))) == 1


def test_same_parent_source_cannot_change_run_or_authorization_to_reclaim(authorized_parent):
    item = authorized_parent
    pipe.prepare(item["run"], authorization=item["auth_path"])
    existing_claim = next((item["registry"] / "_plaintext_continuations").glob("*.json"))
    original_claim_bytes = existing_claim.read_bytes()
    another_run = item["tmp_path"] / "another-run"
    item["auth"]["run_dir"] = str(another_run)
    another_auth = item["tmp_path"] / "ANOTHER_AUTHORIZATION.json"
    pipe.core._write(another_auth, item["auth"])
    with pytest.raises(RuntimeError, match="同故事/同父续行已有登记"):
        pipe.prepare(another_run, authorization=another_auth)
    assert not another_run.exists()
    assert existing_claim.read_bytes() == original_claim_bytes
    assert all(path.read_bytes() == raw for path, raw in item["original_bytes"].items())
    assert len(list((item["registry"] / "_plaintext_continuations").glob("*.json"))) == 1
    assert not list(item["run"].glob("REQUEST_*.json"))


def test_second_registry_directory_cannot_bypass_same_parent_claim(authorized_parent):
    item = authorized_parent
    pipe.prepare(item["run"], authorization=item["auth_path"])
    other_run = item["tmp_path"] / "other-run"
    item["auth"]["run_dir"] = str(other_run)
    other_auth = item["tmp_path"] / "OTHER_AUTHORIZATION.json"
    pipe.core._write(other_auth, item["auth"])
    mirror = item["tmp_path"] / "mirror-registry"
    with pytest.raises(RuntimeError, match="同故事/同父续行已有登记"):
        pipe.prepare(other_run, authorization=other_auth, registry_dir=mirror)
    assert not mirror.exists()
    assert all(path.read_bytes() == raw for path, raw in item["original_bytes"].items())
