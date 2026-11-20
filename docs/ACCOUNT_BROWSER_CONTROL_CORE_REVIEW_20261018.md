# 账号浏览器管控核心实施记录

本模块为`src/operations_accounts/browser_control.py`，不包含平台操作、不改原业务库、operation lease、配额或发布账本。测试只用开发检查点下的隔离SQLite，未访问真实账号、未部署。

## 公开接口

- `BrowserControlStore(path, clock=time.time, owner_ttl=90)`：专用库首建。既有库只读检查schema，前端构造与`snapshot`不取写锁；不在连接中切换journal mode。

既有库须完整匹配owner/command列、两个主键及账号幂等唯一约束；半初始化、相同表名但不兼容结构或缺唯一约束均明确拒绝，只读路径不自动补DDL。需要维护时另做显式离线核对；未知库不当成空新库覆盖。
- `submit(account_id, binding_version, kind, idempotency_key, payload, priority=0)`返回原始command字典；相同幂等键且请求变化拒绝，结果未知也返回原ID，不新派。
- `get(command_id)`、`snapshot(account_id)`、`list_pending_accounts()`只读。snapshot结构为`{account_id,owner,commands}`，每条命令含`command_id/task_id/account_id/binding_version/kind/payload/priority/state/cursor/result/error_code`等。
- `acquire_owner(account_id,binding_version,owner_id)`、`heartbeat(account_id,owner_id,generation)`、`release_owner(...)`持久单owner/generation。只允许已知干净释放后新代次；不按查询者PID猜原owner死亡。心跳过期只读投影`outcome_unknown`，不抢占；写失败时原actor保存unknown并停止后续派发。
- `complete_waiting(command_id,owner_id,generation,result=None)`仅原活跃owner结束已知窗口等待；它本身不核登录、不恢复后台，业务核验由原身份恢复handler负责。
- `BrowserControlActor(store,account_id,binding_version,owner_id,handlers,admission=None,context=None,heartbeat_seconds=30)`：`start/run_next/close/stop_heartbeat`，同一账号handler固定一个owner线程，共享`context`资源。后台心跳线程只写管控元数据，不操作浏览器。
- handler签名`handler(ctx: BrowserTaskContext,payload:dict)->dict | BrowserCommandResult`。ctx提供`task_id/account_id/binding_version/resource/command`及`safe_point(cursor)->elapsed_seconds`、`check_dispatch()`。admission签名`admission(ctx,phase)`，phase为`start/resume/dispatch`。身份、暂停、原业务锁、授权由runtime接线核验，不在核心硬编码平台规则。
- `BrowserCommandResult(state='waiting_human',result={...})`是短返回人工等待；`BrowserControlDeferred(code,message)`仅在handler未启动前把原任务保留queued；已启动后若抛Deferred则保守记录未知。`BrowserControlRejected`仅表示明确已知拒绝，未知运输异常不能当作已知失败。

## 优先与恢复边界

`safe_point(cursor)`先保存原后台paused与真实游标，再在同一线程执行更高priority的publish/publish_verify/comment；每条重新执行start admission，回原后台前执行resume admission。没有safe_point的旧任务先完整结束，不在任意RPC中断。

所有优先任务成功且恢复门通过时，返回同一原函数栈继续，`elapsed_seconds`可供播放时限扣除优先工作耗时。优先失败、待人工、未知或恢复门变化时保存paused、停止原栈；已知失败也采取保守停止。旧业务若捕获异常，`ctx.suspension_reason`仍强制最终paused，不能由返回字典洗成成功。后续实际IO前`ctx.check_dispatch()`也拒绝已暂停上下文。

已知paused可继续单独manual/recovery，但不会从游标盲重跑旧handler，也不自动把paused写回成功；未知原任务挡所有新派发。此实现不宣称跨进程重启后自动恢复任意旧业务栈。旧协议worker不可热接管，部署仍需原任务正常交还。

## 离线证据

隔离JUnit记录位于`data/development_checkpoints/account_browser_control_20261018/core_tests_v*.xml`。v2为17项通过，v3为21项通过；新增暂停异常吞没及已知暂停后恢复专线的最后v4复验23项通过，67.87秒。早期一次默认C盘pytest临时目录权限失败、一次亚秒TTL依赖Windows磁盘速度导致测试失败均保留；心跳测试随后改为受控clock与实际持久heartbeat逐次观测，不假定亚秒磁盘时延。

关键案例覆盖：多线程同幂等/同owner竞争、真实独立进程查询不误判、写锁存在时只读snapshot、stale不抢占、代次拒绝迟到命令、账号/绑定隔离、同线程真实游标发布插入与原栈恢复、未知跨重建保留、人工短返回、长操作期间持久心跳、无safe_point不抢占、派发前复核，以及暂停后禁止业务盲恢复。

主审后强化既有schema兼容门，新增半初始化、缺列与缺账号幂等唯一约束三项；对应8项重点复验通过，见`core_schema_tests_v2.xml`，其中重新构造existingStore期间另连接持有BEGIN IMMEDIATE，仍只读查询成功。没有对已有生产库迁移或自动修补。

## 主审并发锁问题修复

组合主审在高频heartbeat/RO snapshot/最终transition之间发现rollback journal竞争，原失败保留于`data/qa/account_browser_control_20261018/PRIMARY.xml`。仅增加writer锁后，handler内的RO snapshot仍可遇提交独占窗口，因此改为同一resolved path共享的进程内metadata连接RLock，涵盖不同Store实例与RO连接；RO仍使用SQLite mode=ro，不取数据库写事务。跨进程仍由原BEGIN IMMEDIATE和原busy失败门约束，不吞异常、不重试外部任务。

保持现有SQLite与rollback journal，不默认引入WAL，也不修改任何既有库模式。新增实际并发用例把原元数据写事务保持超过SQLite两秒busy期限，另一Store的heartbeat在进程锁等待后成功，确认journal仍DELETE；不是扩大SQLite超时。新目标与完整复验记录使用`core_lock_target_v2.xml`及后续完整记录，旧失败不覆盖。

最终目标3项通过（27.94秒），完整核心27项通过（195.69秒），完整证据为`core_lock_full_v2.xml`。仅writer锁的中间失败也保留为`core_lock_full.xml`，没有把它算作通过。
