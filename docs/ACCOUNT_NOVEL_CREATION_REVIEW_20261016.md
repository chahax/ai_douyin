# 账号选题到目标小说完整创作：实施与使用

日期：2026-10-16。范围为本轮用户指定的“账号选题 → 目标小说完整创作”。开发方案见 [开发计划](ACCOUNT_NOVEL_CREATION_PLAN_20261016.md)。

## 实际实现

本轮新增独立 `account_novel_creation/v1`，串起已有小说推广账号机会、目标书匹配、实际章节正文冻结和完整创作器。页面入口为“热门选题 → 选题卡 → 当前运营账号（小说推广）→ 小说账号机会 → 目标小说完整创作”。原页面的旧机会卡函数未被当前页面调用；实际接线是在 `_render_briefs` 选择小说账号后直接分支，先于法律专用的 `PreVideoScriptService`，没有解除该服务的法律领域限制。

| 环节 | 当前行为 |
|---|---|
| 账号选题 | 读取同账号现有 ContentOpportunity，可复用现有研究/机会服务刷新；校验账号状态、profile_version、领域/策略版本、机会状态和有效期 |
| 目标小说 | 扫描本地小说库，按账号题材和机会标签匹配，可指定书ID；记录匹配项和排除原因，无匹配不默认选第一本 |
| 原文范围 | 绑定 book_id、原文件与元数据/依据的字节 SHA256；已知番茄 material.txt 按采集器“详情页”边界剔除简介，仅将实际章节正文交给创作器 |
| 完整创作 | 复用 CreativeWorkflow 的源理解、候选、导演前期、完整剧本、分镜和同稿审查；MiniMax 创作、DeepSeek 审查 |
| 完整返修 | 独立子类隔离本次 prompt/Schema，不改旧全局合同；整份新稿采用、全部分镜重建、全文复审，最多两轮内容返修 |
| 执行恢复 | 独占准备/执行锁、原目录恢复、既有逻辑任务去重及预算；每次新派发复核本地冻结、实际账号机会和服务协议；重复执行完成任务不新增调用 |
| 完成判断 | 核对原文范围、最终全文、分镜、同稿机器审查、交接哈希及底层完整输出清单后，根状态为 `machine_text_complete` |

机器文本完成不表示用户采用、人工审美通过或视频通过。本入口没有新增逐稿人工批准前置；旧底层 `assistant_review_required` 和 pending 回执如实保留，在根报告中单独说明其来源，`human_approved=false`。它们不被篡改成新的人批记录。本轮不进入视频生成、推广申请、发布或回填。

## 保存位置与入口

默认任务根目录为 `D:\IT\ai_douyin\data\account_novel_creation\v1`。网页以账号UUID和机会ID派生稳定目录，重复点击沿用原任务；具体绝对路径直接显示在页面。

每个任务保存：

- `SELECTION.json`：账号/机会快照、候选依据、选定书ID、实际正文区间。
- `BINDING.json`：正文/依据/配置/代码身份、实际模型服务协议、预算和逻辑任务身份。
- `ENTRY_CONTEXT.json`：实际账号库/选题库与账号、机会来源绑定，不含登录信息。
- `frozen/`：实际章节正文、元数据、文本使用依据及账号机会快照。简介不作为剧情事实来源。
- `creative/SCREENPLAY.md`、`SCREENPLAY.json`、`STORYBOARD.json`、`EDITORIAL_REVIEW_PACKET.json`：完整创作产物及同稿审查。
- `creative/` 内原生请求/响应、用量、状态与交接，以及根目录 `STATUS.json`、后台 `execution.log`。

CLI 可在项目根目录运行。以下的账号键、机会ID与任务目录需填写真实值：

