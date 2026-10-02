from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from src.trend_intelligence.models import TrendObservation
from pathlib import Path

import pytest

from src.operations_accounts import AccountProfile, stable_account_uuid
from src.trend_intelligence.content_analysis import (
    ContentAnalysisBatchService,
    ContentAnalysisProviderRegistry,
    ContentAnalysisRequest,
    LocalContentToolchain,
    LocalQwenParaformerProvider,
    MetadataContentAnalysisProvider,
)
from src.trend_intelligence.repository import TREND_SCHEMA_VERSION, TrendRepository


def _profile(domain: str) -> AccountProfile:
    key = f"content_{domain}"
    return AccountProfile(
        account_uuid=stable_account_uuid(key),
        account_key=key,
        domain_strategy_id=domain,
        seed_keywords=["婚姻", "债务"] if domain == "legal_services" else ["重生", "复仇"],
        service_scope=["离婚咨询"] if domain == "legal_services" else ["小说推文"],
        target_audiences=["已婚人群"] if domain == "legal_services" else ["爽文读者"],
        negative_keywords=["赌博"],
        domain_config=(
            {"practice_areas": ["婚姻", "债务"]}
            if domain == "legal_services"
            else {"genres": ["重生", "复仇"]}
        ),
    )


def _request(
    domain: str = "legal_services",
    *,
    item_id: str = "douyin:101",
    title: str = "律师告诉你：夫妻共同债务怎么留证据？",
) -> ContentAnalysisRequest:
    return ContentAnalysisRequest(
        item_id=item_id,
        video_id=item_id.rsplit(":", 1)[-1],
        title=title,
        author="测试账号",
        hashtags=["婚姻", "债务"] if domain == "legal_services" else ["重生", "复仇"],
        raw_text=title,
        account_profile=_profile(domain),
    )


def test_metadata_provider_outputs_explainable_legal_relevance_and_format() -> None:
    analysis = MetadataContentAnalysisProvider().analyze(_request())
    assert analysis.status == "degraded"
    assert analysis.presentation_type == "talking_head"
    assert analysis.hook_type == "question"
    assert analysis.relevance is not None
    assert analysis.relevance.score >= 80
    assert "婚姻" in analysis.relevance.matched_seed_keywords
    assert any(item.channel == "title" for item in analysis.evidence)
    assert analysis.uncertainties


def test_metadata_provider_classifies_novel_story_independently() -> None:
    analysis = MetadataContentAnalysisProvider().analyze(
        _request(
            "novel_promotion",
            title="重生后妹妹抢走未婚夫，直到订婚宴真相反转",
        )
    )
    assert analysis.presentation_type == "story_drama"
    assert analysis.hook_type in {"contrast", "conflict"}
    assert analysis.relevance.score >= 80
    assert "追更" in analysis.user_intents


def test_metadata_request_rejects_hidden_local_artifacts() -> None:
    with pytest.raises(ValueError, match="metadata_only"):
        ContentAnalysisRequest(
            item_id="x",
            video_id="",
            title="x",
            author="",
            account_profile=_profile("legal_services"),
            qwen_analysis_path="secret.json",
        )


