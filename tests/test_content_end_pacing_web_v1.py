"""New-source web settings reach the same frozen brief; old runs stay unchanged."""
import json
from types import SimpleNamespace

import pytest

from src.web import natural_director_panel_v10 as panel
from src.content_factory import performance_timing_reference_v2 as pacing
from src.content_factory import visual_storytelling_v1 as visual


def setup_entry(tmp_path, monkeypatch):
    auth = tmp_path / "AUTHORIZATION.json"
    auth.write_text('{"human_authorization":"offline fixture"}', encoding="utf-8")
    calls = []

    def prepare(*args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "prepared", "automatic_media_submit": False}

    monkeypatch.setattr(panel, "_editor", lambda: None)
    monkeypatch.setattr(panel, "_runtime", lambda: SimpleNamespace(prepare_source=prepare))
    return auth, calls


def test_web_freezes_content_end_policy_in_new_source_brief(tmp_path, monkeypatch):
    auth, calls = setup_entry(tmp_path, monkeypatch)
    result = panel.prepare_source(tmp_path / "writer", authorization_path=auth,
        source_path=tmp_path / "source.txt", source_kind="original",
        brief={"source_kind": "original", "target_duration_seconds": 69})
    assert result["status"] == "prepared" and len(calls) == 1
    brief = calls[0][1]["brief"]
    assert brief == visual.apply_brief({"source_kind": "original", "target_duration_seconds": 69})
    assert brief["target_duration_seconds"] == 69
    assert "min_duration_seconds" not in brief
    assert brief["performance_timing_reference"] == pacing.profile()
    assert calls[0][1]["authorization_path"] == auth


def test_web_does_not_add_new_policy_to_existing_legacy_source(tmp_path, monkeypatch):
    auth, calls = setup_entry(tmp_path, monkeypatch)
    source = tmp_path / "writer"
    source.mkdir()
    binding = source / "BINDING.json"
    binding.write_text(json.dumps({"brief": {"target_duration_seconds": 120}}), encoding="utf-8")
    original = binding.read_bytes()
    with pytest.raises(ValueError):
        panel.prepare_source(source, authorization_path=auth, source_path=tmp_path / "source.txt",
            brief={"target_duration_seconds": 120})
    assert calls == [] and binding.read_bytes() == original
