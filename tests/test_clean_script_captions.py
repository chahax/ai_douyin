"""Synthetic-only overlay checks; these fixtures are never media approvals."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from scripts import render_clean_script_captions as captions


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _asr(text):
    # Fabricated timing for synthetic tests, not a claimed transcription of audio.
    count = sum(c.isalnum() for c in text)
    return [{"text": text, "timestamp": [[100 + i * 100, 180 + i * 100] for i in range(count)]}]


@pytest.mark.parametrize("heard", ["测试未完成。", "测试完成完成。", "测试。"])
def test_captions_cannot_replace_missing_extra_or_wrong_spoken_words(heard):
    with pytest.raises(ValueError, match="actual dialogue mismatch"):
        captions.caption_cues("测试完成。", _asr(heard), 5)


@pytest.mark.parametrize("written,heard", [("4.2万", "42万"), ("-42元", "42元"), ("40%", "40")])
def test_numeric_meaning_is_not_removed_as_punctuation(written, heard):
    with pytest.raises(ValueError, match="numeric dialogue mismatch"):
        captions.caption_cues(written, _asr(heard), 5)


@pytest.mark.parametrize("stamps", [
    [[-1, 80], [100, 180]],
    [[100, 100], [200, 280]],
    [[100, 280], [200, 380]],
    [[100, 180], [200, 1002]],
])
def test_unordered_empty_or_out_of_clip_timing_is_rejected(stamps):
    with pytest.raises(ValueError, match="outside this clip or unordered"):
        captions.caption_cues("测试", [{"text": "测试", "timestamp": stamps}], 1)


def test_cues_keep_exact_script_text_and_nonoverlapping_measured_time():
    dialogue = "先等一下，这份金额还没核对清楚。核完再约。"
    result = _asr(dialogue)
    cues = captions.caption_cues(dialogue, result, 5)
    assert "".join(cue["text"] for cue in cues) == dialogue
    assert len(cues) > 1
    assert all(0 <= cue["start"] < cue["end"] <= 5 for cue in cues)
    assert all(left["end"] <= right["start"] for left, right in zip(cues, cues[1:]))


def _command(*args):
    return subprocess.check_output(list(args), stderr=subprocess.PIPE)


@pytest.fixture(scope="module")
def synthetic_seed(tmp_path_factory):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Local ffmpeg/ffprobe are required for the synthetic integration check")
    folder = tmp_path_factory.mktemp("synthetic_caption_seed")
    video = folder / "S01.mp4"
    # Intentionally uneven frame spacing makes preserving PTS meaningful.
    _command("ffmpeg", "-v", "error", "-n", "-f", "lavfi", "-i",
             "color=c=gray:s=160x288:r=24:d=1", "-f", "lavfi", "-i",
             "sine=frequency=440:sample_rate=48000:duration=1", "-vf",
             "select='not(eq(mod(n,3),1))'", "-fps_mode", "vfr", "-c:v",
             "libx264", "-bf", "0", "-pix_fmt", "yuv420p", "-video_track_timescale",
             "24000", "-c:a", "aac", str(video))
    script_sha = hashlib.sha256(b"synthetic locked script fixture").hexdigest()
    packet_path = captions.build_review_packet(folder, video, _sha(video), script_sha)
    packet = _read(packet_path)
    # A separate original tail is deliberately retained outside rendered output.
    tail = folder / "S01.last_frame.png"
    shutil.copyfile(packet_path.parent / packet["frames"][-1]["file"], tail)
    return folder, script_sha


@pytest.fixture
def run_fixture(tmp_path, monkeypatch, synthetic_seed):
    seed, script_sha = synthetic_seed
    folder = tmp_path / "run"
    shutil.copytree(seed, folder)
    video = folder / "S01.mp4"
    packet_path = next((folder / "review_packets").rglob("packet.json"))
    packet = _read(packet_path)
    packet["source_video"] = str(video)
    _write(packet_path, packet)
    record = {"status": "downloaded", "local_video": str(video),
              "video_sha256": _sha(video), "review_packet": str(packet_path)}
    _write(folder / "S01.json", record)
    transcript_path = folder / "synthetic_transcript.json"
    _write(transcript_path, {"audio": str(packet_path.parent / packet["audio"]),
                            "result": _asr("测试完成。"),
                            "fixture_only": "Synthetic sine tone; no speech recognition or media approval claimed"})
    review_path = folder / "synthetic_caption_review.json"
    _write(review_path, {"source_sha256": record["video_sha256"],
                         "native_caption_free": True, "caption_area_clear": True,
                         "notes": "Synthetic flat gray lavfi input contains no native lettering; test fixture only",
                         "evidence": [str((packet_path.parent / packet["frames"][0]["file"]).relative_to(folder))]})
    manifest = {"script_sha256": script_sha}
    script = {"shots": [{"shot_id": "S01", "dialogue": "测试完成。"}]}
    # Authentication of real locked scripts is outside this synthetic renderer test.
    monkeypatch.setattr(captions, "locked", lambda actual: (manifest, script))
    return folder, video, packet_path, transcript_path, review_path


def _video_packet_times(path):
    value = json.loads(_command("ffprobe", "-v", "error", "-select_streams", "v:0",
                               "-show_packets", "-show_streams", "-show_entries",
                               "stream=time_base:packet=pts", "-of", "json", str(path)))
    base = Fraction(value["streams"][0]["time_base"])
    return sorted(int(packet["pts"]) * base for packet in value["packets"])


def _audio_bytes(path):
    return _command("ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
                    "-c:a", "copy", "-f", "data", "pipe:1")


def test_full_synthetic_render_keeps_audio_pts_and_raw_tail_without_a_box(run_fixture):
    folder, source, packet_path, transcript, review = run_fixture
    record_before = (folder / "S01.json").read_bytes()
    original_sha, tail_sha = _sha(source), _sha(folder / "S01.last_frame.png")
    before_pts = _video_packet_times(source)
    assert len({right - left for left, right in zip(before_pts, before_pts[1:])}) > 1

    report = captions.render(folder, "S01", transcript, review)
    rendered = Path(report["video"])
    assert _audio_bytes(rendered) == _audio_bytes(source)
    assert _video_packet_times(rendered) == before_pts
    assert _sha(source) == original_sha
    assert _sha(folder / "S01.last_frame.png") == tail_sha
    assert (folder / "S01.json").read_bytes() == record_before
    assert report["status"] == "candidate_pending_review"
    assert report["media_review"] == "pending"
    assert report["raw_tail_replaced"] is False
    assert report["video_generation_submitted"] is False
    assert report["external_audio_uploaded"] is False
    rendered_packet = _read(Path(report["review_packet"]))
    assert rendered_packet["source_sha256"] == _sha(rendered)
    assert rendered_packet["review_status"] == "pending"
    assert rendered_packet["automated_visual_or_voice_verdict"] is False

    ass = rendered.with_suffix(".ass").read_text(encoding="utf-8-sig")
    style_format = next(line for line in ass.splitlines() if line.startswith("Format: Name,"))
    style_line = next(line for line in ass.splitlines() if line.startswith("Style: "))
    style = dict(zip((key.strip() for key in style_format.removeprefix("Format: ").split(",")),
                     style_line.removeprefix("Style: ").split(",")))
    assert style["PrimaryColour"] == "&H00FFFFFF"
    assert style["BackColour"].startswith("&HFF")
    assert style["BorderStyle"] == "1"  # outline, never ASS opaque-box style 3
    assert 0 < float(style["Outline"]) <= 2
    assert "\\p1" not in ass and "\\clip" not in ass
    assert all("\\pos(80,245)" in line for line in ass.splitlines() if line.startswith("Dialogue:"))
    with pytest.raises(FileExistsError, match="Preserve the existing caption attempt"):
        captions.render(folder, "S01", transcript, review)


@pytest.mark.parametrize("failure", ["native_text", "packet_outside", "audio_outside", "wrong_source", "wrong_script", "audio_changed"])
def test_caption_permission_and_original_audio_binding_are_required(run_fixture, failure):
    folder, video, packet_path, transcript, review = run_fixture
    packet = _read(packet_path)
    if failure == "native_text":
        value = _read(review)
        value["native_caption_free"] = False
        _write(review, value)
    elif failure == "packet_outside":
        outside = folder.parent / "outside_packet.json"
        shutil.copyfile(packet_path, outside)
        record = _read(folder / "S01.json")
        record["review_packet"] = str(outside)
        _write(folder / "S01.json", record)
    elif failure == "audio_outside":
        outside = folder / "outside_audio.wav"
        shutil.copyfile(packet_path.parent / packet["audio"], outside)
        packet["audio"] = str(outside)
        packet["evidence"].append({"file": str(outside), "sha256": _sha(outside)})
        _write(packet_path, packet)
        value = _read(transcript)
        value["audio"] = str(outside)
        _write(transcript, value)
    elif failure == "wrong_source":
        packet["source_video"] = str(folder / "different_original.mp4")
        _write(packet_path, packet)
    elif failure == "wrong_script":
        packet["script_sha256"] = "0" * 64
        _write(packet_path, packet)
    elif failure == "audio_changed":
        audio = packet_path.parent / packet["audio"]
        audio.write_bytes(audio.read_bytes() + b"changed")
    with pytest.raises(ValueError):
        captions.render(folder, "S01", transcript, review)
    assert not list(folder.glob("S01.clean_captions.*"))
