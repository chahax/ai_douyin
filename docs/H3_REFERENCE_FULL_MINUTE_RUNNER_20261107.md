# Ref2VA 一分钟成片串行执行器（2026-11-07）

本执行器只消费已经冻结的四份 v20 delivery 计划。每段重新绑定同一组五张已审核参考图（三个人物正面及房间正面、侧面），使用 Ref2VA；不构造新图、不调用编剧或 motion 模型、不接续旧 FL2VA 片或 8.7 秒小样。四段各 362 帧、736×1312、24 fps，合计 1448 帧、60⅓ 秒，最终音频 48 kHz 双声道、2,896,000 个有效采样。

入口：`scripts/run_h3_reference_full_minute_v20.py`；实现：`src/content_factory/visual_h3_reference_full_minute_v20.py`。默认 `status` 只读。生产根为 `data/video_generation/h3_reference_full_minute_20261107_v1`；资产 `MANIFEST.json` 保留，执行计划另存 `RUNNER_PLAN.json`。

## 已实现边界

- `prepare` 逐份核对原 Seedance REQUEST、原提示词、经 root 审核的参考机制适配稿、对白逐字及顺序、四份 delivery 计划、五槽 Ref2VA 图与来源。原稿和适配稿分别记录 SHA，不声称适配后仍与旧稿完全相同。
- `tick` / `execute` 仅通过既有 delivery 的 submit / poll / collect。已有原生 ID 优先续收；结果未知、失败、中断、内容拒绝均不重新 POST。进程退出后从冻结计划和原 ID 续接。
- 并发锁覆盖本执行器及四个 delivery 的 `RUNNER.lock`，单段 worker 未退出时不得同时启动总执行器。
- `NATIVE_IDS.json`、追加式 `job_ids.txt` 和 `LOG.md` 保留每段唯一原 ID。ID 先持久化，再进行可能较慢或失败的 CPU ASR。
- 每段 technical_saved 后自动运行 CPU 抽帧、最后一帧及 ASR。CPU QA 出错保留原片，只允许 `qa` 重跑 CPU，不重新生成媒体。
- 四份 delivery 必须精确绑定同一个 v21 reuse manifest 和相同的五张图。每次提交前仍轻核四份冻结 PLAN、图、提示词和审核文件；原 delivery 的提交门负责完整重核这个共同 manifest、两份 donor 与参考图。监督器不再另外为其余三段重复深验。合成前只做一次共同来源的完整深验，再核四份原生结果。原 PREPARATION 和初版源码逐字归档，新 PREPARATION 明确绑定前代、最终 CPU 测试与新源码；RUNNER_PLAN 未改。
- 进入下一段前必须有 root 实看审核。审核文件绑定原 ID、视频 SHA、适配提示词 SHA、全局参考集合 SHA、执行计划 SHA、CONTACT、原生最后帧和实际 OBJECTIVE_QA。没有审核继续有限轮询；明确拒绝则停止。
- 四段原生文件均齐、四段 root 审核通过、另有四段合成审核后才允许 `assemble`。核实四个独立原 ID、文件和源路径，逐段复核实际解码帧数和时钟，才调用既有纯 CPU 合成与最终时钟校验 helper。未登记的既有成片不覆盖。
- 暂停不阻止已知原 ID 收存，但阻止新提交。轮询和总等待有界；到期或 KeyboardInterrupt 不删除原 ID。

## 运行

准备已冻结输入（仅 CPU，未提交媒体）：

```powershell
.\.venv\Scripts\python.exe scripts/run_h3_reference_full_minute_v20.py prepare --run data/video_generation/h3_reference_full_minute_20261107_v1 --manifest data/video_generation/h3_reference_full_minute_20261107_v1/MANIFEST.json --audit data/video_generation/h3_reference_full_minute_20261107_v1/PROMPT_ADAPTATION_AUDIT.json --prompt-approval data/video_generation/h3_reference_full_minute_20261107_v1/ROOT_PROMPT_APPROVAL.json --authorization data/video_generation/h3_reference_full_minute_20261107_v1/USER_AUTHORIZATION.json
```

确认独立 S01 worker 已退出后，由 root 启动或续接：

```powershell
.\.venv\Scripts\python.exe scripts/run_h3_reference_full_minute_v20.py execute --poll-seconds 30 --max-seconds 86400
```

CPU QA 单独重试和合成分别为 `qa --segment S01`、`assemble`。它们都不会重新提交视频；assemble 在未满足全部审核与时钟门时拒绝。

## Root 审核格式

