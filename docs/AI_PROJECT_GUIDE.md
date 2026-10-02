---
doc_status: current
doc_category: model_navigation
last_reviewed: 2026-10-03
runtime_scope: v23_baseline_with_unregistered_offline_plan_repairs
---

# 大模型项目分析与操作导航

本页供进入仓库的大模型或开发助手定位项目、分析任务并选择现有执行入口。核心目标是
AI 剧本与视频制作，重点支持文本阶段和视频片段的暂停、查看、返修及恢复。
本页提供导航和证据核对方法；具体授权、规则和合同仍来自用户、任务绑定及下面的权威入口。

## 最小阅读包

| 顺序 | 阅读内容 | 要解决的问题 |
|---|---|---|
| 1 | [AGENTS.md](../AGENTS.md)与当前会话 | 用户允许做什么，视频与发布审核如何执行 |
| 2 | [项目介绍](PROJECT_INTRO.md) | 产品当前以什么为核心，研究/运营处于什么位置 |
| 3 | [方向报告](../data/qa/creative_platform_refactor_20261002/direction_report.html) | 重构目标与用户的分段调试需求 |
| 4 | [当前实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md) | 已实现合同、治理版本、门禁和 F01–F07 状态 |
| 5 | [系统架构](SYSTEM_ARCHITECTURE.md)与本页的代码表 | 到哪些模块核对实际行为 |
| 6 | 目标任务的 state.json、materials.json、阶段/媒体回执 | 本次任务实际绑定什么、停在哪里、哪些结果可复用 |

若只分析项目，先读前五项并核对相应代码；未指定具体任务时不要随意选一个历史 run 当作当前任务。
若恢复任务，先读第六项再决定命令，不凭最新文档推断旧任务采用了新规则。

最新用户要求与既有有效授权优先。冲突时查清日期、任务范围和冻结身份，并把无法核实的部分记为未知。
当前实现描述工作目录；治理包和 run 中保存的合同、请求及审核决定描述它们各自的版本。
单片特许、历史方案、目录名与旧通过记录都不能扩大当前权限或替代本次证据。

## 产品方向与完成范围

主链为：创作简报/故事来源 → 完整剧本与复审 → 导演安排与分段分镜 → 实际请求预览 →
明确生成当前段 → 用户审核 → 批准原尾帧续段 → 合成 → 用户整片审核 → 独立发布及核验。

核心流程与已发现 P1 问题已有离线闭环。v23 修复在途反馈被保存覆盖：通过短状态提交锁、不可变命令、
派发门和实际消费反馈 ID 解决；新反馈继续待修，原调用、token、返修及失败预算不重置。

F02 页面完整操作链/文本派发前预览、F03 执行锁及旧环境恢复、F04 核心责任拆分和 F05 显式字段来源
仍待完善；F06 人工质量和 F07 真实服务/媒体格式/浏览器链路仍待验收。当前包 28 候选、0 人工金标、
0 合格留出，不能宣称创作质量或收益提升。后续状态只在证据到位后更新[当前实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md)。

## 2026-10-03 离线计划修订

v23基线之后新增了状态组前提、schema字段隔离、manifest绑定补丁校验与完整计划内容返修修复，
见[证据分类、最小修复及分工评估](CREATIVE_PLAN_EVIDENCE_AND_REPAIR_20261003.md)。
这些改动尚未注册为新的生产治理包；默认目录仍为冻结v23。当前源码与v17/v23绑定不符时，
调用前门禁必须停止，不能改写冻结哈希或静默迁移。测试使用独立假服务治理夹具，
离线通过不表示真实创作质量通过。旧任务仍为needs_attention，预算及历史不变。

## 版本与默认值

- 当前新治理任务默认注册目录为 `data/creative_governance/20261002_v23_feedback_consistency`。
  这是治理包版本，不是所有任务的提示词或审核版本。
- [运行入口](../scripts/run_creative_workflow.py)的普通新原创默认模型分工为创作/审查配置，文本审核通常是 v5；
  [核心运行器](../src/content_factory/creative_workflow.py)的生产协议未显式指定时仍可为 legacy。
