from pathlib import Path
import json,hashlib
from datetime import datetime

ROOT=Path.cwd()
OUT=ROOT/'data/qa/creative_platform_refactor_20261002/documentation_sync_v23'
OUT.mkdir(exist_ok=True)
backups=OUT/'before';backups.mkdir(exist_ok=True)
files={}
meta='---\ndoc_status: current\ndoc_category: mainline\nlast_reviewed: 2026-10-02\n---\n\n'

files['README.md']='''# AI 剧本与视频制作平台

本项目围绕创作简报、完整剧本、导演安排、视频请求预览、逐段生成和用户人工审核运行。
用户可以在文本阶段和视频片段之间暂停、比较版本、提交反馈并恢复；账号研究提供可选输入，
浏览器发布和运营复盘是独立下游。

截至 2026-10-02，核心流程和已发现的 P1 闭环已完成离线验收。v23 修复了运行中反馈丢失，
仍需完善完整页面操作链、执行锁恢复工具，以及真实创作质量和服务运行证据。

## 从这里开始

- [项目介绍](docs/PROJECT_INTRO.md)：产品目标、核心功能与当前阶段。
- [大模型项目分析与操作导航](docs/AI_PROJECT_GUIDE.md)：阅读顺序、代码定位、执行入口和恢复边界。
- [文档索引](docs/README.md)：区分现行说明、专门流程与历史资料。
- [创作平台当前实现](docs/CREATIVE_WORKFLOW_IMPLEMENTATION.md)：现行合同、治理绑定和 F01–F07 状态。
- [操作指南](docs/USER_GUIDE.md)：文本调试、单段候选、人工批准、合成与交付。
- [系统架构](docs/SYSTEM_ARCHITECTURE.md)和[当前能力](docs/CURRENT_CAPABILITIES.md)。
- [创作阶段调试](docs/CREATIVE_STAGE_DEBUGGING.md)：断点、单步、反馈、版本和恢复。

## 执行边界

- 文本自动推进、断点和单步使用同一运行器。必修反馈、待核实审核、未知外部结果或预算不足阻止推进。
- 新治理任务绑定 v23；普通入口的协议默认值和旧任务绑定以实际代码、`state.json` 为准，不能统一改绑。
- 生成服务成功且文件完整保存后，视频内容状态为 `awaiting_human_review`。助手不主动抽帧、听看、ASR 或调用音画审核模型。
- 用户明确批准当前视频及服务返回的原始尾帧后，才可继续紧邻下一段；被拒绝的片段回到有证据的责任阶段修复。
- 合成成功仍等待用户整片审核。发布需要已批准成片、绑定账号、平台主动 AI 声明和虚构说明读回；待核验保留提交锁。
- 同任务恢复保留累计调用、token、返修和本稿视频失败账本。换目录、改焦点或清理登记不产生新额度。
- 文本调用、媒体生成和浏览器发布分别按用户已有授权执行；分析或预览任务不自动触发付费生成与发布。

## 当前证据与下一步

[v23 验收](data/qa/creative_platform_refactor_20261002/feedback_consistency_v23/acceptance_report.html)
保存 743 项核心和 13 项 UI 回执；[独立复核](data/qa/creative_platform_refactor_20261002/v23_confirmation/confirmation.json)
另重跑 18 项反馈边界并核对源码和工件哈希。它们证明相应离线执行行为，真实创作效果和生产全链路仍待验证。

当前优先完善分段工作台并开展人工质量试点；核心责任拆分和字段依赖优化逐步推进。
完整清单见[实现文档的剩余项](docs/CREATIVE_WORKFLOW_IMPLEMENTATION.md#独立复核后的剩余项)。

## 历史路线

2026-09-04 退出生产的 `presenter_anime`、`dual_framepack_active` 和 `single_template`
及其样片保留为历史资产，不能恢复为默认生产入口。通用工作流中的
`video_pipeline=disabled_pending_redesign` 针对这些旧路线；当前创作候选通过上述独立显式入口执行。

[视频流程 V2 历史设计基线](docs/VIDEO_PIPELINE_V2_BASELINE.md)和
[重置归档](docs/archive/2026-09-video-pipeline-reset/ARCHIVE_MANIFEST.md)用于追溯。
'''

