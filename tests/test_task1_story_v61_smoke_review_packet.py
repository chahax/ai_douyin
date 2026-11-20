from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image
import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/prepare_task1_story_v61_smoke_review_packet.py"


def _module():
    spec = importlib.util.spec_from_file_location("v61_smoke_packet", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_reports_staging_oserror_as_closed_json(monkeypatch, capsys) -> None:
    module = _module()
    monkeypatch.setattr(
        module, "prepare_packet",
        lambda **kwargs: (_ for _ in ()).throw(OSError("synthetic rename collision")),
    )
    assert module.main([]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False
    assert payload["human_review_completed"] is False
    assert payload["douyin_upload_allowed"] is False
    assert payload["fanqie_backfill_allowed"] is False


def _inputs(tmp_path: Path):
    module = _module()
    shots = []
    for scene_id, duration in module.gate.SHOT_DURATIONS.items():
        video = tmp_path / f"{scene_id}.mp4"
        video.write_bytes(f"{scene_id}-video".encode())
        sha = module._sha256(video)
        audio = tmp_path / f"{scene_id}.wav"
        audio.write_bytes(f"{scene_id}-dialogue-audio".encode())
        audio_sha = module._sha256(audio)
        musetalk = tmp_path / f"{scene_id}-musetalk.mp4"
        musetalk.write_bytes(f"{scene_id}-musetalk-stage".encode())
        musetalk_sha = module._sha256(musetalk)
        shots.append({
            "scene_id": scene_id,
            "assets": [{
                "scene_id": scene_id,
                "video_path": str(video),
                "duration_s": duration,
                "provider_name": "comfyui_ltx_i2v",
                "metadata": {
                    "final_sha256": sha,
                    "has_presenter": False,
                    "musetalk_used": True,
                    "dialogue_audio_path": str(audio),
                    "dialogue_audio_sha256": audio_sha,
                    "musetalk_sha256": musetalk_sha,
                    "musetalk_artifact_path": str(musetalk),
                    "per_stage_sha256": {
                        "dialogue_audio_sha256": audio_sha,
                        "musetalk_sha256": musetalk_sha,
                        "rife_sha256": sha,
                    },
                    "rife_fps": 50.0,
                },
            }],
            "missing": [],
        })
    progress = {
        "schema_version": module.gate.PROGRESS_SCHEMA,
        "task_id": 1,
        "scope": "failed_scene_smoke",
        "expected_plan_sha256": module.gate.EXPECTED_PLAN_SHA256,
        "selected_shot_ids": list(module.gate.SHOT_IDS),
        "result": "FAILED_SCENE_SMOKE_RENDERED_AWAITING_HUMAN_REVIEW",
        "finished_at": datetime.now(timezone.utc).isoformat(),
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
        "shots": shots,
    }
    progress_path = tmp_path / "progress.json"
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    template = json.loads(
        module.DEFAULT_TEMPLATE.read_text(encoding="utf-8")
    )
    template_path = tmp_path / "template.json"
    template_path.write_text(json.dumps(template, ensure_ascii=False), encoding="utf-8")
    return module, progress_path, template_path


def _fake_extract(video: Path, output: Path, timestamp: float) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 96), (30, 60, 90)).save(output)


def _fake_contact(items, output: Path) -> None:
    assert len(items) == 21
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 568), (10, 10, 10)).save(output)


def test_prepares_machine_packet_but_never_human_approval(tmp_path: Path) -> None:
    module, progress_path, template_path = _inputs(tmp_path)
    output_root = tmp_path / "packet"
    review_path = tmp_path / "review.json"
    result = module.prepare_packet(
        progress_path=progress_path,
        template_path=template_path,
        output_root=output_root,
        review_path=review_path,
        probe_video=lambda path: {
            "duration_seconds": module.gate.SHOT_DURATIONS[path.stem], "fps": 50.0,
        },
        extract_frame=_fake_extract,
        build_contact_sheet=_fake_contact,
    )
    packet = json.loads(Path(result["packet_path"]).read_text(encoding="utf-8"))
    review = json.loads(review_path.read_text(encoding="utf-8"))
    assert packet["candidate_count"] == 7
    assert all(len(item["frames"]) == 3 for item in packet["candidates"])
    assert packet["machine_gate_passed"] is True
    assert packet["human_review_completed"] is False
    assert packet["full_19_shot_generation_allowed"] is False
    assert packet["douyin_upload_allowed"] is False
    assert review["review_status"] == "pending_review"
    assert review["reviewer"] == ""
    assert review["reviewed_at"] is None
    assert "signature_path" not in review
    assert all(item["decision"] == "pending" for item in review["shots"])
    assert all(item["identity_consistent"] is None for item in review["shots"])
    assert review["machine_review_packet_sha256"] == module._sha256(Path(result["packet_path"]))


