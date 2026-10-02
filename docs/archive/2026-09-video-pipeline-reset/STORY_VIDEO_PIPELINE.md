---
doc_status: implemented
doc_category: video-pipeline
last_reviewed: 2026-07-22
---

# Story Video Pipeline

`story_video/v1` turns approved generated scene clips into one complete story video. It treats narration and character dialogue as separate lines with named voices, then records the actual audio timeline and runs the final video quality gate.

## Responsibilities

| Stage | Owner | Output |
|---|---|---|
| Storyboard | Hermes | One approved keyframe per `scene.id`, plus prompt, seed, and model record. |
| Image-to-video | Claude Code | One checked LTX clip per `scene.id`; fixed camera and controlled motion. |
| Voice and assembly | Codex / `ai_douyin` | Per-line narrator/character TTS, scene timing, final H.264 video, timeline, and quality report. |

The `responsibilities` map is recorded in the manifest for handoff traceability; the actual owner names do not change rendering behavior.

## Manifest

```json
{
  "template": "story_video/v1",
  "title": "深夜转账陷阱",
  "quality_profile": "publish",
  "responsibilities": {
    "storyboard": "hermes",
    "animation": "claude_code",
    "assembly": "codex"
  },
  "cast": {
    "narrator": {
      "name": "旁白",
      "voice": "zh-CN-XiaoxiaoNeural",
      "tts_provider": "edge"
    },
    "aning": {
      "name": "阿宁",
      "voice": "zh-CN-YunxiNeural",
      "tts_provider": "edge"
    }
  },
  "scenes": [
    {
      "id": "phone_message",
      "video_path": "scenes/phone_message.mp4",
      "lines": [
        {
          "speaker": "narrator",
          "text": "深夜，阿宁收到了一条陌生消息。",
          "pause_after_seconds": 0.15
        },
        {
          "speaker": "aning",
          "text": "这笔钱，真的能马上到账吗？"
        }
      ]
    }
  ]
}
```

- `speaker` must exist in `cast`.
- A line uses `audio_path` directly when a recorded or externally generated voice asset already exists; otherwise it synthesizes `text` using that speaker's `tts_provider` and `voice`.
- Edge-TTS lines may set `rate` (`+5%` / `-8%`), `volume` (`+3%` / `-2%`), and `pitch` (`+2Hz` / `-3Hz`). These values are included in the audio cache key, so a prosody change creates a new asset.
- Scenes play in manifest order. Each generated scene video loops or trims to its own narrator-plus-dialogue duration, then all scenes are concatenated full-screen.
- Use `pause_after_seconds` to separate consecutive speakers. No static top/bottom panels are added.

## Run

```powershell
.venv\Scripts\python.exe main.py story-video `
  --manifest data\stories\anti_fraud\story.json `
  --output data\stories\anti_fraud\final.mp4
```

Artifacts written next to `final.mp4`:

- `final.manifest.json`: resolved inputs, cast, and responsibility map.
- `final.timeline.json`: each actual narrator/character line with start/end time and audio source.
- `final.quality.json`: final delivery and frame-quality acceptance result.
- `final.story/`: generated line audio and per-scene intermediates for debugging and correction.

For a scene correction, only replace that scene's `video_path` (or an individual line's `audio_path`) and rerun the same manifest. The final output is written atomically through `*.pending.mp4`, so a failed quality gate does not replace the last accepted story video.