files['docs/README.md']=meta+'''# 文档索引

当前主线是 AI 剧本与视频制作平台。阅读现行行为时，从产品方向、当前实现及实际任务回执开始；
历史设计、单片特许和旧治理版本不自动适用于新任务。

## 主线阅读顺序

| 文档 | 用途 |
|---|---|
| [项目介绍](PROJECT_INTRO.md) | 核心功能、用户目标与当前阶段 |
| [方向报告](../data/qa/creative_platform_refactor_20261002/direction_report.html) | 重构方向与产品取舍 |
| [当前实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md) | 已接线功能、版本、审核门和剩余项 |
| [大模型项目分析与操作导航](AI_PROJECT_GUIDE.md) | 代码定位、命令选择、证据核对和恢复规则 |
| [操作指南](USER_GUIDE.md) | 日常文本与镜段操作路径 |
| [阶段调试](CREATIVE_STAGE_DEBUGGING.md) | 断点、版本、反馈和恢复 |
| [系统架构](SYSTEM_ARCHITECTURE.md) | 模块职责与依赖边界 |
| [当前能力](CURRENT_CAPABILITIES.md) | 实现状态与验证范围 |
| [架构状态](ARCHITECTURE_STATUS.md)及[开发进度](DEVELOPMENT_PROGRESS.md) | 已完成机制和下一阶段工作 |

[AGENTS.md](../AGENTS.md)保存用户执行要求。最新会话中的用户授权、任务冻结版本、当前代码与回执
共同决定一次操作是否可执行；导航或历史样片本身不授予新增调用、视频批准或发布权限。

## 专门流程

- [可复用视频创作](REUSABLE_VIDEO_WORKFLOW.md)：简报、完整新稿、表达参考和资产复用；按日期保留演进记录。
- [视频制作记录](SCRIPT_VIDEO_RUN.md)：指定制作任务及其来源、叙事和审核记录；旧审核默认已被最新用户要求替代。
- [动作与对白时序合同](CREATIVE_ACTION_TIMING_CONTRACT.md)：文本计划的动作、交互、摄影和时序。
- [账号绑定与运营维护](operations/ACCOUNT_BINDING_AND_MAINTENANCE.md)。
- [账号内容机会架构](ACCOUNT_CONTENT_OPPORTUNITY_ARCHITECTURE.md)及[热点运营闭环](TREND_OPERATIONS_CLOSED_LOOP.md)。
- [抖音主动 AI 声明](DOUYIN_AI_DECLARATION.md)。
- [Seedance 参考资料](reference/seedance/README.md)：资料快照；实际调用以绑定模型、当前服务合同和回执为准。
- [本地导演台](DIRECTOR_WORKBENCH.md)及[导演稿文本验收](DIRECTOR_PIPELINE_TESTING.md)：具体实验或模块说明，不代表整个平台生产质量已通过。

## 当前验收与治理

- [v23 F01 验收](../data/qa/creative_platform_refactor_20261002/feedback_consistency_v23/acceptance_report.html)。
- [v23 独立反馈边界复核](../data/qa/creative_platform_refactor_20261002/v23_confirmation/confirmation.json)。
- [剩余重构方向](../data/qa/creative_platform_refactor_20261002/implementation_review_v22/review_report.html)：F01 已由 v23 修复；F02–F07 状态以当前实现文档为准。
- [v23 迁移边界](../data/creative_governance/20261002_v23_feedback_consistency/MIGRATION.md)：旧任务不静默改绑或重领预算。

工作目录说明可继续维护。治理包中的 `implementation_documents` 是当时验收的冻结快照，
不会随本索引更新；运行源码及冻结包完整性另按其哈希清单核对。

## 历史资料

- [视频流程 V2 历史设计基线](VIDEO_PIPELINE_V2_BASELINE.md)：2026-09 的重置设计，包含已被替代的自动内容检查设想。
- [截至 v22 的实现归档](archive/creative_workflow/CREATIVE_WORKFLOW_IMPLEMENTATION_through_v22.md)。
- [2026-09 视频生产线重置归档](archive/2026-09-video-pipeline-reset/ARCHIVE_MANIFEST.md)。
- `archive/2026-08-video-workflow/`、`archive/2026-07-cleanup/` 和 `archive/video-debug/` 保留更早资料。

历史资料可用于定位旧任务，不能据此恢复旧生产路线、改写原审核或把过去的特许推广到当前任务。
'''

