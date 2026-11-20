import asyncio
import json
import warnings
from dataclasses import asdict

import pytest

from src.content_factory.presenter.models import PresenterRequest, PresenterResult
from src.content_factory.presenter.script_segmenter import ScriptSegmenter
from src.content_factory.presenter_pipeline import PresenterPipeline
from src.platform_adapter.fanqie_promotion import (
    FanqiePromotionService,
    FanqiePromotionTask,
)
from src.shared import rate_limiter


CTA_ALIAS = "大秦嬴政-face"
CTA_LINE = f"想看原文，在评论区搜“{CTA_ALIAS}”。"


def _task(tmp_path, *, alias=CTA_ALIAS):
    material = tmp_path / "material.txt"
    material.write_text("测试素材", encoding="utf-8")
    return FanqiePromotionTask(
        task_id="qa_cta",
        book_name="大秦：我，嬴政！开局面壁穿越者",
        promotion_alias=alias,
        material_path=str(material),
    )


def test_generate_script_prompt_and_result_use_alias(monkeypatch, tmp_path):
    service = FanqiePromotionService(root_dir=tmp_path)
    captured = []

    def fake_chat(messages, **_kwargs):
        captured.extend(messages)
        return json.dumps({"script_content": CTA_LINE}, ensure_ascii=False)

    monkeypatch.setattr(
        "src.platform_adapter.fanqie_promotion.llm_client.chat_completion_tracked",
        fake_chat,
    )
    script = service._generate_script(_task(tmp_path))

    assert CTA_ALIAS in captured[1]["content"]
    assert CTA_ALIAS in script


@pytest.mark.parametrize("alias, expected", [(CTA_ALIAS, CTA_ALIAS), ("", "大秦：我，嬴政！开局面壁穿越者")])
def test_fallback_script_uses_alias_or_deliberate_book_fallback(tmp_path, alias, expected):
    service = FanqiePromotionService(root_dir=tmp_path)
    script = service._fallback_script(_task(tmp_path, alias=alias))

    assert f"评论区搜“{expected}”" in script


def test_default_article_cleanup_remains_unchanged():
    cleaned = PresenterPipeline()._clean_direct_article(
        "正文。请点赞收藏转发。想看原文，在评论区搜“测试”。"
    )

    assert "点赞" not in cleaned
    assert "评论区搜" not in cleaned


def test_preserve_cta_opt_in_keeps_full_alias_and_other_cleaning():
    source = "\ufeff# 标题\n正文 https://example.com 。\n" + CTA_LINE
    cleaned = PresenterPipeline()._clean_direct_article(source, preserve_cta=True)

    assert "\ufeff" not in cleaned
    assert "# 标题" not in cleaned
    assert "https://example.com" not in cleaned
    assert CTA_LINE in cleaned


def test_resolve_and_segment_preserve_cta_with_punctuation():
    request = PresenterRequest(
        text="剧情钩子。" + CTA_LINE,
        input_mode="article_direct",
        preserve_engagement_cta=True,
        max_segments=0,
    )
    resolved = PresenterPipeline()._resolve_script(request)
    joined = "".join(
        segment.text
        for segment in ScriptSegmenter(max_segments=0).split(resolved, title="测试")
    )

    assert "评论区搜" in joined
    assert CTA_ALIAS in joined


def test_generate_promo_video_enables_preserve_flag(monkeypatch, tmp_path):
    task = _task(tmp_path)
    task_file = tmp_path / "task.json"
    task_file.write_text(json.dumps(asdict(task), ensure_ascii=False), encoding="utf-8")
    captured = []

    class FakePipeline:
        def run(self, request):
            captured.append(request)
            return PresenterResult(True, "ok", work_dir=str(tmp_path))

        run_assets_preview = run

    service = FanqiePromotionService(root_dir=tmp_path / "runtime")
    monkeypatch.setattr(service, "_generate_script", lambda _task: CTA_LINE)
    monkeypatch.setattr(
        "src.platform_adapter.fanqie_promotion.PresenterPipeline",
        FakePipeline,
    )

    service.generate_promo_video(task_file=str(task_file), assets_only=True)

    assert captured[0].preserve_engagement_cta is True
    assert captured[0].input_mode == "article_direct"


def test_rate_limiter_reuses_within_same_running_loop():
    async def check():
        rate_limiter.reset_limiter()
        first = rate_limiter._get_limiter()
        second = rate_limiter._get_limiter()
        assert first is second

    asyncio.run(check())


def test_rate_limiter_recreates_across_event_loops_without_warning():
    rate_limiter.reset_limiter()

    async def get_and_acquire():
        limiter = rate_limiter._get_limiter()
        await rate_limiter.acquire(caller="fanqie_promo")
        return limiter

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        first = asyncio.run(get_and_acquire())
        second = asyncio.run(get_and_acquire())

    assert first is not second
    assert not [
        item
        for item in caught
        if issubclass(item.category, RuntimeWarning)
        and "re-used across loops" in str(item.message)
    ]


def test_reset_limiter_clears_loop_tracking():
    rate_limiter._get_limiter()
    rate_limiter.reset_limiter()

    assert rate_limiter._limiter is None
    assert rate_limiter._limiter_loop_id is None
