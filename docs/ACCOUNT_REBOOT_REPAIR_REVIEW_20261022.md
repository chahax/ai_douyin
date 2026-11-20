# 账号重启恢复修复与验收

用户在原因分析后明确“你修”；随后明确授权“允许取消这条旧开窗任务并核验”。本轮不新增媒体、发布或评论。

## 已实施

- 浏览器扫描同时发现 queued、在途/未知任务和未交还 owner，不再漏掉只有旧 running 的账号。
- 领取任务与 admission_pending 阶段同事务保存；调用业务 handler 之前先提交 handler_entered。单独的执行表及事件表记录请求 SHA、owner、代数、时间与退避，旧任务不补造阶段。
- 只有主机上次启动周期、请求/绑定/owner/代数完全匹配且持久证据证明尚未进入 handler 的 running，才沿原 ID 回到队列。阶段缺失、已进入业务、paused、waiting_human、unknown 及证据变化继续阻挡。原命令快照随恢复审计保留。
- 额度耗尽最多等待 5 分钟再检查，跨 UTC 日期提前重查；人工处理完成和解除熔断不被这个退避延迟。普通每日额度没有扩大。
- 启动宽限 5 分钟后，符合条件的启动前历史暂停可申请一次原身份核验；同账号同 boot 只一次且至少间隔 24 小时。只处理约定的验证/导航暂态；主动暂停、未知结果不自动放行。旧 owner、原任务、业务租约、人工窗口或读取异常会阻挡；核验失败后不循环重试。
- 账号管控心跳区分“扫描正常”和“旧执行者阻挡”。前端分别显示账号暂停、owner 心跳、任务阶段；心跳过期不再显示为可信执行中。队列页面限定最多 100 条轻量记录，不读取历史 payload/result 大块审计内容。
- 原 Windows 任务 AI_Douyin_Streamlit 保留登录触发，增加每 5 分钟补启动；Interactive 和 IgnoreNew 保持。它补起缺失进程，不会因为账号暂停杀掉运行中的服务，也不处理活进程卡死。计划维护需先禁用此任务，结束后启用。仍需当前用户已登录，不是无人登录系统服务。

## 测试

最终通过收据 core2.xml（64）、final1.xml（85）、presentation.xml（56）、guard.xml（87），共 292 次执行、196 个不同用例。包括实际子进程 os._exit 中断前后、真实 SQLite 原 ID 接续与拒绝重放、额度退避、原身份通过/失败/后续暂停、发布优先、页面显示，以及本地真实 Chrome 新旧搜索卡片读取和超时页面保留。

测试中保留了失败证据：首次临时目录父目录缺失；初版通用退避影响人工完成后的即刻续行，已缩到额度耗尽；旧页面 fixture 受运行环境的托管开关影响，已明确隔离；本地 Chrome 的 200ms 测试超时偶发发生于文档提交前，已改为 1000ms，仍由 2 秒未结束网络请求强制触发 networkidle 超时并验证真实证据。生产浏览器的安全判断未因此放宽。旧失败 XML 保留，不将失败轮改写为通过。

这些是代码、隔离浏览器和恢复边界验证，不等同于原账号已完成一次抖音搜索或观看。

## 生产部署与历史任务处置

部署前精确核对原 PID12416、创建时间、命令行及无子进程；账号计划与运行租约为空，通用任务没有 running。三库栅栏与浏览器库事务保护下只停止原空闲后台，原任务、历史发布结算、未知记录和暂停不变。原 Windows 任务已启动 PID33496；生产即时证据在 data/account_reboot_repair/20261022 和 data/service_startup_monitor。

旧开窗任务 `6dbb0d77e18240a49b4df7d014089e89` 无执行阶段证据。经用户单独明确授权，已保存完整原命令、原 owner、授权及跨启动/原 profile 无进程证据，并以 operator_cancelled_unknown_manual 处置，original_outcome_known=false；未重派旧窗口。只交还原 generation42，后续由正常管控获取新代。原暂停没有直接改 active，已登记一次原身份核验。

真实原身份核验 `44a1edc21c894814a4ed92ac79be1983` 已成功，expected_account_uuid 匹配原账号；账号恢复 active/revision65，generation43实际领取并执行维护 `a6514d1597c046cea2f94946d4eff648`。原完整快照与部署源码 SHA 核验通过。