files['docs/PROJECT_INTRO.md']=meta+'''# 项目介绍

这是一个以 AI 剧本与视频制作为核心的平台。用户提供原创创作简报、小说正文或已有视频分析，
系统组织编剧与导演产出完整剧本、导演安排、分段分镜和实际生成请求。文本与视频都支持分段调试，
让用户在责任阶段修问题，保留原输入、输出、审核、反馈和预算后继续。

## 核心功能

1. 冻结创作来源与要求，建立逻辑任务及其预算。
2. 生成和审核完整剧本；内容返修提交完整新稿并全文复审，不能把新旧稿拼接后伪装成模型新稿。
3. 将叙事、动作、情绪反应窗口和镜头安排转为可对照的实际请求。
4. 在文本阶段暂停、单步、对比版本并提交反馈；运行中新增反馈也不能被保存覆盖。
5. 显式生成当前镜段，保存候选后等待用户人工审核；批准原始尾帧后再继续下一段。
6. 合成批准链，等待整片人工审核，再独立进入浏览器发布、作品核验和运营复盘。

用户当前最关心情感表达、事件表达和画面表达。总时长按简报中的实际策略解释；
技术连续、字段齐全和接口成功均不能替代用户对视频的判断。

## 当前阶段

核心流程及已发现的 P1 闭环已通过离线验收。当前新治理任务绑定 v23，旧任务保持原协议、
模型配置、预算和历史。工作台完整页面链与异常恢复工具仍待完善，真实质量试点和生产运行证据仍待补齐。

账号绑定、内容研究、标签趋势和机会分析继续保留，提供可选创作输入和独立运营能力。
创作不要求先完成热门内容采集，生成也不自动触发发布。

进一步阅读[当前实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md)、[操作指南](USER_GUIDE.md)及
[大模型项目分析与操作导航](AI_PROJECT_GUIDE.md)。
'''

files['docs/CURRENT_CAPABILITIES.md']=meta+'''# 当前能力

当前重点是完整剧本、导演安排、实际请求预览、逐段视频候选和用户人工审核。
以下“已接线”指代码和相应离线证据，不将夹具回归等同于真实创作质量或生产验收。

| 能力 | 当前实现状态 | 验证或使用边界 |
|---|---|---|
| 来源冻结、逻辑任务、预算 | 已接线 | 同任务恢复继承来源、模型、协议和累计额度 |
| 完整剧本与全文复审 | 已接线 | 完整新稿整体采用；审核意见须核实，主观观感不伪写为通过 |
| 导演安排与分段分镜 | 已接线 | 关联状态计划、原剧情和实际视频请求 |
| 文本自动推进、断点、单步 | 已接线 | 待核实、unknown、预算和反馈门阻止继续 |
| 不可变版本与差异比较 | 已接线 | 输入及输出身份保留，当前与历史分开 |
| 在途反馈一致性 | v23 离线验收通过 | 短提交锁、命令重放、派发门；仅解决本次输入消费的反馈 |
| 媒体预览、显式提交和原 ID 查询 | 已接线 | 未决反馈阻止新提交；unknown 不盲重发 |
| 视频用户审核与批准尾帧续段 | 已接线 | 文件成功后 awaiting_human_review；批准绑定原视频、回执和原始尾帧 |
| 批准链合成和整片交付 | 服务/CLI 已接线 | 合成后再次等待整片人工审核；完整页面链尚待补齐 |
| 浏览器发布与作品核验 | 已接线并有离线夹具 | 主动 AI 声明、虚构前缀、账号绑定；真实浏览器验收待补 |
| 质量样本、金标/留出与费用证据 | 接口已接线 | 当前治理包 28 候选、0 人工金标、0 合格留出，不能宣称改善 |
| 账号身份、登录健康、内容研究 | 保留 | 真实身份及页面证据须核对，平台验证可能需要用户处理 |
| 标签、时间趋势、机会和运营回接 | 保留 | 研究为可选输入；缺失指标为 null，不能推断发布效果因果 |

## 尚待完成

F02 页面完整准备/续段/合成/整片审核及文本派发前预览，F03 执行锁与旧环境恢复工具，
F04 核心预算/校验/返修继续拆分，F05 显式字段来源合同，F06 人工质量试点和 F07 真实运行证据。
详细完成标准见[当前实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md)与[后续方向](../data/qa/creative_platform_refactor_20261002/implementation_review_v22/review_report.html)。

## 历史路线范围

`presenter_anime`、`dual_framepack_active`、`single_template` 等旧自动生产组合已经退出生产。
通用节点 `video_pipeline=disabled_pending_redesign` 不表示当前独立创作候选入口被禁止。
项目没有默认的“关键词输入后全自动生成并发布合格视频”能力。

视频内容只由用户审查；助手不主动抽帧、听看、ASR 或调用音画审核模型。
当前执行要求以 [AGENTS.md](../AGENTS.md)和会话中的用户授权为准。
'''