- 新治理任务必须显式采用 `--production-protocol governed_production_v1` 与
  `--review-policy-version evidence_review_v6`，并满足对应模型/编剧配置约束。当前页面不提供完整协议选择。
- 恢复旧任务沿用 `model_profile`、`writer_prompt_version`、`review_policy_version`、`production_protocol`、
  `rule_registry_binding`、材料和预算；不能因仓库现在是 v23 就补写新绑定。
- 新任务 CLI 的预算取 [v5 配置](../config/creative_workflow_budget_v5.json)：20 次调用、500000 reported tokens、
  8 次结构修复、5 轮共享内容返修。旧任务继承原值；内容返修与全文复审均占调用预算。
- 默认同稿视频失败上限为 10，技术失败和用户拒绝按现行媒体账本累计。新故事使用既有登记入口，
  同稿不能通过换目录、改焦点、删登记或改状态重领额度。
- 源码/规则绑定不符时在调用前停止。旧环境恢复或只读的边界见 [MIGRATION.md](../data/creative_governance/20261002_v23_feedback_consistency/MIGRATION.md)。

## 代码定位

| 问题或责任 | 先读实现 |
|---|---|
| 来源、简报、任务登记和预算参数 | [run_creative_workflow.py](../scripts/run_creative_workflow.py)、[creative_workflow_inputs.py](../src/content_factory/creative_workflow_inputs.py) |
| 核心文本编排与模型调用 | [creative_workflow.py](../src/content_factory/creative_workflow.py) |
| 完整新稿返修 | [creative_full_script_revision.py](../src/content_factory/creative_full_script_revision.py) |
| 导演与分段安排 | [creative_segmented_director.py](../src/content_factory/creative_segmented_director.py) |
| 自动/断点/单步阶段控制 | [creative_stage_runtime.py](../src/content_factory/creative_stage_runtime.py) |
| 冻结输入、结果与字段投影 | [creative_stage_contracts.py](../src/content_factory/creative_stage_contracts.py) |
| 当前/历史版本、反馈与 resolution | [creative_stage_debug.py](../src/content_factory/creative_stage_debug.py) |
| 在途反馈、停止及派发顺序 | [creative_state_store.py](../src/content_factory/creative_state_store.py)、[creative_execution_control.py](../src/content_factory/creative_execution_control.py) |
| 文本复核证据与交接门 | [creative_review_gate.py](../src/content_factory/creative_review_gate.py)、[creative_governed_runtime.py](../src/content_factory/creative_governed_runtime.py) |
| 预览、候选、责任反馈及合成 | [creative_media_workbench.py](../src/content_factory/creative_media_workbench.py) |
| 单段提交、原 ID 查询与失败账本 | [creative_segment_execution.py](../src/content_factory/creative_segment_execution.py) |
| 用户媒体决定和批准身份校验 | [media_review_policy.py](../src/content_factory/media_review_policy.py) |
| 成片交付、发布核验与运营回接 | [creative_delivery.py](../src/content_factory/creative_delivery.py)、[douyin_adapter.py](../src/platform_adapter/douyin_adapter.py) |
| 人工样本、留出、评分和费用 | [creative_quality_evidence.py](../src/content_factory/creative_quality_evidence.py)、[creative_evaluation.py](../src/content_factory/creative_evaluation.py) |
| 创作页面 | [creative_workflow_dashboard.py](../src/web/creative_workflow_dashboard.py)、[creative_workbench_panel.py](../src/web/creative_workbench_panel.py) |
| 队列和迁移就绪 | [queue.py](../src/scheduler/queue.py)、[runner.py](../src/scheduler/runner.py)、[migration.py](../src/shared/migration.py) |

用 `rg` 按字段、函数或错误定位，再读相关调用链；核心 runner 较大，避免一开始加载整个文件和全部 QA 目录。
模型角色、模板和默认配置应沿实际调用的导入路径核对，不能根据文件名猜测正在使用哪个版本。

