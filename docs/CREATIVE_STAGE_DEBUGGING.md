# 创作阶段调试、版本与人工审核

2026-10-18新来源准备如需当前对白/动作估时规则，使用`scripts/run_performance_timing_natural_director_v2.py source-prepare`（参数沿v10），或当前自然导演页面的新来源准备。`profile()`提供同一完整规范，`estimate_dialogue(明确汉字读法, delivery_state, pause_seconds=明确停连)`仅作本地参考；未知读法只给部分估时，不能据此自动改秒或验收。旧v1/v10冻结运行用原恢复命令，不通过新准备补写；实际验证和六段49秒编辑候选见[逐句估时v2交接](PERFORMANCE_TIMING_V2_REVIEW_20261018.md)。本次十轮已用完，不以入口更新继续派发。

2026-10-18当前新文本入口为`scripts/run_natural_director_v10.py`：`prepare --run-dir 新自然导演目录 --parent-run 已知全文通过的v9编剧目录 --authorization-path 实际授权`；新来源使用`source-prepare`、`source-execute`，仅编剧/同稿审核后进入自然导演。`preview/inspect`只读，`execute`实际派文本，`recover`只恢复核实过的本地投影。共享5+5轮在campaign锁及持久原生复盘门核对，不改原预算；未知、截断和旧office pending不能续。主稿19段132秒已通过机器文本与实际SDK整包审查，可用`scripts/render_natural_director_v10.py --run-dir 已通过目录 --output-dir 独立交付目录`输出完整阅读稿。代码、实际结果、已知故障恢复和跨故事边界见[自然导演v10交接](NATURAL_DIRECTOR_V10_REVIEW_20261018.md)。下方v9等为冻结历史命令，本轮没有新媒体。

2026-10-18新小说/原创统一质量入口为`scripts/run_novel_agent_v9.py fetch/prepare/preview/inspect/execute`，可通过`prepare --source-kind novel|original --brief-json 要求.json`冻结完整创作要求。`execute --engine langgraph`使用新进程及项目隔离依赖；测试关闭宿主pytest自动插件。`prepare-known-director-continuation --run-dir 新目录 --parent-run 原v8目录`仅接受完整已知的导演合同失败，核原stop/用量/同稿审查、聚合全部内容诊断并继承实际消耗与剩余候选；未知或无法明确解析的结果保持停止，不换目录/版本重领。最终`SCREENPLAY.md`、`PRODUCTION_HANDOFF.json`、`VIDEO_REQUESTS.json`必须整体通过原生审核与重建；新增请求、参考图或尾帧不得绕过审发一致门。具体证据与范围见[质量v9交接](NARRATIVE_QUALITY_V9_REVIEW_20261018.md)。新链本轮不派发视频；下方为历史命令。

2026-10-18小说新任务使用`scripts/run_novel_agent_v7.py fetch/prepare/preview/inspect/execute`，完整命令与实际测试见[全流程交接](NOVEL_FULL_FLOW_REVIEW_20261018.md)。`execute --engine langgraph`使用项目隔离依赖和同一原生派发门；`prepare-director-continuation --run-dir 新目录 --parent-run 原v6目录`仅针对已知完整的导演时间线ID别名停点，本地派生、继承全链消耗与剩余额度、唯一续行且仅一次导演审查，不再新增导演候选，不能迁移旧耗尽/未知任务。`recover-projection`只恢复已核实本地检查点，不派模型；未知请求仍停止。旧运行按原版本查看；下方命令为当时历史入口。

2026-10-17新增独立本地诊断入口 `scripts/run_novel_logic_v4.py diagnose/benchmark/replay-v3`，见[小说逻辑 P0/P1 主审与命令](NOVEL_LOGIC_P0_P1_REVIEW_20261017.md)。场记、同稿九维审核声明、逐项核实和容量用于离线程序决定；根结果无生产派发/交接权限。回放只核旧证据并保留原结论，不接管 v3、不重领调用。网页及真实模型仍使用其原冻结入口。

