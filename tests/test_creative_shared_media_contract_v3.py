"""Synthetic original-byte and request gates; no human/media quality claim."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import socket

import pytest

from src.content_factory import creative_shared_media_contract_v3 as media
from src.content_factory import creative_shared_production_contract_v1 as shared
from tests.test_creative_shared_production_pipeline_v1 import provider_fixture


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("media contract v3 tests are offline")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bootstrap_fixture(tmp_path):
    script, manifest, state = provider_fixture(tmp_path)
    for entity in [*manifest["actors"], *manifest["scenes"]]:
        entity["asset_binding"] = shared.unknown("离线bootstrap视觉角色未批准")
    manifest["asset_catalog"] = []
    state["global_manifest_sha256"] = shared.digest(manifest)
    compiled = shared.compile_segment_context(manifest, script, state, ["B1.S01"], bootstrap=True)
    return script, manifest, state, compiled


def continuation_fixture(tmp_path):
    script, manifest, state = provider_fixture(tmp_path)
    _, _, _, initial = bootstrap_fixture(tmp_path)
    tail_path = tmp_path / "synthetic_provider_original_tail.png"
    tail_path.write_bytes(b"OFFLINE_ORIGINAL_SERVICE_TAIL_NOT_PIXELS")
    video_path = tmp_path / "synthetic_original_video.mp4"
    video_path.write_bytes(b"OFFLINE_ORIGINAL_SERVICE_VIDEO_NOT_PLAYABLE")
    tail_sha, video_sha = media._sha_file(tail_path), media._sha_file(video_path)
    previous_request = media.compile_request_preview(initial, initial["prompt_fragment"], 4)["request"]
    receipt_path, review_path = tmp_path / "original_receipt.json", tmp_path / "human_review.json"
    receipt = {"technical_status": "succeeded", "provider_task_status": "succeeded", "status": "awaiting_human_review",
        "provider": "ark_api", "model": manifest["provider_policy"]["model"],
        "task_id": "offline-task", "segment_id": "M001", "last_frame_source": "generation_service_original",
        "last_frame": str(tail_path), "last_frame_sha256": tail_sha,
        "video_path": str(video_path), "video_sha256": video_sha,
        "final": {"id": "offline-task", "status": "succeeded", "content": {"last_frame_url": "https://offline.invalid/original-tail"}},
        "request": previous_request, "request_sha256": shared.digest(previous_request),
        "plan_snapshot": {"shared_context": initial, "completed_source_refs": [], "source_refs": ["B1.S01"]}}
    receipt_sha = save(receipt_path, receipt)
    review = {"decision": "approved", "decision_source": "explicit_user_statement",
        "user_statement": "离线模拟用户通过M001并确认两位人物主体。不是实际授权。",
        "source_receipt": str(receipt_path), "source_receipt_sha256": receipt_sha,
        "original_video": str(video_path), "original_video_sha256": video_sha,
        "raw_tail": str(tail_path), "raw_tail_sha256": tail_sha,
        "global_manifest_sha256": shared.digest(manifest),
        "actor_subject_mapping": [{"actor_id": a["id"], **a["asset_binding"]["value"],
            "subject_description": "离线模拟视觉主体：" + "、".join(f["value"] for f in a["profile"].values())}
            for a in manifest["actors"]]}
    review_sha = save(review_path, review)
    state.update(completed_source_refs=["B1.S01"], previous_scene_id="meeting_room")
    evidence = {"path": str(tail_path), "sha256": tail_sha, "role": "first_frame",
        "source": "generation_service_original", "source_task_id": "offline-task", "source_segment_id": "M001",
        "source_video_sha256": video_sha, "human_review_path": str(review_path), "human_review_sha256": review_sha,
        "human_review_decision": "approved", "global_manifest_sha256": shared.digest(manifest),
        "actor_ids": [a["id"] for a in manifest["actors"]]}
    binding = {"role": "first_frame", "assets": [{"asset_id": "original_M001_tail", "kind": "image",
        "path": str(tail_path), "sha256": tail_sha}], "tail_evidence": evidence}
    compiled = shared.compile_segment_context(manifest, script, state, ["B1.S02"], media_binding=binding)
    source = {"generation_receipt_path": str(receipt_path), "generation_receipt_sha256": receipt_sha,
        "human_review_path": str(review_path)}
    return script, manifest, state, compiled, source, receipt, review


def rebuild(tmp_path, fixture, *, receipt=None, review=None):
    script, manifest, state, compiled, source, original_receipt, original_review = fixture
    receipt = receipt or deepcopy(original_receipt)
    review = review or deepcopy(original_review)
    source = deepcopy(source)
    source["generation_receipt_sha256"] = save(Path(source["generation_receipt_path"]), receipt)
    review["source_receipt_sha256"] = source["generation_receipt_sha256"]
    review_sha = save(Path(source["human_review_path"]), review)
    binding = deepcopy(compiled["media_binding"])
    binding["tail_evidence"]["human_review_sha256"] = review_sha
    compiled = shared.compile_segment_context(manifest, script, state, ["B1.S02"], media_binding=binding)
    return compiled, source


def test_bootstrap_projects_cast_costume_and_scene_into_real_payload(tmp_path):
    _, manifest, _, compiled = bootstrap_fixture(tmp_path)
    original = deepcopy(compiled)
    preview = media.compile_request_preview(compiled, compiled["prompt_fragment"], 4)
    assert preview["request"]["content"] == [{"type": "text", "text": compiled["prompt_fragment"]}]
    for actor in manifest["actors"]:
        for field in shared.PROFILE_FIELDS:
            assert actor["profile"][field]["value"] in preview["request"]["content"][0]["text"]
    assert manifest["scenes"][0]["appearance"]["value"] in preview["request"]["content"][0]["text"]
    assert preview["proof"]["bootstrap_visual_cast_approved"] is False
    assert preview["proof"]["media_status"] == "awaiting_human_review"
    assert preview["proof"]["calls_authorized"] is False and preview["new_paid_calls"] == 0
    assert compiled == original


def test_original_approved_tail_with_mapped_roles_passes_without_old_manifest_equality(tmp_path):
    _, _, _, compiled, source, receipt, _ = continuation_fixture(tmp_path)
    assert receipt["plan_snapshot"]["shared_context"]["global_manifest_sha256"] != compiled["global_manifest_sha256"]
    preview = media.compile_request_preview(compiled, compiled["prompt_fragment"], 4, original_tail_source=source)
    proof = preview["proof"]["original_tail_proof"]
    assert proof["explicit_user_tail_approval_verified"] is True
    assert proof["actor_subject_mapping_declared_by_user"] is True
    assert proof["assistant_pixel_identity_verified"] is False
    assert preview["proof"]["input_mode"] == "first_frame"
    assert preview["request"]["content"][1]["role"] == "first_frame"


@pytest.mark.parametrize("failure", ["no_evidence", "unknown", "rejected", "no_mapping", "no_subject_description", "wrong_subject", "changed_tail", "changed_video", "source_gap", "request_drop_cast"])
def test_unknown_unapproved_unmapped_or_changed_original_blocks(tmp_path, failure):
    fixture = continuation_fixture(tmp_path)
    _, _, _, compiled, source, receipt, review = fixture
    expected = ""
    if failure == "no_evidence": source = None; expected = "original saved receipt"
    elif failure == "unknown": receipt["technical_status"] = "unknown"; expected = "unknown, failed"
    elif failure == "rejected": review["decision"] = "rejected"; expected = "explicit user approval"
    elif failure == "no_mapping": review.pop("actor_subject_mapping"); expected = "subject mapping"
    elif failure == "no_subject_description": review["actor_subject_mapping"][0].pop("subject_description"); expected = "subject mapping"
    elif failure == "wrong_subject": review["actor_subject_mapping"][0]["subject_key"] = "xiaolin_subject"; expected = "subject mapping"
    elif failure == "changed_tail": Path(receipt["last_frame"]).write_bytes(b"ALTERED"); expected = "bytes changed"
    elif failure == "changed_video": Path(receipt["video_path"]).write_bytes(b"ALTERED"); expected = "bytes changed"
    elif failure == "source_gap": receipt["plan_snapshot"]["source_refs"] = ["B1.S03"]; expected = "immediate source prefix"
    elif failure == "request_drop_cast":
        receipt["request"]["content"][0]["text"] = "只有动作，没有人物身份"
        receipt["request_sha256"] = shared.digest(receipt["request"])
        expected = "complete fixed identity projection"
    if failure not in ("no_evidence", "changed_tail", "changed_video"):
        compiled, source = rebuild(tmp_path, fixture, receipt=receipt, review=review)
    with pytest.raises(ValueError, match=expected):
        media.compile_request_preview(compiled, compiled["prompt_fragment"], 4, original_tail_source=source)


def test_actual_wire_tail_changed_or_mixed_with_video_blocks(tmp_path):
    _, _, _, compiled, source, _, _ = continuation_fixture(tmp_path)
    preview = media.compile_request_preview(compiled, compiled["prompt_fragment"], 4, original_tail_source=source)
    changed = deepcopy(preview["request"])
    changed["content"][1]["image_url"]["url"] = "data:image/png;base64,YW5vdGhlciBpbWFnZQ=="
    with pytest.raises(ValueError, match="actual attachments"):
        media.validate_actual_request(compiled, changed, "ark_api", original_tail_source=source)
    changed = deepcopy(preview["request"])
    changed["content"].append({"type": "video_url", "video_url": {"url": "https://offline.invalid/video"}, "role": "reference_video"})
    with pytest.raises(ValueError, match="mutually exclusive"):
        media.validate_actual_request(compiled, changed, "ark_api", original_tail_source=source)


def trusted_fixture(tmp_path):
    script, manifest, state = provider_fixture(tmp_path)
    mode = "trusted_generated_reference"
    manifest["provider_policy"]["allowed_reference_modes"].append(mode)
    manifest["provider_policy"]["identity_reference_mode"] = mode
    video_path = tmp_path / "trusted_original_video.mp4"
    video_path.write_bytes(b"OFFLINE_TRUSTED_ORIGINAL_VIDEO_BYTES")
    url = "https://offline.invalid/provider-original.mp4"
    manifest["asset_catalog"][0].update(kind="video", path=url, sha256=media._sha_file(video_path))
    state["global_manifest_sha256"] = shared.digest(manifest)
    compiled = shared.compile_segment_context(manifest, script, state, ["B1.S01"])
    now = datetime(2026, 10, 12, tzinfo=timezone.utc)
    receipt = {"technical_status": "succeeded", "provider_account_binding_sha256": "a" * 64,
        "provider": "ark_api", "model": manifest["provider_policy"]["model"],
        "video_path": str(video_path), "video_sha256": media._sha_file(video_path), "task_id": "offline-trusted",
        "completed_at": (now - timedelta(days=1)).isoformat(), "technical_metadata": {"duration_seconds": 5},
        "final": {"id": "offline-trusted", "status": "succeeded", "content": {"video_url": url}}}
    path = tmp_path / "trusted_original_receipt.json"
    evidence = {"asset_id": "asset_main", "generation_receipt_path": str(path),
        "generation_receipt_sha256": save(path, receipt), "input_account_binding_sha256": "a" * 64,
        "input_url_expires_at": (now + timedelta(hours=1)).isoformat()}
    authorization = {"mode": "reference_video", "decision_source": "explicit_user_statement",
        "user_statement": "离线模拟专项视频参考模式批准，不是生产授权", "global_manifest_sha256": shared.digest(manifest)}
    return compiled, [evidence], authorization, now, receipt


def test_original_reference_video_needs_separate_authorization_and_known_trusted_binding(tmp_path):
    compiled, sources, authorization, now, _ = trusted_fixture(tmp_path)
    with pytest.raises(ValueError, match="separate explicit mode authorization"):
        media.compile_request_preview(compiled, compiled["prompt_fragment"], 4, trusted_video_sources=sources, now=now)
    preview = media.compile_request_preview(compiled, compiled["prompt_fragment"], 4,
        reference_mode_authorization=authorization, trusted_video_sources=sources, now=now)
    assert preview["request"]["content"][1]["role"] == "reference_video"
    assert preview["proof"]["reference_video_mode_authorized"] is True
    assert preview["proof"]["calls_authorized"] is False


@pytest.mark.parametrize("failure", ["cross_account", "other_provider", "unknown_model", "unknown", "expired", "old_original", "wrong_url"])
def test_trusted_video_unknown_expired_account_or_original_url_blocks(tmp_path, failure):
    compiled, sources, authorization, now, receipt = trusted_fixture(tmp_path)
    if failure == "cross_account": sources[0]["input_account_binding_sha256"] = "b" * 64
    elif failure == "other_provider": receipt["provider"] = "another_platform"
    elif failure == "unknown_model": receipt["model"] = "unverified-model"
    elif failure == "unknown": receipt["technical_status"] = "unknown"
    elif failure == "expired": sources[0]["input_url_expires_at"] = (now - timedelta(seconds=1)).isoformat()
    elif failure == "old_original": receipt["completed_at"] = (now - timedelta(days=31)).isoformat()
    elif failure == "wrong_url": receipt["final"]["content"]["video_url"] = "https://offline.invalid/edited-video"
    sources[0]["generation_receipt_sha256"] = save(Path(sources[0]["generation_receipt_path"]), receipt)
    with pytest.raises(ValueError):
        media.compile_request_preview(compiled, compiled["prompt_fragment"], 4,
            reference_mode_authorization=authorization, trusted_video_sources=sources, now=now)
