# 视频候选统一比选

`video_candidate_benchmark/v1` 用同一套质量门禁比较不同模型、参数或后处理版本。它解决“每个 AI 都说自己的结果很好，但没有统一验收”的问题。

## 约束

- 每个候选必须提供独立的 `video_control/v1` 清单。
- 同一次比选必须使用相同控制模式。
- 同一次比选必须使用相同参考图。
- 先执行硬门禁；拒绝项不会因为综合分高而被推荐。
- 只在通过硬门禁的候选中比较亮度、色度、漂移、活动范围、静态区域和目标 FPS。

## 清单

```json
{
  "template": "video_candidate_benchmark/v1",
  "id": "shot_01_compare",
  "ranking": {
    "target_fps": 30,
    "target_duration": 3.0
  },
  "candidates": [
    {
      "id": "liveportrait",
      "tool": "liveportrait",
      "control_manifest": "liveportrait.control.json"
    },
    {
      "id": "ltx",
      "tool": "ltx_i2v",
      "control_manifest": "ltx.control.json"
    }
  ]
}
```

## 运行

```powershell
.\.venv\Scripts\python.exe scripts\video_candidate_benchmark.py `
  data\qa\liveportrait_xiaojie_3q_benchmark.json `
  --output-dir data\qa\liveportrait_xiaojie_3q_benchmark
```

输出包含：

- 每个候选的独立门禁报告
- 通过/拒绝状态
- 统一质量分
- 排名
- 推荐候选和视频路径

该工具不会生成视频，只负责管理 Hermes、Claude Code、ComfyUI 或其他模型交付的候选结果。只要这些工具提交相同格式的控制清单，就可以统一验收。

## Hermes / Claude Code 交付规范

给执行模型的固定要求：

1. 每次只生成一个候选，不自行宣布通过。
2. 必须同时交付视频路径和 `video_control/v1` 清单。
3. 同一轮候选必须使用同一参考图、同一控制模式和相同区域定义。
4. 工具名、seed、工作流路径写入候选记录。
5. 最终选择只读取比选报告的 `winner`，不读取执行模型的自评。

## 本机实测

清单：

`D:\IT\ai_douyin\data\qa\liveportrait_xiaojie_3q_benchmark.json`

报告：

`D:\IT\ai_douyin\data\qa\liveportrait_xiaojie_3q_benchmark\liveportrait_xiaojie_3q_fps_compare.benchmark.json`

结果：

- `liveportrait_smooth30`：通过，93.835 分
- `liveportrait_rife426`：通过，93.040 分
- `liveportrait_raw16`：通过，88.008 分
- 推荐：`liveportrait_smooth30`
