# 确定性全屏镜头运动

`deterministic_camera/v1` 把一张批准的 9:16 故事板变成全屏缓慢推近、拉远或平移视频。

它适合“只要画面流畅、有一点动态，不需要人物真实动作”的镜头。每帧都从同一张原图做仿射裁切和重采样，因此不会换脸、改变手指、生成第二部手机，也不会出现三段式或只有中间窗口在动。

## 与其他模式的边界

| 需求 | 使用工具 |
|---|---|
| 整幅静态故事板缓慢推近或平移 | `deterministic_camera/v1` |
| 人物和镜头都必须完全静止，只需要来信光 | `deterministic_motion/v1` |
| 人物需要眨眼、转头或说话 | LivePortrait、Sonic 或受限 I2V |
| 需要真实空间视差和暴露新背景 | 分层 2.5D 或生成式视频，不能用本工具伪造 |

## 清单

```json
{
  "template": "deterministic_camera/v1",
  "source_image": "approved_storyboard.png",
  "output_path": "approved_storyboard_push_in.mp4",
  "width": 704,
  "height": 1248,
  "fps": 25,
  "duration_seconds": 3.88,
  "motion": {
    "start_zoom": 1.0,
    "end_zoom": 1.05,
    "start_center": [0.5, 0.5],
    "end_center": [0.51, 0.49],
    "easing": "smooth"
  },
  "safety": {
    "maximum_zoom": 1.08,
    "maximum_zoom_delta": 0.08,
    "maximum_pan_distance": 0.04,
    "minimum_activity_ratio": 0.03,
    "maximum_luma_range": 6
  },
  "encoding": {
    "crf": 18,
    "preset": "slow"
  }
}
```

## 硬限制

- 缩放不能超过 `maximum_zoom`。
- 起点和终点裁切框都必须完全位于原图内，不能产生黑边。
- 平移距离不能超过 `maximum_pan_distance`。
- 动态太弱或因裁切导致整体亮度变化过大时拒绝输出。
- 本工具只能用于明确允许镜头移动的镜头；固定机位人物微动继续使用其他模式。

## 执行

```powershell
.\.venv\Scripts\python.exe scripts\deterministic_camera.py camera.json --dry-run
.\.venv\Scripts\python.exe scripts\deterministic_camera.py camera.json `
  --qa-dir D:\IT\ai_douyin\data\qa\shot_id
```

视频可写入 ComfyUI `output`，但 `--qa-dir` 必须指向 `ai_douyin\data\qa`。门禁清单、报告和抽帧证据不能混入 ComfyUI 项目。

## 自动路由

`video_control_plan/v1` 中满足以下意图时自动选择本工具：

```json
{
  "motion": "none",
  "camera": "moving",
  "background": "static",
  "preserve_reference": true
}
```

计划报告会生成 `primary_tool=deterministic_camera`，代理任务包会要求 Claude Code 执行 `scripts\deterministic_camera.py`。验收项使用 `declared_camera_motion`，而不是把已声明的推拉误判成固定镜头失败。
