# 账号浏览器业务桥实施与接线

本文件描述代码接入，不能替代真实账号部署或发布回执。用户已批准“按方案开发，发布优先后恢复后台”。本子模块没有重启服务、浏览器、修改生产数据库/锁或向平台发布。部署开关复用项目Settings/.env的`AI_DOUYIN_BROWSER_CONTROL`（默认false）；显式进程环境变量优先，开发期间不在现有服务中启用。旧worker不能热接管；其原ID、原运行锁和旧人工窗口记录继续阻止新资源启动。

## 实际入口

新增 `src/operations_accounts/browser_control_runtime.py`，以管控core的持久命令、资源owner/代次为基础。

* `queue_publish_request(account_key, request, authorization=...)`：仅冻结已存在视频的SHA、原授权和账号/身份/profile版本，持久入队；不创建浏览器。
* `queue_prepared_publication(path)`：核对原明确采用完整片的独立授权文件与成片SHA，不把旧制作回执改写为人工通过。
* `queue_manual_window(account_uuid, account_key, requested_by, incident_id=...)`：人工处理短命令；当前异常在入队和实际派发前分别复核，同异常命令幂等。新异常仍有自己的机会。
* `managed_maintenance(...)`：原维护服务按原调度运行ID等待同一actor执行结果，保留原operation_lease、播放配额及业务日志；已知失败/受阻不写成功。
* `managed_recovery(account_key)`：原后台完成流程中的同身份探测由同一actor执行，原核验门和后端_finish_recovery保持。
* `managed_adapter_call(account_key, method, params, operation_profile=None)`：仅同步作品、读取评论和核验准确已发布作品三个只读方法；结果恢复原dataclass。作品指标UI/CLI迁移至此，固定creator_metrics_ui/cli分别保留原100次/日、60秒冷却、600/1800秒锁时长；其他方法不能借用该配额。没有开放任意方法或互动调用。
* `queue_official_console(account_uuid, account_key, requested_by)`：专属官方管理按钮只入队，后台按原official_console的100次/日、无冷却、1800秒锁核原身份并打开同context的独立官方管理tab。短命令返回waiting_human，不暂停account_controls，不新增“处理完成”步骤；用户关闭此管理tab后只结清此任务，不关闭其他验证页。窗口占用期间其他业务仍排队。
* `background_safe_point(cursor) -> elapsed_seconds`：原完整播放项结束后保存实际游标/累计结果，同线程串行执行优先发布，成功后恢复原循环。调用者补偿发布耗时，不吞播放预算；其他旧路径只在整轮结束后让位。
* `pump_pending()`：仅后端cron每5秒扫描，启动单账号owner线程。CLI/网页只入队和查询。另一进程已有active/unknown owner时不再启动替代线程。

`BorrowedSession` 为每个任务创建固定tab；Page、Locator、兼容的Page(session)都绑定自身tab_id，实际cmd前检查owner、账号禁用/绑定版本、后台暂停与原锁。跨tab和owner级生命周期命令被拒绝。借用stop只关闭本任务tab；save_state和new_tab也检查派发门。

## 人工处理与恢复

新的人工命令只做短开窗，返回waiting_human，不以长wait_for_close阻塞worker。原页面保留时仍可读取状态和持久排队。前端显示“处理后点击完成，无需关闭窗口”，handoff_ready只允许提交原完成请求，不等于身份已验证。

完成请求仍经原调度后台claim、原账号身份probe和_finish_recovery。核验通过后只结束manual待人命令，验证tab继续保留。原失败维护回执保持failed/blocked，不变为成功；后台按原恢复计划接续。实际关窗则单独记录已知关闭，不冒充身份通过。状态读取失败/原任务未知不释放owner或重派。

新宿主发现账号profile/身份绑定版本改变时，先于claim检查；已知干净且没有人工tab/未决任务，正常关闭context并释放owner，下一轮产生新代次。存在人工页、paused/unknown时等待原任务交还。空闲120秒且无待办/保护页可回收context与owner。

## 发布边界

实际发布handler继续使用原DouyinAdapter/PublishWorkflow的主动AI声明、虚构前缀读回、唯一提交锁、准确作品核验及证据。发布结果未知、作品核验待确认或评论结果未知时保留未知并阻止后台恢复，不重复上传/评论。评论仅在对应作品核验通过后使用冻结原授权与文字调用独立publication_comment模块。

后台播放安全点插入发布时保留父operation_lease的精确owner，不清/抢原锁；同一个资源actor串行，另在原数据库事务中累计当日发布运行次数并核20次上限，原播放独立配额不重置。嵌套失败暂停原后台，不承诺进程丢失后的旧Python执行栈可自动恢复。

## 检查与未接入范围

本桥最终22项回归通过22.32秒，原生报告为`data/development_checkpoints/account_browser_control_20261018/runtime_bridge_tests_v4.xml`；覆盖真实actor+原Runtime.probe_recovery同context保留人工tab、实际Page/Locator护栏、迟到/其他任务/错线程回调拒绝、原父lease计数、配置变化释放与合法新版命令保存、已关闭异常在实际派发前拒绝。原117项runtime/maintenance/manual/UI/scheduler/publish边界回归通过。测试使用隔离临时库与假页面transport，不能据此声明真实账号验证码已通过或作品已发布。

兼容补丁新增7项固定配额/官方窗口占用及关闭/并发入队/共享配置检查通过（compatibility_target.xml），两个实际Streamlit AppTest渲染与点击通过（compatibility_ui.xml），配置改变后先观察原console关闭再释放owner及配置覆盖2项通过（console_changed_profile.xml）。混合旧UI/桥41项最初为39通过、2个既有30秒AppTest超时，原报告runtime_bridge_tests_compat.xml保留，独立复验另存不覆盖失败证据。

旧UI两节点隔离复验为1通过/1超时：指标页未绑定账号的原用例通过，旧空账号完整趋势页仍超时（compatibility_legacy_ui_isolated.xml）。一次20秒线程栈诊断定位到_render_research_run_logs的Path.read_text（trend_dashboard.py:1346），未进入本次官方管理或指标采集分支；末尾另记录既有“音画表达证据齐全”混合int/string列的PyArrow错误。诊断原日志与原失败XML保存，未放宽原30秒测试或擅自扩大修改历史日志页面的范围，故不能称该旧完整页测试已通过。

兼容扩展涉及的performance/trend页面和metrics CLI未在首次编辑前追加原始副本，这是检查点流程遗漏；已保留当前实际文件，并仅反向重建本次补丁前代码于compatibility_reconstruction。MANIFEST明确is_original_pre_edit_snapshot=false，不把重建内容SHA冒充当时原始字节证据；不回写工作区或覆盖原16文件检查点。

CLI为 `scripts/account_browser_control.py status account01` 和 `queue-prepared-publication <原PREPARED.json>`，均不执行浏览器。新增前端队列视图显示owner代次、执行/待人/排队及保存游标。作品指标UI及原`collect_creator_metrics.py`保持原功能与额度，启用管控后由同一后端owner执行；专属官方管理窗口按上述独立角色保留。直接旧一键创作路由不因此恢复生成，尚未声称全项目所有旧工具均已兼容。正式部署前仍需主agent核对旧窗口/锁正常交还及全部实际入口。
