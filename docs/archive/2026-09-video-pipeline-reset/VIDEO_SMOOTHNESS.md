# 视频流畅度修复

`video_smoothness/v1` 用于画面结构已经通过，但低帧率、重复帧或帧间速度突变造成卡顿的镜头。

它不会修复脸、手、手机或背景变形。输入视频必须先通过 `video_control/v1`，否则执行器直接返回 `blocked`。

## 为什么不能只看 FPS

把 16 fps 文件声明成 30 fps，或者简单复制帧，技术元数据会显示 30 fps，但肉眼仍然卡顿。执行器把原片和输出都放到同一个目标时间轴，再比较：

- `duplicate_ratio`：近似重复帧比例。
- `normalized_jerk`：相邻运动速度的突变量。
- `cadence_outlier_ratio`：异常快慢帧比例。
- `motion_path`：总运动量，用于防止插帧把动作抹掉或制造额外抖动。
- `smoothness_score`：只用于同一镜头前后比较，不跨镜头比较。

## 清单

```json
{
  "template": "video_smoothness/v1",
  "input_video": "accepted_16fps.mp4",
  "input_control_manifest": "accepted_16fps.control.manifest.json",
  "input_control_report": "accepted_16fps.control.report.json",
  "output_video": "accepted_smooth30.mp4",
  "smoothing": {
    "algorithm": "minterpolate",
    "target_fps": 30,
    "analysis_width": 160
  },
  "acceptance": {
    "minimum_score_gain": 5,
    "maximum_duplicate_ratio": 0.12,
    "minimum_motion_retention": 0.7,
    "maximum_motion_retention": 1.4,
    "maximum_duration_delta": 0.08,
    "minimum_motion_distance": 0.12,
    "duplicate_threshold": 0.12
  },
  "encoding": {
    "crf": 18,
    "preset": "slow"
  }
}
```

## 执行

```powershell
.\.venv\Scripts\python.exe scripts\video_smoothness.py smoothness.json --dry-run
.\.venv\Scripts\python.exe scripts\video_smoothness.py smoothness.json
```

正式输出需要同时满足：

1. 输入结构门禁已通过。
2. 输出重新通过同一个结构门禁。
3. 输出帧率达到目标。
4. 流畅度分数至少达到配置的改善量。
5. 重复帧率、运动保留率和时长变化均在范围内。

低运动或已达到目标帧率的输入返回 `no_action`，避免为了“30 fps”对静止画面制造无意义中间帧。
