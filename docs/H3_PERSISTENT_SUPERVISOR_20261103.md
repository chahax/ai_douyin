# H3 完整链持久监护设计

目标：补上生成调度进程意外退出后无人恢复的缺口。保持当前冻结 runner、PLAN 和在途 GPU 任务不变。新增独立 supervisor；Windows 当前用户计划任务每分钟及登录时直接以 pythonw 启动 supervise，IgnoreNew保证已有任务持续运行，ExecutionTimeLimit=PT0S。采用直接监护而非两分钟短任务再启动孙进程，避免任务调度器Job对象在短任务结束时清理后代进程的风险。主机关闭时不能生成，不承诺关机期间连续运行。

supervisor 持独占文件锁，保存自身 PID、创建时间和准确命令身份，30秒心跳及结构化事件。venv 的 python 启动器和其同命令子进程归为一个家族，收养当前 runner 时跟踪全部成员，不因父启动器退出或 PID 复用误判。监护不结束在途进程、不重启 ComfyUI、不管理浏览器、不发布。

runner 家族全部消失后，读取冻结源/hash、人工暂停标志和本地状态，再查询原段 history 与 queue。原 ID 已知成功或仍在运行/排队时，允许原 execute 恢复收存或查询；从未提交的下一段仅在服务可达、队列为空时继续。无 ID 的 claim、原 ID 在 history 和 queue 都消失、已知失败、配置变化、人工暂停均停止自动恢复并记录原因。不以空队列当成功。网络错误指数退避，启动失败有界并冷却；同一无进展位置重复退出达到阈值后停机报警，避免无限重启。

监护由主代理部署后只通过 Start-ScheduledTask 启动，不能把DETACHED_PROCESS本身当作已证明脱离Codex生命周期。监护启动的后续 runner 为隐藏本地进程，stdout/stderr 从创建起持续写 D 盘文件，并由独立 wrapper 保存真实 returncode。对已存在的被收养进程无法事后补获原 stdout/returncode，记录 unavailable，不伪造。并发 ensure 工具和 supervisor 均有锁。完成记录经核对后监护退出，后续计划触发读到终态立即结束，不新增业务。

PAUSE.json暂停自动恢复及监护，不强杀当前运行中的生成进程；若需暂停现有runner的后继派发，仍须通过原流程的明确暂停操作。Windows任务安装前检查同名任务的动作、用户SID、工作目录及触发条件；不匹配就保留原任务并拒绝覆盖，安装后再次回读核验。

部署前需冻结 SUPERVISOR_PLAN 和主代理审查记录；计划任务 XML/安装脚本只准备不执行。测试覆盖原 ID 成功恢复、在途查询、未知保护、忙 GPU、PID 复用、重复监护、wrapper 输出与退出码，以及本地无媒体 supervisor 小样。

开发验收：23项针对回归通过（data/qa/h3_supervisor_ready_20261103.xml），真实本地dummy进程被监护识别并收养，未访问媒体服务；独立wrapper保存stdout/stderr并记录退出码7。SUPERVISOR_PLAN SHA为4ca36510ace58deb6749cf1e9c00150ddcca7a270f84f4dcb4bb845d924f5902。主代理负责计划任务部署和当前生产runner实际收养验收；子任务没有部署或启动生产监护。

网页只读展示监护状态、进程身份与心跳新鲜度。心跳超过90秒或PID/创建时间/命令不匹配时明确显示未受保护；业务STATE=running不再被当作持久监护仍在运行。退避、未知任务阻塞和配置变化各自显示。

## 本次退出的已知证据

旧日志最后派发 F0009 于北京时间2026-11-02 23:32:57；服务随后完成。11月3日14:48检查时 runner 不在、F0009 在服务上已成功但本地仍 submitted，队列为空。原 execute 恢复后仅收存 F0009，14:52派发 F0010。原运行没有独立 stdout/stderr、退出码或监护记录，因此目前不能断言是模型、网络、工具生命周期或系统终止导致。Windows Application 00:00—01:00 的1000/1001事件只读查询结果另存检查证据；没有匹配事件不证明没有退出。

## 生产部署验收

2026-11-03 15:44完成当前用户计划任务登记，15:44:51监护PID32196启动并收养原runner家族，未启动第二生成任务。任务直接pythonw supervise、每分钟+登录、IgnoreNew、PT0S。重复触发后同一监护家族存活，30秒心跳持续；DEPLOYMENT_ACCEPTANCE.json保存实际身份及页面只读状态protected=true。

23项最终回归通过。初次受限安装拒绝访问，授权安装时发现XML utf-8声明与COM字符串编码冲突；原失败文件保留，派生INSTALL_COM_STRING.ps1只去XML声明后登记成功，原冻结supervisor/config不改。安装回读与证据在data/h3_supervision/full_script_20261103。未主动模拟终止生产runner，真实退出恢复路径用无媒体dummy测试；生产仅验收接管、心跳和防重复。原中断原因仍未确证。
