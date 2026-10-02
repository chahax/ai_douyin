# 跨镜头画风一致性门禁

`video_style_gate/v1` 在镜头进入故事合成前，检查它与唯一批准画风参考是否一致。

它不会用“同为动漫”这种宽泛标签放行，而是比较归一化区域的：

- 色相、饱和度和明度分布。
- 线条密度与边缘强度。
- 平均亮度、对比度和饱和度。
- 同一视频抽样帧之间的画风漂移。

视频候选必须先通过自己的 `video_control/v1` 报告，否则状态为 `blocked`，避免用画风分数掩盖手、脸、背景或镜头错误。

## 清单

```json
{
  "template": "video_style_gate/v1",
  "id": "anti_fraud_style_v1",
  "reference": {
    "id": "approved_style",
    "path": "approved_style.png",
    "region": [0, 0, 1, 1]
  },
  "candidates": [
    {
      "id": "shot_01",
      "path": "shot_01.mp4",
      "control_report": "shot_01.control.report.json",
      "region": [0, 0, 1, 1]
    }
  ],
  "sampling": {
    "sample_count": 5,
    "fingerprint_size": 128
  },
  "acceptance": {
    "maximum_style_distance": 0.2,
    "maximum_palette_distance": 0.28,
    "maximum_edge_density_delta": 0.12,
    "maximum_edge_strength_delta": 0.035,
    "maximum_temporal_drift": 0.1
  }
}
```

不同构图但同一角色时，应分别填写归一化 `region`，只比较人物或服装区域；同场景镜头可以使用整帧。区域太小会被拒绝，防止通过挑选一块纯色背景规避验收。

## 执行

```powershell
.\.venv\Scripts\python.exe scripts\video_style_gate.py style.json
```

## 失败处理

- `style_palette_mismatch`：可尝试 `reference_appearance_lock` 或重新调色。
- `style_lineart_mismatch`、`render_style_mismatch`：必须更换故事板或重新生成，调色不能修复线稿和渲染方式。
- `temporal_style_drift`：视频内部画风随时间变化，应拒绝生成结果，不能只截取一帧放行。
