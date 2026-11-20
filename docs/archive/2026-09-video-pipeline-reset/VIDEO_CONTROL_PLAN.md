# 批量镜头视频控制计划

## 目的

`video_control_plan/v1` 把故事板中的多个镜头一次性编译为：

- 每个镜头允许使用的控制模式。
- 首选本地工具和实际解析后的工具。
- 本机模型、节点和后处理组件是否齐全。
- 生成前必须提供的素材。
- 生成后必须执行的固定验收项。
- 缺少关键能力时直接阻止生成，而不是继续改提示词碰运气。

它不负责运行 ComfyUI，而是作为 Hermes、Claude Code 和本地调度器之间的固定任务合同。

## 使用

示例：

`D:\IT\ai_douyin\docs\examples\video_control_plan.example.json`

编译：

```powershell
D:\IT\ai_douyin\.venv\Scripts\python.exe `
  D:\IT\ai_douyin\scripts\video_control_plan.py `
  D:\IT\ai_douyin\docs\examples\video_control_plan.example.json `
  --output D:\IT\ai_douyin\data\qa\video_control_plan.example.report.json
```

退出码：

- `0`：全部镜头已有可执行本地路线。
- `2`：至少一个镜头被阻止，不能进入生成队列。

## 清单格式

```json
{
  "template": "video_control_plan/v1",
  "id": "episode_001",
  "allow_fallback": false,
  "defaults": {
    "camera": "locked",
    "background": "static",
    "preserve_reference": true
  },
  "shots": [
    {
      "id": "s01_l01",
      "intent": {
        "motion": "micro",
        "framing": "medium",
        "contains_hands": true,
        "contains_phone": true
      }
    }
  ]
}
```

`defaults` 会与每个镜头的 `intent` 合并，镜头自己的值优先。镜头 ID 必须唯一。

## 固定路由

| 镜头意图 | 路由 |
|---|---|
| 手或手机必须稳定的微动镜头 | `deterministic_2d_compositor` |
| 无手头肩表情微动 | `liveportrait` |
| 无手头肩音频口型 | `sadtalker` |
| 动漫旁白，不强制逐字口型 | `liveportrait` + `audio_mux` |
| 动漫精准口型 | `sonic`，缺权重时阻断 |
| 中景轻微身体动作 | `framepack` |
| 固定背景的人物动作迁移 | `wan_animate_move` |
| 人物替换并继承环境光 | `wan_animate_replacement` |
| 运镜或动态环境 | `ltx_i2v` 或可用自由生成工具 |

提示词中的 `keep phone fixed`、`hands unchanged`、`same lighting` 不会改变路由决策。

动漫镜头必须明确 `visual_style=anime`。如果只需要画面流畅，设置
`audio_driven=true`、`lip_sync_required=false`，系统使用 LivePortrait 表情微动并后期混入旁白；如果要求精准口型，设置 `lip_sync_required=true`，系统只允许 Sonic，模型不齐时直接阻止，不再静默降级到 SadTalker。

## 验收项

报告中的 `acceptance_checks` 根据镜头自动生成：

- 所有镜头：技术规格、身份、光线、镜头约束、动作范围。
- 手部镜头：手部结构和手的位置。
- 手机镜头：单手机、手机位置和手物接触。
- 音频镜头：口型同步和嘴形。
- 人物迁移：蒙版边缘和静态背景。
- 重光镜头：蒙版边缘、背景光匹配和肤色。
- 多人物镜头：人数和角色身份分离。

这些检查项应转成对应的 `video_control/v1` 区域门禁和人工抽帧检查，不允许由生成代理自行删除。

## Hermes 与 Claude Code 分工

Hermes：

1. 根据故事板填写镜头意图，不选择模型参数。
2. 明确手、手机、人物数量、镜头运动、背景运动和是否音频驱动。
3. 提交 `video_control_plan/v1`。

Claude Code：

1. 运行 `video_control_plan.py`。
2. 只执行 `generation_allowed=true` 的镜头。
3. 按 `resolved_tool` 使用现有工作流，不自行换模型。
4. 按 `required_assets` 检查输入。
5. 生成后执行 `acceptance_checks`、质量门禁和候选比较。
6. 任一硬门禁失败就保留报告并停止该镜头，不批量扩散失败参数。