## 执行入口与副作用

所有脚本路径相对仓库根目录；命令参数以该版本的 `--help` 和绑定回执为准。
下面是操作导航，不自动授予外部调用权限。用户已授权的范围持续有效，执行前核对该范围及预算即可。

| 入口与操作 | 行为及副作用 |
|---|---|
| [debug_creative_workflow.py](../scripts/debug_creative_workflow.py) RUN inspect / compare | 本地只读阶段、版本和差异，不调用模型 |
| 同入口 feedback / stop / resume | 记录本地命令；feedback 传所见双哈希，resume 只解除停止意图 |
| [run_creative_workflow.py](../scripts/run_creative_workflow.py) --next-stage / --stop-after-stage | 执行文本模型并可能付费；按原参数恢复，同一运行器保留预算 |
| [compile_creative_seedance_segments.py](../scripts/compile_creative_seedance_segments.py) RUN OUTPUT | 本地编译并冻结预览；返修交接按实际情况使用 --revised |
| [creative_workbench.py](../scripts/creative_workbench.py) RUN prepare-segment | 本地准备单段计划，绑定实际首帧/前段批准原尾帧 |
| [run_creative_seedance_segment.py](../scripts/run_creative_seedance_segment.py) preview PLAN --output-dir DIR | 本地生成实际请求预览并写预览回执，不提交生成任务 |
| 同入口 submit | 明确提交当前段，可能付费；pending 反馈、未知任务、待审或额度门阻止新提交 |
| 同入口 query | 续查已记录原 ID 并更新本地回执，不创建替代任务 |
| creative_workbench.py RUN inspect-media / register-candidate | 本地核对或登记已有候选及来源 |
| 同入口 review-media 或 [review_media_candidate.py](../scripts/review_media_candidate.py) | 按用户实际决定写人工回执；工作台路径还可登记秒点与责任证据 |
| creative_workbench.py RUN assembly-chain / assemble --execute | 核对批准链，显式运行本地 FFmpeg 合成；输出仍待整片人工审核 |
| 同入口 prepare-delivery | 本地生成已批准完整成片的发布预览 |
| 同入口 publish --execute | 对绑定账号执行浏览器发布，产生外部提交及锁 |
| 同入口 verify-publish / collect-operations | 访问原账号/作品核验或取指标，写对应本地回执，不重传 |
| 同入口 collect-quality-case / annotate-quality / freeze-quality / quality-report | 本地采集与评分；人工标签只能引用真实人工判定 |

### 分析任务的安全起点

以下示例只检查本地已有任务。路径及 stage_id 必须替换成实际值：

```powershell
$runDir = 'D:/IT/ai_douyin/data/creative_workflows/实际任务目录'
& '.venv/Scripts/python.exe' 'scripts/debug_creative_workflow.py' $runDir inspect
& '.venv/Scripts/python.exe' 'scripts/debug_creative_workflow.py' $runDir compare --stage writer_script
& '.venv/Scripts/python.exe' 'scripts/creative_workbench.py' $runDir inspect-media
```

不要把分析请求解释为授权新模型调用、视频生成或发布。需要执行时使用当前服务/CLI，并保存实际回执，
不要手写成功状态、人工批准、resolution、状态索引或预算账本。

## 任务证据读取顺序

默认创作目录在 `data/creative_workflows/`；实际目录以逻辑任务登记和用户指定为准。

1. `materials.json` 与 `state.json`：来源身份、协议、模型/提示版本、预算、调用、停点和待办反馈。
2. 对应 `<stage_id>.json`：真实请求、原响应、技术校验和输出；已归档记录用于核对历史。
3. `.creative_debug/inputs/`、`results/`、`artifacts/`、`index.json`：冻结输入/结果、不可变版本和索引。
4. `.creative_debug/feedback/` 与 `.creative_debug/state_commands/`：用户原话、精确版本、resolution 和命令顺序。
5. `.creative_debug/dispatch_permits/` 及审核包/决定：派发许可、消费反馈、文本核实与交接依据。
6. 媒体 `receipt.json`、用户审核回执、源版本链、原视频/原始尾帧：原任务 ID、技术/内容状态和批准身份。
7. 交付目录的发布回执、原声明操作证据、作品核验和运营文件：核对准确账号、作品与未决状态。

