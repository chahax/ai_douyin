"""Independent source-history and identity checks, using invented local sources."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.content_factory import novel_adaptation_contracts_v1 as contracts
from src.content_factory import novel_adaptation_pipeline_v1 as pipeline
from src.content_factory import novel_adaptation_acquisition_v1 as acquisition
from test_novel_adaptation_contracts_v1 import example_context


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(pipeline, "ROOT", root)
    monkeypatch.setattr(pipeline, "CANONICAL_REGISTRY", root / "registry")


def test_partial_copy_of_stopped_story_does_not_restart_its_budget(tmp_path):
    trial = pipeline.ROOT / "data/novel_platform_trials/synthetic_old"
    trial.mkdir(parents=True)
    text = ("母亲把父亲留下的信递给孩子，孩子决定循着地址寻找父亲。" * 12
            + "第二天，孩子走到山下，看见熟悉的旧门牌，想起母亲的叮嘱。" * 12)
    chapter = trial / "001.txt"
    chapter.write_text("第一章\n\n" + text, encoding="utf-8")
    checkpoint = {"book_id": "synthetic-book", "book_name": "旧标题",
                  "status": "stopped_response_truncated", "calls_started": 11,
                  "known_reported_tokens": 180079,
                  "new_writer_requests_allowed_without_new_scope": False}
    (trial / "FINAL_TRIAL_CHECKPOINT.json").write_text(json.dumps(checkpoint), encoding="utf-8")
    source_receipt = {"status": "source_saved", "source_integrity": {
        "body_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()},
        "source": {"chapters": [{"file": str(chapter)}]}}
    (trial / "ACQUISITION_RESULT_v4.json").write_text(json.dumps(source_receipt), encoding="utf-8")
    copied_excerpt = tmp_path / "重新保存的片段.txt"
    copied_excerpt.write_text(text[45:245], encoding="utf-8")
    result = pipeline.prepare(tmp_path / "new_run", source_path=copied_excerpt,
                              title="本次改编标题", scope="旧书一部分正文")
    assert result["status"] == "legacy_dispatch_blocked"
    assert result["state"]["legacy_calls_started"] == 11
    assert result["state"]["legacy_reported_tokens"] == 180079
    assert not list((tmp_path / "new_run").glob("REQUEST_*.json"))


def test_reserved_narrator_id_cannot_change_a_character_dialogue_speaker():
    context = deepcopy(example_context())
    def rename(value):
        if isinstance(value, str):
            return "narrator" if value == "C1" else value
        if isinstance(value, list):
            return [rename(item) for item in value]
        if isinstance(value, dict):
            return {key: rename(item) for key, item in value.items()}
        return value
    context = rename(context)
    issues = contracts.validate_stage("analysis", context["analysis"], context)
    issues += contracts.validate_stage("screenplay", context["screenplay"], context)
    if not issues:
        reading = contracts.render_screenplay(context["screenplay"])
        assert "小林：我现在就去找他。" in reading
        assert "旁白：我现在就去找他。" not in reading


def test_caller_scope_is_kept_separate_from_acquired_chapter_facts(tmp_path):
    chapter = tmp_path / "chapter.txt"
    chapter.write_text(example_context()["source"]["text"], encoding="utf-8")
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"status": "source_saved", "source": {"book_id": "new-book",
        "book_name": "独立小说", "chapters": [{"path": str(chapter), "title": "第一章 门口"}]},
        "scope": {"acquired_chapters": 1, "chapter_titles": ["第一章 门口"]}}), encoding="utf-8")
    result = pipeline.prepare(tmp_path / "run", acquisition_receipt=receipt, scope="高潮选段")
    scope = result["source"]["scope"]
    assert isinstance(scope, dict)
    assert scope["acquired_chapters"] == 1 and scope["chapter_titles"] == ["第一章 门口"]
    assert scope["adaptation_scope"] == "高潮选段"


def test_existing_native_project_relative_chapter_path_remains_usable(tmp_path):
    book = tmp_path / "book"
    (book / "chapters").mkdir(parents=True)
    chapter = book / "chapters/001.txt"
    chapter.write_text("第一章\n\n" + example_context()["source"]["text"], encoding="utf-8")
    relative = str(chapter.resolve().relative_to(Path.cwd().resolve()))
    metadata = book / "meta.json"
    metadata.write_text(json.dumps({"book_id": "native-relative-book", "book_name": "既有采集书",
        "fetch_log": [{"file": relative, "title": "第一章", "char_count": 40}]}), encoding="utf-8")
    result = acquisition.import_saved_book(metadata, tmp_path / "bridge")
    assert result["status"] == "source_saved"
    assert result["source"]["chapters"][0]["path"] == str(chapter.resolve())


def test_chapter_relative_paths_do_not_choose_a_different_existing_file(tmp_path, monkeypatch):
    project = tmp_path / "native_project"
    project.mkdir()
    monkeypatch.setattr(acquisition, "ROOT", project)
    book = tmp_path / "book"
    (book / "chapters").mkdir(parents=True)
    chapter = book / "chapters/001.txt"
    chapter.write_text("第一章\n\n真实正文", encoding="utf-8")
    (project / "data").mkdir()
    (project / "data/001.txt").write_text("项目根同名正文", encoding="utf-8")
    metadata = book / "meta.json"
    metadata.write_text(json.dumps({"fetch_log": [{"file": "chapters/001.txt", "title": "第一章"}]}), encoding="utf-8")
    result = acquisition.import_saved_book(metadata, tmp_path / "bridge")
    assert result["source"]["chapters"][0]["path"] == str(chapter.resolve())
    metadata.write_text(json.dumps({"fetch_log": [{"file": "data/../../outside.txt"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="越出"):
        acquisition.import_saved_book(metadata, tmp_path / "bad_bridge")
