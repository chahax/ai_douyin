from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.services import fanqie_review_service as service


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    qa = tmp_path / "qa"
    qa.mkdir()
    database = tmp_path / "closed_loop.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY);
            INSERT INTO alembic_version VALUES('0009_publish_monitor_bind_fields');
            CREATE TABLE fanqie_promotion_tasks(id INTEGER PRIMARY KEY);
            CREATE TABLE fanqie_video_jobs(id INTEGER PRIMARY KEY);
            CREATE TABLE fanqie_reviews(id INTEGER PRIMARY KEY);
            CREATE TABLE fanqie_operation_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_uuid TEXT UNIQUE NOT NULL,
                task_id INTEGER,
                event_type TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT,
                actor_type TEXT,
                actor_id TEXT,
                payload_json TEXT,
                artifact_path TEXT,
                audit_artifact_hash TEXT,
                created_at TEXT
            );
            """
        )
    monkeypatch.setattr(service, "QA_ROOT", qa.resolve())
    monkeypatch.setattr(service, "CLOSED_LOOP_DB_PATH", database.resolve())
    return qa


def _smoke_review(
    qa: Path,
    name: str = "task1_story_v61_smoke_review.json",
    *,
    spoken_renderer: str = "musetalk_v15",
) -> Path:
    progress = qa / "progress.json"
    packet = qa / "machine_packet.json"
    contact = qa / "contact.png"
    contact.write_bytes(b"contact-sheet")
    durations = (2.8, 1.8, 1.5, 2.4, 2.0, 2.3, 1.3)
    review_shots = []
    progress_shots = []
    packet_candidates = []
    for index, (scene_id, duration) in enumerate(
        zip(service.SMOKE_SHOT_IDS, durations, strict=True), start=1
    ):
        candidate = qa / f"shot_{index}.mp4"
        candidate.write_bytes(f"video-{index}".encode())
        candidate_sha = _sha(candidate)
        checks = {key: None for key in service.SMOKE_SHOT_CHECKS}
        review_shots.append({
            "scene_id": scene_id,
            "expected_duration_seconds": duration,
            "candidate_path": str(candidate),
            "candidate_sha256": candidate_sha,
            "machine_observed_duration_seconds": duration,
            "machine_observed_fps": 50.0,
            **checks,
            "decision": "pending",
            "notes": "",
        })
        metadata = {
            "final_sha256": candidate_sha,
            "has_presenter": False,
            "musetalk_used": True,
        }
        musetalk = qa / f"shot_{index}_musetalk.mp4"
        musetalk.write_bytes(f"musetalk-{index}".encode())
        metadata.update({
            "musetalk_artifact_path": str(musetalk),
            "musetalk_sha256": _sha(musetalk),
        })
        packet_renderer = {
            "spoken_renderer": "musetalk_v15",
            "spoken_renderer_artifact_path": str(musetalk),
            "spoken_renderer_sha256": _sha(musetalk),
            "spoken_renderer_audit_path": "",
            "spoken_renderer_audit_sha256": "",
        }
        if spoken_renderer == "sadtalker_fullframe":
            spoken = qa / f"shot_{index}_sadtalker.mp4"
            spoken_audit = qa / f"shot_{index}_sadtalker.audit.json"
            rife_binding = qa / f"shot_{index}_rife_binding.json"
            spoken.write_bytes(f"spoken-{index}".encode())
            _write(spoken_audit, {"scene_id": scene_id, "passed": True})
            _write(rife_binding, {
                "schema": "fanqie_sadtalker_fullframe/rife_binding/v1",
                "source_sha256": _sha(spoken),
                "output_sha256": candidate_sha,
                "rife_model": "rife47.pth",
                "rife_multiplier": 2,
                "delivery_fps": 50,
            })
            metadata.update({
                "spoken_renderer": "sadtalker_fullframe",
                "spoken_renderer_used": True,
                "sadtalker_fullframe_used": True,
                "musetalk_used": False,
                "spoken_renderer_artifact_path": str(spoken),
                "spoken_renderer_sha256": _sha(spoken),
                "spoken_renderer_audit_path": str(spoken_audit),
                "spoken_renderer_audit_sha256": _sha(spoken_audit),
                "rife_binding_path": str(rife_binding),
                "rife_binding_sha256": _sha(rife_binding),
                "per_stage_sha256": {
                    "rife_binding_sha256": _sha(rife_binding),
                },
            })
            packet_renderer = {
                "spoken_renderer": "sadtalker_fullframe",
                "spoken_renderer_artifact_path": str(spoken),
                "spoken_renderer_sha256": _sha(spoken),
                "spoken_renderer_audit_path": str(spoken_audit),
                "spoken_renderer_audit_sha256": _sha(spoken_audit),
                "rife_binding_path": str(rife_binding),
                "rife_binding_sha256": _sha(rife_binding),
            }
        progress_shots.append({
            "scene_id": scene_id,
            "assets": [{
                "scene_id": scene_id,
                "video_path": str(candidate),
                "metadata": metadata,
            }],
        })
        packet_candidates.append({
            "scene_id": scene_id,
            "video_path": str(candidate),
            "video_sha256": candidate_sha,
            "has_presenter": False,
            **packet_renderer,
        })
    _write(progress, {
        "schema_version": "fanqie_v61_failed_smoke_progress/v1",
        "task_id": 1,
        "scope": "failed_scene_smoke",
        "expected_plan_sha256": service.EXPECTED_PLAN_SHA256,
        "selected_shot_ids": list(service.SMOKE_SHOT_IDS),
        "result": "FAILED_SCENE_SMOKE_RENDERED_AWAITING_HUMAN_REVIEW",
        "gates": {
            "static_validation_passed": True,
            "audio_prepared": True,
            "runtime_preflight_passed": True,
            "failed_scene_smoke_rendered": True,
            "human_video_approval_obtained": False,
            "matching_fanqie_task_confirmed": False,
            "publish_allowed": False,
            "fanqie_backfill_allowed": False,
        },
        "shots": progress_shots,
    })
    _write(packet, {
        "schema_version": "fanqie_v61_smoke_machine_review_packet/v2",
        "task_id": 1,
        "scope": "failed_scene_smoke",
        "plan_sha256": service.EXPECTED_PLAN_SHA256,
        "source_progress_path": str(progress),
        "source_progress_sha256": _sha(progress),
        "candidate_count": 7,
        "frames_per_candidate": 3,
        "machine_gate_passed": True,
        "human_visual_and_audio_semantic_review_required": True,
        "human_review_completed": False,
        "full_19_shot_generation_allowed": False,
        "douyin_upload_allowed": False,
        "fanqie_backfill_allowed": False,
        "contact_sheet_path": str(contact),
        "contact_sheet_sha256": _sha(contact),
        "candidates": packet_candidates,
    })
    review = qa / name
    _write(review, {
        "schema_version": "fanqie_v61_failed_smoke_human_review/v1",
        "task_id": 1,
        "scope": "failed_scene_smoke",
        "plan_sha256": service.EXPECTED_PLAN_SHA256,
        "review_status": "pending_review",
        "reviewer": "",
        "signature_path": "legacy.sig",
        "source_progress_path": str(progress),
        "reviewed_progress_sha256": _sha(progress),
        "machine_review_packet_path": str(packet),
        "machine_review_packet_sha256": _sha(packet),
        "candidate_contact_sheet": str(contact),
        "candidate_contact_sheet_sha256": _sha(contact),
        "global_gates": {key: None for key in service.SMOKE_GLOBAL_CHECKS},
        "shots": review_shots,
    })
    return review


def _full_review(qa: Path, name: str = "task1_story_v61_full_review.json") -> Path:
    candidate = qa / "full.mp4"
    contact = qa / "full_contact.png"
    packet = qa / "full_machine_packet.json"
    audit = qa / "candidate_audit.json"
    candidate.write_bytes(b"whole-video")
    contact.write_bytes(b"whole-contact")
    _write(audit, {
        "schema_version": "fanqie_v61_full_candidate_audit/v2",
        "shot_count": 19,
        "machine_composition_gate_passed": True,
        "candidate_path": str(candidate),
        "candidate_sha256": _sha(candidate),
    })
    frames = []
    for index in range(11):
        frame = qa / f"frame_{index + 1}.png"
        frame.write_bytes(f"frame-{index}".encode())
        frames.append({"path": str(frame), "sha256": _sha(frame)})
    _write(packet, {
        "schema_version": "fanqie_v61_full_machine_review_packet/v1",
        "task_id": 1,
        "scope": "full_19_beat_candidate",
        "plan_sha256": service.EXPECTED_PLAN_SHA256,
        "candidate_path": str(candidate),
        "candidate_sha256": _sha(candidate),
        "contact_sheet_path": str(contact),
        "contact_sheet_sha256": _sha(contact),
        "candidate_audit_path": str(audit),
        "candidate_audit_sha256": _sha(audit),
        "probe": {"duration_seconds": 40.8},
        "frames": frames,
        "machine_gate_passed": True,
        "human_visual_audio_editorial_review_required": True,
        "human_full_video_review_completed": False,
        "matching_fanqie_task_confirmed": False,
        "douyin_upload_allowed": False,
        "fanqie_backfill_allowed": False,
    })
    review = qa / name
    _write(review, {
        "schema_version": "fanqie_v61_full_human_review/v1",
        "task_id": 1,
        "scope": "full_19_beat_candidate",
        "plan_sha256": service.EXPECTED_PLAN_SHA256,
        "review_status": "pending_review",
        "decision": "pending",
        "candidate_path": str(candidate),
        "candidate_sha256": _sha(candidate),
        "contact_sheet_path": str(contact),
        "contact_sheet_sha256": _sha(contact),
        "machine_review_packet_path": str(packet),
        "machine_review_packet_sha256": _sha(packet),
        "checks": {key: None for key in service.FULL_REVIEW_CHECKS},
    })
    return review


def _playback(seconds: float) -> tuple[str, str]:
    finished = datetime.now(timezone.utc) - timedelta(seconds=1)
    started = finished - timedelta(seconds=seconds)
    return started.isoformat(), finished.isoformat()


def _all_confirmed(item: dict) -> dict[str, bool]:
    return {key: True for key in item["required_confirmations"]}


def _v62_partition(
    framepack_scenes: set[str], composite_scenes: set[str] | None = None
) -> tuple[list[dict], dict[str, list[str]]]:
    action_scenes = [
        "b01_boast", "b02_grab_reaction", "b03_object_question",
        "b04_confused_answer", "b05_age_burst", "b06_pull_away",
        "b07_protest", "b11_flip", "b12_car_reveal", "b16_escape", "b18_cta",
    ]
    composite_scenes = composite_scenes or set()
    stable_scenes = sorted(service.V62_STABLE_INSERT_SCENES)
    partition = {
        "local_framepack_i2v": [scene for scene in action_scenes if scene in framepack_scenes],
        "local_comfyui_ltx_i2v": [
            scene for scene in action_scenes
            if scene not in framepack_scenes and scene not in composite_scenes
        ],
        "local_composite_rife_bridge_and_ltx": [
            scene for scene in action_scenes if scene in composite_scenes
        ],
        "deterministic_camera_motion_candidate_only": stable_scenes,
    }
    renderer_by_scene = {
        scene: renderer for renderer, scenes in partition.items() for scene in scenes
    }
    rows = [
        {
            "scene_id": scene,
            "provider_metadata": {"renderer": renderer_by_scene[scene]},
        }
        for scene in action_scenes + stable_scenes
    ]
    return rows, partition


def test_v62_renderer_partition_accepts_one_framepack_replacement() -> None:
    rows, partition = _v62_partition({"b01_boast"})

    assert service._validate_v62_renderer_partition(rows, partition) == {
        "deterministic_camera_motion_candidate_only": 8,
        "local_comfyui_ltx_i2v": 10,
        "local_composite_rife_bridge_and_ltx": 0,
        "local_framepack_i2v": 1,
    }


def test_v62_renderer_partition_accepts_framepack_and_rife_bridge_composite() -> None:
    rows, partition = _v62_partition({"b01_boast"}, {"b02_grab_reaction"})

    assert service._validate_v62_renderer_partition(rows, partition) == {
        "deterministic_camera_motion_candidate_only": 8,
        "local_comfyui_ltx_i2v": 9,
        "local_composite_rife_bridge_and_ltx": 1,
        "local_framepack_i2v": 1,
    }


def test_v62_renderer_partition_rejects_cross_renderer_duplicate() -> None:
    rows, partition = _v62_partition({"b01_boast"})
    partition["local_comfyui_ltx_i2v"].append("b01_boast")

    with pytest.raises(ValueError, match="多个渲染器"):
        service._validate_v62_renderer_partition(rows, partition)


def test_v62_renderer_partition_rejects_scene_audit_mismatch() -> None:
    rows, partition = _v62_partition({"b01_boast"})
    rows[0]["provider_metadata"]["renderer"] = "local_comfyui_ltx_i2v"

    with pytest.raises(ValueError, match="镜头审计不一致"):
        service._validate_v62_renderer_partition(rows, partition)


def test_smoke_review_moves_from_pending_to_approved_and_writes_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    qa = _configure(monkeypatch, tmp_path)
    review = _smoke_review(qa)
    pending = service.list_reviews("pending_review", sync_database=True)
    assert [item["path"] for item in pending] == [str(review.resolve())]
    assert pending[0]["database_status"] == "queued"
    assert len(pending[0]["required_confirmations"]) == 17
    started, finished = _playback(15)
    result = service.decide_review(
        review, decision="approved", reviewer="operator", notes="通过",
        expected_review_sha256=pending[0]["review_sha256"],
        confirmations=_all_confirmed(pending[0]),
        playback_started_at=started, playback_finished_at=finished,
    )
    assert result["status"] == "approved"
    saved = json.loads(review.read_text(encoding="utf-8"))
    assert all(saved["global_gates"].values())
    assert saved["shots"][0]["decision"] == "approved"
    assert saved["shots"][0]["lip_sync_is_acceptable"] is True
    assert "signature_path" not in saved
    assert saved["decision_source"] == "authenticated_streamlit_frontend"
    with sqlite3.connect(service.CLOSED_LOOP_DB_PATH) as connection:
        events = connection.execute(
            "SELECT from_status, to_status, payload_json FROM fanqie_operation_events ORDER BY id"
        ).fetchall()
    assert len(events) == 2
    assert events[-1][0] is None and events[-1][1] is None
    assert json.loads(events[-1][2])["action"] == "review_approved"


def test_full_review_requires_every_check_and_real_playback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    qa = _configure(monkeypatch, tmp_path)
    review = _full_review(qa)
    item = service.list_reviews("pending_review")[0]
    started, finished = _playback(41)
    incomplete = _all_confirmed(item)
    incomplete.pop(next(iter(incomplete)))
    with pytest.raises(ValueError, match="逐项提交"):
        service.decide_review(
            review, decision="approved", reviewer="operator",
            expected_review_sha256=item["review_sha256"],
            confirmations=incomplete,
            playback_started_at=started, playback_finished_at=finished,
        )
    short_start, short_finish = _playback(5)
    with pytest.raises(ValueError, match="计时不足"):
        service.decide_review(
            review, decision="approved", reviewer="operator",
            expected_review_sha256=item["review_sha256"],
            confirmations=_all_confirmed(item),
            playback_started_at=short_start, playback_finished_at=short_finish,
        )
    service.decide_review(
        review, decision="approved", reviewer="operator",
        expected_review_sha256=item["review_sha256"],
        confirmations=_all_confirmed(item),
        playback_started_at=started, playback_finished_at=finished,
    )
    saved = json.loads(review.read_text(encoding="utf-8"))
    assert all(saved["checks"].values())
    assert saved["frontend_attestation"]["actual_playback_seconds"] == 41
    assert len(saved["frontend_attestation"]["confirmations"]) == 14


def test_empty_template_is_invalid_and_never_enters_pending_queue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    qa = _configure(monkeypatch, tmp_path)
    template = qa / "task1_story_v61_failed_smoke_review_template.json"
    _write(template, {
        "schema_version": "fanqie_v61_failed_smoke_human_review/v1",
        "review_status": "not_started",
        "machine_review_packet_path": "",
        "shots": [{"candidate_path": ""} for _ in range(7)],
    })
    assert service.list_reviews("pending_review", sync_database=True) == []
    invalid = service.list_reviews("invalid")
    assert len(invalid) == 1
    assert "task 1" in invalid[0]["validation_error"]


def test_complete_sadtalker_smoke_candidate_enters_pending_queue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    qa = _configure(monkeypatch, tmp_path)
    review = _smoke_review(qa, spoken_renderer="sadtalker_fullframe")
    pending = service.list_reviews("pending_review", sync_database=True)
    assert [item["path"] for item in pending] == [str(review.resolve())]
    assert pending[0]["database_status"] == "queued"


def test_sadtalker_packet_without_bound_audit_is_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    qa = _configure(monkeypatch, tmp_path)
    review = _smoke_review(qa, spoken_renderer="sadtalker_fullframe")
    value = json.loads(review.read_text(encoding="utf-8"))
    packet = Path(value["machine_review_packet_path"])
    packet_value = json.loads(packet.read_text(encoding="utf-8"))
    packet_value["candidates"][0]["spoken_renderer_audit_sha256"] = "0" * 64
    _write(packet, packet_value)
    value["machine_review_packet_sha256"] = _sha(packet)
    _write(review, value)
    assert service.list_reviews("pending_review") == []
    assert "SadTalker" in service.list_reviews("invalid")[0]["validation_error"]


def test_musetalk_metadata_without_bound_artifact_is_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    qa = _configure(monkeypatch, tmp_path)
    review = _smoke_review(qa)
    value = json.loads(review.read_text(encoding="utf-8"))
    progress = Path(value["source_progress_path"])
    progress_value = json.loads(progress.read_text(encoding="utf-8"))
    progress_value["shots"][0]["assets"][0]["metadata"]["musetalk_artifact_path"] = ""
    _write(progress, progress_value)
    value["reviewed_progress_sha256"] = _sha(progress)
    packet = Path(value["machine_review_packet_path"])
    packet_value = json.loads(packet.read_text(encoding="utf-8"))
    packet_value["source_progress_sha256"] = _sha(progress)
    _write(packet, packet_value)
    value["machine_review_packet_sha256"] = _sha(packet)
    _write(review, value)
    assert service.list_reviews("pending_review") == []
    assert "MuseTalk" in service.list_reviews("invalid")[0]["validation_error"]


def test_wrong_machine_schema_never_enters_pending_queue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    qa = _configure(monkeypatch, tmp_path)
    review = _smoke_review(qa)
    value = json.loads(review.read_text(encoding="utf-8"))
    packet = Path(value["machine_review_packet_path"])
    packet_value = json.loads(packet.read_text(encoding="utf-8"))
    packet_value["schema_version"] = "wrong/v1"
    _write(packet, packet_value)
    value["machine_review_packet_sha256"] = _sha(packet)
    _write(review, value)
    assert service.list_reviews("pending_review") == []
    assert "schema" in service.list_reviews("invalid")[0]["validation_error"]


def test_final_decision_cannot_be_overwritten(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    qa = _configure(monkeypatch, tmp_path)
    review = _smoke_review(qa)
    item = service.list_reviews("pending_review")[0]
    service.decide_review(
        review, decision="rejected", reviewer="operator", notes="动作不自然",
        expected_review_sha256=item["review_sha256"],
    )
    with pytest.raises(ValueError, match="不能覆盖"):
        service.decide_review(
            review, decision="rejected", reviewer="operator", notes="再次驳回",
            expected_review_sha256=_sha(review),
        )


def test_active_frontend_review_lock_blocks_second_operator(tmp_path: Path) -> None:
    review = tmp_path / "review.json"
    review.write_text("{}", encoding="utf-8")
    with service._review_lock(review):
        with pytest.raises(ValueError, match="另一位操作人"):
            with service._review_lock(review):
                raise AssertionError("second operator must not enter")


def test_abandoned_frontend_review_lock_is_reclaimed(tmp_path: Path) -> None:
    review = tmp_path / "review.json"
    review.write_text("{}", encoding="utf-8")
    lock = review.with_name(f".{review.name}.frontend-review.lock")
    _write(lock, {
        "token": "abandoned",
        "pid": max(os.getpid() + 10_000_000, 99_999_999),
        "host": service.socket.gethostname(),
        "acquired_at": "2000-01-01T00:00:00+00:00",
    })
    with service._review_lock(review):
        current = json.loads(lock.read_text(encoding="utf-8"))
        assert current["token"] != "abandoned"
        assert current["pid"] == os.getpid()
    assert not lock.exists()
    assert list(tmp_path.glob("*.abandoned")) == []


def test_stale_frontend_hash_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    qa = _configure(monkeypatch, tmp_path)
    review = _smoke_review(qa)
    stale = _sha(review)
    value = json.loads(review.read_text(encoding="utf-8"))
    value["notes"] = "另一个会话刚更新"
    _write(review, value)
    with pytest.raises(ValueError, match="已变化"):
        service.decide_review(
            review, decision="rejected", reviewer="operator", notes="驳回",
            expected_review_sha256=stale,
        )


def test_candidate_tampering_removes_item_from_pending_queue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    qa = _configure(monkeypatch, tmp_path)
    review = _full_review(qa)
    value = json.loads(review.read_text(encoding="utf-8"))
    Path(value["candidate_path"]).write_bytes(b"tampered")
    assert service.list_reviews("pending_review") == []
    assert "SHA-256" in service.list_reviews("invalid")[0]["validation_error"]


def test_db_decision_failure_restores_pending_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    qa = _configure(monkeypatch, tmp_path)
    review = _smoke_review(qa)
    original = review.read_bytes()
    original_append = service._append_event

    def fail_decision(**kwargs):
        if kwargs["action"] == "review_rejected":
            raise sqlite3.OperationalError("database locked")
        return original_append(**kwargs)

    monkeypatch.setattr(service, "_append_event", fail_decision)
    with pytest.raises(ValueError, match="数据库事件写入失败"):
        service.decide_review(
            review, decision="rejected", reviewer="operator", notes="驳回",
            expected_review_sha256=_sha(review),
        )
    assert review.read_bytes() == original


def test_final_file_without_matching_decision_event_is_audit_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    qa = _configure(monkeypatch, tmp_path)
    review = _smoke_review(qa)
    item = service.list_reviews("pending_review", sync_database=True)[0]
    service.decide_review(
        review, decision="rejected", reviewer="operator", notes="动作不自然",
        expected_review_sha256=item["review_sha256"],
    )
    with sqlite3.connect(service.CLOSED_LOOP_DB_PATH) as connection:
        connection.execute(
            "DELETE FROM fanqie_operation_events WHERE payload_json LIKE ?",
            ('%"action": "review_rejected"%',),
        )
        connection.commit()
    audit_errors = service.list_reviews("audit_error", sync_database=True)
    assert [entry["path"] for entry in audit_errors] == [str(review.resolve())]
    assert audit_errors[0]["database_status"] == "decision_event_missing"


def test_incomplete_decision_event_is_audit_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    qa = _configure(monkeypatch, tmp_path)
    review = _smoke_review(qa)
    item = service.list_reviews("pending_review", sync_database=True)[0]
    service.decide_review(
        review, decision="rejected", reviewer="operator", notes="动作不自然",
        expected_review_sha256=item["review_sha256"],
    )
    with sqlite3.connect(service.CLOSED_LOOP_DB_PATH) as connection:
        row = connection.execute(
            "SELECT id, payload_json FROM fanqie_operation_events "
            "WHERE payload_json LIKE ?",
            ('%"action": "review_rejected"%',),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[1])
        payload.pop("decision_source")
        connection.execute(
            "UPDATE fanqie_operation_events SET payload_json = ? WHERE id = ?",
            (json.dumps(payload, ensure_ascii=False, sort_keys=True), row[0]),
        )
        connection.commit()
    audit_errors = service.list_reviews("audit_error", sync_database=True)
    assert [entry["path"] for entry in audit_errors] == [str(review.resolve())]
    assert audit_errors[0]["database_status"] == "decision_event_missing"


def test_approved_artifact_tampering_becomes_audit_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    qa = _configure(monkeypatch, tmp_path)
    review = _full_review(qa)
    item = service.list_reviews("pending_review", sync_database=True)[0]
    started, finished = _playback(41)
    service.decide_review(
        review, decision="approved", reviewer="operator", notes="通过",
        expected_review_sha256=item["review_sha256"],
        confirmations=_all_confirmed(item),
        playback_started_at=started, playback_finished_at=finished,
    )
    saved = json.loads(review.read_text(encoding="utf-8"))
    Path(saved["candidate_path"]).write_bytes(b"tampered-after-approval")
    audit_errors = service.list_reviews("audit_error", sync_database=True)
    assert [entry["path"] for entry in audit_errors] == [str(review.resolve())]
    assert "SHA-256" in audit_errors[0]["validation_error"]