```powershell
.\.venv\Scripts\python.exe scripts\run_account_novel_creation_v1.py prepare --account-key 具体小说账号 --opportunity-id 具体机会ID --run-dir data\account_novel_creation\v1\具体任务
.\.venv\Scripts\python.exe scripts\run_account_novel_creation_v1.py preview --run-dir data\account_novel_creation\v1\具体任务
.\.venv\Scripts\python.exe scripts\run_account_novel_creation_v1.py execute --run-dir data\account_novel_creation\v1\具体任务
.\.venv\Scripts\python.exe scripts\run_account_novel_creation_v1.py inspect --run-dir data\account_novel_creation\v1\具体任务
```

`prepare/preview/inspect` 不调用模型；`execute` 才进入真实文本服务并可能产生费用。默认最多20次调用、500000 reported tokens、两轮内容返修、8次格式/合同修复，预算与逻辑任务绑定，恢复不能修改。本轮测试没有真实服务调用。

可选 `--books-root` 指定既有素材目录，或用 `--catalog` 指定JSON候选列表；列表中的文件路径相对列表位置解析。`--target-book-id` 指定目标书，仍须满足账号机会、材料与来源资格。账号/选题库可用 `--account-db`、`--trend-db` 指定，首次准备后冻结，不能换库恢复。

## 材料条件与停点

自动发现读取每本书的 `meta.json`、`material.txt` 及可选 `text_authorization.json`。已有下载不自动视为文本使用授权；可在候选清单中绑定既有真实依据，或为已确认范围登记依据文件。依据字段为 `book_id`、原文件字节 `source_sha256`、`allow_text_adaptation=true`、`allow_model_input=true` 和真实依据 `reference`。程序不代写真实书籍授权，也不据此声称平台推广任务已生效。

无匹配书、正文/依据缺失时记录 `needs_materials/no_matching_book`，不调用模型。补齐后可在原目录再次准备，先前失败和缺口归档到 `PREPARATION_HISTORY`。已经开始的创作保持原来源和原消耗，不能借此重选书或重领预算。

未知结果、用量未知、截断、未明确完成、在途锁及输入/协议变化均停止。未知响应保存原文、元数据和原生响应包；总用量写 `null` 并分别保留已知用量，不按零消耗解释，不自动重派。账号或机会在阶段间变为禁用/拒绝，也会在下一次真实派发前停止，标明未派发。

## 验证证据与实际边界

验收证据保存在 `data/qa/account_novel_creation_20261016_v1/`：

- `baseline_rerun.xml`：旧账号领域、机会服务和完整创作相关289项回归通过。首轮系统临时目录被环境权限阻断；改用项目内新临时目录后复验，无代码失败。
- `final_suite.xml`：本轮新增模块、真实页面分支及数据库到默认工作流的首轮集中离线验收，96项通过。
- `final_suite_v2.xml`：最终集中验收98项通过、0失败、0错误、0跳过，包括实际网页面板的准备/启动、查看者权限与空文件产物停点检查。
- `dashboard_route.xml`：独立 AppTest 验证当前实际页面进入小说分支，没有进入法律专用创作器。
- `ACCEPTANCE.json`：最终范围、测试回执和交付文件SHA256清单。新增代码及8个新测试文件的Ruff检查通过。

子 agent 分别实施选择、创作适配、CLI/面板，主 agent 审查接线及失败用例；选择模块子 agent 另作只读独立故障审查。修复了选择与冻结之间的原文变化遗漏、Windows CRLF二次转换、未知用量原生响应包丢失等实际复现问题。完整入口测试使用临时账号/机会数据库和模拟服务，但实际执行新 CLI 适配及 CreativeWorkflow，不以 mock 返回 completed 代替产物。

首次入口测试曾误将4份纯QA逻辑登记写到默认本地登记库；已按其 `run_dir` 严格匹配对应QA根，归档到 `data/qa/novel_entrypoints_initial_registry_archive_20261016`，证据保留。后续测试均使用独立登记库，没有修改生产历史登记或新增真实调用。

本轮验收只证明代码接线、合同、恢复和离线故障处理。未选择真实账号/目标书执行新一轮付费创作，未新增真实创作质量通过。书籍匹配当前使用可解释词项规则；素材不足时停在材料阶段，未自动启动番茄新书采集。现有采集能力仍可先获取素材，再从原准备任务继续。