files['docs/SYSTEM_ARCHITECTURE.md']=meta+'''# 系统架构

创作执行与账号运营分别组织。研究可作为创作输入；文本交接、媒体生成、用户审核和发布保持各自的
版本、回执及执行门，任何阶段的技术成功都不自动代替下一阶段的审核。

## 核心执行链

```text
原创简报 / 小说正文 / 已有视频分析 / 表达参考
        ↓ 冻结材料、逻辑任务和预算
候选与人物 → 导演简报 → 完整剧本生成与全文复审
        ↓ 用户可暂停、比较和反馈；返修回到责任阶段
整体导演安排 → 状态计划与分段分镜 → 请求编译和来源绑定
        ↓ 明确执行当前段
服务成功与文件保存 → awaiting_human_review → 用户决定
        ↓ 批准当前原片与服务原始尾帧后继续紧邻下一段
批准链合成 → 整片 awaiting_human_review → 用户整片批准
        ↓ 独立交付和明确发布
绑定账号浏览器发布 → 原作品独立核验 → 对应作品运营回接
```

## 模块与入口

| 边界 | 主要实现 | 职责 |
|---|---|---|
| 任务入口 | scripts/run_creative_workflow.py、creative_workflow_inputs | 材料、简报、逻辑任务登记及继承预算 |
| 文本编排 | creative_workflow、creative_full_script_revision、creative_segmented_director | 编剧/导演调用、完整新稿、文本审核和分镜安排 |
| 阶段控制 | creative_stage_runtime、creative_stage_contracts、creative_stage_debug | 同一运行器的自动/调试、冻结输入、版本、依赖和反馈 |
| 状态提交 | creative_state_store、creative_execution_control | 跨进程短提交锁、有序不可变命令、状态版本、派发许可和消费证明 |
| 媒体执行 | creative_media_workbench、creative_segment_execution、media_review_policy | 请求/候选来源链、预算、原 ID 查询、人工决定、批准链和合成 |
| 交付发布 | creative_delivery、DouyinAdapter、PublishWorkflow | 成片批准、账号核验、主动声明、提交锁和独立作品核验 |
| 质量证据 | creative_quality_evidence、creative_evaluation | 候选、人工金标、冻结留出、评分及原始用量 |
| 创作页面 | creative_workflow_dashboard、creative_workbench_panel | 复用共享命令/服务；部分计划与回执仍需 CLI 或路径输入 |
| 队列 | scheduler.queue、scheduler.runner | 原子领取、租约/心跳、未知结果与迟到提交保护 |
| 研究与运营 | operations_accounts、trend_intelligence、platform_adapter | 身份绑定、调研、趋势、机会、作品与评论回接 |

以上 creative 模块位于 `src/content_factory/`，页面位于 `src/web/`。准确代码链接及命令副作用
见[大模型导航](AI_PROJECT_GUIDE.md)。核心 runner 仍承载较多预算、验证与返修逻辑，F04 是继续拆分责任的增量工作。

## 状态与并发

文本和媒体执行锁避免同任务重复派发，崩溃遗留锁仍须对账；它们与 v23 的短状态提交锁不同。
短提交锁不跨模型等待持有，反馈、停止/恢复及运行器提交以同一命令顺序协调。
旧内存保存先重放已接受命令；返修只解决冻结请求真正消费的反馈，新反馈继续待修。

未决反馈失效下游并阻止新的文本或绑定媒体提交；在途响应保留，原媒体 ID 查询继续可用。
任务状态、产物版本、反馈和 resolution 可追溯，不通过删除回执或换目录恢复额度。

## 治理与历史

只有 `production_protocol=governed_production_v1` 的新任务绑定当前 v23 治理包；
该协议需要 `evidence_review_v6`。普通入口及旧任务的真实配置以参数和任务状态为准。
恢复不能更换已保存的协议、模型、提示词、审核版本或预算；源码/规则哈希不符时在调用前停止。

工作目录文档可维护，冻结治理包和其中的实现文档快照保留。
旧任务在原冻结环境恢复或只读；跨版本迁移和执行锁接管工具尚未提供完整操作闭环。

## 验证范围

核心流程和 F01 已有离线执行证据。完整工作台、真实内容质量和真实服务/媒体格式/浏览器发布
仍按 F02–F07 单独验收，见[当前实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md)。
旧视频组合保留在[历史设计基线](VIDEO_PIPELINE_V2_BASELINE.md)及归档中，不能据代码存在恢复生产。
'''

