# 视频视觉验收包

## 为什么需要

像素统计门禁可以发现闪烁、背景漂移、动作过大和技术规格错误，但不能可靠判断：

- 是否出现双手机。
- 是否多手指、少手指或手物脱离。
- 人物是否悄悄换脸。
- 口型是否自然。
- 蒙版边缘是否穿帮。

因此每条模型视频必须同时具备机器门禁和固定视觉证据。

## 生成证据包

清单模板：`video_review_packet/v1`

示例：

`D:\IT\ai_douyin\docs\examples\sadtalker_review_packet.example.json`

运行：

```powershell
D:\IT\ai_douyin\.venv\Scripts\python.exe `
  D:\IT\ai_douyin\scripts\video_review_packet.py `
  D:\IT\ai_douyin\docs\examples\sadtalker_review_packet.example.json
```

输出包括：

- 均匀分布的 3–9 张原始帧。
- `contact_sheet.png`：参考图和抽样帧。
- `difference_sheet.png`：相对首帧放大四倍的差分。
- `review.json`：技术规格、数值门禁状态、路由和逐项人工检查。
- 音频镜头自动检查音轨存在、音视频时长差不超过 `0.2` 秒。
- 配置 `mouth_region=[x,y,width,height]` 后，自动检查嘴部区域是否存在可见运动。

`review.json` 初始状态固定为 `pending_manual_review`，工具不会因为数值门禁通过而自动宣布画面通过。

## 最终签核

人工或视觉模型看完证据后填写 `video_review_decision/v1`：

```json
{
  "template": "video_review_decision/v1",
  "review_report": "review.json",
  "output_path": "decision.report.json",
  "reviewer": "codex",
  "decisions": {
    "technical_metadata": {
      "status": "passed",
      "notes": ""
    },
    "identity_consistency": {
      "status": "failed",
      "notes": "中间帧脸型和眼睛发生明显变化"
    }
  }
}
```

运行：

```powershell
D:\IT\ai_douyin\.venv\Scripts\python.exe `
  D:\IT\ai_douyin\scripts\video_review_decision.py `
  decision.json
```

硬规则：

- 每个 `acceptance_checks` 项都必须有明确决定。
- `failed` 必须填写原因。
- 不允许出现未声明的检查项。
- 机器门禁必须通过。
- 自动音轨、时长和嘴部运动检查必须通过。
- 只要一个视觉项失败，`composition_eligible=false`，退出码为 `2`。
- 只有机器门禁和全部视觉项都通过，视频才能进入配音、拼接和发布。
