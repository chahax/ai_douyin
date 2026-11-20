# 关键帧局部方向光

`keyframe_relight/v1` 用于故事板光源方向或局部色温不正确，但人物、手、手机和构图已经批准的情况。

它不是生成模型，不重绘结构。执行器只在批准遮罩内应用同一套方向渐变，遮罩外像素必须完全不变。修正后的 PNG 再作为 LTX、Wan、FramePack 或确定性合成器的关键帧。

## 适用边界

| 问题 | 使用方式 |
|---|---|
| 台灯在左侧，人物左脸却没有暖光 | 对人物遮罩运行 `keyframe_relight/v1` |
| 视频不同帧忽明忽暗 | 使用 `video_temporal_repair/v1` |
| 动态人物需要继承另一段背景视频的光 | 使用 Wan Replacement + Relighting LoRA |
| 需要生成新的投影、复杂反射或改变光源几何 | 使用 IC-Light 重做静态关键帧并重新人工验收 |

本工具不能生成真实的新阴影、反射或遮挡关系。需要这些内容时应回到静态关键帧阶段，不应逐帧重绘视频。

## 清单

```json
{
  "template": "keyframe_relight/v1",
  "source_image": "approved_keyframe.png",
  "mask_image": "approved_subject_mask.png",
  "output_image": "approved_keyframe_relight.png",
  "mask_blur": 4,
  "light": {
    "direction": "top_left",
    "highlight_ev": 0.32,
    "shadow_ev": -0.06,
    "color": [255, 214, 170],
    "color_strength": 0.08,
    "curve": 1.0
  },
  "safety": {
    "maximum_mask_area_ratio": 0.65,
    "maximum_mean_pixel_change": 28,
    "minimum_mean_pixel_change": 0.8,
    "minimum_directional_luma_shift": 1.5
  }
}
```

方向支持 `left`、`right`、`top`、`bottom`、`top_left`、`top_right`、`bottom_left` 和 `bottom_right`。

## 执行

```powershell
.\.venv\Scripts\python.exe scripts\keyframe_relight.py relight.json --dry-run
.\.venv\Scripts\python.exe scripts\keyframe_relight.py relight.json
```

只有以下条件全部满足才会产生正式输出：

1. 有效遮罩面积不超过清单上限。
2. 遮罩内平均变化处于允许范围。
3. 指定方向产生了可测量亮度差。
4. 遮罩外变化像素严格为零。

报告中的 `directional_luma_shift` 应为正数；数值过小表示方向光肉眼不可见，过大则应降低 `highlight_ev` 或 `color_strength`，每轮只改一个参数。
