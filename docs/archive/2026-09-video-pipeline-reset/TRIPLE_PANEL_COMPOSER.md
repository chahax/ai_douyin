---
doc_status: implemented
doc_category: video-template
last_reviewed: 2026-07-21
---

# Single Scene / Triple Panel Composer

`triple_panel/v1` defaults to a **full-screen middle video** when the top and bottom sources are both omitted. This is the normal mode for a single generated scene. A real three-panel layout is enabled only when both static top and bottom images are explicitly provided. ComfyUI is responsible only for the middle source video; FFmpeg owns the final layout, duration, audio, and encoding.

## Manifest

```json
{
  "template": "triple_panel/v1",
  "duration_seconds": 20,
  "quality_profile": "publish",
  "audio_path": "voice.wav",
  "panels": {
    "top": {
      "source": null,
      "motion": "static"
    },
    "middle": {
      "source": "middle.mp4",
      "motion": "generated"
    },
    "bottom": {
      "source": null,
      "motion": "static"
    }
  }
}
```

- Both `top.source` and `bottom.source` set to `null`: the middle video fills the entire output canvas. No empty upper/lower panels are rendered.
- Both `top.source` and `bottom.source` set to image paths: render the intentional three-panel layout, with static top/bottom and a dynamic middle.
- Providing only one static panel is rejected to avoid an accidental empty band.
- `middle` must be a video path and is looped or trimmed to `duration_seconds`.
- Relative asset paths are resolved relative to the manifest file.

Optional three-panel manifest:

```json
"panels": {
  "top": {"source": "top.png", "motion": "static"},
  "middle": {"source": "middle.mp4", "motion": "generated"},
  "bottom": {"source": "bottom.png", "motion": "static"}
}
```

## Compose

```powershell
.venv\Scripts\python.exe main.py triple-panel `
  --manifest data\projects\demo\triple_panel.json `
  --output data\videos\demo_triple_panel.mp4
```

Each output writes two adjacent records:

- `demo_triple_panel.manifest.json`: the fully resolved source-of-truth used for rendering.
- `demo_triple_panel.quality.json`: media specification, sampled-frame metrics, and per-panel motion acceptance.

## Acceptance policy

The template enforces these rules before reporting success:

| Layout | Required policy | Failure condition |
|---|---|---|
| Full-screen | Middle must be dynamic | No visible sampled-frame motion |
| Three-panel | Top/bottom static; middle dynamic | Any static-panel motion or no middle motion |

The gate uses deterministic non-uniform sample times so a looped clip is not repeatedly sampled at the same phase. A static panel fails at a sampled RGB frame distance above `1.2` or more than `2%` active pixels; a dynamic middle panel must exceed either `1.2` mean distance or `0.2%` active pixels. These values should be calibrated from approved samples before changing them globally. General delivery checks still enforce the selected quality profile, audio stream, duration, H.264, `yuv420p`, and final quality report. Rendering first writes `*.pending.mp4`; only a passing report replaces the formal output path.