2026-10-17新建小说改编默认 `scripts/run_novel_plaintext_v3.py fetch/prepare/preview/inspect/execute`，见[原生文本真实试跑](NOVEL_PLAINTEXT_PIPELINE_REVIEW_20261017.md)。阶段为writer_full/review_full：完整原生文本→同源全文审查，明确内容失败才有界整稿返修。纯工具缺失/引文排版不拒writer；未知或截断仍停止。当前真实run为`data/novel_adaptation_production/20261017_plaintext_v3/run`，已6次/81788、继承后20次/310301，content_revision_exhausted、pending=null；同目录重入0调用。`DRAFT_005.md`与`REVIEW_006.json`是最新未通过稿及审查，无SCREENPLAY/OUTPUT_MANIFEST。不要改旧绑定或换目录重领容量；本轮未派媒体。

2026-10-17新增[独立小说改编路线](NOVEL_ADAPTATION_ROUTE_REVIEW_20261017.md)，CLI为`scripts/run_novel_adaptation_v1.py fetch/prepare/preview/inspect/execute`，网页为“小说改编”。分析、改编计划、剧本、全文审查均有原生回执与问题定位；完成响应可在中断后原证据恢复，未知/截断停止。同故事历史停止不能换目录重领；当前旧小说11次/180079 tokens仅可预览。`text_ready_for_director`只证明机器文本交接，非人批或分镜/视频完成。本轮只有离线验收。

2026-10-16新增[小说账号完整创作入口](ACCOUNT_NOVEL_CREATION_REVIEW_20261016.md)：`scripts/run_account_novel_creation_v1.py` 的 `prepare/preview/inspect` 只本地，`execute` 才推进原目录下的完整文本任务。网页入口位于“热门选题 → 选题卡”的小说账号分支；阶段回执保存在任务子目录 `creative/`。缺材料可原目录补齐，未知用量/结果、锁或身份改变不能重派；机器文本完成不写用户采用或视频通过。旧任务不通过此入口迁移。

2026-10-12独立组合入口：`scripts/run_creative_studio_v1.py inspect/status/preview/recover`，见[实施交接](CREATIVE_STUDIO_COMPOSITION_REVIEW_20261012.md)。默认工作区`data/creative_studio_workspaces/legal_scene_20261012_v1`保存完整源、DAG、空间与SDK请求；已存在时禁止prepare覆盖。`recover`只输出原ID查询/对账/停止建议，不派发请求。只有媒体参数编译成功时导演图像节点仍未完成；视频保存始终待用户审核。恢复基线使用`restore_creative_studio_baseline_v1.py`新目录解压，不覆盖原账本。

当前最新真实停点是独立`capability_v5`中的518–520：三份响应HTTP200、tool_calls完整且用量已知，但排时合同拒绝，7/7候选耗尽。不是服务结果未知。只读`run_creative_capability_production_v5.py status`核对原账本、请求/响应身份、实际出站证明与容量；已保存执行重入新增派发0。

诊断修复只读命令`preview_creative_endpoint_feedback_v6.py`消费完整冻结与事件/回执绑定，复算原三份失败、保留520原生全文一次并输出新完整请求预览，明确remaining0和dispatch_allowed=false。当前可读请求位于`data/qa/creative_capability_production_adapter_20261012/endpoint_diagnostic_repair/preview_r2`。新适配及子类是离线新增模块，未替换默认v23或已冻结生产入口；细节、实际用量与未解决项见[最新交接](CREATIVE_CAPABILITY_PRODUCTION_ADAPTER_REVIEW_20261012.md)。

先前`preview_creative_capability_pipeline_v5.py`、517/4候选停点及独立v3调试记录仍保留原范围，分别见[能力优先阶段交接](CREATIVE_CAPABILITY_FIRST_REVIEW_20261012.md)、[来源拒绝测试](CREATIVE_COMPLETE_WORKFLOW_PRODUCTION_TEST_20261012.md)、[独立v3补齐](CREATIVE_COMPLETE_WORKFLOW_COMPLETION_20261012.md)。不能凭最新文档恢复或迁移旧任务。

