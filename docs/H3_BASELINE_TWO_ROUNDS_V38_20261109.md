# v38：确认的 v34 基线，两轮完整分钟与中间总体审核

新根 `data/video_generation/h3_baseline_two_rounds_20261109_v1`。用户原话保存在 `ROOT_USER_SCOPE.json`，新共用授权逐字引用它；八个视频、每轮四个是工程范围，不伪称用户逐字给过次数。零图片生成、零云媒体、零发布，不恢复旧任务或改旧暂停/未知记录。

基线唯一为已确认的 `h3_continuity_full_minute_20261109_v1`，输入来自 `data/qa/h3_baseline_rollback_20261109_v1` 的四份实际 REQUEST 与首图快照。实际模型文字以 `REQUEST.prompt.condition.inputs.prompt` 为字节权威。可读 PROMPT 快照是 Windows CRLF，而实际请求为 LF；差别只记录为展示副本换行转换，不冒充实际提示词改变。

## R1 最小变化

每段实际提示只增加两句：一条无字幕说明，一条按原镜头时间窗指定伙伴、面包或门口视线的复合句。闭眼窗维持原闭眼动作，手部窗沿原近景。不增加通用侧脸、三分之二侧脸、固定机位或多图参考说明。

原分镜、声音独立区、心声闭嘴、人物服装映射、动作与十句台词不重写。`prompts/Sxx.byte_diff.json` 记录两个 UTF-8 字节插入位置，移除后精确恢复真实请求原文；声音区保持连续逐字节相同。

每段模型图从该段实际 baseline REQUEST 深复制。只改 `condition.prompt`、同一 PNG 字节的新 staging 路径，以及四个新输出前缀。baseline seed、模型/编码器/VAE、采样器、调度器、12步、736×1312、362帧、24fps与原生音频接线全保留。每个新 POST 使用新的 client_id 和独立 native ID，不调用图片模型。

```text
python scripts/run_h3_baseline_two_rounds_v38.py prepare --round R1
python scripts/run_h3_baseline_two_rounds_v38.py execute --round R1
```

Root 技术启动记录 `R1/LAUNCH_APPROVAL.json` 使用 schema `h3_baseline_round_technical_launch/v38`，绑定本轮 PLAN、共用授权、`_sources()`、CPU 验收，并填写 `approved_for_technical_execution=true`。

## 四段保存与第二轮

每轮 `shots/Sxx` 保存 workflow、GRAPH_BINDING、实际 REQUEST/CLAIM/RESPONSE/STATE/HISTORY 和 native RESULT；原生四件是 video/audio/first/last。四段均技术保存后自动 CPU 合成 1448 帧 / 60.333333 秒、48kHz / 2896000 样本的完整片，输出 `BASELINE_R1_736x1312.mp4` 及 `FINAL_RESULT.json`。

Root 对第一完整片进行总体视频审核后记录 `R1/ROOT_OVERALL_VIDEO_REVIEW.json`：

```json
{
  "schema": "h3_baseline_overall_review/v38",
  "review_completed_by": "root_agent",
  "overall_video_review_completed": true,
  "allow_prepare_r2": true,
  "final_result": {"path": "实际R1/FINAL_RESULT.json", "sha256": "实际SHA"},
  "reviewed_video": {"path": "实际R1完整片", "sha256": "实际SHA"},
  "findings": []
}
```

这不要求 R1 质量通过。问题和失败内容保留，用来决定第二轮改什么。R1 未完成或未真实绑定总体审核时不能准备 R2。

R2 显式 `ROUND_SPEC.json` schema `h3_baseline_round_spec/v38`，字段为 `round=R2`、`r1_overall_review` 绑定，以及四个有序 `segments=[{id,prompt:{path,sha256},first:{path,sha256}}]`。每段文字和已有首图都由 Root 明确指定；不调用图片生成、不让模型自行选参数，原十句和 baseline seed/其他采样参数仍保留。

```text
python scripts/run_h3_baseline_two_rounds_v38.py prepare --round R2
python scripts/run_h3_baseline_two_rounds_v38.py execute --round R2
```

两片及全部失败/审核证据分别保存。R2 不会自动以另一条路径重发 R1 的未知任务。

## 收存边界

每轮先跟踪已知原 ID，再检查当前源与启动资格。当前授权、提示词变更或暂停只阻新派发；已有 ID 仍按冻结图收存。POST 前冻结 CLAIM，响应不确定保持 unknown，停止后继派发，不盲重 POST。使用既有共享 GPU/input 锁、单 runner 锁与队列门；执行器不重启服务或改模型依赖。

CPU 回归使用独立本地 HTTP 和真实 362 帧 CPU 音视频，验证两个完整 1448 帧测试片、原四件收存、未知保护和 R2 中间审核门；不是新小说成片或语义验收。