每段：`segments/S01/ROOT_SEGMENT_REVIEW.json`（其他段替换编号）。所有文件绑定均为绝对路径及实际物理文件 SHA256。

```json
{
  "schema": "root_reference_segment_review/v20",
  "segment_id": "S01",
  "shot_id": "S01",
  "prompt_id": "原生 ID",
  "video": {"path": "原生视频绝对路径", "sha256": "实际 SHA"},
  "source_prompt_sha256": "适配稿 SHA",
  "global_references_sha256": "RUNNER_PLAN 全局参考 SHA",
  "runner_plan_sha256": "RUNNER_PLAN 物理文件 SHA",
  "reviewed_by": "root_agent",
  "approved_for_next": true,
  "evidence": {
    "contact": {"path": "CONTACT.jpg 绝对路径", "sha256": "实际 SHA"},
    "last": {"path": "RESULT.files.last.path", "sha256": "实际 SHA"},
    "asr": {"path": "OBJECTIVE_QA.json 绝对路径", "sha256": "实际 SHA"}
  }
}
```

整部合成前：`ROOT_FINAL_REVIEW.json`。

```json
{
  "schema": "root_reference_final_review/v20",
  "reviewed_by": "root_agent",
  "approved_for_assembly": true,
  "runner_plan_sha256": "RUNNER_PLAN 物理文件 SHA",
  "global_references_sha256": "RUNNER_PLAN 全局参考 SHA",
  "native_ids": ["S01 ID", "S02 ID", "S03 ID", "S04 ID"],
  "video_sha256": ["S01 SHA", "S02 SHA", "S03 SHA", "S04 SHA"]
}
```

这只允许按已审原段合成。最终成片仍标记为需要 root 整体审看，不授予发布资格。

## CPU 验证

预览开关加入前测试文件 `tests/test_visual_h3_reference_full_minute_v20.py`：27 passed，22.19 秒，证据 `data/qa/h3_reference_full_minute_shared_reuse_final.xml`。包含协议与来源篡改、逐段审核、已有 S01 接管、未知不重派、等待预算与中断、锁竞争、CPU QA 失败原 ID 保留、四段独立原片/合成门、同一 manifest 的一次深验与四段轻验、源或图片改变仍阻止 POST、前代执行器审计，以及实际 CPU ffmpeg 小尺寸四段时钟测试。初版 19 项为历史证据，不与这 27 项累加。测试中没有生产视频提交；小尺寸时钟夹具明确为合成测试，不是正式成片。

本文件不把程序测试、技术收存或 CPU ASR 等同于内容验收。实际生产状态以 delivery 原 ID 和 root 审核为准。

## 用户明确要求的诊断预览（v23）

用户后续明确要求“你不用拦，我需要看的是自动化出来的成片，分析是调整还是换线路”。原话在 `USER_DIAGNOSTIC_PREVIEW_REQUEST.json`。因此新增显式诊断预览开关，保留原 S02 的视觉拒绝，不进行返修或重生成：

```powershell
.\.venv\Scripts\python.exe scripts/run_h3_reference_full_minute_v20.py preview-enable --request data/video_generation/h3_reference_full_minute_20261107_v1/USER_DIAGNOSTIC_PREVIEW_REQUEST.json
```

此命令仅冻结 `USER_PREVIEW_OVERRIDE.json`，绑定用户原话、原 RUNNER_PLAN、已知原 ID/结果和原 false 审核；不提交或轮询媒体。原独立 worker 退出后，同一 `execute` 可以继续原 S03/S04，技术收存后不再等待语义通过。未知、原 ID、来源、锁、参考图和时钟保护保持；所有 false 审核不改为 true，状态仍列出 `quality_failed`。

原四段齐全并完成 CPU QA 后，诊断合成命令为：

```powershell
.\.venv\Scripts\python.exe scripts/run_h3_reference_full_minute_v20.py assemble-preview
```

输出名 `DIAGNOSTIC_PREVIEW_736x1312.mp4`，回执 `DIAGNOSTIC_PREVIEW_RESULT.json` 标记 `diagnostic_preview=true`、保留 `quality_failed/quality_unreviewed`，`production_approved=false/publication=false`。原普通 `assemble` 的四段 root 通过和终审门不变。废弃 v22 选片草案已移到 `data/qa/proposals/v22_selection_abandoned_20261107`，未接线、未运行。

本次最终合并回归：33 passed，18.54 秒，0 失败/跳过；证据 `data/qa/h3_reference_full_minute_diagnostic_preview.xml`，包含原 27 项及预览继续、未知不重派、原拒绝/原话/源文件篡改拒绝、诊断标签和合成时钟。与历史计数不累加。
