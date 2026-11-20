from __future__ import annotations

import json

import httpx

from src.content_factory.seedance_client import SeedanceClient, SeedanceConfig
from src.services.provider_call_ledger import ProviderCallLedger, backfill_receipts


def test_seedance_client_records_one_sanitized_call(tmp_path):
    polls = 0

    def handler(request):
        nonlocal polls
        if request.method == "POST":
            return httpx.Response(200, json={"id": "cgt-ledger-1"})
        polls += 1
        return httpx.Response(
            200,
            json={
                "id": "cgt-ledger-1",
                "status": "succeeded",
                "model": "doubao-seedance-test",
                "usage": {"completion_tokens": 321},
            },
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    ledger_path = tmp_path / "calls.sqlite3"
    client = SeedanceClient(
        SeedanceConfig(
            api_key="secret-key",
            model="doubao-seedance-test",
        ),
        http_client=http,
        ledger_path=ledger_path,
    )
    request = client.build_task_payload(
        "这段完整提示词不能进入调用总账",
        duration=4,
    )
    created = client.create_task(request)
    client.wait_for_task(created["id"], timeout_seconds=1, poll_interval_seconds=0)
    client.close()
    http.close()

    rows = ProviderCallLedger(ledger_path).list_calls()
    assert len(rows) == 1
    assert rows[0]["task_id"] == "cgt-ledger-1"
    assert rows[0]["status"] == "succeeded"
    assert rows[0]["response_metadata"]["usage"]["completion_tokens"] == 321
    serialized = json.dumps(rows, ensure_ascii=False)
    assert "这段完整提示词" not in serialized
    assert "secret-key" not in serialized
    assert rows[0]["request_metadata"]["prompt_characters"] > 0
    assert rows[0]["request_metadata"]["prompt_sha256"]


def test_backfill_indexes_video_and_image_receipts(tmp_path):
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    video = {
        "schema": "creative_seedance_segment_receipt/v1",
        "status": "succeeded",
        "provider": "ark_api",
        "request": {
            "model": "doubao-seedance-2-0-mini",
            "duration": 5,
            "content": [{"type": "text", "text": "private video prompt"}],
        },
        "task_id": "cgt-old-1",
        "final": {
            "id": "cgt-old-1",
            "status": "succeeded",
            "model": "doubao-seedance-2-0-mini",
            "usage": {"completion_tokens": 100},
        },
        "created_at": "2026-09-01T00:00:00+00:00",
    }
    image = {
        "schema": "ark_visual_asset_receipt/v1",
        "status": "downloaded",
        "model": "doubao-seedream-5-0-pro",
        "size": "1440x2560",
        "request_sha256": "abc",
        "prompt_sha256": "def",
        "api_calls": 1,
        "usage": {"output_tokens": 20},
        "submitted_at": "2026-09-02T00:00:00+00:00",
    }
    video_dir = receipts / "video"
    image_dir = receipts / "image"
    video_dir.mkdir()
    image_dir.mkdir()
    (video_dir / "receipt.json").write_text(json.dumps(video), encoding="utf-8")
    (image_dir / "receipt.json").write_text(json.dumps(image), encoding="utf-8")
    (receipts / "unrelated.json").write_text("{}", encoding="utf-8")

    ledger = ProviderCallLedger(tmp_path / "calls.sqlite3")
    result = backfill_receipts(ledger, [receipts])
    rows = ledger.list_calls()

    assert result["imported"] == 2
    assert len(rows) == 2
    assert {row["operation"] for row in rows} == {
        "video_generation",
        "image_generation",
    }
    assert ledger.summary()["total_logged_tokens"] == 120
    assert "private video prompt" not in json.dumps(rows, ensure_ascii=False)


def test_backfill_accepts_legacy_dreamina_shot_receipt(tmp_path):
    receipt = {
        "shot": "S01",
        "status": "downloaded",
        "created_at": "2026-09-07T00:00:00+00:00",
        "prompt": "legacy private prompt",
        "model": "seedance2.5",
        "resolution": "480p",
        "aspect": "9:16",
        "duration": 6,
        "provider": "dreamina_cli",
        "submit_id": "legacy-submit-1",
        "cost_credits": 72,
        "latest_response": {
            "submit_id": "legacy-submit-1",
            "gen_status": "success",
            "credit_count": 72,
        },
    }
    source = tmp_path / "S01.json"
    source.write_text(json.dumps(receipt), encoding="utf-8")
    ledger = ProviderCallLedger(tmp_path / "calls.sqlite3")

    result = backfill_receipts(ledger, [tmp_path])
    rows = ledger.list_calls()

    assert result["imported"] == 1
    assert rows[0]["provider"] == "dreamina_cli"
    assert rows[0]["model"] == "dreamina-seedance-2-5-260628"
    assert rows[0]["task_id"] == "legacy-submit-1"
    assert rows[0]["response_metadata"]["cost_credits"] == 72
    assert "legacy private prompt" not in json.dumps(rows, ensure_ascii=False)


def test_failed_submission_is_recorded(tmp_path):
    def handler(_):
        return httpx.Response(400, json={"error": {"code": "bad", "message": "rejected"}})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    ledger_path = tmp_path / "calls.sqlite3"
    client = SeedanceClient(
        SeedanceConfig(api_key="secret"),
        http_client=http,
        ledger_path=ledger_path,
    )
    request = client.build_task_payload("prompt", duration=4)
    try:
        client.create_task(request)
    except Exception:
        pass
    finally:
        client.close()
        http.close()

    rows = ProviderCallLedger(ledger_path).list_calls()
    assert len(rows) == 1
    assert rows[0]["status"] == "request_rejected"
    assert rows[0]["http_status"] == 400
    assert rows[0]["error_code"] == "bad"