本页描述 2026-10-02 重构后已接线的创作控制面。完整方向与取舍见
[`direction_report.html`](../data/qa/creative_platform_refactor_20261002/direction_report.html)。

## 2026-10-03 离线计划修订

v23基线之后新增了状态组前提、schema字段隔离、manifest绑定补丁校验与完整计划内容返修修复，
见[证据分类、最小修复及分工评估](CREATIVE_PLAN_EVIDENCE_AND_REPAIR_20261003.md)。
这些改动尚未注册为新的生产治理包；默认目录仍为冻结v23。当前源码与v17/v23绑定不符时，
调用前门禁必须停止，不能改写冻结哈希或静默迁移。测试使用独立假服务治理夹具，
离线通过不表示真实创作质量通过。旧任务仍为needs_attention，预算及历史不变。

## 状态边界

- `technical_status=succeeded` 只表示外部任务成功并且文件、哈希已经保存。
- 新视频候选统一写 `content_status=awaiting_human_review`。程序不主动抽帧、听看、
  ASR 或调用媒体审核模型，也不把接口成功写成内容 `passed`。
- 用户决定只有 `approved` / `rejected`，并绑定原视频、服务原始尾帧和用户原话。
- 发布适配器可以返回 `post_publish_verification_pending`。这表示平台接受了提交，
  不表示最终发布完成；Worker 保持 `awaiting_verification`，提交锁继续有效。

## 运行到断点或单步

原创、小说和原视频驱动入口继续使用 `scripts/run_creative_workflow.py`。原有材料、
逻辑任务和预算参数不变，只增加两种互斥的调试控制：

```powershell
# 在指定阶段完成并写入不可变产物后暂停
.\.venv\Scripts\python.exe scripts\run_creative_workflow.py `
  --source-driver novel --title 示例 --novel D:\materials\story.txt `
  --run-dir D:\runs\example --stop-after-stage writer_script

# 恢复同一目录，跳过已缓存阶段，只完成下一个新阶段后暂停
.\.venv\Scripts\python.exe scripts\run_creative_workflow.py `
  --source-driver novel --title 示例 --novel D:\materials\story.txt `
  --run-dir D:\runs\example --next-stage
```

断点状态为 `debug_breakpoint`，属于正常暂停，不是 `needs_attention`。每个已验证阶段
会在运行目录的 `.creative_debug/artifacts/` 保存以输出和输入 SHA-256 寻址的不可变快照；
`.creative_debug/index.json` 只保存版本索引。旧的阶段回执、调用次数和任务预算不会重置。

## 只读检查、比较和反馈

以下命令不调用模型或媒体服务：

```powershell
.\.venv\Scripts\python.exe scripts\debug_creative_workflow.py D:\runs\example inspect
.\.venv\Scripts\python.exe scripts\debug_creative_workflow.py D:\runs\example compare --stage writer_script
.\.venv\Scripts\python.exe scripts\debug_creative_workflow.py D:\runs\example feedback `
  --stage writer_script --disposition must_fix --message "B03 的刺激前缺少可见动机"