files['docs/ARCHITECTURE_STATUS.md']=meta+'''# 架构状态

核心创作流程和已发现的 P1 闭环已完成离线验收，项目进入工作台完善与人工创作试点阶段。
当前新治理任务绑定 v23；实际任务仍以各自保存的协议、模型和规则版本为准。

| 边界 | 当前状态 | 后续工作 |
|---|---|---|
| 文本阶段、版本和反馈 | 已接线；v23 修复在途反馈一致性 | 逐步拆分核心校验、调用、预算与返修责任 |
| 请求、逐段候选和人工批准链 | 服务与 CLI 已接线 | 完整准备、续段、合成和整片审核页面 |
| 发布与运营 | 独立下游已接线，有离线夹具 | 真实账号浏览器与准确作品核验 |
| 质量与成本 | 样本、评分和用量接口已接线 | 人工金标、冻结留出、重复评估及真实成本证据 |
| 异常恢复与迁移 | 保留锁、原 ID 查询、原预算和历史 | 执行锁诊断/接管与可重建旧环境工具 |
| 账号研究 | 原能力保留 | 作为可选创作输入和运营复盘 |

文本/媒体执行锁与 v23 短提交锁职责不同：短提交锁保障命令提交一致性，执行锁保障派发独占。
短锁在进程强退后由系统释放，不代表遗留执行锁的恢复工具已经完成。

系统结构见[系统架构](SYSTEM_ARCHITECTURE.md)，行为及待办见[当前实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md)。
旧通用自动视频节点仍为 `disabled_pending_redesign`；当前显式创作入口已单独接线。
'''

files['docs/DEVELOPMENT_PROGRESS.md']=meta+'''# 开发进度

本页记录 2026-10-02 的工作目录状态；详细合同与任务版本以[当前实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md)为准。

## 已完成的离线机制

- 创作来源冻结、逻辑任务登记、共享预算、完整剧本生成/返修和全文复审。
- 导演安排、分段分镜、实际请求编译与版本绑定。
- 自动文本、断点、单步、不可变版本、输入/输出对比、反馈与下游失效。
- 媒体显式提交、原 ID 续查、用户审核、批准原始尾帧续段、批准链合成与成片交付。
- 独立浏览器发布、主动声明、原作品核验和运营回接接口。
- 质量候选、人工金标、冻结留出及原调用费用证据接口。
- v23 F01：在途反馈不丢失，返修只解决实际消费的反馈，新反馈继续阻断，预算/历史不重置。

## 验证证据

[v23 验收](../data/qa/creative_platform_refactor_20261002/feedback_consistency_v23/acceptance_report.html)
保存 743 项核心加 13 项 UI、合计 756 项不同用例的通过回执。
[独立复核](../data/qa/creative_platform_refactor_20261002/v23_confirmation/confirmation.json)
核对计数和冻结哈希，另重跑 18 项反馈边界通过；该复核未全量重跑 756 项。

这些是离线代码和执行链证据。当前包仍为 28 候选、0 人工金标、0 合格留出；
真实创作质量、降本和生产全链路不能据此记为通过。

## 下一阶段

| 项目 | 状态 | 目标 |
|---|---|---|
| F01 在途反馈一致性 | 离线闭环通过 | 已发现问题已修复；新增边界按实际故障补充 |
| F02 工作台 | 待完善 | 文本派发前预览，页面完成单段准备、批准续段、合成和整片审核 |
| F03 恢复工具 | 待完善 | 执行锁对账/接管、旧冻结环境恢复及显式迁移证据 |
| F04 核心责任拆分 | 增量推进 | 分离预算、请求、合同、审核与返修编排 |
| F05 字段来源合同 | 增量推进 | 明确消费来源和重建原因，保守未知依赖回退 |
| F06 人工质量试点 | 待执行 | 独立简报、真实返修、金标/留出与重复比较 |
| F07 真实运行验收 | 待执行 | 服务故障、媒体技术格式及授权浏览器链路证据 |

近期优先工作台和人工质量试点；恢复工具并行建设，核心拆分与依赖优化随实际瓶颈推进。
原 Presenter、双角色 FramePack、模板循环及关键词直达自动生成发布组合继续退役。
'''

