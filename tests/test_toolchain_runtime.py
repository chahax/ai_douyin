"""Observable local processing without model calls or elapsed-time completion guesses."""
from __future__ import annotations

import subprocess
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest

from src.trend_intelligence.content_analysis import toolchain as runtime
from src.trend_intelligence.content_analysis.artifacts import read_json, write_json


def test_live_logs_and_frame_progress_are_visible_before_process_exit(tmp_path):
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import pathlib, sys, time\n"
        "print('真实观测', flush=True)\n"
        "print('diagnostic before exit', file=sys.stderr, flush=True)\n"
        "print('Observed 999/6 frames', flush=True)\n"
        "print('Observed 3/99 frames', flush=True)\n"
        "print('Observed 3/6 frames', flush=True)\n"
        "print('Observed 2/6 frames', flush=True)\n"
        "while not pathlib.Path(sys.argv[1]).exists(): time.sleep(0.02)\n"
        "print('Observed 6/6 frames', flush=True)\n",
        encoding="utf-8",
    )
    release, output = tmp_path / "release", tmp_path / "qwen.json"
    progress = runtime._StageProgress(tmp_path, "a" * 64)
    progress.stage("analyze_frames_and_fuse", sample_frame_count=6, analyzed_frame_count=0)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(runtime.LocalContentToolchain._run_command,
                                 [sys.executable, str(worker), str(release), str(output)], progress=progress)
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                current = read_json(progress.path)
                if current.get("analyzed_frame_count") == 3:
                    break
                if future.done():
                    future.result()
                    pytest.fail("worker exited before release")
                time.sleep(.05)
            else:
                pytest.fail("flushed progress was not visible during execution")
            assert not future.done()
            assert "真实观测" in output.with_suffix(".stdout.log").read_text(encoding="utf-8")
            assert "before exit" in output.with_suffix(".stderr.log").read_text(encoding="utf-8")
            assert current["status"] == "running"
            assert "completed_at" not in current
            assert current["semantic_review_status"] == "not_performed"
        finally:
            release.touch()
        future.result(timeout=10)
    current = read_json(progress.path)
    assert current["analyzed_frame_count"] == 6
    assert current["status"] == "running"  # Subprocess exit is not evidence validation.


def test_timeout_kills_own_child_and_preserves_partial_logs(tmp_path, monkeypatch):
    worker = tmp_path / "timeout_worker.py"
    worker.write_text("import sys, time\nprint('partial', flush=True)\n"
                      "print('diagnostic', file=sys.stderr, flush=True)\ntime.sleep(30)\n", encoding="utf-8")
    output = tmp_path / "result.json"
    children = []
    original_popen = subprocess.Popen

    def track_child(*args, **kwargs):
        child = original_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(runtime.subprocess, "Popen", track_child)
    monkeypatch.setattr(runtime, "_command_timeout", lambda *args, **kwargs: 1.5)
    with pytest.raises(subprocess.TimeoutExpired):
        runtime.LocalContentToolchain._run_command([sys.executable, str(worker), "input", str(output)])
    assert len(children) == 1 and children[0].poll() is not None
    assert output.with_suffix(".stdout.log").read_text(encoding="utf-8").strip() == "partial"
    assert output.with_suffix(".stderr.log").read_text(encoding="utf-8").strip() == "diagnostic"


def test_nonzero_child_preserves_error_without_loading_entire_log(tmp_path):
    worker = tmp_path / "failure_worker.py"
    worker.write_text("import sys\nprint('x' * 20000, file=sys.stderr)\n"
                      "print('specific failure', file=sys.stderr)\nsys.exit(7)\n", encoding="utf-8")
    output = tmp_path / "result.json"
    with pytest.raises(RuntimeError, match="specific failure") as failure:
        runtime.LocalContentToolchain._run_command([sys.executable, str(worker), "input", str(output)])
    assert len(str(failure.value)) < 2600
    assert output.with_suffix(".stderr.log").stat().st_size > 20000


def test_model_timeouts_scale_with_actual_frame_count_and_audio_duration(tmp_path):
    manifest = tmp_path / "frame_manifest.json"
    command = [sys.executable, "analyze_video_frames_qwen.py", "frames", "output", "--frame-manifest", str(manifest)]
    write_json(manifest, {"frames": [{}] * 20})
    assert runtime._command_timeout(command) == 1200
    write_json(manifest, {"frames": [{}] * 900})
    assert runtime._command_timeout(command) == 6 * 3600
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(1)
        stream.writeframes(b"\x00\x00" * 1800)
    assert runtime._command_timeout([sys.executable, "transcribe_video_local.py", str(audio), "output"]) == 3900


def test_successful_injected_runner_records_stages_but_never_semantic_approval(tmp_path):
    from test_content_analysis_pipeline import _make_video, _fake_model_command, _local_request

    video = tmp_path / "source.mp4"
    _make_video(video)
    service = runtime.LocalContentToolchain(output_root=tmp_path / "out", command_runner=_fake_model_command)
    prepared = service.prepare_request(_local_request(video))
    progress = read_json(Path(prepared.qwen_analysis_path).with_name("stage_progress.json"))
    assert progress["status"] == "completed"
    assert progress["artifact_validation_status"] == "passed"
    assert progress["semantic_review_status"] == "not_performed"
    assert progress["analyzed_frame_count"] == progress["sample_frame_count"] >= 4
    assert [stage["name"] for stage in progress["stages"]] == [
        "probe", "extract_frames", "analyze_frames_and_fuse", "validate_evidence"]
    assert all(stage["status"] == "completed" and stage["completed_at"] for stage in progress["stages"])
    assert datetime.fromisoformat(progress["completed_at"]) >= datetime.fromisoformat(progress["started_at"])
    assert datetime.fromisoformat(progress["completed_at"]).utcoffset().total_seconds() == 0


def test_failed_runner_records_failure_without_a_completed_cache(tmp_path):
    from test_content_analysis_pipeline import _make_video, _local_request

    video = tmp_path / "source.mp4"
    _make_video(video)

    def fail(command):
        raise RuntimeError("model inference failed")

    with pytest.raises(RuntimeError, match="model inference failed"):
        runtime.LocalContentToolchain(output_root=tmp_path / "out", command_runner=fail).prepare_request(_local_request(video))
    progress = read_json(next((tmp_path / "out").rglob("stage_progress.json")))
    assert progress["status"] == "failed"
    assert progress["stage"] == "analyze_frames_and_fuse"
    assert progress["stages"][-1]["status"] == "failed"
    assert progress["error_type"] == "RuntimeError"
    assert "completed_at" not in progress
    assert not list((tmp_path / "out").rglob("completed.json"))
