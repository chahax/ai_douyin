# 账号浏览器管控：主审与部署交接

用户已批准“按方案开发，发布优先后恢复后台”。本轮按账号管控层实施，先记录分析和检查点，由三个独立模块实施，再由主 agent 审查接线及真实本地浏览器行为。分析、实施合同、core/tabs/runtime/独立复验文档保留，不覆盖旧冻结、媒体、失败和账本。

## 实际功能

账号拥有持久命令队列和单一浏览器 owner；业务在原 owner 线程串行执行，各自借用固定标签页。后台播放在完成一个完整项目后保存实际游标和累计结果，允许优先执行已授权发布，核验成功后回到原循环和标签页。无可靠恢复点的路径等待整轮结束；进程丢失后不能自动重建旧 Python 执行栈。

人工验证采用短开窗请求和可查询等待状态，保留原验证页。“处理完成”仍由后台核验原身份和原阻断，不把关窗当验证成功。官方管理页单独保留原用途，关闭该标签页只结清自身，不改变账号暂停或关闭验证页。指标 UI/CLI 保留原配额，通过同一 owner 执行。前端增加“账号浏览器管控与发布队列”。

发布继续复用原表单、主动 AI 声明及读回、虚构声明前缀、唯一提交锁和准确作品核验。只有作品核验成功后才执行原授权的普法评论；评论点击前保存幂等记录，结果未知不重发。未知发布、绑定变化、人工验证和旧运行锁均不被新队列清除。

## 验证及保留的问题

最终受影响套件 `data/qa/account_browser_control_20261018/AFFECTED_FINAL.xml` 为 **150 项通过**。真实 Chrome 本地组合 `browser_control_combined_local_03/RESULT.json` 为 **15/15**，实际覆盖 core → resource → borrowed session → worker，确认原 context/storage/worker 复用、任务分 tab、发布插入前游标落盘、同线程串行及原 locator 恢复。业务网页及 admission 在此实测中使用本地 fixture，不能当真实抖音发布验收。

随后仅补充发布开始前的只读配额准入：原当日 20 次上限或原熔断仍有效时，同一命令继续排队，handler/browser 尚未启动；原事务内二次门不变。另 **2 项真实 actor 回归通过**，包含次 UTC 日同 ID 准入，以及嵌套发布受限时原后台保留游标并暂停，不把吞异常后的返回写成功。此增量不冒称已重新运行 150 项，绑定见 `PUBLISH_QUOTA_GATE_REVIEW.json`。

首次广覆盖报告 `PRIMARY.xml` 为 454 通过、4 失败，完整保留：其中 core 心跳与连接争用已修复，并进入最终受影响套件；另三个旧节点原参数隔离复验为 4 个参数用例通过。兼容新增真实 Streamlit 页面渲染点击 2 项通过，配置/关闭顺序 2 项通过。另一旧完整趋势页仍在读取历史日志时超过原 30 秒，并发现既有混合类型表格错误；未修改其超时或宣称该页面全通过，证据见 runtime review。

首次 16 文件检查点为真实编辑前副本。兼容扩展三个文件漏做编辑前副本，已明确以反向重建保存，不冒充原始快照。源码与报告 SHA 绑定见 `data/development_checkpoints/account_browser_control_20261018/PRIMARY_FINAL_BINDING.json`。既有 manual-window 新库 WAL 分支来源由 `MANUAL_WINDOW_WAL_PROVENANCE.json` 核对，本轮未引入或修改；新 core 存储未启用 WAL。

## 本次真实切换与发布停点

旧人工窗口于北京时间 23:42 正常结束并释放原锁。切换前重新只读核对所有账号的 refresh/smart/playback、人工窗口、处理请求和 runtime locks 均无在途，才重启项目后台服务。首次新服务实际 PID 23624，health HTTP 200；项目 `.env` 仅新增 `AI_DOUYIN_BROWSER_CONTROL=1`，没有复制凭据。调度、worker、旧三个账号后台组件、人工窗口和新 browser_control 均有新鲜健康回执。

配额增量的第二次切换采用 `scripts/handoff_idle_browser_control.py`：在 control DB 写事务阻止下一次 claim，核对精确 PID/创建时间/owner nonce/账号/代次、全部非终态命令仅 queued、原业务无租约/未决引用/未结束运行、旧人工任务无在途、服务没有子进程，才停止原服务。确认进程死亡后只调用原 `release_owner` 交还，不修改命令、旧账号或未知状态。脚本 11 个隔离分支通过，新增两门及正常交还 3 项复验通过；第一次生产调用因 PowerShell 未加引号的浮点参数精度被身份门拒绝，未停止服务，按完整精度字符串重新核对后成功，未放宽任何比较。证据为 `HANDOFF_SCRIPT_REVIEW.json` 与 `OWNER_HANDOFF_QUOTA_PATCH.json`。

最终实际服务 PID **43636**，health HTTP 200，owner 第 **2** 代，发布命令仍是原 ID，原暂停与配额记录保持。最终验收为 `DEPLOYMENT_QUOTA_PATCH.json`。这是对已证明未派发队列的监督升级，不是失联/未知 owner 自动接管流程。

已将用户原明确采用的 60 秒成片及发布文案、标签、普法评论冻结入队，原命令 **55c79f0c86b8485ab95318b26dac1aec**；命令与原视频 SHA/账号/授权文件绑定。此操作不是平台上传。当前账号原暂停原因为 `human_required`，原当日运行次数为 20；实际服务没有启动浏览器子进程，也没有上传、发布或评论。恢复原验证及配额条件后仍使用同一命令，不重新创建视频提交。

部署前后证据见检查点下 `DEPLOY_PREFLIGHT_FINAL.json`、`DEPLOYMENT.json` 和 `DEPLOYMENT_QUOTA_PATCH.json`；最终源码与增量报告另绑定 `PRIMARY_FINAL_BINDING_V2.json`，首版绑定保留。真实验证码、平台主动声明、作品审核展示及评论可见性尚待平台执行，不能以本地实测或服务健康代替。
