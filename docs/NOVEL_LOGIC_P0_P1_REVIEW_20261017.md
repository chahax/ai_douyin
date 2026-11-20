---
doc_status: implementation_review
doc_category: novel_branch
last_reviewed: 2026-10-17
runtime_scope: novel_logic_v4_offline_domain_core
---

# 小说场记与问题核实：P0/P1 实施及主审

用户要求“你验证开发”后，按[开发计划](NOVEL_LOGIC_P0_P1_IMPLEMENTATION_PLAN_20261017.md)实现独立 v4 领域核心和离线 CLI。子 agent 分别开发合同、场记规则、问题核实与程序决定；主 agent 负责组合入口、构造样本、旧小说证据回放、跨模块审查和验收。另有内部独立 agent 尝试反例。

本轮没有把源码送入 Claude Code 或外部模型。此前“仅发送方案文档”的范围保持；本轮没有新的 MiniMax、DeepSeek、媒体或发布请求。

## 实际实现

| 代码 | 实际行为 |
|---|---|
| `src/content_factory/novel_logic_contracts_v4.py` | 同源同稿产物头、场记事件、九维全文审查、逐项核实、分集/导演消费最小字段校验 |
| `src/content_factory/novel_scene_logic_v4.py` | 检查明示连续事件中人物在场、姿态、位置及独占持有的结构化状态边界，输出待核实候选 |
| `src/content_factory/novel_logic_adjudication_v4.py` | 同根因去重、核实处置、原生 pass 门、重大未决及完整返修/全文复核路由、只读容量检查 |
| `src/content_factory/novel_logic_workflow_v4.py` | 真正组合上述模块；场记候选进入同一个程序决定；报告案例分母和故事级拆分 |
| `src/content_factory/novel_logic_replay_v4.py` | 沿旧冻结验证已保存 v3 请求/响应，逐份核对原生稿、全文审查及同源同稿覆盖，原结论不改 |
| `scripts/run_novel_logic_v4.py` | 独立本地 `diagnose`、`benchmark`、`replay-v3`；没有生产 execute 动作 |

场记模块**不从自由文学文本抽取真值**。它消费显式结构化事件，检查结果仍需对照完整正文和稿件核实。普通回忆、电话、共同持有、相对空间、同事件概述/展开和持续动作不会仅因字面不同被确认为重大问题。绝对位置比较只用于已明确标注的稳定位置与同一参考框架，不要求小说猜米制坐标。

分集与导演部分目前只冻结最小字段和引用合同，没有实现跨章检索、实际导演分段、素材绑定或媒体制作。

## 主审发现与实际修复

1. **场记自冲突曾可能被原生 pass 掩盖。** 同一人物在同一相位同时被明示为站立、坐着时，没有边界候选便可能放行。现在辅助场记返回技术 `needs_attention`，组合入口和 gate 消费分析失败状态；不伪造作者内容错误或要求编剧改 JSON。
2. **候选无法从“可能重大”核实成“确认重大”。** 原问题的严重度必须保留，但处置原来无法表达核实后的影响。现在处置可用成对 `effective_severity` / `effective_severity_certainty`，保留具体依据和原问题；明确重大进入完整返修，明确轻微可按建议保留，未知不能默认降级。
3. **候选可能在适配时被漏传。** 每个场记候选现在必须恰好对应一个 `origin_candidate_id` 问题，并核对来源、稿件、事件和根因。遗漏、重复映射或旧候选混入停止。
4. **minor 标签不能掩盖既有阻断。** 原问题仍明确阻断时，普通 advisory 和非阻断布尔值不能将其静默放行。问题驳回必须逐项记录依据。
5. **已知轻微意见曾过度触发核实。** 只有成立性未决、影响已确认 minor 且原问题/处置均无阻断时，现在随原生 pass 保留，不追加付费核实。严重度未知、可能重大或任一侧仍阻断继续拦截；原生 revise 仍须重新全文通过。

DeepSeek 原生 revise 即使意见全部被驳回，仍须对同一完整正文和完整稿重新全文审核，取得新的原生 pass。完整结果已经 pass 时，零剩余调用容量可本地交付；仅当下一步需要新请求时才检查对应核实/全文审查/返修及总调用、token 容量。本模块只给下一步建议，不领取或消费生产 claim。