def test_local_provider_parses_qwen_paraformer_and_scene_evidence(tmp_path) -> None:
    qwen_path = tmp_path / "qwen.json"
    transcript_path = tmp_path / "transcript.json"
    scenes_path = tmp_path / "scenes.json"
    qwen_path.write_text(
        json.dumps(
            {
                "schema": "local_qwen_frame_analysis/v1",
                "answer": json.dumps(
                    {
                        "summary": "律师口播并展示转账记录，解释夫妻债务证据。",
                        "content_category": "法律科普",
                        "visual_timeline": [
                            {"time": "约0秒", "event": "人物提出共同债务问题"},
                            {"time": "约5秒", "event": "画面放大转账与聊天记录"},
                        ],
                        "visible_text": ["婚后借钱不一定共同偿还"],
                        "editing_style": ["快节奏字幕", "口播与录屏混合"],
                        "hook_and_retention": ["他背着你借钱，你也得还吗？"],
                        "uncertainties": ["无法确认个案事实"],
                    },
                    ensure_ascii=False,
                ),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    transcript_path.write_text(
        json.dumps(
            {"result": [{"text": "夫妻共同债务要看共同意思表示和家庭用途。"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    scenes_path.write_text(
        json.dumps(
            {
                "scenes": [
                    {"start": 0, "end": 5, "asr_text": "夫妻共同债务怎么认定"},
                    {"start": 5, "end": 10, "asr_text": "先保留转账和聊天证据"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    request = _request()
    request.media_access_mode = "local_media_authorized"
    request.qwen_analysis_path = str(qwen_path)
    request.transcript_path = str(transcript_path)
    request.scene_alignment_path = str(scenes_path)

    analysis = LocalQwenParaformerProvider().analyze(request)

    assert analysis.status == "degraded"  # Legacy JSON has no original-media provenance.
    assert analysis.media_evidence["visual"]["status"] == "unverified"
    assert analysis.presentation_type == "mixed"
    assert analysis.pacing == "fast"
    assert analysis.transcript_summary.startswith("夫妻共同债务")
    assert len(analysis.segments) == 2
    assert any(
        item.channel == "asr" and item.start_seconds == 5
        for item in analysis.evidence
    )
    assert analysis.relevance.score >= 80


def test_local_provider_requires_explicit_media_authorization(tmp_path) -> None:
    qwen = tmp_path / "qwen.json"
    qwen.write_text("{}", encoding="utf-8")
    request = _request()
    request.media_access_mode = "local_media_authorized"
    request.qwen_analysis_path = str(qwen)
    request.media_access_mode = "metadata_only"
    with pytest.raises(PermissionError, match="local_media_authorized"):
        LocalQwenParaformerProvider().analyze(request)


def test_batch_service_caches_results_and_round_trips_nested_evidence(tmp_path) -> None:
    repository = TrendRepository(tmp_path / "trend.db")
    service = ContentAnalysisBatchService(repository)
    requests = [
        _request(item_id="douyin:1"),
        _request(item_id="douyin:2", title="婚后债务怎么认定？律师解读"),
    ]
    requests = _qualified_requests(repository, requests)
    first = service.analyze(requests)
    second = service.analyze(requests)

    assert first.degraded_count == 20
    assert first.cached_count == 0
    assert second.cached_count == 20
    stored = repository.list_content_analyses(
        account_uuid=requests[0].account_profile.account_uuid
    )
    assert len(stored) == 20
    assert stored[0].relevance is not None
    assert stored[0].evidence[0].channel == "title"
    assert TREND_SCHEMA_VERSION >= 4


def test_local_batch_failure_can_degrade_to_metadata(tmp_path) -> None:
    repository = TrendRepository(tmp_path / "trend.db")
    service = ContentAnalysisBatchService(repository)
    request = _request()
    request.media_access_mode = "local_media_authorized"

    result = service.analyze(
        _qualified_requests(repository, [request]),
        implementation_id="local_qwen_paraformer",
        allow_metadata_fallback=True,
    )

    assert result.degraded_count == 20
    assert result.failed_count == 0
    assert result.errors and "requires a Qwen or transcript artifact" in result.errors[0]
    assert result.analyses[0].provider_id == "metadata_heuristic"


def test_batch_rejects_cross_account_requests(tmp_path) -> None:
    service = ContentAnalysisBatchService(TrendRepository(tmp_path / "trend.db"))
    with pytest.raises(ValueError, match="one account"):
        service.analyze([_request(), _request("novel_promotion")])


def test_registry_supports_manual_implementation_switch() -> None:
    registry = ContentAnalysisProviderRegistry()
    registry.register(MetadataContentAnalysisProvider())
    registry.register(LocalQwenParaformerProvider())
    assert [item.provider_id for item in registry.list_available()] == [
        "local_qwen_paraformer",
        "metadata_heuristic",
    ]
    with pytest.raises(KeyError, match="unknown"):
        registry.get("missing")


def test_local_toolchain_invokes_existing_scripts_with_isolated_outputs(tmp_path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    video = tmp_path / "video.mp4"
    _make_video(video)
    commands: list[list[str]] = []

    def run(command: list[str]) -> None:
        commands.append(command)
        _fake_model_command(command)

    request = _request()
    request.media_access_mode = "local_media_authorized"
    request.local_video_path = str(video)
    toolchain = LocalContentToolchain(
        project_root=project_root,
        output_root=tmp_path / "analysis",
        command_runner=run,
    )
    prepared = toolchain.prepare_request(request)

    assert len(commands) == 1  # No audio stream: probe verifies absence, ASR is not fabricated.
    assert Path(prepared.qwen_analysis_path).is_file()
    assert Path(prepared.transcript_path).is_file()
    analysis = LocalQwenParaformerProvider().analyze(prepared)
    assert analysis.status == "completed"
    assert analysis.media_evidence["audio"]["status"] == "verified_no_speech"
    assert analysis.media_evidence["audio"]["prosody_status"] == "not_analyzed"
    assert analysis.media_evidence["visual"]["analyzed_frame_count"] >= 4
    assert toolchain.prepare_request(request).qwen_analysis_path == prepared.qwen_analysis_path
    assert len(commands) == 1


def _make_video(path, *, audio=False):
    command = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64:r=4:d=2"]
    if audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "aac"]
    command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(command, check=True, capture_output=True)


def _fake_model_command(command):
    from src.trend_intelligence.content_analysis.artifacts import read_json, write_json, sha256, transcript_evidence
    if command[0] == "ffmpeg":
        subprocess.run(command, check=True, capture_output=True)
        return
    if "transcribe_video_local.py" in command[1]:
        write_json(command[3], {"schema": "local_video_transcript/v1",
                               "result": [{"text": "测试", "timestamp": [[200, 400], [400, 800]]}]})
        return
    assert "analyze_video_frames_qwen.py" in command[1]
    manifest_path = command[command.index("--frame-manifest") + 1]
    transcript_path = command[command.index("--transcript") + 1]
    manifest = read_json(manifest_path)
    evidence = [{"id": f["id"], "channel": "visual", "start_seconds": f["time_seconds"],
                 "end_seconds": f["time_seconds"], "text": "红色画面"} for f in manifest["frames"]]
    asr = transcript_evidence(read_json(transcript_path))
    evidence.extend(asr)
    expression = {"schema": "video_expression_analysis/v1", "core_message": {"text": "红色画面示例", "evidence_ids": ["V0001"]},
                  "expression_modes": [{"mode": "text_cards", "evidence_ids": ["V0001"]}],
                  "visual_expression": [{"text": "固定画面", "evidence_ids": ["V0001"]}],
                  "audio_expression": [{"text": "测试文字", "evidence_ids": ["A0001"]}] if asr else [],
                  "conflict": {"status": "not_observed"}, "evidence": evidence}
    write_json(command[3], {"schema": "local_qwen_frame_analysis/v2", "source_video_sha256": manifest["source_video_sha256"],
              "frame_manifest_path": manifest_path, "frame_manifest_sha256": sha256(manifest_path),
              "analyzed_frame_ids": [f["id"] for f in manifest["frames"]], "transcript_sha256": sha256(transcript_path),
              "batches": [{"observations": [{"frame_id": f["id"], "event": "红色画面"} for f in manifest["frames"]]}],
              "answer": {"summary": "红色画面示例", "expression_analysis": expression}})


def _local_request(video):
    request = _request()
    request.media_access_mode = "local_media_authorized"
    request.local_video_path = str(video)
    return request


def test_real_extraction_tracks_first_last_timestamps_and_audio_scope(tmp_path):
    video = tmp_path / "speech.mp4"
    _make_video(video, audio=True)
    prepared = LocalContentToolchain(output_root=tmp_path / "out", command_runner=_fake_model_command).prepare_request(_local_request(video))
    analysis = LocalQwenParaformerProvider().analyze(prepared)
    assert analysis.status == "completed"
    assert analysis.media_evidence["visual"]["sample_times_seconds"] == [0.0, .75, 1.5, 1.75]
    assert analysis.media_evidence["audio"]["status"] == "transcribed"
    assert analysis.media_evidence["audio"]["coverage_end_seconds"] == 2
    assert analysis.media_evidence["audio"]["lip_sync_status"] == "not_analyzed"
    assert analysis.expression_analysis["evidence"][-1]["start_seconds"] == .2


def test_frame_tampering_is_rejected_and_cached_attempt_is_not_reused(tmp_path):
    from src.trend_intelligence.content_analysis.artifacts import read_json
    video = tmp_path / "video.mp4"
    _make_video(video)
    toolchain = LocalContentToolchain(output_root=tmp_path / "out", command_runner=_fake_model_command)
    request = _local_request(video)
    first = toolchain.prepare_request(request)
    qwen = read_json(first.qwen_analysis_path)
    manifest = read_json(qwen["frame_manifest_path"])
    Path(manifest["frames"][0]["path"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="sampled frame changed"):
        LocalQwenParaformerProvider().analyze(first)
    assert toolchain.prepare_request(request).qwen_analysis_path != first.qwen_analysis_path


def test_same_size_source_change_invalidates_content_cache(tmp_path):
    video = tmp_path / "video.mp4"
    _make_video(video)
    toolchain = LocalContentToolchain(output_root=tmp_path / "out", command_runner=_fake_model_command)
    request = _local_request(video)
    first = toolchain.prepare_request(request)
    original = video.read_bytes()
    assert b"Lavf" in original
    changed = original.replace(b"Lavf", b"Lavx")
    assert len(changed) == len(original)
    video.write_bytes(changed)
    assert toolchain.prepare_request(request).qwen_analysis_path != first.qwen_analysis_path


def test_empty_asr_does_not_claim_no_speech_or_write_completed_cache(tmp_path):
    video = tmp_path / "sound.mp4"
    _make_video(video, audio=True)
    def runner(command):
        if "transcribe_video_local.py" in command[1]:
            Path(command[3]).write_text('{"result": []}', encoding="utf-8")
        else:
            _fake_model_command(command)
    with pytest.raises(ValueError, match="empty ASR is not verified"):
        LocalContentToolchain(output_root=tmp_path / "out", command_runner=runner).prepare_request(_local_request(video))
    assert not list((tmp_path / "out").rglob("completed.json"))
    assert list((tmp_path / "out").rglob("failed.json"))


def test_malformed_visual_answer_is_not_a_successful_summary(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"answer": "this is an unfinished model answer"}), encoding="utf-8")
    request = _request()
    request.media_access_mode = "local_media_authorized"
    request.qwen_analysis_path = str(path)
    with pytest.raises(ValueError):
        LocalQwenParaformerProvider().analyze(request)


def test_local_batch_failure_defaults_to_fail_closed(tmp_path):
    repository = TrendRepository(tmp_path / "trend.db")
    result = ContentAnalysisBatchService(repository).analyze(
        _qualified_requests(repository, [_request()]), implementation_id="local_qwen_paraformer")
    assert result.failed_count == 20
    assert result.degraded_count == 0
    assert not result.analyses


def test_asr_evidence_uses_real_pauses_and_does_not_guess_mixed_word_alignment():
    from src.trend_intelligence.content_analysis.artifacts import transcript_evidence
    rows = transcript_evidence({"result": [{"text": "你 得 还 钱 我 不 还", "timestamp":
        [[100, 200], [200, 300], [300, 400], [400, 500], [1000, 1100], [1100, 1200], [1200, 1300]]}]})
    assert [(row["text"], row["start_seconds"], row["end_seconds"]) for row in rows] == [
        ("你得还钱", .1, .5), ("我不还", 1.0, 1.3)]
    uncertain = transcript_evidence({"result": [{"text": "hello world，合同", "timestamp": [[100, 200]]}]})
    assert len(uncertain) == 1
    assert uncertain[0]["text"] == "hello world，合同"


@pytest.mark.parametrize("mutation", ["frame_time", "frame_text", "asr_text", "asr_time", "extra_asr"])
def test_expression_cannot_self_certify_forged_media_evidence(tmp_path, mutation):
    from src.trend_intelligence.content_analysis.artifacts import read_json, write_json
    video = tmp_path / "sound.mp4"
    _make_video(video, audio=True)
    prepared = LocalContentToolchain(output_root=tmp_path / "out", command_runner=_fake_model_command).prepare_request(_local_request(video))
    payload = read_json(prepared.qwen_analysis_path)
    evidence = payload["answer"]["expression_analysis"]["evidence"]
    visual = next(item for item in evidence if item["channel"] == "visual")
    audio = next(item for item in evidence if item["channel"] == "asr")
    if mutation == "frame_time":
        visual["end_seconds"] += .1
    elif mutation == "frame_text":
        visual["text"] = "不存在的争抢文件动作"
    elif mutation == "asr_text":
        audio["text"] = "不存在的威胁对白"
    elif mutation == "asr_time":
        audio["start_seconds"] += .1
    else:
        evidence.append({**audio, "id": "A9999"})
    write_json(prepared.qwen_analysis_path, payload)
    with pytest.raises(ValueError, match="evidence|observation"):
        LocalQwenParaformerProvider().analyze(prepared)


def test_bound_semantic_rejection_cannot_be_overridden_by_editing_review_or_moving_artifact(tmp_path):
    from src.trend_intelligence.content_analysis.artifacts import require_no_semantic_rejection, sha256, write_json
    qwen = tmp_path / "qwen.json"
    qwen.write_text('{"answer": "rejected candidate"}', encoding="utf-8")
    registry = tmp_path / "rejections"
    require_no_semantic_rejection(qwen, rejection_root=registry)  # Unreviewed is not rejected.
    review_path = tmp_path / "semantic_review.json"
    review = {"schema": "source_expression_semantic_review/v1", "artifact_sha256": sha256(qwen), "decision": "failed"}
    write_json(review_path, review)
    with pytest.raises(ValueError, match="known semantic failure"):
        require_no_semantic_rejection(qwen, rejection_root=registry)
    write_json(review_path, {**review, "decision": "passed"})
    with pytest.raises(ValueError, match="known semantic failure"):
        require_no_semantic_rejection(qwen, rejection_root=registry)
    copy = tmp_path / "moved" / "qwen.json"
    copy.parent.mkdir()
    copy.write_bytes(qwen.read_bytes())
    with pytest.raises(ValueError, match="known semantic failure"):
        require_no_semantic_rejection(copy, rejection_root=registry)
    qwen.write_text('{"answer": "new independent candidate"}', encoding="utf-8")
    require_no_semantic_rejection(qwen, rejection_root=registry)


def test_provider_rejects_known_semantic_failure_before_using_model_summary(tmp_path):
    from src.trend_intelligence.content_analysis.artifacts import read_json, sha256, write_json
    video = tmp_path / "video.mp4"
    _make_video(video)
    prepared = LocalContentToolchain(output_root=tmp_path / "out", command_runner=_fake_model_command).prepare_request(_local_request(video))
    qwen = Path(prepared.qwen_analysis_path)
    write_json(qwen.with_name("semantic_review.json"), {"schema": "source_expression_semantic_review/v1",
               "artifact_sha256": sha256(qwen), "decision": "failed", "blocked_for_script_generation": True})
    with pytest.raises(ValueError, match="known semantic failure"):
        LocalQwenParaformerProvider().analyze(prepared)


def _qualified_requests(repository, seed):
    requests = [replace(seed[i % len(seed)], item_id=f"douyin:{i}", video_id=str(i)) for i in range(20)]
    repository.save_collection([
        TrendObservation(item_id=r.item_id, video_id=r.video_id, url="", title=r.title,
            author=r.author, keyword=("婚姻" if i % 2 else "债务"), sort_key="latest",
            sort_label="latest", rank=i+1, metric_kind="views", metric_value=50_000)
        for i, r in enumerate(requests)
    ], provider="fixture", keywords=["婚姻", "债务"], account_uuid=requests[0].account_profile.account_uuid)
    return requests
