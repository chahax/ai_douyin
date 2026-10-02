# 受控时序修复

`video_temporal_repair/v1` 补齐了此前只写在策略中、没有真实执行器的 `deflicker`。

允许修复：

- 全局曝光闪烁。
- 全局色度闪烁。
- 已通过结构验收的视频插帧。

禁止掩盖：

- 手、手机、脸或人物身份变形。
- 静态背景漂移。
- 参考图锁定失败。
- 镜头运动或动作范围超限。

执行器先读取原始 `video_control/v1` 和报告。存在结构失败时直接返回 `blocked`；修复后重新运行相同门禁，并要求亮度波动达到最小改善比例。

## 清单

```json
{
  "template": "video_temporal_repair/v1",
  "input_video": "input.mp4",
  "input_control_manifest": "input.control.manifest.json",
  "input_control_report": "input.control.report.json",
  "output_video": "output_deflicker.mp4",
  "repair": {
    "deflicker": {
      "enabled": true,
      "algorithm": "luma_gain",
      "target": "reference",
      "strength": 1.0,
      "maximum_gain_delta": 0.35
    },
    "interpolation": "minterpolate",
    "target_fps": 30
  },
  "acceptance": {
    "minimum_luma_improvement": 0.15
  }
}
```

## 执行

```powershell
.\.venv\Scripts\python.exe scripts\video_temporal_repair.py repair.json --dry-run
.\.venv\Scripts\python.exe scripts\video_temporal_repair.py repair.json
```

只有 `status=accepted` 且输出控制报告再次通过，修复视频才能进入候选比较或故事合成。

`algorithm=ffmpeg` 使用原生 `deflicker`，适合轻度曝光抖动；`algorithm=luma_gain` 两遍扫描视频，并把每帧平均亮度限制性拉回批准参考图，适合固定镜头的强周期闪烁。两种算法都不能绕过结构门禁。
