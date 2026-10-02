# 动漫微动旁白混音

## 适用场景

当用户更看重画面稳定和流畅，而不要求逐字口型时，使用：

`动漫头像 → LivePortrait 微动 → 循环到旁白长度 → 混入音频 → 双门禁`

它不会伪装成精准口型模式，路由清单必须设置：

```json
{
  "audio_driven": true,
  "visual_style": "anime",
  "lip_sync_required": false
}
```

## 混音清单

模板：`video_audio_mux/v1`

示例：

`D:\IT\ai_douyin\docs\examples\liveportrait_voiceover_mux.example.json`

运行：

```powershell
D:\IT\ai_douyin\.venv\Scripts\python.exe `
  D:\IT\ai_douyin\scripts\video_audio_mux.py `
  D:\IT\ai_douyin\docs\examples\liveportrait_voiceover_mux.example.json
```

## 循环模式

| 模式 | 行为 | 使用建议 |
|---|---|---|
| `pingpong` | 正放后倒放并循环 | 默认；首尾连续，适合轻微表情和呼吸 |
| `repeat` | 直接重复原视频 | 原视频本身首尾一致时使用 |
| `hold` | 播放一次后冻结尾帧 | 动作不能倒放、但允许后段静止时使用 |

默认输出：

- 保持源视频分辨率和帧率。
- H.264/yuv420p。
- AAC 192 kbps、48 kHz、双声道。
- 视频长度以旁白音频为准。
- 写入独立 `.mux.report.json`，不覆盖模型原始输出。

## 固定验收顺序

1. 对混音后的视频运行 `video_control_audit.py`。
2. 生成 `video_review_packet/v1`。
3. 自动确认音轨存在和音视频时长差不超过 `0.2` 秒。
4. 人工确认循环没有跳切、身份稳定、背景和光线不闪。
5. 运行 `video_review_decision.py`。
6. 只有 `composition_eligible=true` 才允许进入故事拼接。

## 已验证样片

视频：

`D:\IT\ai_douyin\data\qa\liveportrait_voiceover_v1\xiaojie_liveportrait_voiceover_v1.mp4`

结果：

- `704x1248`
- `30 fps`
- `5.5` 秒
- H.264/yuv420p + AAC
- 音视频时长差 `0.028` 秒
- 数值门禁通过
- 自动音频门禁通过
- 人工视觉签核通过
- `composition_eligible=true`

