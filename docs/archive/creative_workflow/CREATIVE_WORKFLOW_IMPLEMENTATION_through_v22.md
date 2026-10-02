# 创作平台当前实现（2026-10-02，v22）

本文件以 [方向报告](../data/qa/creative_platform_refactor_20261002/direction_report.html) 为核心，承接 v20 复核清单和 v21 P1 闭环。当前实现是完整剧本、导演安排、请求预览、逐段生成与用户审核工作台。研究是可选输入，发布与运营是独立下游。

## 当前责任边界

| 责任 | 当前实现 | 执行边界 |
|---|---|---|
| 创作简报、来源冻结 | creative_workflow_inputs / logical task registry | 原文件哈希、来源范围、逻辑任务与预算绑定 |
| 故事、人物与候选 | creative_workflow / existing role clients | 原请求、原响应、候选依据保留 |
| 完整剧本与全文复核 | creative_full_script_revision / existing review gates | 完整新稿整体采用；未核实意见、unknown、预算不足不放行 |
| 整体导演安排、分段分镜 | creative_segmented_director / state-plan modules | 保留未来正文、上一镜终态；返修版本化上下文与派生产物 |
| 阶段运行、输入、结果和依赖 | creative_stage_runtime / creative_stage_contracts | 自动、断点、单步共用；实际输入字段投影与完整请求兼容证据 |
| 媒体请求、候选与反馈 | creative_media_workbench / creative_segment_execution | 独占提交、ID 续查、源版本链、人工决定、镜段秒点及责任路由 |
| 批准链合成、完整成片待审 | creative_media_workbench.assemble_approved | 采用现有原音轨 concat 配方；合成成功仍等待整片人工审核 |
| 浏览器发布、运营回接 | creative_delivery / existing DouyinAdapter | 完整成片批准、账号校验、AI 主动声明、虚构前缀、提交锁与独立核验 |
| 质量样本及费用证据 | creative_quality_evidence / creative_evaluation | 候选不计金标；人工标注、留出隔离、原始用量及缺失字段保留 |

没有增加第三审核模型或更换技术栈。原有执行器继续负责模型、验证、预算、浏览器与指标采集；阶段编排、媒体执行和交付边界已拆出独立模块。

## 输入、产物与返修

`.creative_debug/inputs` 保存 `creative_stage_input/v1`：task/run/stage、角色、完整 payload、输入与提示哈希、模型配置类别、规则绑定、审核版本、预算及实际消费的父字段投影。字段投影只记录请求中真实存在的非空对象或数组，不按语义猜测依赖。

`.creative_debug/results` 保存 `creative_stage_result/v1`：输入绑定、不可变产物、技术验证、调用计数及下一步。原始模型响应、验证结果、文本复核与视频人工决定继续分开记录。产物地址同时包含输出和输入哈希，因此相同输出、不同请求不会覆盖。

必修反馈先按保守阶段图失效下游。回放修复后的上游时仍重建原反馈上下文。下游完整输入和提示均未改变时生成兼容证明并复用；任一改变则归档原请求和相关复核决定后重建。未知调用不因失效而归档成可重发任务。新响应已经收到或已校验、但最终登记中断时，可无额外调用恢复；旧阶段历史不被改写。

页面提交反馈同时检查所见输入和输出哈希。CLI 可传 `--expected-input-sha256` 与 `--expected-output-sha256`。建议仅留档，必修才产生返修门。版本对比同时返回输入和输出差异；正文相同也展示输入版本变化。指定重复输出哈希时，须同时提供 `--base-input-sha256` / `--target-input-sha256` 消除歧义。

## 自动、调试与停止

现有 `run_creative_workflow.py` 是同一执行入口。无断点参数时自动推进文本，`--next-stage` 单步，`--stop-after-stage` 指定断点。全文/聚焦审核待核实、unknown、媒体人工审核和预算边界仍停止。自动文本通过不自动付费生成或发布。