files['docs/USER_GUIDE.md']=meta+'''# 操作指南

先确认本次是新故事还是恢复同一任务，并确认用户已授权的调用范围和预算。
研究、文本、媒体、审核和发布分别执行；分析或预览不会自动触发生成与发布。
详细执行要求见 [AGENTS.md](../AGENTS.md)及[当前实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md)。

## 文本创作与分段调试

1. 在“创作空间 → 双角色剧本”选择小说、已有原视频分析或原创简报，填写来源和参考路径。
2. 新任务冻结材料并登记预算；已有任务从原运行目录恢复，不能换目录或修改预算领取新额度。
3. 查看剧本与导演安排，在阶段调试区运行下一阶段、指定断点或停止后续派发。
4. 对当前输入/输出版本提交原话反馈。`must_fix` 阻止下游，`suggestion` 留档；当前页面自动传递所见版本哈希。
5. 恢复时先到最早未解决责任阶段返修，再重建失效下游。运行中新增反馈也会保留；已有响应不自动解决未消费的反馈。

页面目前不是完整的治理协议配置入口。新原创普通入口通常使用已实现的 v5 文本审核，
新治理任务需在 CLI 明确选择 `governed_production_v1` 与 `evidence_review_v6`；旧任务沿用原绑定。
完整文本派发前预览仍属 F02，不将差异查看称为完整预览已完成。

### 只读检查与局部控制

在项目根目录运行；将路径替换为实际已有任务。以下命令不调用生成模型或媒体生成服务：

```powershell
$runDir = 'D:/IT/ai_douyin/data/creative_workflows/实际任务目录'
& '.venv/Scripts/python.exe' 'scripts/debug_creative_workflow.py' $runDir inspect
& '.venv/Scripts/python.exe' 'scripts/debug_creative_workflow.py' $runDir compare --stage writer_script
& '.venv/Scripts/python.exe' 'scripts/debug_creative_workflow.py' $runDir stop
```

`resume` 只解除停止意图，不单独启动模型执行；继续文本还需页面或 `run_creative_workflow.py`
按原材料和原参数恢复。stage_id 以 inspect 的实际记录为准，具体示例见[阶段调试](CREATIVE_STAGE_DEBUGGING.md)。

## 单段视频与用户决定

1. 文本审核及反馈门满足后，编译当前剧本/分镜为媒体预览，查看实际请求和来源绑定。
2. 使用 `creative_workbench.py prepare-segment` 准备当前单段计划；首段绑定首帧依据，续段绑定紧邻前段人工批准的服务原始尾帧。
3. `run_creative_seedance_segment.py preview` 查看本段实际请求。用户制作授权与预算支持时，显式 `submit` 当前段。
4. 有原任务 ID 时使用 `query` 续查；结果未知且无 ID 时先对账。不要新目录重发。
5. 保存成功后，用户播放并给出决定，程序仅记录技术成功和 `awaiting_human_review`。
6. 从当前回执登记候选，再记录用户原话及 approved/rejected。不通过时可按秒点和实际证据定位责任阶段，返修后才另行生成。

当前页面已有预览、启动单段操作和用户视频决定，但单段计划、保存目录和候选回执仍需输入路径。
完整无内部路径的准备/续段操作链尚待 F02 完善。

助手不主动抽帧、听看、ASR 或调用音画审核模型。只有用户明确批准，且原片、回执和原始尾帧身份仍匹配，
才允许继续下一段。计划切镜使用另外经过批准的新机位首帧，同时保留前段批准依据。

## 合成与发布

批准顺序、原片和版本链核对后，通过 `assembly-chain` 建链，显式 `assemble --execute`
采用原音轨生成整片候选。合成成功再次等待用户整片审核，不能从逐段批准推断整片已批准。

完整成片的 `segment_id=final` 人工批准回执可用于 `prepare-delivery` 生成交付预览。
核对账号、标题、简介、AI 主动声明要求与虚构前缀后，按发布授权显式执行 `publish --execute`。
随后用 `verify-publish` 核验原作品；待核验保留提交锁，不能重传。
`collect-operations` 只回接对应账号与作品，缺失指标保留 null。

页面的交付入口仍要求完整成片审核回执路径；准备、合成、交付等准确参数见
[大模型导航的命令表](AI_PROJECT_GUIDE.md#执行入口与副作用)和各脚本 `--help`。

## 异常与额度

- 正常断点与用户停止可按原目录恢复，不清零预算。
- 审核待核实、未决 must_fix、unknown 或预算不足先解决对应原因，不用调试按钮绕过。
- 进程异常留下文本/媒体执行锁时，核对旧进程、原请求 ID 和原回执。当前没有完整的锁接管工具，不能直接删除锁重发。
- 治理源码哈希不符时，旧任务在原冻结环境恢复或只读。导航更新不授权将历史任务改绑 v23。
- 新剧本按既有登记入口建立独立计数；同稿恢复和返修累计失败。缺少真实任务的授权或信息时继续可完成的只读核对。

## 研究与运营

账号绑定、登录健康、授权只读调研、标签趋势、机会排行及发布后复盘继续保留，
可作为创作输入或独立操作。退役视频组合与历史样片不能作为当前默认生成能力。
'''

