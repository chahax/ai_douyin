# 人工开窗真实失败复现与修复候选（2026-11-05）

当前修复候选已通过真实空白页启动、RPC与关闭收尾，原生单测1 passed；生产账号的人工继续与真实播放尚未验收。原小说号任务3cad88d74cae4fa99a71e163114b2d59保持outcome_unknown，候选未部署；本轮未重派、结清、恢复账号或重启生产后台。上一轮管理页的542项回归不代表生产闭环通过。

## 本人授权后的实际执行停点

本人确认“确认结束旧请求，部署并开窗一次”，同时明确收尾不能证实则停止。已通过冻结SHA、原ID/binding/owner/gen/CAS与空闲业务检查，并调用既有原ID取消接口。原3cad88…变为failed/operator_cancelled_unknown_manual，原未知结果和before_snapshot保留。

原后台随后无法核实失败启动的worker退出，原gen24收尾门拒绝、未生成retirement；进程当前无子进程不能替代该证据。已按本人条件停止：没有重启、没有部署或新开窗。两账号仍暂停，个人Chrome和account01不操作。证据STOPPED_AT_CLEANUP_GATE.json。修复候选和真实空白页验证仍有效，但不能据此声称生产账号窗口已打开。

## 最新结果：已定位并修复依赖选择，真实原生用例已通过

用户反馈手动Chrome能打开个人资料选择页。只读进程跟踪确认：后台Python为普通完整性8192，但优先加载的.local_py中node.exe继承Low文件标签，驱动与根Chrome都降至4096。项目.venv中同版本node.exe无Low标签，内容SHA与.local_py完全相同（58e74bf02fc5bbacc41dcb8bef089961cd5bddd37830b87784e4fc624d145d1f）。

Windows说明新进程完整性受用户与可执行文件完整性共同约束：[Microsoft MIC文档](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control)。此处具体原因由本机进程与文件标签共同证明，不归因于验证码、原账号窗口占用或特定防护软件。

修复在worker环境中优先选择现有项目.venv的Playwright Node；保留显式PLAYWRIGHT_NODEJS_PATH配置，不更改文件标签/系统ACL，不提管理员权限。可见模式分别验证Chrome沙箱开启与项目原默认参数，两次真实ready、RPC与关闭家族收尾均通过。此前排除的原生pytest用例test_real_worker_identity_rpc_is_fail_closed_on_local_page已在正常桌面单独重跑：1 passed（65.75秒，缓存目录警告不影响结果）。最终156项回归和6项原未知取消安全测试通过，未与旧542相加。

候选还未部署。生产原manual3cad88d74cae4fa99a71e163114b2d59仍outcome_unknown，不能用新测试成功改写旧结果。原取消接口要求冻结本人明确授权、原ID/SHA/owner/gen/CAS一致，保存before_snapshot且original_outcome_known=false；原host清理门通过并回到可证明空闲边界才加载修复。下一步计划为检查点CONTINUATION_PLAN.json，仅拟结束此旧开窗、部署、再打开小说号一次，不包括处理完成、身份恢复、养号派发或其他账号。

以下为修复过程中的失败证据与当时结论，保留为历史。

## 真实证据

测试使用一次性、无触发器的Windows交互任务，pythonw入口补齐生产同样的依赖路径和日志流。每次独立测试profile均在项目data/qa/manual_browser_startup_20261105下，从未读取原账号认证快照或使用抖音URL。任务已在结束后移除，未新建定时监控。

1. 正常桌面Default中，原C盘TEMP使Playwright创建playwright-artifacts目录时EPERM。
2. 仅为浏览器worker家族指定D盘项目私有临时目录后，测试进入launching_browser，Chrome报告ProcessSingleton锁文件创建失败、退出码21。
3. 可见模式确认Chrome错误行为“Lock file can not be created: 拒绝访问。(0x5)”。重新创建仅当前用户可访问的全新QA profile仍失败，不能据此猜原账号目录已被占用。
4. 另一次测试停在starting_driver，45秒有界超时且清理核实；这条不同停点原样保留，不能改成成功。
5. 未找到对应Windows Defender 1123/1124事件；没有证据将拒绝归因于特定防护软件或具体规则。没有修改系统ACL、关闭防护、改用其他浏览器运行原账号或提升浏览器权限。

QA最初一次自身依赖/日志流配置错误与首次pytest父目录缺失也保留，不能算浏览器产品缺陷或算通过。

## 已实现的修复候选

- 新增轻量browser_startup_diagnostics，只保留固定阶段、分类、进程退出码、ready与cleanup布尔证据；不保存异常原文、浏览器argv、URL、凭据。
- worker启动异常通过结构回执返回；失败worker等父进程采集家族后再退出，避免先EOF丢失后代清理证据。
- 父进程错误对象保留安全启动证据；worker私有TMP/TEMP/TMPDIR使用D盘项目目录，不改变整个系统环境或系统权限。
- manual handler仅在本次never-ready、清理已核实且worker引用为空时返回明确failed；清理不明或ready后的错误保持outcome_unknown。不自动重试、不修改旧未知记录、不发起身份核验或恢复。
- 管理页显示具体失败阶段和收尾是否核实，区分互斥创建失败与已证实目录占用，不把Chrome错误推断为验证码。

## 测试边界与部署

真实worker协议、临时SQLite actor、真实Streamlit控件覆盖失败回执、去重、原ID保持、未知保护、清理后退休、UI按钮/文案及非敏感诊断。最终针对性与兼容合并回归155 passed、0 failed、0 error，见data/qa/manual_browser_startup_20261105/combined.xml；不与旧542简单相加。原生成功启动/RPC仍是失败，不从本轮排除后冒称全通过。

新源码候选清单独立保存；原管理页SOURCE_MANIFEST不重写。后台5236已加载的旧管控模块不被注入或热改。原未知任务不满足旧部署脚本的空闲前提；不得重跑该部署脚本、清owner或通过临时桥绕过。

待办：结合用户正常桌面手动启动Chrome的结果，继续定位当前Windows访问拒绝。原生启动成功和当前原未知的可靠收尾未解决前，本次不能声明生产开窗链路已修好或恢复养号。
