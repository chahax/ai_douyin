from src.content_factory.story_video import StoryLine


def test_story_line_accepts_edge_tts_prosody() -> None:
    line = StoryLine.from_dict(
        {
            "speaker": "lead",
            "text": "测试",
            "rate": "-8%",
            "volume": "+3%",
            "pitch": "-2Hz",
        },
        scene_id="scene",
        line_index=0,
    )

    assert line.rate == "-8%"
    assert line.volume == "+3%"
    assert line.pitch == "-2Hz"


def test_story_line_rejects_invalid_edge_tts_prosody() -> None:
    try:
        StoryLine.from_dict(
            {"speaker": "lead", "text": "测试", "rate": "fast"},
            scene_id="scene",
            line_index=0,
        )
    except ValueError as exc:
        assert "rate must look like" in str(exc)
    else:
        raise AssertionError("invalid rate should be rejected")