## 验证及证据

证据目录：`data/qa/novel_logic_p0_p1_20261017`。最终验收 **509 项通过、0 失败、0 跳过**：新模块组合 262 项（合同75、场记54、程序门96、主审组合15、独立反例22），旧入口247项。原始结果为 `FINAL_NEW_TESTS.xml` 与 `LEGACY_TESTS.xml`；262包含独立22项，不重复相加。代码/接口身份见 `FINAL_REVIEW_CHECKPOINT.json`、`INTERFACE_FREEZE.json`。

- 新合同、场记、问题门和实际组合 CLI 的测试包括：原生 pass 后新问题、原生 revise 全驳回、重大未决、候选核实后的升级/降级、错源错稿、缺辅助产物、技术未知、容量耗尽和零余量完整结果。
- 旧 v3 原生文本与 v1/v2 相关 **247 项回归通过**，见 `LEGACY_TESTS.xml`；原模块未修改。
- `tests/fixtures/novel_logic_v4/rule_corpus_v1.json` 保存 **60 对 / 120 个**预先标注的明确状态规则案例，6 个构造场景；80 个开发案例、40 个故事 ID 留出案例均符合预期。正例候选 60 个均检出，对照 60 个无错误候选。
- 这些场景共享十类规则模板；留出仅隔离故事 ID，不代表未见自然语言故事泛化。标签是构造状态真值，不是独立人工文学金标，不声称达到架构方案中的真实语义检出率、误报率或判定覆盖率。保留诊断还包括初事件未声明连续性等正常未比较项，不能把其数量解释为重大歧义率。
- `V3_CLI_REPLAY.json` 来自实际独立 CLI 对旧运行的只读回放：第一章 6045 字符，三稿分别 4737 / 7064 / 6889 字符；三次审核均九维、同源同稿证据有效，原生结论仍全部 `revise`。这只证明旧证据和覆盖，不为旧语义判断背书，也未自动补写 v4 场记或改判通过。
- 保护基线覆盖 566 个旧文件，包含原 185 项保护清单、旧生产目录及冻结源码；结束时逐文件核对，不覆盖原停止、账本或原架构审查版本。

本书仍为累计 **20 次 / 310301 reported tokens**、调用容量 0、`content_revision_exhausted`，未决为空。没有新增正式 `SCREENPLAY`、`OUTPUT_MANIFEST` 或生产导演交接。

## 本地复现

```powershell
.\.venv\Scripts\python.exe scripts/run_novel_logic_v4.py diagnose --input data/qa/novel_logic_p0_p1_20261017/OFFLINE_SCENE_CONFLICT_INPUT.json
.\.venv\Scripts\python.exe scripts/run_novel_logic_v4.py benchmark --input tests/fixtures/novel_logic_v4/rule_corpus_v1.json
.\.venv\Scripts\python.exe scripts/run_novel_logic_v4.py replay-v3 --run-dir data/novel_adaptation_production/20261017_plaintext_v3/run
```

`--output` 仅新建结果，不覆盖既有文件；回放输出不能写进旧生产目录。CLI 返回 0 表示本地诊断/回放完成，不表示小说内容或视频通过。

`diagnose` 的 native-evidence 布尔字段是调用方声明，本入口不替调用方验证原生回执真实性。即使领域 gate 为 pass，根结果仍是 `offline_diagnostic`，明确 `production_dispatch_allowed=false`、`production_handoff_created=false`、`human_approved=false`，不创建正式文本交接。示例中的证据标记是构造夹具，不能当服务回执。

## 阶段边界与后续

本轮完成 P0 最小接口/规则案例及 P1 离线领域核心、组合入口和主审。自然语言模型场记抽取、真实案例独立标注及语义质量验收尚未完成；构造案例不能代替它们。

P2 还需独立环境验证 LangGraph、把冻结原生请求/响应验证与唯一 claim 实际接入新模块，并接网页进度/恢复；当前网页新任务仍沿原 v3，不静默替换。P3 需要有效新冻结和真实容量后验证新完整稿、核实、整稿返修及全文复审；P4 才进行实际导演分段，P5 按既有权限进入媒体和业务链路。旧书停点不因本轮开发、框架或新目录改变。