files['docs/AI_PROJECT_GUIDE.md']='''---
doc_status: current
doc_category: model_navigation
last_reviewed: 2026-10-02
runtime_scope: v23_working_tree
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
'''

# Keep the detailed implementation contract, adding navigation and protocol scope.
p=ROOT/'docs/CREATIVE_WORKFLOW_IMPLEMENTATION.md';s=p.read_text(encoding='utf-8-sig')
needle='## 当前责任边界'
insert='''## 文档与任务版本

本文说明现行实现；项目入口和操作定位见[文档索引](README.md)及[大模型项目分析与操作导航](AI_PROJECT_GUIDE.md)。
方向报告保持产品方向依据，AGENTS.md 与当前会话保存用户执行要求，实际 run 的冻结材料/合同决定恢复行为。
工作目录说明可以维护；治理包内的 implementation_documents 是验收时快照，不随导航更新改写。

当前新治理任务默认绑定 v23，须显式采用 `governed_production_v1` 与 `evidence_review_v6`。
普通新原创 CLI 默认的文本审核通常是 v5，未显式指定生产协议时仍可为 legacy；页面不提供完整协议选择。
不能把“当前新治理包”解释成所有新旧任务都已采用该协议；恢复以 state.json 中的原绑定为准。

'''
assert needle in s;s=s.replace(needle,insert+needle,1);files['docs/CREATIVE_WORKFLOW_IMPLEMENTATION.md']=s

# Replace outdated validation references, preserving current detailed debugging behavior.
p=ROOT/'docs/CREATIVE_STAGE_DEBUGGING.md';s=p.read_text(encoding='utf-8-sig')
start=s.index('## 本轮治理绑定与验收');end=s.index('## v22 工作台入口',start)
s=s[:start]+'''## 当前治理绑定与验收

显式启用 `governed_production_v1` 与 `evidence_review_v6` 的新治理任务绑定 v23；
普通入口和旧任务仍以各自协议为准，恢复不能更换已保存的模型、提示词、规则或预算。
冻结历史包保留，[迁移边界](../data/creative_governance/20261002_v23_feedback_consistency/MIGRATION.md)
要求对未决外部任务对账并携带原额度，本版没有自动跨版本迁移命令。

当前 F01 行为见 [v23 验收](../data/qa/creative_platform_refactor_20261002/feedback_consistency_v23/acceptance_report.html)，
[独立复核](../data/qa/creative_platform_refactor_20261002/v23_confirmation/confirmation.json)另重跑 18 项反馈边界。
原 v20、v21 和 v22 回执保留为对应版本历史。假服务、视频字节和人为批准夹具不证明真实内容质量。

'''+s[end:]
s=s.replace('## v22 工作台入口','## 当前工作台入口',1)
s=s.replace('当前完整行为见 [创作平台实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md)。','当前完整行为见 [创作平台实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md)，入口与副作用见\n[大模型导航](AI_PROJECT_GUIDE.md)。',1)
files['docs/CREATIVE_STAGE_DEBUGGING.md']=s

# Keep historical baselines and dated production records; mark their scope explicitly.
p=ROOT/'docs/VIDEO_PIPELINE_V2_BASELINE.md';s=p.read_text(encoding='utf-8-sig')
s=s.replace('doc_status: current','doc_status: historical',1).replace('doc_category: video_pipeline_source_of_truth','doc_category: historical_design',1).replace('last_reviewed: 2026-09-05','last_reviewed: 2026-10-02',1)
s=s.replace('# 视频流程 V2 空白基线','# 视频流程 V2 历史设计基线',1)
marker='## 当前决定'
note='''## 当前使用范围

本页保留 2026-09-04/05 的视频生产线重置设计，用于追溯退役路线和当时的候选合同。
2026-10-02 的完整剧本、导演、请求预览、显式镜段生成与用户审核实现见
[当前实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md)及[系统架构](SYSTEM_ARCHITECTURE.md)。

下文“待实现”“自动质量检测”“逐帧/转写”等属于历史设计，不是当前助手执行要求。
依据[AGENTS.md](../AGENTS.md)的 2026-09-30 更新，视频内容仅由用户人工审查，技术成功进入
`awaiting_human_review`。旧组合仍退役，当前独立显式创作入口已接线；真实质量验收仍待完成。

'''
assert marker in s;s=s.replace(marker,note+'## 重置时的决定',1);files['docs/VIDEO_PIPELINE_V2_BASELINE.md']=s

