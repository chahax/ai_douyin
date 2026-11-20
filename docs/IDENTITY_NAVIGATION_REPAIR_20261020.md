# 原身份核验超时修复与实测停点

用户在前一条误入测试取消完成后明确要求继续调试测试。本轮已发起原账号一次真实身份核验；并未发起观看、互动、发布或媒体生成。

## 真实结果

核验任务 `66847ff658b54c939c816e258c0df99d` 于北京时间17:25进入原管控队列。浏览器约14.9秒启动成功，随后核验处理抛出 `AccountRuntimeError`，原任务为 `outcome_unknown`，账号暂停到revision50。服务仍为PID21472、owner gen35，业务lease已释放。原任务只有handler阶段和包装异常类型，**不能据此证明底层一定是导航超时**。原绑定身份未更新，实际观看测试没有提交。

完整原任务保存在 `data/browser_navigation_repair/20261020/production_smoke/RECOVERY_FAILURE_ORIGINAL.json`；原失败不改写为成功。

## 已修复、尚未部署

- 身份页原先不处理已提交目标页面的原生跳转超时。现在仅在导航已提交、目标精确匹配、文档可读时读取原页面身份；仍须通过验证码检测和原身份匹配。目标错误、未提交、仍加载或未读到身份时保持暂停。超时恢复路径不点击个人页或重载。
- 已知导航失败返回结构化身份核验失败，保留安全导航证据。它不表示登录过期，也不自动重试。
- 管控未知异常增加有界异常链诊断，仅记录类型、允许的错误码及脱敏导航事实，不记录异常原文、页面文本、URL或凭据。通用未知保护保持。
- 两处旧回归夹具隔离遗漏已修正：本地runtime测试不走真实管控入口，cron测试隔离部署维护模块。生产数据库保护曾拦截误访问，未放行真实数据读写。

## 验证

最终有效95个不同用例通过，来自多批报告，不是一次95全绿：

- `TEST_IDENTITY_V3.xml`：86通过、1个旧cron隔离夹具失败。
- `TEST_RECOVERY_FINAL.xml`：修夹具后25个账号恢复测试及2个异常链测试通过，包含对上述失败的复验。
- `TEST_CHROME_IDENTITY_V2.xml`：本地真实Chrome身份页超时后同一文档核验通过。首次200ms用例因页面未满足可读门而失败；保留失败报告，改为1秒导航期限与5秒未结束请求验证目标场景。
- `TEST_DISPOSITION.xml`：6个隔离SQLite处置保护测试通过。

报告、源文件SHA及有效去重结果在同目录 `REPAIR_VALIDATION.json`。这不证明原平台核验、采集或实际观看已恢复。

## 部署前阻塞与具体处置方案

新核验是独立的真实未知任务；此前用户“取消”只针对误入测试46186a，不能复用于本任务。`AGENTS.md`要求未知原ID/锁保留、不盲重派。

已准备但未执行 `scripts/dispose_recovery_probe_20261020.py`：须提供本任务明确取消和部署批准；冻结原命令，校验原PID/创建时间、账号profile、gen35、paused50、所有业务lease与人工窗口空闲、仅本条实际未决。持有数据库写栅栏后，仅停止已核对的本项目服务，等待原专属无头浏览器自然退出，保存原unknown完整快照和不确定性，再审计取消本核验并交还原owner。任何变化或退出不明都停止，不盲杀子进程，不重跑原任务。

批准后计划部署修复，使用普通额度新核验一次；通过后执行一条、15秒、最多2分钟的观看诊断。仅排队/健康页/心跳均不能作为观看成功。原每日三随机时段设置与点赞评论关闭保持。

## 用户批准后的部署与核验

用户明确“允许处置这条核验并继续部署实测”，批准保存在 `production_smoke/DISPOSAL_APPROVAL.json`。原66847已按审计脚本取消，原unknown完整快照、不确定性和原生历史保留；原21472及专属浏览器退出，gen35交还。执行收据为 `RECOVERY_DISPOSAL_EXECUTION.json`。

通过原Windows任务部署PID2104，源SHA全部符合验收清单且mtime早于新进程。启动后健康页200。唯一新核验 `f8c8000a7380458d9314beb404a9c433` 已succeeded且healthy=true，原绑定身份通过，账号恢复active。

唯一观看测试 `703eaaf13f60457c95b5729c5560b1ed` 已入队；首次提交在入队前数据库占锁，查询固定幂等键确认不存在后使用同一键提交成功，没有第二条测试。恢复后的原smart-operations任务 `50dcfaef34d14051b99008432afcbf56` 先取得浏览器执行，已实际同步3条作品并开始读取评论，测试等待同账号互斥；尚未宣称观看成功。

## 本轮生产终态

原smart任务完成3条作品、3条评论同步，但搜索阶段连续两次检测到380×384的可操作验证框，结果partial，管控任务failed。账号因此paused/revision53，不能把同步成功当成相关视频采集成功。

唯一15秒测试703e完成身份核验后，在research阶段出现 `OperationalError: database is locked`，结果明确failed，实际观看0条、0秒，无点赞评论。本轮没有第二次观看派发，也没有新的未知任务。

原账号处理窗口8e704已由自动异常流程打开，状态waiting_human；其可见窗口当前检测为`current_no_challenge`，与此前后台搜索的challenge_ready分开保存，不能据此写成平台验证已完成。已请用户确认窗口内容；原窗口保留。