```

`inspect.stages` 每个逻辑阶段只展示最近一次完成验证的产物，并核对不可变快照、
当前阶段回执、输入与输出哈希；完整执行记录在 `inspect.history`，被替代版本标为
`historical`。反馈只绑定当前验证产物；失效版本仍可作为问题证据，但不能作为推进依据。
UI 默认展示当前阶段，可查看只读历史并比较最近两版，CLI 的 `compare` 也可指定历史哈希。

`must_fix` 把责任阶段标为 `needs_revision`，按 `debug_stage_dependencies` 的传递依赖
把已有下游标为 `invalidated`；其他尚未解决的反馈目标保持 `needs_revision`。此图采用
现有顺序编排的保守阶段前置关系，新阶段在验证完成时登记；无图的旧任务按首次遍历
兼容建立，后续返修执行顺序不改变上下游关系。显式独立分支遵守其声明的依赖。
历史产物、反馈原话、resolution 和调用记录继续保留。v22 已记录实际消费字段投影；
完整输入和提示哈希均一致时，生成兼容证明并复用下游，任一变化仍重建。不能凭“看起来无关”复用审核。

恢复先修复有未解决反馈的最早前置阶段，不取决于反馈登记先后。已解决上游的返修
上下文在下游仍有未解决反馈时继续重放，但逐项核对原反馈、resolution、当前输出，
并保留运行器原有输入/提示/输出哈希检查。已修复上游造成的失效中间阶段可重建后
到达下游目标；无可验证父依据、回执变化、结果未知或预算不足时在调用前停止。
单步将返修和失效重建产生的新验证版本计为一步，缓存重放不计新步骤。

创作页面复用同一个命令层，提供阶段列表、运行下一阶段、运行到指定 `stage_id` 和绑定
反馈。页面和 CLI 都不会因调试模式增加预算。

## 记录用户视频决定

候选文件成功保存后，由用户实际播放检查。用户明确决定后，记录其原话：

```powershell
.\.venv\Scripts\python.exe scripts\review_media_candidate.py `
  D:\runs\example\SEG001\receipt.json approved `
  --user-statement "我已人工看过这一段，同意继续下一段。"