记录 schema、来源路径、哈希、阶段和时间。目录叫 final、passed、complete 或截图存在都不自动证明对应验收完成。
不要批量读取无关真实任务、认证信息或所有样片；报告中只保留必要证据，密钥和会话凭据不写入文档。

## 状态如何处理

| 状态或条件 | 正确下一步 |
|---|---|
| debug_breakpoint | 正常断点；按原目录、材料和预算运行下一阶段 |
| user_stop / execution_control.action=stop | 保留在途结果；resume 后再按原入口恢复执行 |
| debug_revision_required / pending must_fix | 先返修最早责任阶段，下游不得新增调用；在途响应保留 |
| script_review_pending 或聚焦审核待核实 | 阅读当前全文/证据包，按现有核实合同记录真实判断，不手写放行 |
| needs_attention | 查看 last_error、回执及绑定，先定位具体原因 |
| outcome_unknown 或未知外部调用 | 有 ID 续查原任务；无 ID 对账，不自动重试或换目录 |
| blocked_before_dispatch / blocked_before_submit | 核对是否确未派发及保留的预留；按实现恢复，不删除记录补额度 |
| media_handoff_pending_capability / reviewed_revision_media_handoff_pending_capability | 已形成文本交接；核对能力、源版本、文本门及计划后再准备媒体 |
| technical_status=succeeded + awaiting_human_review | 用户审查视频，助手只核对服务和文件；不写内容 passed |
| approved / rejected | 核对真实用户决定和原片/尾帧身份；拒绝回到有证据的责任阶段 |
| post_publish_verification_pending / awaiting_verification | 核验原作品并保留提交锁，不能重传 |
| 源码/规则/输入哈希不符，预算耗尽或遗留执行锁 | 在新增调用前停止，核对原绑定、进程、原 ID 和回执，按恢复边界处理 |

停止不是取消远程调用。短提交锁的系统释放不等于文本/媒体执行锁可以直接删除。
F03 工具未完成前，对未知外部副作用不做盲重发；也不能用 `--retry-unconfirmed-transport` 自动绕过未决结果。

## 内容和发布不可跨越的边界

- 视频内容由用户人工审核。助手不主动抽帧、听看、ASR 或调用音画审核模型，不从技术成功推断通过。
- 用户明确批准当前原片和服务原始尾帧后才续下一段，身份变化使批准失效。历史单片声音待审特许不推广。
- 文本返修保持主题与用户要求，采用本次完整新稿并复审；不把旧拍与新拍拼接伪装成模型完整输出。
- 文本验证只证明明确合同和证据，不能把情绪标签、反应窗口字段或连续性自动解释为实际表演效果。
- 合成后仍须用户整片批准，发布必须引用当前批准的完整成片。
- 发布采用浏览器，主动选择并读回平台“内容由AI生成”；话题、文案及平台自动标签不替代主动声明证据。
- 虚构剧情简介首部为“剧情虚构，非真实事件。”；真实纪实需显式关闭 fictional_story，仍执行实际适用的声明要求。
- 发布待核验不记最终完成，不解除锁或重传；仅回接绑定账号与准确作品，缺失指标为 null。

## 验证与分析输出

反馈边界先看 [test_creative_feedback_consistency.py](../tests/test_creative_feedback_consistency.py)；
版本/重放、媒体/交付和治理分别看 [test_creative_stage_debug.py](../tests/test_creative_stage_debug.py)、
[test_creative_remaining_refactor.py](../tests/test_creative_remaining_refactor.py)和
[test_creative_governed_protocol.py](../tests/test_creative_governed_protocol.py)。

