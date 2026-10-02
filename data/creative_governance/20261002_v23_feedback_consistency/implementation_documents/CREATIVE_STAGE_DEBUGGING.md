# 创作阶段调试、版本与人工审核

本页描述 2026-10-02 重构后已接线的创作控制面。完整方向与取舍见
[`direction_report.html`](../data/qa/creative_platform_refactor_20261002/direction_report.html)。

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


## 本轮治理绑定与验收

新治理任务默认使用 `20261002_v23_feedback_consistency`；冻结 v20–v22
及其复核报告保持原样。旧治理任务不能静默换绑，具体迁移与 provenance 要求见
[新冻结包迁移说明](../data/creative_governance/20261002_v23_feedback_consistency/MIGRATION.md)。
逻辑任务预算继续绑定原任务；显式迁移应另外确认未决外部任务并携带原额度账本，
新目录不授权领取新额度。本轮未迁移生产任务。

本轮以 [v20 最新复核](../data/qa/creative_platform_refactor_20261002/v20_confirmation/confirmation_report.html)
为清单，以 [方向报告](../data/qa/creative_platform_refactor_20261002/direction_report.html)
为目标；实际运行器、CLI/UI 共用命令层、连续两轮和多阶段反馈的离线执行证据见
[本轮验收报告](../data/qa/creative_platform_refactor_20261002/p1_closure_v21/acceptance_report.html)。
该验收使用假服务响应，只证明操作链路，不证明新提示效果、创作质量或媒体内容通过。


## v22 工作台入口

当前完整行为见 [创作平台实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md)。停止/恢复命令为
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