```

批准会生成相邻的 `*.human_review.json`。原始视频、原始尾帧、源回执或批准回执任一
发生变化，续段校验都会关闭。拒绝回执不会解锁续段，修复应回到用户指出的责任阶段。

## 队列与恢复

- SQLite 使用 `pending -> running` 条件更新原子领取；两个 Worker 只有一个能取得执行权。
- 领取记录包含 owner、租约和心跳。过期租约转为 `outcome_unknown`，不自动重试可能仍在
  发生的外部副作用。
- 线程超时同样返回 `outcome_unknown`，必须先查询原任务或人工核对，再决定是否重试。
- Docker 启动必须完成 Alembic 迁移并通过业务就绪检查；严格启动不能使用开发回退。


## 当前治理绑定与验收

显式启用 `governed_production_v1` 与 `evidence_review_v6` 的新治理任务绑定 v23；
普通入口和旧任务仍以各自协议为准，恢复不能更换已保存的模型、提示词、规则或预算。
冻结历史包保留，[迁移边界](../data/creative_governance/20261002_v23_feedback_consistency/MIGRATION.md)
要求对未决外部任务对账并携带原额度，本版没有自动跨版本迁移命令。

当前 F01 行为见 [v23 验收](../data/qa/creative_platform_refactor_20261002/feedback_consistency_v23/acceptance_report.html)，
[独立复核](../data/qa/creative_platform_refactor_20261002/v23_confirmation/confirmation.json)另重跑 18 项反馈边界。
原 v20、v21 和 v22 回执保留为对应版本历史。假服务、视频字节和人为批准夹具不证明真实内容质量。

## 当前工作台入口

当前完整行为见 [创作平台实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md)，入口与副作用见
[大模型导航](AI_PROJECT_GUIDE.md)。停止/恢复命令为
`debug_creative_workflow.py RUN stop` 与 `resume`。停止只影响后续派发，预算与在途回执保留。

`creative_workbench.py RUN --help` 列出媒体登记、秒点反馈、请求准备、批准链合成、交付、
浏览器发布续查、运营回接以及质量样本命令。付费生成必须单独使用 segment `submit`；
发布和本地合成分别需要明确的 `publish --execute`、`assemble --execute`。

阶段反馈可带 `--expected-input-sha256`、`--expected-output-sha256` 防止旧页面误绑。
返修后的新输入会归档相关原审核包和决定，新复核不能沿用旧放行记录。相同输出来自不同
请求时，产物与反馈的输入身份也保留。进程崩溃遗留执行锁时先核对原进程和回执，不盲目解除重发。

## v23 运行中反馈（F01）

运行时可提交带所见双哈希的反馈。反馈与 stop/resume 追加不可变命令并共享短提交锁；runner 每次保存重放命令。并发反馈、停止交错和崩溃重放不覆盖记录、不重置额度。已在途响应保存为历史，新反馈未解决时停止下游。返修仅解决实际冻结输入消费的反馈，新到反馈保留原绑定并继续待修。原已交接任务反馈后重新打开。

[本轮 F01 验收](../data/qa/creative_platform_refactor_20261002/feedback_consistency_v23/acceptance_report.html)；原 v21/v22 验收为历史。完整页面链、执行锁接管和旧环境恢复仍待后续工作，不能用提交锁的自动释放替代这些能力。


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


### 2026-10-04 明确恢复后的文本续行

用户授权后续文本暂不设总token硬限；旧49次/490913与原500000上限保留为冻结历史。新增物理适配v4、无损审查传输v8及独立续行入口，旧v17/v23不迁移。当前离线316项及7个subtests通过，不构成整片质量通过。见[续行合同、产物与验证边界](CREATIVE_TEXT_CONTINUATION_20261004.md)。

## 2026-10-05 S6完整实际表演与文本制作交接

独立S6任务已得到第77次整片导演规划、九份源核对的完整局部实际表演、91.442857秒确定性编译及第158次有效全文审查。[完整正文](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/resume_20261005_v15/DELIVERABLE_s6_d6/CREATIVE_REVIEW_COPY.md)与[后续制作交接](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/resume_20261005_v15/DELIVERABLE_s6_d6/MEDIA_HANDOFF_REQUIREMENTS.md)现可直接审阅，详见[版本与实际执行记录](THIS_TIME_I_LEAVE_S6_PRODUCTION_RECORD_20261005.md)。状态为等待用户内容/审美确认，不代表实际声画或用户质量通过。

`python scripts/show_s6_text_handoff_v16.py`仅本地重验并幂等保存完整交接，不派发模型或媒体。生产独立v15冻结183源码，保存器v16单独SHA记录；默认平台v23和旧任务未迁移。完整原稿/R01仍进入实际模型请求，MiniMax创作、DeepSeek全文审查未换模型；旧70结果未知及64010预留保持，旧账本未重置。

当前媒体0，实际图片0；后续按少量样板确认、选定实图回传导演、核对长句段长承载、逐段生成并等待用户人工审核推进。助手不主动抽帧/听看/ASR或音画审核模型。问题分类与验证边界见[交接证据说明](CREATIVE_S6_HANDOFF_EVIDENCE_20261005.md)。


## 2026-10-06 S7完整文本交接

[完整导演与表演阅读稿](../data/production_revisions/this_time_i_leave_s7_review_evidence_repair_20261006/DELIVERABLE_s7_d1/CREATIVE_REVIEW_COPY_READABLE.md)现包含十镜62.26秒与完整原稿、资产及制作条件。265全文审查有效，0未决必修问题；这是文本交接完成，仍待用户内容/审美与实际声画确认。过程和故障分流见[实际记录](THIS_TIME_I_LEAVE_S7_REVISION_20261005.md)。

独立v45通过原导演上下文/当前执行排时分离、共用表演范围及工具格式/本地业务验收分离完成，旧冻结v17/v23与源码回执不改。机械当前动作翻译仅消费真实当前原动作和起态，明确不携带R01全文；创作、导演和实际表演请求确实消费完整S7/R01。累计消耗完整承接，无自动重试，0媒体。用户实际确认后记录原话与交接SHA；少量样板选定并回传导演后再核对媒体授权与段长。


## 2026-10-08 完整法律正文续行

用户已明确要求继续生成剧本，实际指令绑定此前披露的修正冲突。完整正文、全文返修、证据编号审查、短事件链与标签建议隔离的真实过程见[完整法律剧本制作记录](LEGAL_COMPLETE_SCRIPT_PRODUCTION_20261008.md)。原方向、旧账本与冻结记录保留，正文质量与接口/离线验证分开记；导演、表演和媒体不继承为本稿已完成。


### 2026-10-08 最新完整法律正文停点

298/300形成[完整四拍法律剧本](../data/production_revisions/legal_trend_text_trial_20261008/round_11/DELIVERABLE_r8/FULL_SCRIPT.md)及有效同稿全文复审，当前0未决必修、四项情绪要求均satisfied，待用户实际采用正文。审查原六条意见由模型有据重新归类，原记录和正文不改；186离线回归通过，本轮21文本/351888 reported tokens，媒体0。导演输入仅离线准备，新导演、表演、编译与交接未完成。全过程、审查局限和账本见[实际记录](LEGAL_COMPLETE_SCRIPT_PRODUCTION_20261008.md)。


### 2026-10-08 法律正文已采用、导演与实际表演完成

用户实际采用298完整正文后，完成304整片导演、306–309四拍实际表演和311有效全片文本复审，11镜230.4秒的[完整导演/表演/制作交接](../data/production_revisions/legal_director_performance_20261008/round_06/DELIVERABLE_d1/DIRECTOR_PERFORMANCE_READABLE.md)现可审阅。原步骤23/对白16保持，0未决必修，89必要离线检查通过；原稿已采用，具体导演与审美/媒体尚待确认。原对照表与具名对象修复、310引用不足拒绝及审查局限、实际账本见[制作记录](LEGAL_DIRECTOR_PERFORMANCE_20261008.md)。本轮11文本/314511 reported tokens，累计311/5335773，媒体0；旧账本、未知请求与默认v23不改。人物/背景实图及真实声画未完成，不是视频生成或质量通过。


### 2026-10-08 法律片完整审片文件（本次整批审核例外）

用户明确授权服务原始尾帧连续生成、全部完成后统一人工审核。原四段复用，新增21次Seedance Mini 480p视频请求，25段已完整保存并合成243.296秒的[完整审片文件](../data/video_generation/legal_trend_20261008/remaining_batch_v1/LEGAL_FULL_REVIEW_v1.mp4)。全部新段和整片为awaiting_human_review，未抽帧、听看、ASR或模型音画审核，未发布、未自动重生成。原稿、导演交接、旧账本和默认逐段批准规则保留；本次例外不授予其他片批量续段。源对白/窗口完整进入实际请求，但真实表演与长句接话未验证；LG01原整镜说明夹带下一步对白的候选保留供用户审核，后续提示词范围已修正。实际内容与剩余问题见[交付记录](../data/video_generation/legal_trend_20261008/remaining_batch_v1/DELIVERY_REPORT.md)及[实际提示词](../data/video_generation/legal_trend_20261008/remaining_batch_v1/ACTUAL_PROMPTS.md)。


### 2026-10-09 法律片人工审查与离线返修

用户指出重复催签、词句/发音问题、重复工牌和场景不一致并取消字幕，完整审片已绑定原话记rejected。核实整镜未来动作和完整重音说明泄入当前段请求；25段输入只有文字/图片，没有实际声线绑定。13项当前段隔离/状态/字幕/声线生产门离线检查通过；v3候选仍production_ready=false，完整模型表演返修、具体身份/声音问题及新的媒体范围未完成。原25段、冻结文本及旧账本保留，本轮新增付费0。见[问题、原因边界和修复](LEGAL_VIDEO_HUMAN_FEEDBACK_20261009.md)。


## 2026-10-09 完整新稿与审查资格分开调试

《桌上一张纸》采用316完整模型正文及318同稿全文审查，等待人类采用；317旧异议和逐项资格证据保留。不得把“必须同拍完成后果”“必须B1揭示B2信息”等额外分拍选择自动当正文必修。真动作错误须生成模型提交完整新稿再全文复审，不能手动修正文。新步骤14条，旧23步骤状态义务/230.4秒排时失效，不可换哈希强行套用。离线检查70项通过，新增媒体0，创作质量尚无人类批准。入口与账本见[本轮记录](LEGAL_PLAIN_SCRIPT_REVISION_20261009.md)。


## 2026-10-09 原辞职剧情短版重做

当前采用316/318完整短稿，319导演与327/323/324/328局部表演，329同稿制作全文复审；92.2秒四镜、9生成段计划95秒。320状态无变化转移及321空对象类型失败完整保留，新v3将源确定状态归编译器，模型只生成表演与时间。20项必要离线验证通过，真实Seedance Mini 480p整批请求已开始；所有新媒体等待用户人工审核，不表示实际质量通过。授权、源依赖复用/返修、真实回执与风险见[短版重做记录](LEGAL_SHORT_REMAKE_20261009.md)。旧全文、旧243.296秒rejected成片与旧账本保留，不迁移默认v23，不清零失败预算。


### 本次短版完整视频已保存

9段Seedance Mini 480p视频全部技术成功，原生尾帧连续，已完整合成 **95.872秒** 的[辞职剧情短版审片文件](../data/video_generation/legal_short_remake_20261009/batch_v1/LEGAL_SHORT_FULL_REVIEW_v1.mp4)。新视频9次/957942 reported tokens；11次文本/238829，当前文本累计329/5676014，旧未知与预留保留。当前20项必要离线验证通过、329全文制作审查无未决必修；真实声画由用户审核，片段及整片 awaiting_human_review。未抽帧、听看、ASR、音画审核、重派或发布；未新增图片。实际提示词、旧片SHA未变核对、代码17文件快照与未审项目见[真实交付报告](../data/video_generation/legal_short_remake_20261009/batch_v1/DELIVERY_REPORT.md)。

## 2026-10-09 短版人工反馈后的交锋与节奏全文返修

95.872秒短版已按用户实际反馈记整片rejected，原9段、视频和技术回执快照保留。MiniMax339完整新稿、DeepSeek340同稿全文复审完成，无未决必修；八句159发音字、四拍16步骤，纸一次递到小林面前后静止，周姐从公司立场转个人劝说，小林回应后坚持。完整新稿等待用户内容核对，新的导演、表演窗口、状态编译及媒体尚未完成。11次文本163952 reported tokens，累计340/5839966；新媒体0，未知与旧账本保留。10项必要离线回归通过，不代表创作质量。原因分类、实际产物、合同错误及后续节奏验收见[本轮记录](LEGAL_CONFLICT_AND_PACE_REVISION_20261009.md)。默认v23和旧冻结源未迁移，旧92.2秒/table_middle合同不能套新稿。


## 2026-10-10 当前文本返修停点

最新完整自然应答候选为[380/381完整新稿](../data/production_revisions/legal_natural_interaction_20261010/round_05/REVIEWED_CANDIDATE/FULL_SCRIPT.md)，不是362旧稿的导演/表演缓存。独立入口scripts/run_legal_natural_dialogue_revision_v5_20261010.py的status只读；finish要求全文复审和同源独立编辑门，不以零issues直接等同人工采用。已完成的375/377/378原稿与各自审查、拒绝依据不改；没有在途调用和自动重试。当前待用户内容核对，新的整片导演/并行排时和视频未完成。详见[实际过程](LEGAL_NATURAL_INTERACTION_REVISION_20261010.md)。


## 2026-10-11 第三段人数与空间连续返修

487稿第三段已按用户反馈记rejected：人物位置改变、多出人物。已确认原批准尾帧没有漏传，但文字模型自行声明屏幕布局，原审查漏核其来源，实际prompt缺闭合演员名单。独立合同v5/v6和执行入口v6/v7已修闭合人物场景、原帧机位权威、全字段无来源布局验收及审查提醒与必修改分离，22+19项必要离线检查通过。真实507/508新稿被验收阻断；509完整响应抄错顶层源SHA而拒收，两轮内容返修已满，本次新视频0。累计509次/7,772,480 reported tokens，未知历史和媒体失败预算承接。后续机械身份由编译器绑定的合同v7仅离线，不采用旧509，不把测试算成创作/视频质量通过。实际请求、人工反馈、生产停点与继续范围见[返修记录](CREATIVE_CONTINUATION_SPATIAL_REPAIR_20261011.md)。默认v23、旧冻结记录和逐段人工审核规则不迁移。


### 2026-10-11 新协议续行生产结果

最新第三段续行入口：.venv\Scripts\python.exe scripts/run_selected_script_continuation_v8.py status。新原生和编译身份分别核验，不能手工删509字段采用旧稿。当前生产已完成510/511与third_v8，视频awaiting_human_review、新尾帧saved_unapproved。已有receipt仅可media_query，不得再次media_submit；下段须用户明确批准本段。证据：script487_continuation_v8/PRODUCTION_RESULT.json、third_v8/receipt.json；详情见[返修记录](CREATIVE_CONTINUATION_SPATIAL_REPAIR_20261011.md)。


### 2026-10-12 共用身份合同审计与当前拒绝

third_v8已按用户“性别改变、人物没对齐”反馈记rejected。开场/第二/第三实际请求同源且原尾输入正确，但角色只定义ID/称呼/剧情职责，缺性别外貌服装声线及角色到画中人的映射；旧资产身份服装仍待定，当前十项门未检查完整共用身份与投影覆盖。见[全片共用制作元素审计](CREATIVE_SHARED_PRODUCTION_ELEMENTS_AUDIT_20261011.md)。本轮新增模型/媒体0，不观看媒体、不修改冻结代码；新共享manifest尚未部署，不从已拒尾帧续段。旧awaiting_human_review为交付时历史快照。
# 2026-10-12接口能力定位入口

遇到角色错配、缺参考或格式错误，先查[模型能力与环境核对](CREATIVE_PROVIDER_ENVIRONMENT_AUDIT_20261012.md)，逐层比较官方型号/协议、通用客户端、选定入口和实际HTTP参数。文档支持不等于已接线，输入受信不等于视觉通过；DeepSeek严格外层字符串不约束内层合同。新增只读审计不发生成请求，旧失败与候选额度保持原绑定。



## 2026-10-12 新法律来源完整文本后台测试

用户已确认先采集法律号新数据后跑完整流程。新独立接线与后台已启动，首次实际搜索触发human_required，0新样本、0模型/媒体；当前待用户在已开的验证窗口完成提示。范围、合同、离线/独立证据与实际停点见 [新来源后台实施与停点](CREATIVE_FRESH_LEGAL_BACKGROUND_REVIEW_20261012.md)。旧512导演7/7、累计520/7964215及历史未知完整保留；新批次不能重领同故事额度，不盲重启原RUN_CLAIM。只在新批样本门通过后进入完整文本/导演/表演/制作交接，本次不生成媒体或发布。


## 2026-10-15 世界框架、逐场情境与全体人物表演

用户新增要求已进入独立通用合同，规范见[世界/场次/表演说明](CREATIVE_WORLD_SCENE_WORKFLOW_GUIDE_20261015.md)，接线计划见[通用流程接入](CREATIVE_WORLD_SCENE_INTEGRATION_PLAN_20261015.md)。本会话负责通用代码和离线验证，当前样片实际重写及视频生成由另一会话推进；不要混用双方的产物和消耗。

独立world_scene_context/v1与workflow28不静默迁移默认v23/旧冻结入口。完整世界/场次/ensemble需要进入实际生成、原规划四审、同源全文审查及下游上下文；旧正文缺新字段直接拒收，不由渲染补写。正文排列序不作完成时间，动作对白可并行，动作前提仍需原生初态或有据先后。当前新入口为无网络preview/Mock，真实接口、创作质量与视频人工批准各自验收，最终接线状态以本轮实际交接为准。

本轮已完成通用合同与离线接线验收，实际入口/证据/未接入生产范围见[最终交接](CREATIVE_WORLD_SCENE_WORKFLOW_REVIEW_20261015.md)。源码及文档增量副本另存creative_world_scene_release_20261015_v1，旧入口和账本保留。