`debug_creative_workflow.py RUN stop/resume` 写独立控制回执及历史。停止阻止后续派发；正在运行的调用保存响应和文件，已有媒体 ID 可继续查询。恢复不重置预算。同任务文本派发和媒体回执写入均使用独占锁。媒体另有同稿提交登记与默认 10 次失败上限：技术失败和用户拒绝累计，同一计划不可借换目录再提交，未知任务或候选待审时禁止该段再发。额度拒绝记录为 `blocked_before_submit`，与已经调用服务但结果未知分开。旧稿账本保留且不扣到新稿；新稿仍须通过既有新稿登记入口创建，不能用改目录领取额度。进程异常退出留下锁时，先核对原进程、请求 ID 和原回执，不能直接盲重试。

## 媒体与交付链

1. `compile_creative_seedance_segments.py` 冻结当前剧本、分镜、能力审计、交接和模板预览。未解决文本反馈或待复核时拒绝登记当前预览。
2. `creative_workbench.py RUN prepare-segment` 将模板与实际首帧来源绑定为单段计划。续段必须是同一版本链紧邻前段的人工批准原始尾帧；计划切镜必须另有已审新机位首帧，并保留前段批准。
3. `run_creative_seedance_segment.py preview/submit/query` 使用共享执行器。预览与提交采用同一实际模板；提交回执独占创建。未知无 ID 时停止对账，有 ID 时只续查。查询已保存候选保留用户决定。即使源文件后来变化，也能查询原 ID；源变化阻止沿用内容批准。
4. 候选只记录技术成功和 `awaiting_human_review`。`review-media` 绑定原视频、候选、镜段、可选时间范围、用户原话和版本链。不通过且无责任证据时待定位；有当前上游版本及证据才登记该责任阶段 must_fix，不自动重生成。
5. `assembly-chain` 与 `assemble --execute` 验证批准顺序、原始文件和来源，采用各段原音轨生成整片候选。整片还需单独人工批准。仅 `segment_id=final` 的批准成片能生成发布交付。
6. `prepare-delivery` 先生成可核对的交付预览。`publish --execute` 调用现有账号绑定浏览器发布，主动设置并读回 AI 声明，虚构声明始终置于简介首部。发布结果、原声明动作、截图和提交锁回接到交付目录。
7. `verify-publish` 只核验原作品，未取得准确链接或待平台审核不能记最终完成；`collect-operations` 只回接同账号同作品，缺失指标为 null，不自动改稿或再次发布。

程序不抽帧、听看、ASR 或调用音画审核模型。自动测试中的媒体字节、人工决定和浏览器页面均为明确标注的夹具，不能计为真实内容审核或真实发布。

## 质量验收

`collect-quality-case` 从已验证阶段复制冻结源，默认开发候选。`annotate-quality` 要求人工金标、原话及精确源哈希。开发样本不能转为留出；`freeze-quality` 检查独立组、同源泄漏与样本缺口。同一故事的变体和重复执行不增加独立样本数。

原标准保持：80 个人工批准独立样本、40 个冻结留出、4 类错误/正确覆盖、每版本 3 轮；另核对 12 个修复案例、6 个独立创作简报和 10 个边界案例。`quality-report` 接入既有评分器与原调用回执。未确认调用、缺失账单、时延或人工工时不填零，不以估算证明真实降本。真实创作质量、留出通过和优化收益须满足证据门后才能宣称。

## 版本与证据

当前新治理任务绑定 `data/creative_governance/20261002_v22_platform_refactor_workbench`。v20 和 v21 原包保留；旧任务不静默改绑。新独立故事通过既有登记入口绑定 v22。同意图仍绑定原目录与预算；本版不提供跨治理版本自动迁移命令，旧任务在原冻结环境恢复或保持只读。不能删除登记、改焦点或新建目录为同一故事重领额度。MIGRATION.md 明确未来迁移须承接累计预算、历史及未决反馈并重验全部采用产物。

本轮验收位于 `data/qa/creative_platform_refactor_20261002/remaining_refactor_v22`。它验证现行执行链的代码、预算、历史和故障恢复；没有真实付费媒体生成、发布或新增人工质量金标。先前试跑与 P1 验收继续保留。

历史实现与试跑说明见 [截至 v21 的归档](archive/creative_workflow/CREATIVE_WORKFLOW_IMPLEMENTATION_through_v21.md)。
