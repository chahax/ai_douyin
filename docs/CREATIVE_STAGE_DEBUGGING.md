# 创作阶段调试、版本与人工审核

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
