# 确定性单图动画

`deterministic_motion/v1` 用于不适合交给 I2V 重画的镜头：

- 人物、手、手机和原始光线必须保持稳定。
- 只需要肉眼可见但克制的来信光、窗外光点或空气颗粒。
- 输出必须平滑、可复现，并自动通过 `pixel_locked` 门禁。

该工具不调用 LTX、Wan、FramePack 或其他生成模型。相同清单会产生相同动画，适合作为动漫旁白镜头的稳定保底方案。

## 清单

```json
{
  "template": "deterministic_motion/v1",
  "source_image": "master.png",
  "output_path": "output/shot.mp4",
  "width": 704,
  "height": 1248,
  "fps": 25,
  "duration_seconds": 3.88,
  "safety": {
    "minimum_activity_ratio": 0.001,
    "maximum_effect_area_ratio": 0.04
  },
  "effects": {
    "light_pulses": [
      {
        "name": "phone_glow",
        "rect": [0.16, 0.72, 0.12, 0.12],
        "color": [85, 145, 255],
        "opacity": 0.2,
        "blur": 12,
        "start": 0.7,
        "peak": 1.92,
        "end": 2.7
      }
    ],
    "particles": []
  }
}
```

`rect` 使用 `[x, y, width, height]` 的 0–1 归一化坐标。所有效果区域面积之和超过安全上限时，清单会在渲染前被拒绝。

## 执行

```powershell
.\.venv\Scripts\python.exe scripts\deterministic_motion.py `
  docs\examples\deterministic_motion.example.json `
  --dry-run

.\.venv\Scripts\python.exe scripts\deterministic_motion.py `
  docs\examples\deterministic_motion.example.json `
  --qa-dir D:\IT\ai_douyin\data\qa\shot_id
```

执行器会生成：

- H.264 / `yuv420p` 视频。
- `*.control.manifest.json`。
- `*.control.report.json`。
- `*.motion.report.json`。

只有 `status=accepted` 才允许进入配音与故事合成。活动面积太大、光色漂移、效果不可见或锚点偏离都会被拒绝。
