# 浏览器历史版本启动对照（2026-11-05）

本轮没有复现生产manual3ec86a9d1e004f79a3dfc6604b82a48a的starting_driver 45秒超时；没有足够证据认定回滚可以解决。未回滚生产、未重启管理后台、未第二次派发原账号窗口。两个账号保持暂停。

## 最新授权采样结果

本人明确允许加载诊断并开窗一次后，已通过原Windows交互任务部署，后台1236/HTTP200。仅新派manual67648030dfc04113b65d65bde10199d9一次，带allow_automatic_resume=false。第26代原账号窗口已waiting_human，原窗口显示回执restored=true；约6.182秒driver ready，实际venv Node为8192普通完整性。页面验证探测verification_unknown，不据此确定验证码有无。

两个账号仍paused73/41，未提交处理完成或恢复、未重派、未操作网页或H3。原45秒超时这次未复现，根因仍不能确定；一次开窗成功不等于稳定性问题已彻底解决。只依据原后台回执与进程元数据确认，未使用受安全停止的浏览器UI工具。证据OBSERVATION_RESULT.json。下方“候选未部署/未开窗”均是此采样之前的历史阶段。

## 历史成功证据与源码限制

11月3日manual_window_visibility_20261103/ACCEPTANCE.json记录原manual2fb93…为waiting_human、原窗口在系统清单462596可见，并成功显示原tab。这确认了用户记忆中“之前确实能开”。

但成功时browser_session.py的SHA为f2d3c50c…，在保存的29份同名源码中未找到完全相同的副本。此次使用11月3日before备份62aaf5fa…作近似源码对照，不能称它就是那份精确成功源码。另提取Git3251b13（9月10日）的文件，未切换Git工作区或覆盖生产文件。

## 对照条件与结果

只抽取各文件的_PW_SCRIPT字面量，不导入旧业务模块、不执行旧调度器。全部使用当前同一项目venv Node、正常交互桌面、新profile、无认证文件、about:blank、Chrome沙箱开启，检查启动ready、current_url本地RPC和正常退出/家族收尾。9月版本原本无外层启动等待上限；本测试为其加45秒QA外层上限，不把无限等待当成功。历史依赖版本、Chrome版本和当时文件安全标签无法完整重建。

| worker源码 | 次数 | 结果 | 启动、RPC至退出总耗时 |
| --- | --- | --- | --- |
| 当前已部署源码ea2b8095… | 2 | 通过2次 | 7.825秒、5.071秒 |
| 11月3日备份62aaf5fa… | 2 | 通过2次 | 9.599秒、10.107秒 |
| Git3251b13源码92cf7a45… | 2 | 通过2次 | 8.371秒、6.628秒 |

6次驱动初始化约0.224—3.217秒，退出码均0、捕获的家族均退出。这是历史启动worker代码对照，**不是旧版整站、身份核验、人工继续或真实养号闭环验收**。

另外使用当前公开BrowserSession API对比：主线程、命名后台线程、跳过日志输出的stderr读取方式，共4次通过（启动就绪约0.731—1.920秒）。驱动进程均来自venv且为普通完整性8192。被动诊断候选加入后，再跑同样4种API调用，全部通过（约0.892—3.941秒）。这些测试仍使用全新本地profile，不能替代生产故障现场。

## 可以与不能得出的结论

- 历史版本确实有成功记录；在今天受控环境中，旧、新启动worker都能工作。
- 本轮未复现实际45秒超时；没有验证“回滚有效”“把超时调大即可”“线程或日志就是根因”等判断。
- 生产请求目前是明确failed，进程清理已核实，所属gen25已自行released。它没有再次卡成旧的unknown owner。
- 此前Windows浏览器URL安全停止发生在页面复核；本轮未操作浏览器UI，也未用其他工具绕过该停止。

## 新增的安全诊断候选（未部署）

当前日志只有starting_driver阶段，无法知道实际用哪份驱动、超时前Node是否还在、Python在等待哪个函数。因此新增仅观察的driver_start_watch：开始时记录驱动/API来源类别，等待超过15秒记录最多8层函数位置；清理前记录捕获的自身子进程中Node是否存在、PID和来源类别。只保存文件basename、函数名和行号，不保存栈locals、源码行、完整路径、URL、凭据、浏览器正文或完整stderr。

候选54项针对性回归通过，真实空白页API另4次通过，冻结清单为DRIVER_DIAGNOSTICS_CANDIDATE.json。旧部署V2清单保留；诊断代码尚未被17852后台加载，不能声称新诊断已在线。它补足现场证据，不代表底层超时已修复。

如继续取得真实后台现场，需要按新的具体授权加载诊断并仅申请一次新处理窗口，保持allow_automatic_resume=false。旧“仅开窗一次”的授权已用完，不能循环重派。无需重试验证码、清锁或关闭个人Chrome。H3/8190和已取消的Codex监控不动。

## 证据

- data/development_checkpoints/browser_history_compare_20261105/RESULTS.json
- SOURCE_SEARCH.json、PRODUCTION_BASELINE.json、DRIVER_DIAGNOSTICS_CANDIDATE.json
- data/qa/browser_history_compare_20261105/LATEST.json（历史6次）
- api_c173504256a34550a6a67f72a57ccc4f（API前4次）与api_39f65f4570cc4b699bef6acdbe49b8ab（候选后4次）
- diagnostics.xml（54 passed）

一次性QA任务没有触发器，已在结束后移除；本轮未创建任何定时监控。