def test_refuses_to_overwrite_review_or_packet(tmp_path: Path) -> None:
    module, progress_path, template_path = _inputs(tmp_path)
    output_root = tmp_path / "packet"
    review_path = tmp_path / "review.json"
    review_path.write_text("human-work", encoding="utf-8")
    with pytest.raises(ValueError, match="Refusing to overwrite"):
        module.prepare_packet(
            progress_path=progress_path,
            template_path=template_path,
            output_root=output_root,
            review_path=review_path,
            probe_video=lambda path: {"duration_seconds": 2.0, "fps": 50.0},
            extract_frame=_fake_extract,
            build_contact_sheet=_fake_contact,
        )
    assert review_path.read_text(encoding="utf-8") == "human-work"


def test_review_link_failure_rolls_back_published_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, progress_path, template_path = _inputs(tmp_path)
    output_root = tmp_path / "packet"
    review_path = tmp_path / "review.json"
    original_link = module.os.link
    monkeypatch.setattr(
        module.os, "link",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("synthetic link failure")),
    )
    with pytest.raises(OSError, match="synthetic link failure"):
        module.prepare_packet(
            progress_path=progress_path,
            template_path=template_path,
            output_root=output_root,
            review_path=review_path,
            probe_video=lambda path: {
                "duration_seconds": module.gate.SHOT_DURATIONS[path.stem],
                "fps": 50.0,
            },
            extract_frame=_fake_extract,
            build_contact_sheet=_fake_contact,
        )
    monkeypatch.setattr(module.os, "link", original_link)
    assert not output_root.exists()
    assert not review_path.exists()


def test_cleanup_never_deletes_another_invocation_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    output_root = tmp_path / "packet"
    foreign = tmp_path / ".packet.foreign.staging"

    def fail_after_both_staging_dirs_exist(**kwargs):
        own = kwargs["staging_root"]
        own.mkdir(parents=True)
        foreign.mkdir()
        raise ValueError("simulated packet failure")

    monkeypatch.setattr(module, "_prepare_packet", fail_after_both_staging_dirs_exist)
    with pytest.raises(ValueError, match="simulated packet failure"):
        module.prepare_packet(
            progress_path=tmp_path / "progress.json",
            template_path=tmp_path / "template.json",
            output_root=output_root,
            review_path=tmp_path / "review.json",
        )
    assert foreign.is_dir()
    own_dirs = [
        path for path in tmp_path.glob(".packet.*.staging") if path != foreign
    ]
    assert own_dirs == []


def test_rejects_incomplete_render_progress_before_extracting(tmp_path: Path) -> None:
    module, progress_path, template_path = _inputs(tmp_path)
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    progress["result"] = "STATIC_VALIDATION_PASSED"
    progress["shots"] = []
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    with pytest.raises(ValueError, match="completed smoke render"):
        module.prepare_packet(
            progress_path=progress_path,
            template_path=template_path,
            output_root=tmp_path / "packet",
            review_path=tmp_path / "review.json",
            probe_video=lambda path: (_ for _ in ()).throw(AssertionError("no probe")),
            extract_frame=lambda *a: (_ for _ in ()).throw(AssertionError("no extract")),
            build_contact_sheet=lambda *a: (_ for _ in ()).throw(AssertionError("no sheet")),
        )


@pytest.mark.parametrize(
    ("metadata_key", "metadata_value", "error"),
    [
        ("has_presenter", True, "has_presenter must be false"),
        ("musetalk_used", False, "MuseTalk must be used"),
        ("dialogue_audio_sha256", "", "dialogue audio SHA is invalid"),
        ("rife_fps", 25.0, "recorded RIFE fps must be 50"),
    ],
)
def test_rejects_ineligible_candidate_before_extracting(
    tmp_path: Path, metadata_key: str, metadata_value, error: str
) -> None:
    module, progress_path, template_path = _inputs(tmp_path)
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    progress["shots"][0]["assets"][0]["metadata"][metadata_key] = metadata_value
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        module.prepare_packet(
            progress_path=progress_path,
            template_path=template_path,
            output_root=tmp_path / "packet",
            review_path=tmp_path / "review.json",
            probe_video=lambda path: {
                "duration_seconds": module.gate.SHOT_DURATIONS[path.stem],
                "fps": 50.0,
            },
            extract_frame=lambda *args: (_ for _ in ()).throw(AssertionError("no extract")),
            build_contact_sheet=lambda *args: (_ for _ in ()).throw(AssertionError("no sheet")),
        )


