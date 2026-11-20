# 通用 opt-in 旁白前置节点

新入口不依赖历史实验的四条或六条调用记录，也不要求固定小说、固定 run 路径。

```powershell
.venv/Scripts/python.exe scripts/run_narration_prevideo_agent.py prepare --run D:/path/to/new_run --spec D:/path/to/RUN_SPEC.json
.venv/Scripts/python.exe scripts/run_narration_prevideo_agent.py run --run D:/path/to/new_run
```

`RUN_SPEC` 必须显式提供：

- `case`：v2 场景、语义交流组、原句/SHA、原子事实、知情与合法位置的文件绑定。
- `call_budget` 与 `authorization.max_text_calls`：本次独立文本预算；`authorization.publication=false`。
- `sources`：唯一 `id`、基准 `source_case` 绑定、按原对白顺序的 `quote_ids`、每个原动作 span 的 `action_span_map`。
- 可选 `adopted_receipt`：复用已确认的真实文本结果；原生候选（有限规范化后）、独立审核及用量须与保存的 native responses 一致，不能只核内部摘要。

通用 API 是 `narration_prevideo_agent_v1.prepare()` 和 `execute()`。线路为 fresh case → MiniMax 判决 → 有限格式规范化 → 独立语义审核 → 有界返修 → receipt → 实际新 SOURCE_CASE 或机器通知。消费者直接调用 `narration_source_case_adapter_v1.materialize()`，实际写入音轨角色、旁白/口述模式、时窗、原文 spans 与源动作锚点。

prepare/execute 共用非阻塞的跨进程 OS 锁。派发前再核实际 START 数量、所有前次终态、冻结 spec/代码 SHA 与授权预算，避免并发补发 review 或越额。未知调用保留 START/原 ID，不重发。完整 receipt 重入只做验证和消费，不再外呼；预算用尽且尚未通过独审，输出 `needs_semantic_repair` 而非 ready。

默认 transport 使用既有配置的 MiniMax-M3.1-Flash、medium/adaptive 流客户端，`max_retries=0`。每次保存 REQUEST、START、RESPONSE、用量和结果，不写密钥。支持注入 transport 做离线全节点回归。

本轮通用 fresh judge/review/repair 用注入 transport 测试；没有为了这个入口新增第七次真实模型调用。真实验证采用已接受的 C005/C006 结果，在 `data/corpus_production_trials/20261113_narration_generic_adopted_v1/` 新建 `call_budget=0` 的 run，验证原生证据后消费。S03 得到真实新 SOURCE_CASE 及既有 renderer→9ref positive graph CPU 证明；S04 保持严格 after 时得到 `needs_segment_split`。该新 run 无 calls 目录，重入没有外呼。

这是独立可复用的前置节点，尚未替换全局旧默认，也未修改当前冻结 H3 分钟。新 SOURCE_CASE 后仍需时长匹配、完整资产、真实前段尾帧及正常派发审批；CPU 图不等于新成片通过或声纹固定。