for name in ('REUSABLE_VIDEO_WORKFLOW.md','SCRIPT_VIDEO_RUN.md'):
 p=ROOT/'docs'/name;s=p.read_text(encoding='utf-8-sig');head,rest=s.split('\n',1)
 note='''

## 当前使用范围

当前执行行为与新治理包版本见[创作平台当前实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md)，
入口选择见[操作指南](USER_GUIDE.md)及[大模型导航](AI_PROJECT_GUIDE.md)。本页按日期保留
特定制作任务、提示词版本及演进记录；文内各历史“新默认”不自动替换今天的默认或旧任务绑定。

最新用户视频要求见[AGENTS.md](../AGENTS.md)：内容由用户人工审查，助手不主动抽帧、听看、
ASR 或调用音画审核模型，技术成功记录 `awaiting_human_review`。下文旧主动审核、声音待审特许
或单片允许延后审核只在其原任务范围中追溯，不扩大为当前通用规则。任何续段均核对当前用户批准与原始尾帧身份。
'''
 files['docs/'+name]=head+note+'\n'+rest

# Preserve all user policy text and add a short discoverable navigation section.
p=ROOT/'AGENTS.md';s=p.read_text(encoding='utf-8-sig')
s+='''

# 项目文档导航

当前重点是 AI 剧本与视频制作平台，文本阶段与视频片段都需要分段调试。
进入项目先读 [大模型项目分析与操作导航](docs/AI_PROJECT_GUIDE.md)，再按任务查
[当前实现](docs/CREATIVE_WORKFLOW_IMPLEMENTATION.md)及[阶段调试](docs/CREATIVE_STAGE_DEBUGGING.md)。
导航帮助定位来源和命令，不授予额外付费调用、人工批准或发布权限；已有有效用户授权继续适用。
任务协议、治理版本、输入、预算与历史以原冻结绑定为准，不能因阅读新文档自动迁移或重置。
上方按日期保留的审核记录按最新要求和原任务范围解释。
'''
files['AGENTS.md']=s

# Record before-images and frozen-source hashes, then guard each write against concurrent edits.
sha=lambda data:hashlib.sha256(data).hexdigest()
before=[]
for relative,value in files.items():
 path=ROOT/relative
 old=path.read_bytes() if path.exists() else None
 before.append({'path':relative,'existed':old is not None,'before_sha256':sha(old) if old is not None else None})
 if old is not None:
  dst=backups/relative;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(old)

packs=[]
for prior in sorted((ROOT/'data/creative_governance').glob('20261002_v*')):
 manifest=prior/'artifact_manifest.json'
 if not manifest.is_file():continue
 rows=json.loads(manifest.read_text(encoding='utf-8'))['artifacts']
 packs.append({'pack':str(prior.relative_to(ROOT)).replace(chr(92),'/'),'manifest_sha256':sha(manifest.read_bytes()),'files':{r['path']:sha((prior/r['path']).read_bytes()) for r in rows}})
pack=ROOT/'data/creative_governance/20261002_v23_feedback_consistency'
rows=json.loads((pack/'runtime_sources.json').read_text(encoding='utf-8'))['sources']
runtime={r['path']:sha((ROOT/r['path']).read_bytes()) for r in rows}

for relative,value in files.items():
 path=ROOT/relative;prior=next(r for r in before if r['path']==relative)
 assert (sha(path.read_bytes()) if path.exists() else None)==prior['before_sha256'], 'Concurrent document change: '+relative
 text=value.replace('\r\n','\n').rstrip()+'\n'
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8',newline='\n')
 prior['after_sha256']=sha(path.read_bytes());prior['lines']=len(text.splitlines())

manifest={'schema':'creative_documentation_sync/v1','updated_at':datetime.now().astimezone().isoformat(),'files':before,'runtime_before':runtime,'frozen_packs_before':packs,'new_navigation':'docs/AI_PROJECT_GUIDE.md','scope':'Working documentation only; original policy text and historical records retained; runtime and frozen packs unchanged.'}
(OUT/'implementation_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'updated_documents':len(files),'new_guide':str(ROOT/'docs/AI_PROJECT_GUIDE.md'),'files':[r['path'] for r in before]},ensure_ascii=False))