def test_rejects_template_with_inherited_approval_field(tmp_path: Path) -> None:
    module, progress_path, template_path = _inputs(tmp_path)
    template = json.loads(template_path.read_text(encoding="utf-8"))
    template["human_review_completed"] = True
    template_path.write_text(json.dumps(template), encoding="utf-8")
    with pytest.raises(ValueError, match="unrecognized fields"):
        module.prepare_packet(
            progress_path=progress_path,
            template_path=template_path,
            output_root=tmp_path / "packet",
            review_path=tmp_path / "review.json",
            probe_video=lambda path: {
                "duration_seconds": module.gate.SHOT_DURATIONS[path.stem], "fps": 50.0,
            },
            extract_frame=_fake_extract,
            build_contact_sheet=_fake_contact,
        )


def test_rejects_candidate_changed_during_frame_extraction(tmp_path: Path) -> None:
    module, progress_path, template_path = _inputs(tmp_path)
    changed = False

    def mutate_after_first_frame(video: Path, output: Path, timestamp: float) -> None:
        nonlocal changed
        _fake_extract(video, output, timestamp)
        if not changed:
            video.write_bytes(video.read_bytes() + b"tampered")
            changed = True

    with pytest.raises(ValueError, match="candidate changed while review evidence was prepared"):
        module.prepare_packet(
            progress_path=progress_path,
            template_path=template_path,
            output_root=tmp_path / "packet",
            review_path=tmp_path / "review.json",
            probe_video=lambda path: {
                "duration_seconds": module.gate.SHOT_DURATIONS[path.stem], "fps": 50.0,
            },
            extract_frame=mutate_after_first_frame,
            build_contact_sheet=_fake_contact,
        )


def test_rejects_musetalk_artifact_sha_mismatch(tmp_path: Path) -> None:
    module, progress_path, template_path = _inputs(tmp_path)
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    musetalk_path = Path(
        progress["shots"][0]["assets"][0]["metadata"]["musetalk_artifact_path"]
    )
    musetalk_path.write_bytes(musetalk_path.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="MuseTalk stage artifact SHA mismatch"):
        module.prepare_packet(
            progress_path=progress_path,
            template_path=template_path,
            output_root=tmp_path / "packet",
            review_path=tmp_path / "review.json",
            probe_video=lambda path: {
                "duration_seconds": module.gate.SHOT_DURATIONS[path.stem], "fps": 50.0,
            },
            extract_frame=_fake_extract,
            build_contact_sheet=_fake_contact,
        )


def test_sadtalker_packet_binds_rife_source_and_output_evidence(tmp_path: Path) -> None:
    module, progress_path, template_path = _inputs(tmp_path)
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    for shot in progress["shots"]:
        scene_id = shot["scene_id"]
        asset = shot["assets"][0]
        metadata = asset["metadata"]
        spoken = tmp_path / f"{scene_id}_sadtalker.mp4"
        audit = tmp_path / f"{scene_id}_sadtalker.audit.json"
        binding = tmp_path / f"{scene_id}_rife_binding.json"
        spoken.write_bytes(f"{scene_id}-spoken".encode())
        audit.write_text(json.dumps({"scene_id": scene_id}), encoding="utf-8")
        binding.write_text(json.dumps({
            "schema": "fanqie_sadtalker_fullframe/rife_binding/v1",
            "source_sha256": module._sha256(spoken),
            "output_sha256": metadata["final_sha256"],
            "rife_model": "rife47.pth",
            "rife_multiplier": 2,
            "delivery_fps": 50,
        }), encoding="utf-8")
        metadata.update({
            "spoken_renderer": "sadtalker_fullframe",
            "spoken_renderer_used": True,
            "sadtalker_fullframe_used": True,
            "musetalk_used": False,
            "spoken_renderer_artifact_path": str(spoken),
            "spoken_renderer_sha256": module._sha256(spoken),
            "spoken_renderer_audit_path": str(audit),
            "spoken_renderer_audit_sha256": module._sha256(audit),
            "rife_binding_path": str(binding),
            "rife_binding_sha256": module._sha256(binding),
        })
        metadata["per_stage_sha256"].update({
            "spoken_renderer_sha256": module._sha256(spoken),
            "spoken_renderer_audit_sha256": module._sha256(audit),
            "rife_binding_sha256": module._sha256(binding),
        })
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    result = module.prepare_packet(
        progress_path=progress_path,
        template_path=template_path,
        output_root=tmp_path / "packet",
        review_path=tmp_path / "review.json",
        probe_video=lambda path: {
            "duration_seconds": module.gate.SHOT_DURATIONS[path.stem], "fps": 50.0,
        },
        extract_frame=_fake_extract,
        build_contact_sheet=_fake_contact,
    )
    packet = json.loads(Path(result["packet_path"]).read_text(encoding="utf-8"))
    assert all(item["spoken_renderer"] == "sadtalker_fullframe" for item in packet["candidates"])
    assert all(Path(item["rife_binding_path"]).is_file() for item in packet["candidates"])
    assert all(
        module._sha256(Path(item["rife_binding_path"])) == item["rife_binding_sha256"]
        for item in packet["candidates"]
    )
