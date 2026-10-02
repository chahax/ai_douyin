from __future__ import annotations

from src.content_factory.novel_visual_direction import (
    STYLE_ID,
    audit_visual_direction,
    classify_visual_style,
    enrich_storyboard_visuals,
)


def _scene(index: int) -> dict:
    speakers = {
        1: "洛雪微", 3: "林夏", 4: "洛雪微", 6: "洛雪微", 7: "林夏",
        8: "林夏", 9: "洛雪微", 10: "林夏", 11: "洛雪微", 12: "洛雪微",
        13: "洛雪微", 14: "洛雪微", 15: "洛雪微", 17: "洛雪微", 18: "洛雪微",
        19: "洛雪微", 20: "洛雪微", 21: "洛雪微", 22: "林夏", 23: "洛雪微",
    }
    speaker = speakers.get(index)
    return {
        "scene_id": index,
        "narration": "两人在停车场继续完成这段冲突。",
        "dialogue": (
            [{"speaker": speaker, "text": "测试对白", "emotion": "neutral"}]
            if speaker else []
        ),
        "first_frame_prompt": "cinematic opening frame with consistent adult characters",
        "last_frame_prompt": "cinematic closing frame with consistent adult characters",
        "duration_seconds": 4.0,
        "background_style": "dream_shaper_xl",
    }


def test_campus_romance_metadata_selects_specific_style() -> None:
    result = classify_visual_style(
        {
            "categories": ["都市日常", "都市", "校花", "单女主"],
            "abstract": "【恋爱日常+校园+先婚后爱+小甜文】",
        }
    )
    assert result["primary_genre"] == "现代都市校园甜宠轻喜剧"
    assert result["style_profile"]["style_id"] == STYLE_ID
    assert result["style_profile"]["style_id"] != "dream_shaper_xl"
    assert "校园" in result["evidence"]["abstract_tag_line"]


def test_visual_direction_has_composition_and_continuity_gates() -> None:
    wrapper = {
        "schema": "novel_highlight_storyboard/v3",
        "storyboard": {
            "novel_title": "测试",
            "characters": ["林夏", "洛雪微"],
            "scenes": [_scene(index) for index in range(24)],
            "total_duration_seconds": 96.0,
        },
    }
    metadata = {
        "categories": ["都市日常", "校花", "单女主"],
        "abstract": "【恋爱日常+校园+霸道女姐姐+先婚后爱+小甜文】",
    }
    source = (
        "十九啊……穿着衬衫短裙，竖着高马尾。"
        "林夏皮肤白皙，五官清秀，又留着柔顺的刘海，略微偏瘦的体格充满了少年气息。"
        "林夏说完，拿着军训服就朝着外面走去。两人到了停车场。"
    )
    package = enrich_storyboard_visuals(wrapper, metadata, source)
    review = audit_visual_direction(package)
    assert review["decision"] == "passed"
    assert len(package["visual_direction"]["shots"]) == 24
    shot = package["visual_direction"]["shots"][6]
    assert all(shot["composition"].get(key) for key in ("foreground", "midground", "background", "focal_point"))
    assert "军训服" in shot["continuity"]["prop_state"]
    assert package["visual_direction"]["shots"][2]["continuity_mode"] == "timeline_reset"


def test_visual_audit_rejects_missing_background_layer() -> None:
    wrapper = {
        "schema": "novel_highlight_storyboard/v3",
        "storyboard": {
            "novel_title": "测试",
            "characters": [],
            "scenes": [_scene(index) for index in range(24)],
            "total_duration_seconds": 96.0,
        },
    }
    package = enrich_storyboard_visuals(
        wrapper,
        {"categories": ["校园", "单女主"], "abstract": "【恋爱+校园+小甜文】"},
        "停车场。",
    )
    package["visual_direction"]["shots"][0]["composition"]["background"] = ""
    review = audit_visual_direction(package)
    assert review["decision"] == "rejected"
    assert "scene 0: composition.background missing" in review["errors"]


def test_visual_audit_rejects_dialogue_subject_shift() -> None:
    wrapper = {
        "schema": "novel_highlight_storyboard/v3",
        "storyboard": {
            "novel_title": "测试",
            "characters": ["林夏", "洛雪微"],
            "scenes": [_scene(index) for index in range(24)],
            "total_duration_seconds": 96.0,
        },
    }
    package = enrich_storyboard_visuals(
        wrapper,
        {"categories": ["校园"], "abstract": "【恋爱+校园+小甜文】"},
        "停车场。",
    )
    package["storyboard"]["scenes"][8]["dialogue"][0]["speaker"] = "洛雪微"
    review = audit_visual_direction(package)
    assert review["decision"] == "rejected"
    assert any("photography/dialogue subject mismatch" in item for item in review["errors"])


def test_visual_audit_rejects_story_change_after_binding() -> None:
    wrapper = {
        "schema": "novel_highlight_storyboard/v3",
        "storyboard": {
            "novel_title": "测试",
            "characters": ["林夏", "洛雪微"],
            "scenes": [_scene(index) for index in range(24)],
            "total_duration_seconds": 96.0,
        },
    }
    package = enrich_storyboard_visuals(
        wrapper,
        {"categories": ["校园"], "abstract": "【恋爱+校园+小甜文】"},
        "停车场。",
    )
    package["storyboard"]["scenes"][3]["narration"] = "视觉阶段擅自改写剧情。"
    review = audit_visual_direction(package)
    assert review["decision"] == "rejected"
    assert "storyboard bytes changed after visual stage binding" in review["errors"]