当前PID2104健康200，账号暂停，完整结果保存在 `production_smoke/PRODUCTION_RESULT.json`。

## 后续数据库修复（尚未部署）

发现 `TrendRepository.initialize()` 每次构造都会执行完整建表检查并写入user_version，即使结构完整也产生额外写锁。这是已确认的代码问题，但本次原错误没有堆栈，不能断言它是唯一根因，浏览器控制库也实际出现过占锁。

新增只读结构检查：版本、所有必要表/列及索引一致才跳过初始化；结构不完整仍走原迁移，读取失败不能冒充正常。不在线修改journal_mode，不自动重派业务。生产库仅只读验证当前结构满足该路径，耗时0.074秒。验证覆盖真实SQLite writer锁下的初始化、旧版本与缺表/列/索引修复、排他锁拒绝，以及原采集与研究回归。

## 窗口关闭后的继续修复

用户确认“正常显示搜索结果，已关闭窗口”。8e704已succeeded，原生回执window_closed=true、identity_verified=false；服务2104没有浏览器子进程。正常搜索结果与原身份核验分开记录。

研究并发回归真实复现20条仅保存17条、3条database is locked；禁用新只读路径复验旧初始化同样17/20，保留两份失败报告。现对同一数据库的多个Repository实例共用短事务锁，计算和网络在连接范围外，不跨数据库阻塞，不重试业务。最终35项研究/采集/迁移回归全部通过，包括20条完整保存，报告TEST_TREND_SERIAL_FINAL.xml。

另确认管控线程在heartbeat提交遇SQLite BUSY时直接退出，导致服务进程存在但owner停止更新。修复仅在派发前的已回滚事务或正常心跳遇BUSY/LOCKED时等待下次轮询；不伪造续租，TTL到期仍拒绝，handler及结果落库异常不被吞为闲置重试。7项专门测试通过，包括真实rollback-journal读锁阻塞提交、释放后原命令只执行一次、过期owner仍拒绝；报告TEST_ACTOR_BUSY_FINAL.xml。

诊断中一次历史TEXT长度读取耗时115秒，可能加重同库读写争用，已结束且不再重复。历史审计约9.9亿字符，原内容不改；该读取不是新业务任务，也不能据此证明此前全部占锁均由历史字段造成。证据CONTROL_CONTENTION_DIAGNOSIS.json。

首次部署空闲检查因gen36心跳已过期而拒绝，未停止进程、未改owner。改用本次监督部署的精确进程身份、无子进程/原profile、全部业务lease空闲、原命令均明确结清的事务检查；只有停止并确认原进程退出后才审计交还这一代owner，保留过期心跳原值，不将其伪装为存活。部署收据以TREND_DEPLOYMENT_STOP_INTENT.json实际phase为准。

## 修复部署与人工完成核验

69项管控/桥接回归通过（TEST_ACTOR_BUSY_V2.xml，含前6项专项）；另7项最终专项包括新增真实SQLite读锁测试，均通过。与35项研究测试合计105个不同用例；保留首次专项夹具心跳间隔超TTL的失败报告，修正的是测试配置。

18:52通过原Windows任务启动PID13144，源SHA和进程创建前mtime均核对，启动初始端口未就绪后健康200。gen36精确空闲交还原记录入库browser_control_idle_deploy_audit；没有改写旧任务、扩大额度或提交新观看测试。

按用户确认登记处理完成eb1576，由原调度器派发唯一身份核验d2f597584ab3476d91a57c8df3809fa2。18:54该核验succeeded/healthy=true，原账号active revision55，handling completed。新owner为backend:13144:108e0108ef474c8090722af344b6344d、gen37。原到期作品刷新任务4c3f/管控12ad74780ad64e84b2a6b45f262524b5已实际取得新owner运行，尚待最终结果；不把这次身份恢复当作观看成功。证据TREND_DEPLOYMENT_STARTED.json、HUMAN_COMPLETION_AFTER_TREND_DEPLOY.json、POST_TREND_RECOVERY_RESULT.json。

## 后续实际终态：同步成功，搜索仍受阻

原12ad747已succeeded，维护8505b8完成3条作品和3条评论同步，warnings为空、无点赞/评论发送。这是新owner执行原计划并完成的实际证据。

自动接续的smart任务234e3d77572744d18b6cfccd0fb54849最终partial/failed：同样完成3条作品和3条评论，但相关视频0条，搜索遇verification_ui_unconfirmed。原生证据为380×384验证iframe、5次观测、0次challenge_ready确认，不能称用户未完成验证码，也不能移除验证门硬采集。账号因此paused56。

新自动处理窗口d5cd60d958c14f3cb7e3387264d0aab3为waiting_human，其可见页原生探测又为current_no_challenge。说明后台和可见会话表现有差异，尚不能证明具体平台原因；没有再次登记处理完成或重派核验。原用户关闭确认仅对应上一窗口8e704，本窗口保留。最终POST_TREND_FINAL.json。

播放当天已使用3/3次（含旧失败），未追加测试；仍无新成功观看证据。读取监控两次遇短暂SQLite忙，后续可读、owner心跳新鲜，尚不能承诺所有数据库争用消除。未再读大型历史审计全文。服务仍PID13144、gen37，已部署代码与105项回归保持；当前不能把全部账号自动化标为恢复。
