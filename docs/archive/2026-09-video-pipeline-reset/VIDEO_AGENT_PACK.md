# 双代理视频任务包

`video_agent_pack/v1` 把 `video_control_plan_report/v1` 编译成每个镜头独立的：

- `contract.json`
- `hermes_task.md`
- `claude_code_task.md`

它强制隔离两个项目：

- `D:\IT\AI_vido\ComfyUI`：模型、输入素材、工作流和原始视频。
- `D:\IT\ai_douyin`：控制计划、门禁、抽帧、恢复报告和故事合成。

Hermes 只能准备素材，Claude Code 只能按合同执行；任何代理都不能自行宣布视频通过。

## 清单

```json
{
  "template": "video_agent_pack/v1",
  "id": "anti_fraud_agent_pack",
  "namespace": "anti_fraud_v5",
  "plan_report": "../../data/qa/video_control_plan.example.report.json",
  "comfyui_root": "D:\\IT\\AI_vido\\ComfyUI",
  "orchestrator_root": "D:\\IT\\ai_douyin",
  "output_dir": "../../data/qa/anti_fraud_v5/agent_tasks"
}
```

## 执行

```powershell
.\.venv\Scripts\python.exe scripts\video_agent_pack.py `
  docs\examples\video_agent_pack.example.json
```

被工具库存判定为 `blocked` 的镜头仍会生成任务文件，但任务内容只允许停止和报告缺失项，不允许 Claude Code 启动 ComfyUI 队列。
