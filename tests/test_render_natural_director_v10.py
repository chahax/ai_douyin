"""Readable export preserves verified native text; no inference or media calls."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from scripts import render_natural_director_v10 as renderer
from src.content_factory import natural_director_pipeline_v10 as pipeline

_spec = importlib.util.spec_from_file_location("natural_renderer_contract_fixtures", Path(__file__).with_name("test_natural_director_contracts_v10.py"))
fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixtures)


def snapshot(folder):
    return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


@pytest.fixture
def ready(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    native = run / "native"
    native.mkdir()
    handoff = fixtures.file_handoff(native)
    (run / "SCREENPLAY.md").write_text(fixtures.DRAFT, encoding="utf-8")
    (run / "NATURAL_DIRECTOR.md").write_text(fixtures.NATURAL, encoding="utf-8")
    (run / "PRODUCTION_HANDOFF.json").write_text(json.dumps(handoff, ensure_ascii=False, indent=2), encoding="utf-8")
    (run / "VIDEO_REQUESTS.json").write_text(json.dumps(handoff["video_requests"], ensure_ascii=False, indent=2), encoding="utf-8")
    (run / "BINDING.json").write_text('{"source":{"title":"可读交付离线样例"}}', encoding="utf-8")
    (run / "OUTPUT_MANIFEST.json").write_text('{"fixture":"renderer-only, actual shared native gate still verifies"}', encoding="utf-8")
    monkeypatch.setattr(pipeline, "inspect", lambda *_: {"status": "text_ready_for_production", "blockers": [], "pending_call": None})
    monkeypatch.setattr(pipeline, "CreativeRoleClients", lambda: pytest.fail("render must not construct clients"))
    return run, tmp_path / "delivery", handoff


def test_complete_export_preserves_writer_natural_all_prompts_reviews_and_original_files(ready):
    run, output, handoff = ready
    before = snapshot(run)
    result = renderer.render(run, output)
    assert result["status"] == "verified_text_delivery" and result["request_count"] == 2
    assert result["estimated_duration_seconds"] == 20 and result["human_approved"] is False
    body = (output / "COMPLETE_TEXT_DELIVERY.md").read_text(encoding="utf-8")
    assert fixtures.DRAFT in body and fixtures.NATURAL in body
    for item in handoff["video_requests"]["requests"]:
        assert item["prompt"] in body and item["segment_id"] in body
    assert handoff["extract"]["native"]["summary"] in body
    assert handoff["final_review"]["native"]["summary"] in body
    assert (output / "SDK_REQUESTS.json").read_bytes() == (run / "VIDEO_REQUESTS.json").read_bytes()
    assert snapshot(run) == before


def test_repeated_render_is_identical_and_does_not_rewrite_outputs(ready):
    run, output, _ = ready
    renderer.render(run, output)
    before = snapshot(output)
    renderer.render(run, output)
    assert snapshot(output) == before


@pytest.mark.parametrize("status", ["prepared", "needs_attention", "round_limit_exhausted", "upstream_writer_revision_required", "evidence_invalid"])
def test_not_ready_never_creates_deliverable(status, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "inspect", lambda *_: {"status": status})
    out = tmp_path / "output"
    with pytest.raises(ValueError, match="ready"):
        renderer.render(tmp_path / "run", out)
    assert not out.exists()


@pytest.mark.parametrize("flag", [{"blockers": ["stop"]}, {"pending_call": 2}])
def test_ready_label_alone_cannot_bypass_stops(flag, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "inspect", lambda *_: {"status": "text_ready_for_production", **flag})
    with pytest.raises(ValueError):
        renderer.render(tmp_path / "run", tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_original_run_cannot_be_delivery_destination(ready):
    run, _, _ = ready
    before = snapshot(run)
    with pytest.raises(ValueError, match="之外"):
        renderer.render(run, run / "delivery")
    assert snapshot(run) == before


def test_changed_native_or_sdk_request_cannot_render(ready):
    run, output, _ = ready
    requests = json.loads((run / "VIDEO_REQUESTS.json").read_text(encoding="utf-8"))
    requests["requests"][0]["prompt"] += " injected"
    (run / "VIDEO_REQUESTS.json").write_text(json.dumps(requests), encoding="utf-8")
    with pytest.raises(ValueError, match="不一致"):
        renderer.render(run, output)
    assert not output.exists()


def test_native_file_tamper_is_rejected_by_shared_gate_even_with_fake_ready_label(ready):
    run, output, handoff = ready
    request = Path(handoff["native_evidence"]["stages"]["final_review"]["request"]["path"])
    request.write_bytes(request.read_bytes() + b" ")
    with pytest.raises(ValueError, match="bytes/hash"):
        renderer.render(run, output)
    assert not output.exists()


def test_existing_different_delivery_is_not_overwritten(ready):
    run, output, _ = ready
    output.mkdir()
    existing = output / "COMPLETE_TEXT_DELIVERY.md"
    existing.write_text("old explicit delivery", encoding="utf-8")
    with pytest.raises(ValueError, match="不覆盖"):
        renderer.render(run, output)
    assert existing.read_text(encoding="utf-8") == "old explicit delivery"


def test_cli_rejection_has_nonzero_exit_without_outputs(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "inspect", lambda *_: {"status": "needs_attention"})
    assert renderer.main(["--run-dir", str(tmp_path / "run"), "--output-dir", str(tmp_path / "out")]) == 1
    value = json.loads(capsys.readouterr().out)
    assert value["status"] == "delivery_rejected" and value["automatic_media_submit"] is False
    assert not (tmp_path / "out").exists()


def test_prompt_backticks_are_preserved_with_a_safe_outer_fence():
    text = 'A complete prompt with ``` literal and "quoted speech".'
    rendered = renderer._fenced(text)
    assert rendered.startswith("````text\n") and text in rendered and rendered.endswith("````")
