# 番茄专属账号环境

用户要求补齐番茄持久登录，并检查其他账号是否相同。法律号 account01 与小说号 novel_account_02 在 douyin.db 中各有 active 身份绑定及独立 profile；这仅说明绑定存在，不等于业务已全部恢复。原番茄适配器使用公共 data/browser/fanqie/user_data，生产此前没有 platform_identity_bindings。

## 实现

- FanqieAccounts 在既有管控库中添加环境登记表，与平台身份表共用一致性备份。每个新环境用 fanqie:UUID 资源、独立目录、固定绑定版本；显式关联既有抖音运营账号并冻结其身份绑定摘要。关联变化时停止。
- 由专属 owner 子进程执行，原任务与心跳落在共享管控库。开窗、保存关闭、确认身份均有原命令 ID。重复点击复用未决请求；未知任务不重派。抖音 pump 明确忽略番茄命名空间。
- 被动观察当前页面自己发出的官方 user/info 响应，只保留 uid、时间、来源路径。依据为此前保存的官方 public_async_main.js 中 GET /api/platform/user/info/v:version 及 data.uid；不重放认证接口，不采集密码，不保存原始响应。无稳定 ID、响应错误、验证码、过期或身份不符时不放行。
- 身份与环境不同：打开登录页不等于绑定；窗口正常关闭并形成五分钟内身份凭据后，由管理员确认真实身份。绑定后目录读取再次核对原身份与活跃 owner。
- Web 新入口 /fanqie-accounts；CLI scripts/run_fanqie_account.py 提供 install/create/open/status/close/confirm/catalog。查询不启动窗口，操作要求显式入口；网页变更要求登录管理员。
- 旧公共缓存开窗入口停止放行，避免继续借用不明账号。旧登录文件保留，不搬运 cookie。旧推广提交/回填方法尚未迁移到新 owner；本次只接登录核验与目录页读取，不能称推广闭环上线。

## 运行与边界

登录窗口静音可见；控制进程无控制台窗口。登录最长30分钟，超时后保留实际核验结果；未核验不绑定。窗口关闭前检测到有效身份即保存登录会话。独立进程可以加载本次代码，不需要为开番茄窗口重启抖音后台。网页是否已刷新到新导航须独立验证。

本次不改变两抖音账号绑定、不清未知任务或发布锁、不发布/回填、不申请推广词、不调用文本或视频模型。实际验证码仍由用户完成。

测试及实际安装结果在后续验收记录中追加；测试身份和本地 Chrome 页面均不代表真实番茄登录成功。

## 离线验收与部署前记录

- 第一轮联合回归54项通过：data/qa/fanqie_account_20261024_v1.xml。
- 最终新增模块26项通过：data/qa/fanqie_account_20261024_final.xml，包含真实Chrome RPC、Streamlit按钮交互、并发开窗去重、身份变化/过期/未知阻断。第二轮六项重复复验不累加为不同用例。
- 部署发现控制数据库约4GB。第一次备份没有可见进度，精确停止本次部署子进程41256，未执行DDL；留下不完整备份，不可用于恢复。第二次固定读取快照备份在182秒时达到原180秒上限，抛错停止，仍未执行DDL。
- 备份改为固定WAL读取快照，新目标关闭回滚日志及同步写入，完成整份快照后显式fsync，再执行DDL；失败不迁移，进度证据单列。源库不改日志模式。Windows只读句柄fsync测试失败已改为可写句柄并复验1项通过：data/qa/fanqie_backup_fast_v2_20261024.xml。原失败回执保留。
- 生产安装结果只以 data/fanqie_account_control/PROVISION_20261024.json 为准；没有该成功回执不能称迁移完成。

## 实际安装与开窗

23:33安装成功，完整备份schema_backup_9500286cb3a74cbfb89f38ac744b19ca.db。PROVISION_20261024.json核对两个抖音账号的身份、profile、状态、创建时间逐项保持。资源fanqie:52ce7e06afc9451b8a81bfd9269ad94e关联novel_account_02，首次番茄身份绑定仍为null。

23:33:56启动原登录命令17e509dd6f2d485f85b9618bf5ad3928，独立进程54180、owner generation1。23:34:03实际Chrome worker ready；配置可见静音、专属profile。尚不能称用户已完成登录或已取得有效推广书籍。原抖音后台未重启；新worker加载新代码，网页新入口需刷新，旧后台已缓存模块是否热重载不作保证。末轮关联展示/身份变化复验2项通过，备份写盘复验1项通过，均为重复复验不累加测试数量。

## 首窗失败纠正

用户随后反馈未看到窗口。实际原任务23:35:48记录handler_exception:OperationalError、outcome_unknown；原诊断缺少SQLite错误码，不能断言一定是数据库锁。桌面实际窗口枚举没有Chrome，后续原工作进程与Chrome PID已全部退出。保留原任务、gen1过期owner和FAILURE_INSPECTION.json，未重派。此前worker ready不等同用户能看到并继续操作窗口。

新增metadata_read只包围本地数据库读取，SQLITE_BUSY/LOCKED最多五秒重试，其余错误立即阻断；不重放浏览器导航、登录或平台写入。新诊断仅记录阶段、SQLite数值码、类型和次数，避免保存异常文字中的业务信息。失败不能当健康；原任务不回写。测试包含真实SQLite排他锁释放后的恢复、持续占锁和非占锁错误停止。

本轮29项通过，data/qa/fanqie_window_failure_20261024.xml，包含上述3项与原26项、真实Chrome和网页交互。新源码等待下一次合法原环境任务加载；原失败尚未处置，不宣称真实登录窗口已恢复。

## 23:53后的实际登录验收

用户明确批准后，17e509dd原未知请求经原进程创建时间/退出证据独立核对，在保留完整原请求和unknown快照后精确取消，gen1交还。一次性recover脚本已执行，不可重跑。随后931bd真实桌面窗口完成用户登录，旧观察器未覆盖平台实际字面路径`/api/platform/user/info/v:version`，因此旧任务正常保存退出后仍为identity_unverified；该失败保持，不回写成成功。

修复响应路径识别后，9482原专属环境立即获得真实uid，未让用户再次登录。其浏览器保存并关闭成功，但本地终态写库/释放owner遇到database is locked，不能冒称命令已自然完成。新增仅SQLite BUSY/LOCKED事务有界重试及原登录完成结算：要求原进程已退出、明确关闭请求、五分钟内同环境身份证据、保存状态mtime、同一owner/代次且无其他未决命令。依据这些证据结算原9482，保留missing-terminal-write与完整原记录，无登录或平台请求重放。

实际绑定为uid:2521598930983028，专属环境关联novel_account_02，确认链在LOGIN_BINDING_ACCEPTANCE_20261024.json。用户无需重复登录。独立ef76be94590b498cb865beb3f45abcfa已重新启动保存会话，身份一致，目录读取succeeded，CATALOG.json记录10本带“别名推广”入口的真实书籍。尚未证明任一书已有有效AIGC推广任务，尚未生成新剧本或视频。

路径解析相关18项通过（另12项未选），完成结算初轮5项、最终8项通过；这些与已有用例有重叠，不累加为独立数量。证据分别为data/qa/fanqie_literal_version_20261024.xml、fanqie_completion_20261024.xml和fanqie_completion_final_20261024.xml。原失败、未知发布提交锁、其他账号记录保持。