维护实际结果为 partial：读取并同步3条自有已发布视频、3条评论，评论失败0；新搜索视频0、实际观看0秒。搜索“装修合同”观察到阻挡iframe，但可操作验证未确认，error_code=verification_ui_unconfirmed。原计划按该真实结果重新暂停为revision66，没有用作品同步成功抹去搜索失败。

原异常自动开窗已登记新任务 `defce1a4399c4522863e65e38427b820`，由generation44处理并停在waiting_human。新窗口当前回执 surface_state=load_failed、status=verification_unknown，尚不能要求用户完成一个已经确认可操作的验证码。此次单次身份核验授权已实际使用，不新增重试、不关闭或重复派发这条新窗口。

生产中另观察到SQLite争用。只读线程栈 `BACKEND_STACKS_01.txt` 明确显示浏览器每次页面guard在提交额外心跳，其他任务等待同一元数据锁。已将操作前核对改为只读owner/代数/绑定/时效验证，独立心跳照常续约；没有降低数据库同步级别或延长过期owner。87项专项回归通过后，在精确PID33496中只替换这两个已测试方法，保留原方法供回退，未重派业务或打断窗口；实际加载回执为GUARD_PATCH.json。源码也同步保存，重启后使用同实现。之后七个组件观察到新鲜心跳，但不据一次恢复断言所有数据库争用已根治。

当前结论：服务自启、原身份核验、原计划恢复与作品/评论同步已实测；平台搜索验证页加载问题仍存在，账号目前再次暂停。补启动触发配置已读回，运行中触发时保持同一个服务PID；未为验证此设置重启主机或中断业务。Codex automation-2仍保持原PAUSED状态，本轮没有声称恢复该会话定时监控。

## 用户完成验证码后的复核（2026-10-22 21:56）

用户明确“刚刚有个验证码我手动通过了”。经只读核对原窗口 defce1 仍为已知 waiting_human，通过正常 complete_account_handling 登记一次完成请求，未取消或重开窗口。新的身份核验 `15b2d7a9335b4a609497732fb9305c8e` 成功，expected_account_uuid 匹配原账号，账号恢复 active/revision68；原人工窗口任务自动结为 succeeded，标签页保留。

原计划随后实际派发维护 `68e21e6e987b441099362cf216df9528`，generation44 已进入 handler；21:56:31 采样仍在执行。此刻确认账号核验和计划接续成功，尚不能认定本轮搜索或推荐流观看成功。原失败记录保留。完成登记与采样证据分别为 `CAPTCHA_COMPLETION_1792677265250698100.json` 和 `PRODUCTION_VERIFY_1792677391.json`，均位于原修复证据目录。原报告此处本地时间误写22:36，现按回执时间戳更正为21:56。

## 搜索页面停留复查（2026-10-22 22:18）

用户反馈页面似乎又卡住。只读核对确认维护68e21于22:02:20结束，smart计划447102于22:02:41结为completed；原人工任务已succeeded，账号active/revision68，三个计划均无运行租约，七个后台组件心跳新鲜。当前没有卡在该搜索页的执行任务，原处理标签页按设计保留。

实际维护回执 `maintenance_b9183d53f8f442f7b0adc630df9cd0b4.json`：同步3条自有视频、2条评论，1条作品评论同步失败；相关内容采集计数8，去重保留4条。自动分析仍因4/20条视频、1/2个主要标签、19056/1000000点赞门槛而停止，未生成自动选题或剧本；没有实际观看、点赞或发评论。不能将completed解释成所有子功能无告警。

截至采样，下次作品同步为10月23日02:02，智能运营搜索为10月23日22:02，推荐流观看为10月23日11:47:19。三个计划均启用；养号仍遵循已配置随机时间窗，本次未手动派发新任务。新只读生产证据为 `PRODUCTION_VERIFY_1792678694.json`。

## 文件入口

- 原因及架构：docs/ACCOUNT_STARTUP_ARCHITECTURE_20261022.md
- 执行阶段：src/operations_accounts/browser_execution_journal.py
- 重启恢复：src/operations_accounts/browser_boot_recovery.py
- 暂停复核：src/scheduler/account_startup_recheck.py
- 补启动配置：scripts/enable_streamlit_missing_process_catchup.ps1（默认只预览）
- 部署与取消证据：data/account_reboot_repair/20261022/DEPLOY_STOP.json、MANUAL_DISPOSITION.json
- 单次核验授权：data/account_reboot_repair/20261022/CANCEL_AND_PROBE_AUTHORIZATION.json
