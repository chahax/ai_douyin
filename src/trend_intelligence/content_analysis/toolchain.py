"""Offline local-media analysis with content-addressed, complete evidence caches."""
from __future__ import annotations

import hashlib
import gc
import json
import math
import os
import re
import subprocess
import sys
import time
import uuid
import wave
from dataclasses import replace
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .artifacts import read_json, sha256, transcript_evidence, write_json, require_no_semantic_rejection
from .base import ContentAnalysisRequest

CommandRunner = Callable[[list[str]], None]


class _StageProgress:
    """Execution observations only; completed means artifact checks, not semantic approval."""

    def __init__(self, work_dir: Path, source_sha256: str):
        self.path = work_dir / "stage_progress.json"
        self.value = {"schema": "local_content_stage_progress/v1", "status": "running",
                      "source_video_sha256": source_sha256, "started_at": _utc_now(),
                      "semantic_review_status": "not_performed", "stages": []}

    def update(self, **changes) -> None:
        self.value.update(changes)
        self.value["updated_at"] = _utc_now()
        # Windows readers can briefly deny atomic replacement while holding the
        # current status file. Retry this sharing race without truncating it.
        for attempt in range(10):
            try:
                write_json(self.path, self.value)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(.05)

    def stage(self, name: str, **changes) -> None:
        now = _utc_now()
        if self.value["stages"]:
            self.value["stages"][-1].update(status="completed", completed_at=now)
        self.value["stages"].append({"name": name, "status": "running", "started_at": now})
        self.update(stage=name, stage_started_at=now, **changes)
        print(f"Local analysis stage: {name}", flush=True)

    def finish(self, status: str, **changes) -> None:
        now = _utc_now()
        if self.value["stages"]:
            self.value["stages"][-1].update(status=status, **{f"{status}_at": now})
        self.update(status=status, **{f"{status}_at": now}, **changes)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalContentToolchain:
    def __init__(self, *, project_root: str | Path | None = None,
                 output_root: str | Path | None = None, command_runner: CommandRunner | None = None,
                 frame_interval_seconds: float = 2.0, low_memory: bool | None = None):
        self.project_root = Path(project_root or Path(__file__).resolve().parents[3]).resolve()
        # __file__: project/src/trend_intelligence/content_analysis/toolchain.py
        self.output_root = Path(output_root or self.project_root / "data/video_analysis/trend").resolve()
        self.command_runner = command_runner or self._run_command
        self._default_runner = command_runner is None
        from src.shared.config import settings
        self.low_memory = (os.environ.get("SOURCE_ANALYSIS_LOW_MEMORY", str(settings.SOURCE_ANALYSIS_LOW_MEMORY)).strip().lower() in {"1", "true", "yes"}
                           if low_memory is None else bool(low_memory))
        self.max_images = 2 if self.low_memory else 6
        self.cpu_threads = 2 if self.low_memory else None
        self.frame_interval_seconds = max(.5, min(3.0, float(frame_interval_seconds)))
        self.synthesis_provider = os.environ.get("SOURCE_EXPRESSION_SYNTHESIS_PROVIDER", settings.SOURCE_EXPRESSION_SYNTHESIS_PROVIDER)
        if self.synthesis_provider not in {"local_qwen", "configured_llm"}:
            raise ValueError("invalid SOURCE_EXPRESSION_SYNTHESIS_PROVIDER")

    def prepare_request(self, request: ContentAnalysisRequest) -> ContentAnalysisRequest:
        if self.low_memory:
            # Across CLI/web instances, only one low-memory source pipeline may
            # decode or load ASR/Qwen at a time. OS locks vanish on process exit.
            with _single_local_job(self.project_root / "data/video_analysis/local_low_memory.lock"):
                return self._prepare_request(request)
        return self._prepare_request(request)

    def _prepare_request(self, request: ContentAnalysisRequest) -> ContentAnalysisRequest:
        if request.media_access_mode != "local_media_authorized":
            raise PermissionError("toolchain requires local_media_authorized")
        video = Path(request.local_video_path).resolve()
        if not video.is_file():
            raise FileNotFoundError(video)
        video_hash = sha256(video)
        hotwords = " ".join(request.account_profile.matching_terms()[:50])
        parameters = {
            "schema": "local_content_toolchain/v2", "source_sha256": video_hash,
            "resource_mode": "low_memory" if self.low_memory else "standard",
            "max_images": self.max_images, "cpu_threads": self.cpu_threads,
            "decoder_threads": 1 if self.low_memory else None,
            "interval_seconds": self.frame_interval_seconds, "scene_difference_threshold": .22,
            "visual_script_sha256": sha256(self.project_root / "scripts/analyze_video_frames_qwen.py"),
            "asr_script_sha256": sha256(self.project_root / "scripts/transcribe_video_local.py"),
            "toolchain_sha256": sha256(Path(__file__)),
            "evidence_adapter_sha256": sha256(Path(__file__).with_name("artifacts.py")),
            "hierarchical_synthesis_sha256": sha256(Path(__file__).with_name("hierarchical.py")),
            "synthesis_provider": self.synthesis_provider,
            "text_synthesis_sha256": sha256(Path(__file__).with_name("text_synthesis.py")),
            "model_manifest_sha256": (sha256(self.project_root / ".local_models/video_analysis/manifest.json")
                                      if (self.project_root / ".local_models/video_analysis/manifest.json").is_file() else None),
            "hotword": hotwords, "punctuation": False,
        }
        identity = hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest()[:24]
        cache_dir = (self.output_root / identity).resolve()
        if not cache_dir.is_relative_to(self.output_root):
            raise ValueError("analysis output escaped configured output root")
        pointer = cache_dir / "completed.json"
        if pointer.is_file():
            cached = read_json(pointer)
            artifacts = cached.get("artifacts") or []
            if cached.get("parameters") == parameters and artifacts and all(
                Path(item["path"]).is_file() and sha256(item["path"]) == item["sha256"] for item in artifacts
            ):
                require_no_semantic_rejection(cached["qwen_analysis_path"])
                return replace(request, duration_seconds=cached["duration_seconds"],
                               qwen_analysis_path=cached["qwen_analysis_path"],
                               transcript_path=cached["transcript_path"])
        work_dir = cache_dir / f"attempt_{uuid.uuid4().hex[:12]}"
        work_dir.mkdir(parents=True, exist_ok=True)
        write_json(work_dir / "request.json", {"parameters": parameters, "source_video_path": str(video),
                   "started_at": datetime.now(timezone.utc).isoformat()})
        progress = _StageProgress(work_dir, video_hash)
        try:
            progress.update(resource_mode=parameters["resource_mode"], max_images=self.max_images,
                            cpu_threads=self.cpu_threads, decoder_threads=parameters["decoder_threads"])
            progress.stage("probe")
            probe = _probe(video)
            duration = float(probe["format"]["duration"])
            progress.stage("extract_frames", duration_seconds=duration)
            frame_manifest = extract_frames(video, work_dir / "frames", duration, self.frame_interval_seconds,
                                            progress_callback=lambda **counts: progress.update(**counts),
                                            low_memory=self.low_memory)
            frame_manifest_path = work_dir / "frame_manifest.json"
            write_json(frame_manifest_path, frame_manifest)
            progress.update(sample_frame_count=len(frame_manifest["frames"]),
                            decoded_frame_count=frame_manifest["decoded_frame_count"])
            audio, transcript, qwen = work_dir / "audio.wav", work_dir / "transcript.json", work_dir / "qwen.json"
            has_audio = any(stream.get("codec_type") == "audio" for stream in probe.get("streams") or [])
            audio_status, reason = "transcribed", "local Paraformer recognized timestamped speech; acoustic interpretation not performed"
            if has_audio:
                progress.stage("extract_audio")
                audio_command = ["ffmpeg", "-y", "-v", "error"]
                if self.low_memory:
                    audio_command.extend(["-threads", "1"])
                audio_command.extend(["-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(audio)])
                self._execute(audio_command, progress)
                silent, audio_duration = _silent_pcm(audio)
                if audio_duration < duration - .25:
                    raise ValueError("audio extraction does not cover the video duration")
                if silent:
                    audio_status, reason = "verified_no_speech", "all samples in extracted full PCM audio are zero"
                    write_json(transcript, {"schema": "local_video_transcript/v1", "result": []})
                else:
                    command = [sys.executable, str(self.project_root / "scripts/transcribe_video_local.py"),
                               str(audio), str(transcript), "--without-punctuation"]
                    if hotwords:
                        command.extend(["--hotword", hotwords])
                    progress.stage("transcribe_audio")
                    self._execute(command, progress)
                    if not transcript_evidence(read_json(transcript)):
                        raise ValueError("ASR returned no timestamped speech; empty ASR is not verified no-speech")
            else:
                audio_status, reason = "verified_no_speech", "ffprobe verified that the source video has no audio stream"
                write_json(transcript, {"schema": "local_video_transcript/v1", "result": []})
            payload = read_json(transcript)
            payload["provenance"] = {
                "schema": "local_audio_evidence/v2", "source_video_sha256": video_hash,
                "audio_path": str(audio) if has_audio else "", "audio_sha256": sha256(audio) if has_audio else "",
                "coverage_start_seconds": 0.0, "coverage_end_seconds": duration,
                "status": audio_status, "status_reason": reason, "source_probe": probe,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
            write_json(transcript, payload)
            del payload
            if self.low_memory:
                # ASR is already a waited-and-exited child. Only lightweight
                # metadata is retained in this parent before Qwen starts.
                gc.collect()
            progress.stage("analyze_frames_and_fuse", analyzed_frame_count=0, audio_status=audio_status)
            visual_command = [sys.executable, str(self.project_root / "scripts/analyze_video_frames_qwen.py"),
                                 str(work_dir / "frames"), str(qwen), "--frame-manifest", str(frame_manifest_path),
                                 "--transcript", str(transcript), "--interval-seconds", str(self.frame_interval_seconds),
                                 "--synthesis-provider", self.synthesis_provider,
                                 "--max-images", str(self.max_images)]
            if self.low_memory:
                visual_command.append("--low-memory")
            self._execute(visual_command, progress)
            progress.stage("validate_evidence")
            visual = read_json(qwen)
            if (visual.get("schema") != "local_qwen_frame_analysis/v2" or
                    visual.get("source_video_sha256") != video_hash or
                    visual.get("transcript_sha256") != sha256(transcript) or
                    set(visual.get("analyzed_frame_ids") or []) != {item["id"] for item in frame_manifest["frames"]}):
                raise ValueError("visual analysis did not verify all source-bound sampled frames and transcript")
            prepared = replace(request, duration_seconds=duration, qwen_analysis_path=str(qwen), transcript_path=str(transcript))
            from .local import LocalQwenParaformerProvider
            from src.trend_intelligence.media_evidence import media_readiness
            readiness = media_readiness(LocalQwenParaformerProvider().analyze(prepared))
            if not readiness["ready"]:
                raise ValueError("source-media analysis incomplete: " + "; ".join(readiness["reasons"]))
            tracked = [qwen, transcript, frame_manifest_path, *[Path(item["path"]) for item in frame_manifest["frames"]]]
            if has_audio:
                tracked.append(audio)
            write_json(pointer, {"parameters": parameters, "duration_seconds": duration,
                       "qwen_analysis_path": str(qwen), "transcript_path": str(transcript),
                       "artifacts": [{"path": str(path), "sha256": sha256(path)} for path in tracked],
                       "completed_at": datetime.now(timezone.utc).isoformat()})
            progress.finish("completed", analyzed_frame_count=len(visual["analyzed_frame_ids"]),
                            artifact_validation_status="passed")
            return prepared
        except Exception as exc:
            progress.finish("failed", error_type=type(exc).__name__)
            write_json(work_dir / "failed.json", {"status": "failed", "error": f"{type(exc).__name__}: {exc}",
                       "source_video_sha256": video_hash, "failed_at": datetime.now(timezone.utc).isoformat()})
            raise

    def _execute(self, command: list[str], progress: _StageProgress) -> None:
        if self._default_runner:
            self._run_command(command, progress=progress, low_memory=self.low_memory)
        else:
            # Keep the injectable runner's longstanding one-argument contract.
            self.command_runner(command)

    @staticmethod
    def _run_command(command: list[str], *, progress: _StageProgress | None = None,
                     low_memory: bool = False) -> None:
        timeout = _command_timeout(command, duration_seconds=(progress.value.get("duration_seconds") if progress else None))
        output = Path(command[3]) if len(command) > 3 and command[1].endswith(".py") else Path(command[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        stdout_path, stderr_path = output.with_suffix(".stdout.log"), output.with_suffix(".stderr.log")
        if progress:
            progress.update(command_timeout_seconds=timeout, command_started_at=_utc_now(),
                            stdout_log_path=str(stdout_path), stderr_log_path=str(stderr_path))
        environment = _subprocess_environment(low_memory=low_memory)
        # Direct OS file handles avoid pipe deadlocks and preserve logs immediately,
        # including on timeout or failed model inference. No entire-log buffering.
        with stdout_path.open("wb", buffering=0) as stdout, stderr_path.open("wb", buffering=0) as stderr:
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=environment)
            started = time.monotonic()
            cursor, pending = 0, b""
            try:
                while True:
                    remaining = timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, timeout)
                    try:
                        returncode = process.wait(timeout=min(1.0, remaining))
                    except subprocess.TimeoutExpired:
                        returncode = None
                    cursor, pending = _read_frame_progress(stdout_path, cursor, pending, progress)
                    if returncode is not None:
                        break
            except BaseException:
                process.kill()
                process.wait()
                _read_frame_progress(stdout_path, cursor, pending, progress)
                raise
        if returncode:
            with stderr_path.open("rb") as stream:
                stream.seek(max(0, stderr_path.stat().st_size - 10000))
                error = stream.read().decode("utf-8", errors="replace")[-2500:]
            raise RuntimeError(f"local tool {Path(command[0]).name} failed: {error}")


def _subprocess_environment(*, low_memory: bool = False) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["SOURCE_ANALYSIS_LOW_MEMORY"] = "1" if low_memory else "0"
    if low_memory:
        for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            environment[key] = "2"
        environment["SOURCE_ANALYSIS_CPU_THREADS"] = "2"
        environment["TOKENIZERS_PARALLELISM"] = "false"
        environment["OMP_WAIT_POLICY"] = "PASSIVE"
    return environment


@contextmanager
def _single_local_job(lock_path: Path):
    """Serialize low-memory pipelines with an OS lock, never a stale PID/mtime flag."""
    import errno
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        if os.name == "nt":
            import msvcrt

            def acquire():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

            def release():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def acquire():
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            def release():
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        last_notice = None
        while True:
            try:
                acquire()
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                if last_notice is None or time.monotonic() - last_notice >= 30:
                    print("Low-memory analysis waiting for the current local source job to release memory", flush=True)
                    last_notice = time.monotonic()
                time.sleep(1)
        try:
            yield
        finally:
            release()


def _command_timeout(command: list[str], *, duration_seconds: float | None = None) -> float:
    """Budget actual sampled work, with a finite six-hour maximum per model process."""
    script = Path(command[1]).name if len(command) > 1 else ""
    if script == "analyze_video_frames_qwen.py" and "--frame-manifest" in command:
        manifest = read_json(command[command.index("--frame-manifest") + 1])
        return min(6 * 3600, max(300, 300 + 45 * len(manifest.get("frames") or [])))
    if script == "transcribe_video_local.py":
        with wave.open(command[2], "rb") as audio:
            duration_seconds = audio.getnframes() / audio.getframerate()
    if duration_seconds is not None and math.isfinite(float(duration_seconds)):
        return min(6 * 3600, max(300, 300 + 2 * float(duration_seconds)))
    return 3600


def _read_frame_progress(path: Path, cursor: int, pending: bytes,
                         progress: _StageProgress | None) -> tuple[int, bytes]:
    if progress is None or progress.value.get("stage") != "analyze_frames_and_fuse":
        return cursor, pending
    with path.open("rb") as stream:
        stream.seek(cursor)
        while chunk := stream.read(65536):
            cursor += len(chunk)
            lines = (pending + chunk).split(b"\n")
            pending = lines.pop()[-4096:]
            for line in lines:
                match = re.fullmatch(rb"Observed ([0-9]{1,8})/([0-9]{1,8}) frames\r?", line)
                if not match:
                    continue
                count, total = map(int, match.groups())
                if total == progress.value.get("sample_frame_count") and progress.value.get("analyzed_frame_count", 0) < count <= total:
                    progress.update(analyzed_frame_count=count, last_frame_observation_at=_utc_now())
                    print(f"Local frame observations: {count}/{total}; semantic review pending", flush=True)
    return cursor, pending


def _probe(video: Path) -> dict:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(video)],
                            check=True, capture_output=True, text=True, encoding="utf-8")
    return json.loads(result.stdout)


def _silent_pcm(audio: Path) -> tuple[bool, float]:
    with wave.open(str(audio), "rb") as stream:
        frames, rate = stream.getnframes(), stream.getframerate()
        if stream.getsampwidth() != 2 or frames <= 0:
            raise ValueError("expected nonempty signed 16-bit PCM audio")
        silent = True
        for _ in range(0, frames, rate * 30):
            if any(stream.readframes(rate * 30)):
                silent = False
        return silent, frames / rate


def extract_frames(video: Path, output: Path, duration: float, interval: float, *,
                   progress_callback: Callable[..., None] | None = None, low_memory: bool = False) -> dict:
    """Decode first, last, regular samples and substantial shot changes with real PTS."""
    import cv2
    import numpy as np
    output.mkdir(parents=True, exist_ok=True)
    capture = _open_video_capture(cv2, video, low_memory=low_memory)
    if not capture.isOpened():
        capture.release()
        raise ValueError("video could not be decoded")
    fps = capture.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        capture.release()
        raise ValueError("video frame rate unavailable")
    sampling_step = min(interval, duration / 3) if duration > 0 else interval
    frames, previous_small, last_selected, index, last = [], None, -999.0, 0, None
    last_progress = time.monotonic()

    def save(frame, second: float, frame_number: int, reason: str) -> None:
        path = output / f"frame_{len(frames) + 1:05d}.jpg"
        if not cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 90]):
            raise RuntimeError("could not write decoded sample")
        frames.append({"id": f"V{len(frames) + 1:04d}", "path": str(path.resolve()), "sha256": sha256(path),
                       "time_seconds": round(second, 6), "decoded_frame_index": frame_number, "sampling_reason": reason})

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            pts = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if index and pts <= 0:
                raise ValueError("decoder did not provide media timestamps")
            small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (64, 64)).astype(np.float32)
            difference = float(np.mean(np.abs(small - previous_small)) / 255) if previous_small is not None else 0
            reason = "first" if index == 0 else "scene_change" if difference >= .22 and pts-last_selected >= .25 else "interval"
            if index == 0 or pts - last_selected >= sampling_step - .001 or reason == "scene_change":
                save(frame, pts, index, reason)
                last_selected = pts
            previous_small, last = small, (frame, pts, index)
            index += 1
            if progress_callback and time.monotonic() - last_progress >= 5:
                progress_callback(decoded_frame_count=index, sample_frame_count=len(frames),
                                  decoded_through_seconds=pts)
                last_progress = time.monotonic()
        if last is None:
            raise ValueError("video has no decoded frames")
        if frames[-1]["decoded_frame_index"] != last[2]:
            save(*last, "last")
    finally:
        capture.release()
    return {"schema": "local_video_frame_manifest/v2", "source_video_path": str(video.resolve()),
            "source_video_sha256": sha256(video), "duration_seconds": duration, "decoded_frame_count": index,
            "frame_interval_seconds": interval, "actual_max_interval_seconds": sampling_step,
            "sampling": "decoded first/last + regular intervals + pixel-change scene candidates; not continuous visual review",
            "frames": frames, "created_at": datetime.now(timezone.utc).isoformat()}


def _open_video_capture(cv2, video: Path, *, low_memory: bool):
    if not low_memory:
        return cv2.VideoCapture(str(video))
    if not hasattr(cv2, "CAP_PROP_N_THREADS"):
        raise RuntimeError("low-memory video decoding requires OpenCV CAP_PROP_N_THREADS support")
    # Restrict codec-owned frame buffers while preserving every source pixel,
    # decoded timestamp and the existing first/last/scene/interval selection.
    return cv2.VideoCapture(str(video), cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1])