执行离线验证时使用独立数据库、Mock/FakeClients、断网环境和新 QA 输出目录，保留作者原回执。
测试应覆盖实际触发及阻断/恢复行为。文档更新核对链接、入口参数和冻结哈希即可，通常无需重跑模型或全部业务回归。

[v23 作者回执](../data/qa/creative_platform_refactor_20261002/feedback_consistency_v23/acceptance_report.html)
含 756 项通过；[独立复核](../data/qa/creative_platform_refactor_20261002/v23_confirmation/confirmation.json)
另运行 18 项边界，未全量重跑。历史 real receipt replay 未在该验收执行或计通过；
保留的兼容限制以验收报告为准。不要把不同人的计数相加，或把夹具的人为批准计入质量金标。

分析结论应先给当前核心功能/停点，再分开列实证缺陷、实现缺口、架构改善和真实证据缺口。
每项注明触发条件、源文件/回执、影响、建议及验收标准；已验证与推断在对应条目内标清。

交接时至少保存：用户目标与授权、run 路径、任务/协议版本、当前阶段及待修反馈、原外部 ID、累计预算、
改动文件、已运行检查、未运行内容和下一步。源码/规则改动按治理约束新建版本，冻结旧包不改。
本导航及工作目录说明可以更新，但不能将文档变更伪装成旧任务已经迁移或功能已完成。


## 2026-10-03 响应验收与模块合同离线修订

已实现统一响应故障分流；缺工具、截断、空正文及未知结果不再自动重派，原响应与用量保留。
新增整片规划/局部表演/确定性编译的显式离线合同，检查跨拍状态、对白表演窗口及下游失效。
见[实现、合同与验证边界](CREATIVE_RESPONSE_AND_MODULAR_CONTRACT_20261003.md)。
新合同未接生产派发，未注册生产治理包，旧任务绑定、预算和历史不变。
旧运输重试参数保留解析兼容，不再绕过未知请求对账；测试通过不表示创作质量通过。


### 修复后真实文本接口测试（2026-10-03）

真实调用3次已使用原任务剩余额度：共享实际24/24、379026 reported tokens，父冻结state仍保持21/24。微型工具通过，两次整片规划合同失败；局部表演、全文复审和制作交接未完成。不得只读父state再次使用3次额度。详细证据、源码演进和离线修复见 [生产接口测试报告](CREATIVE_PRODUCTION_INTERFACE_TEST_20261003.md)。旧v17/v23绑定未迁移。


### 六组小上下文规则三轮真实对比（2026-10-03，新增授权18次）

用户明确授权新增最多18次后，按冻结矩阵执行三轮。基础Schema业务合同0/3；中文编号/路径/关系说明及其四种增强版本各3/3，全部正常工具返回。只证明该小任务的规则遵守，未形成整片导演计划、局部表演或制作交接，也不证明服务严格解码或创作质量通过。

该规则矩阵结束时共享实际累计42/42、398343/500000 reported tokens，剩余调用0；原父state及原24次诊断记录保持历史值，不能从它们重新领额度。未迁移v17/v23或重置账本。本轮成功安全envelope已保存，历史长分析服务端原因仍未知。详见[规则对比报告与产物](MINIMAX_SMALL_CONTEXT_RULE_TEST_20261003.md)，离线回归581项通过。

### 模块分工真实试跑与停止位置（2026-10-03）

用户已明确新增MiniMax文本调用不逐次申请；保留原累计500000 reported tokens上限。
矩阵结束后的新增7次真实文本调用，使共享累计达到49次、490913/500000，剩9087。
最新完整新稿尚未完成有效全文复审：DeepSeek在11000输出上限处截断，响应被拒绝且没有自动重发。
没有可采用的整片导演计划、逐镜物理表演或制作交接，不能记创作质量通过。
线性steps及多镜源引用合同已离线验证，物理编译适配仍待完成；旧v17/v23、预算和回执未迁移或重置。
详见[实际回执、原因分类、183项验证与下一最小改动](CREATIVE_MODULAR_BD_TRIAL_20261003.md)。
