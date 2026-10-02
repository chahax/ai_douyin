from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from src.content_factory.seedance_client import (
    DEFAULT_MODEL,
    ARK_BASE_URL, ARK_MINI_MODEL,
    SeedanceAPIError,
    SeedanceClient,
    SeedanceConfig,
    SeedanceReference,
    load_prompt_pack_segment,
)
from src.services.seedance_usage_service import summarize_seedance_usage


def test_build_seedance_25_payload() -> None:
    client = SeedanceClient(SeedanceConfig(api_key="test-key"))
    try:
        payload = client.build_task_payload(
            "生成一段竖屏剧情短片",
            duration=4,
            ratio="9:16",
            resolution="720p",
            generate_audio=True,
            seed=42,
            references=[
                SeedanceReference(
                    "image",
                    "https://assets.example/reference.png",
                    "reference_image",
                )
            ],
        )
    finally:
        client.close()

    assert payload["model"] == DEFAULT_MODEL
    assert payload["duration"] == 4
    assert payload["ratio"] == "9:16"
    assert payload["resolution"] == "720p"
    assert payload["generate_audio"] is True
    assert payload["return_last_frame"] is True
    assert payload["content"][0] == {
        "type": "text",
        "text": "生成一段竖屏剧情短片",
    }
    assert payload["content"][1]["role"] == "reference_image"


def test_reference_rejects_local_video_path() -> None:
    with pytest.raises(ValueError, match="public URL"):
        SeedanceReference("video", r"D:\clips\reference.mp4", "reference_video").to_content()


@pytest.mark.parametrize("duration", [3, 31])
def test_seedance_25_rejects_invalid_duration(duration: int) -> None:
    client = SeedanceClient(SeedanceConfig(api_key="test-key"))
    try:
        with pytest.raises(ValueError, match="between 4 and 30"):
            client.build_task_payload("prompt", duration=duration)
    finally:
        client.close()


