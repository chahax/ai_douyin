from __future__ import annotations

import json
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

    assert analysis.status == "completed"
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
    first = service.analyze(requests)
    second = service.analyze(requests)

    assert first.degraded_count == 2
    assert first.cached_count == 0
    assert second.cached_count == 2
    stored = repository.list_content_analyses(
        account_uuid=requests[0].account_profile.account_uuid
    )
    assert len(stored) == 2
    assert stored[0].relevance is not None
    assert stored[0].evidence[0].channel == "title"
    assert TREND_SCHEMA_VERSION == 4


def test_local_batch_failure_can_degrade_to_metadata(tmp_path) -> None:
    repository = TrendRepository(tmp_path / "trend.db")
    service = ContentAnalysisBatchService(repository)
    request = _request()
    request.media_access_mode = "local_media_authorized"

    result = service.analyze(
        [request],
        implementation_id="local_qwen_paraformer",
        allow_metadata_fallback=True,
    )

    assert result.degraded_count == 1
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
    video.write_bytes(b"fixture-video")
    commands: list[list[str]] = []

    def run(command: list[str]) -> None:
        commands.append(command)
        if command[0] == "ffmpeg" and "%04d" in command[-1]:
            frame = Path(command[-1].replace("%04d", "0001"))
            frame.parent.mkdir(parents=True, exist_ok=True)
            frame.write_bytes(b"jpg")
        elif command[0] == "ffmpeg":
            Path(command[-1]).write_bytes(b"wav")
        elif "analyze_video_frames_qwen.py" in command[1]:
            Path(command[3]).write_text(
                json.dumps({"answer": {"summary": "法律口播"}}, ensure_ascii=False),
                encoding="utf-8",
            )
        elif "transcribe_video_local.py" in command[1]:
            Path(command[3]).write_text(
                json.dumps({"result": [{"text": "债务证据"}]}, ensure_ascii=False),
                encoding="utf-8",
            )

    request = _request()
    request.media_access_mode = "local_media_authorized"
    request.local_video_path = str(video)
    toolchain = LocalContentToolchain(
        project_root=project_root,
        output_root=tmp_path / "analysis",
        command_runner=run,
    )
    prepared = toolchain.prepare_request(request)

    assert len(commands) == 4
    assert Path(prepared.qwen_analysis_path).is_file()
    assert Path(prepared.transcript_path).is_file()
    analysis = LocalQwenParaformerProvider().analyze(prepared)
    assert analysis.status == "completed"
