"""Read-only integration against immutable real evidence; no service requests."""
from copy import deepcopy
import json
import socket

import pytest

from scripts import preview_creative_endpoint_feedback_v6 as preview
from src.content_factory import creative_video_trial_contract_v1 as source


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("read-only preview must not connect to a service")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.fixture(scope="module")
def real_preview():
    # No HTTP path exists in this function. Each test also denies sockets.
    return preview.build_preview()


def test_real_exhausted_lineage_replays_without_changing_originals(real_preview):
    report, feedback, request, wire = real_preview
    assert [row["ordinal"] for row in report["audits"]] == [518, 519, 520]
    assert report["director_capacity"]["remaining"] == 0
    assert report["dispatch_allowed"] is False
    assert report["calls_authorized"] is False
    assert report["new_calls"] == report["new_media_calls"] == 0
    assert all(preview.sha(path) == digest for path, digest in report["original_file_hashes"].items())
    assert report["native_plan_adopted"] is False


def test_full_source_and_last_original_native_enter_complete_request_once(real_preview):
    report, feedback, request, wire = real_preview
    inputs = preview.read(preview.frozen.ROOT / "INPUT.json")
    actual = json.loads(request["messages"][1]["content"])
    assert actual["full_current_script"] == inputs["script"]
    assert actual["shared_manifest"] == inputs["manifest"]
    assert actual["planned_initial_state"] == inputs["initial"]
    assert actual["reference_fulltext"] == inputs["original_input"]["reference_fulltext"]
    assert wire["messages"] == request["messages"]
    assert "prior_complete_native_direction" not in feedback
    assert source.digest(feedback["failed_complete_native_result"]) == report["original_failed_native_sha256"]
    diagnostic = feedback["diagnostic"]["endpoint_contract_diagnostic"]
    assert "native" not in diagnostic
    assert diagnostic["invalid_segments"][0]["segment_id"] == "M006"
    assert diagnostic["invalid_segments"][0]["required_seconds_for_requested_tier"] == pytest.approx(15.227273)
    assert diagnostic["invalid_segments"][0]["legal_budget_tiers_for_selected_range"] == ["minimum", "natural"]


def test_replay_rejects_changed_capacity_before_building_body(monkeypatch):
    changed = deepcopy(preview.loop.candidate_capacity(preview.read(preview.frozen.ROOT / "LOOP_STATE.json")))
    changed["remaining"] = 1
    monkeypatch.setattr(preview.loop, "candidate_capacity", lambda state: changed)
    monkeypatch.setattr(preview.clients, "expected_wire_request", lambda request: pytest.fail("body built after wrong lineage"))
    with pytest.raises(ValueError, match="exact completed 7/7"):
        preview.build_preview()


def test_equal_count_tampered_history_is_rejected_before_body(monkeypatch):
    original_read = preview.frozen.old.control.read
    changed = deepcopy(original_read(preview.frozen.ROOT / "LOOP_STATE.json"))
    results = [event for event in changed["director_events"] if event.get("event") == "result"]
    results[-1]["result"]["request_sha256"] = "f" * 64
    assert preview.loop.candidate_capacity(changed)["remaining"] == 0
    def redirected(path):
        if str(path) == str(preview.frozen.ROOT / "LOOP_STATE.json"):
            return deepcopy(changed)
        return original_read(path)
    monkeypatch.setattr(preview.frozen.old.control, "read", redirected)
    monkeypatch.setattr(preview.clients, "expected_wire_request", lambda request: pytest.fail("body built after history tampering"))
    with pytest.raises(ValueError, match="progress differs"):
        preview.build_preview()


def test_output_is_new_review_copy_and_cannot_overwrite_production_or_previous_preview(tmp_path, monkeypatch, real_preview):
    monkeypatch.setattr(preview, "QA_ROOT", tmp_path)
    monkeypatch.setattr(preview, "build_preview", lambda: deepcopy(real_preview))
    with pytest.raises(ValueError):
        preview.write_preview(preview.frozen.ROOT)
    result = preview.write_preview(tmp_path / "r1")
    assert result["dispatch_allowed"] is False
    before = (tmp_path / "r1/READ_ONLY_PREVIEW.json").read_bytes()
    with pytest.raises(ValueError, match="preserve prior previews"):
        preview.write_preview(tmp_path / "r1")
    assert (tmp_path / "r1/READ_ONLY_PREVIEW.json").read_bytes() == before