def test_create_poll_and_download_without_leaking_api_key(tmp_path: Path) -> None:
    polls = 0
    api_authorizations: list[str] = []
    download_authorization: str | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal polls, download_authorization
        if request.url.host == "cdn.example":
            download_authorization = request.headers.get("Authorization")
            return httpx.Response(200, content=b"fake-mp4")
        api_authorizations.append(request.headers.get("Authorization", ""))
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["model"] == DEFAULT_MODEL
            return httpx.Response(200, json={"id": "lsd-test-001"})
        polls += 1
        if polls == 1:
            return httpx.Response(
                200,
                json={"id": "lsd-test-001", "status": "running"},
            )
        return httpx.Response(
            200,
            json={
                "id": "lsd-test-001",
                "status": "succeeded",
                "content": {"video_url": "https://cdn.example/output.mp4?signature=x"},
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = SeedanceClient(
        SeedanceConfig(api_key="secret-key", poll_interval_seconds=0),
        http_client=http_client,
    )
    payload = client.build_task_payload("prompt", duration=4)
    created = client.create_task(payload)
    final = client.wait_for_task(
        created["id"],
        timeout_seconds=2,
        poll_interval_seconds=0,
    )
    output = client.download_video(final, tmp_path / "result.mp4")
    http_client.close()

    assert created["id"] == "lsd-test-001"
    assert final["status"] == "succeeded"
    assert output.read_bytes() == b"fake-mp4"
    assert api_authorizations == ["Bearer secret-key"] * 3
    assert download_authorization is None


def test_wait_raises_on_failed_task() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "lsd-failed",
                "status": "failed",
                "error": {"message": "moderation rejected"},
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = SeedanceClient(
        SeedanceConfig(api_key="secret-key"),
        http_client=http_client,
    )
    with pytest.raises(SeedanceAPIError, match="moderation rejected"):
        client.wait_for_task(
            "lsd-failed",
            timeout_seconds=1,
            poll_interval_seconds=0,
        )
    http_client.close()


def test_load_prompt_pack_segment_rounds_up_to_api_minimum() -> None:
    pack = {
        "schema": "analysis_video_prompt_pack/v1",
        "segments": [
            {
                "id": "segment-S01",
                "source": {"shot_number": "S01"},
                "generation": {"duration_seconds": 3.85},
                "prompts": {"video_prompt_zh": "生成视频"},
            }
        ],
    }

    segment, prompt, duration = load_prompt_pack_segment(pack, "s01")

    assert segment["id"] == "segment-S01"
    assert prompt == "生成视频"
    assert duration == 4


def test_default_payload_is_vertical_480p() -> None:
    client = SeedanceClient(SeedanceConfig(api_key="test-key"))
    try:
        payload = client.build_task_payload("prompt", duration=4)
    finally:
        client.close()

    assert payload["ratio"] == "9:16"
    assert payload["resolution"] == "480p"


def test_ark_mini_uses_separate_credentials_and_default_480p(monkeypatch):
    monkeypatch.setenv('ARK_API_KEY','ark-test-secret')
    monkeypatch.setenv('SEEDANCE_API_KEY','byteplus-test-secret')
    config=SeedanceConfig.from_env('ark_api')
    assert config.api_key=='ark-test-secret'
    assert config.base_url==ARK_BASE_URL and config.model==ARK_MINI_MODEL
    assert 'ark-test-secret' not in repr(config)
    with SeedanceClient(config) as client:
        payload=client.build_task_payload('双人隔桌对坐',duration=6)
        assert payload['resolution']=='480p' and payload['generate_audio'] is True
        assert payload['model']==ARK_MINI_MODEL
        with pytest.raises(ValueError,match='between 4 and 15'):
            client.build_task_payload('prompt',duration=16)
    preview=SeedanceConfig.from_env('ark_api',require_key=False)
    assert preview.api_key=='dry-run' and preview.model==config.model


def test_ark_usage_does_not_apply_byteplus_dollar_rates_or_file_mtime(tmp_path):
    report={'schema':'seedance_generation_report/v1','provider':'ark_api','mode':'submit',
            'request':{'model':ARK_MINI_MODEL,'duration':6,'resolution':'480p'},
            'created':{'id':'cgt-test'},'final':{'id':'cgt-test','status':'succeeded',
                'usage':{'completion_tokens':9000},'updated_at':datetime.now(timezone.utc).timestamp()}}
    (tmp_path/'test.seedance.json').write_text(json.dumps(report),encoding='utf-8')
    summary=summarize_seedance_usage(tmp_path,provider='ark_api')
    assert summary['summary']['estimated_spend_usd'] is None
    assert summary['summary']['completion_tokens']==9000
    assert summary['tasks'][0]['estimated_cost_usd'] is None
    assert summary['tasks'][0]['updated_at'].endswith('+08:00')
    del report['final']['updated_at']
    (tmp_path/'test.seedance.json').write_text(json.dumps(report),encoding='utf-8')
    assert summarize_seedance_usage(tmp_path,provider='ark_api')['tasks'][0]['updated_at']=='未记录'


def test_prompt_pack_preview_cannot_erase_existing_paid_receipt(tmp_path):
    from scripts.seedance_generate import main
    pack={'schema':'analysis_video_prompt_pack/v1','segments':[{'id':'segment-S01',
          'source':{'shot_number':'S01'},'generation':{'duration_seconds':6},
          'prompts':{'video_prompt_zh':'双人隔桌对坐'}}]}
    source=tmp_path/'pack.json';source.write_text(json.dumps(pack),encoding='utf-8')
    receipt=tmp_path/'segment-S01.seedance.json'
    original=json.dumps({'mode':'submit','created':{'id':'cgt-existing'}})
    receipt.write_text(original,encoding='utf-8')
    with pytest.raises(RuntimeError,match='receipt already exists'):
        main([str(source),'--segment','S01','--provider','ark_api','--output-dir',str(tmp_path)])
    assert receipt.read_text(encoding='utf-8')==original


def test_usage_dashboard_summary_tracks_local_remaining_budget(tmp_path: Path) -> None:
    success = {
        "schema": "seedance_generation_report/v1",
        "mode": "submit",
        "segment_id": "segment-S01",
        "request": {
            "model": DEFAULT_MODEL,
            "resolution": "480p",
            "ratio": "9:16",
            "duration": 4,
            "generate_audio": True,
            "content": [{"type": "text", "text": "prompt"}],
        },
        "created": {"id": "lsd-success"},
        "final": {
            "id": "lsd-success",
            "model": DEFAULT_MODEL,
            "status": "succeeded",
            "resolution": "480p",
            "ratio": "9:16",
            "duration": 4,
            "generate_audio": True,
            "updated_at": int(datetime.now(timezone.utc).timestamp()),
            "usage": {"completion_tokens": 1234},
        },
    }
    dry_run = {
        "schema": "seedance_generation_report/v1",
        "mode": "dry-run",
        "segment_id": "segment-S02",
        "request": {
            "model": DEFAULT_MODEL,
            "resolution": "480p",
            "ratio": "9:16",
            "duration": 4,
            "generate_audio": True,
            "content": [{"type": "text", "text": "prompt"}],
        },
    }
    (tmp_path / "success.seedance.json").write_text(
        json.dumps(success), encoding="utf-8"
    )
    (tmp_path / "dry.seedance.json").write_text(
        json.dumps(dry_run), encoding="utf-8"
    )

    usage = summarize_seedance_usage(
        tmp_path,
        monthly_budget_usd=10,
        monthly_quota_seconds=100,
        usd_per_second_480p=0.2056,
    )

    assert usage["summary"]["report_count"] == 2
    assert usage["summary"]["succeeded_count"] == 1
    assert usage["summary"]["dry_run_count"] == 1
    assert usage["summary"]["generated_seconds"] == 4
    assert usage["summary"]["estimated_spend_usd"] == 0.8224
    assert usage["summary"]["remaining_budget_usd"] == 9.1776
    assert usage["summary"]["remaining_quota_seconds"] == 96
    assert usage["platform_quota"]["authoritative_balance_available"] is False

    assert summarize_seedance_usage(
        tmp_path, provider="dreamina_cli"
    )["summary"]["report_count"] == 0
    assert summarize_seedance_usage(
        tmp_path, provider="byteplus_api"
    )["summary"]["report_count"] == 2
