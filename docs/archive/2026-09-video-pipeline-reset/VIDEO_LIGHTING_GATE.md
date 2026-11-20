# 视频光线一致性门禁

`video_lighting_gate/v1` 用唯一批准参考图检查图片或视频的光线是否一致。
它不是美学评分器，而是生成后、合成前的机器门禁。

检测内容：

- 曝光差，使用 EV 表示；
- 冷暖偏色和绿/洋红偏色；
- 对比度、高光比例和阴影比例；
- 画面低频水平/垂直亮度梯度，用于判断主光方向；
- 视频抽样帧之间的曝光、颜色和光向漂移。

视频候选必须先通过自己的 `video_control/v1` 结构报告。手、脸、背景或镜头
尚未通过时，光线门禁返回 `blocked`，不会用调色掩盖结构错误。

## 清单

```json
{
  "template": "video_lighting_gate/v1",
  "id": "shot_01_lighting",
  "reference": {
    "id": "approved_light",
    "path": "approved.png",
    "region": [0.45, 0, 0.55, 1]
  },
  "candidates": [
    {
      "id": "shot_01",
      "path": "shot_01.mp4",
      "control_report": "shot_01.control.report.json",
      "region": [0.45, 0, 0.55, 1]
    }
  ],
  "sampling": {
    "sample_count": 7,
    "fingerprint_size": 128
  },
  "acceptance": {
    "maximum_exposure_ev_delta": 0.35,
    "maximum_temperature_delta": 0.08,
    "maximum_tint_delta": 0.06,
    "maximum_contrast_delta": 0.15,
    "maximum_highlight_ratio_delta": 0.12,
    "maximum_shadow_ratio_delta": 0.12,
    "maximum_direction_angle_degrees": 45,
    "maximum_direction_strength_delta": 0.06,
    "minimum_reference_direction_strength": 0.015,
    "maximum_temporal_exposure_range_ev": 0.25,
    "maximum_temporal_color_range": 0.06,
    "maximum_temporal_direction_range_degrees": 45
  }
}
```

参考和候选必须使用语义一致的 `region`。人物镜头优先框住脸、颈部和衣服，
不要把大面积纯黑背景放进人物光线区域。场景光线则使用整幅画面或固定背景区。

## 执行

```powershell
.\.venv\Scripts\python.exe scripts\video_lighting_gate.py lighting.json
```

## 恢复策略

- `light_direction_mismatch`：先运行 `keyframe_relight` 修批准关键帧，再生成；
- `lighting_exposure_mismatch`、`lighting_color_cast_mismatch`：
  使用 `reference_appearance_lock` 或 `color_match_v2`，不重新生成动作；
- `lighting_contrast_mismatch`：优先局部曲线或参考外观锁定；
- `lighting_temporal_drift`：不能只修中间帧，应逐帧外观锁定或拒绝候选。
