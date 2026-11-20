# 人工窗口不可见修复（2026-11-03）

用户报告 novel_account_02 的“打开此账号处理窗口”不可点击，并确认看不到 Chrome。只看管控任务 waiting_human 不足以证明窗口在用户桌面可操作。原后台 PID34596 和原 Chrome PID33544 的线程桌面，经 GetThreadDesktop/GetUserObjectInformationW 只读核对，均为 `CodexSandboxDesktop-d7f25a34f40c5ffc06f2aea7467c7125`。正常桌面的 Computer Use 窗口清单无 Chrome。这是本次已证实根因，不能误报验证码或要求用户先点击完成。

## 修复

- 人工开窗前检查调用线程的 Windows 桌面；不在 `Default` 或读取不明时，报 `manual_window_noninteractive_desktop`，不再启动不可见人工环境。非 Windows 保持兼容。
- 前端对原执行者已登记的人工窗口提供“重新显示原账号处理窗口”。请求绑定账号、原 manual ID、owner、generation、tab ID、binding；原执行者在串行队列中恢复既有窗口位置并激活该标签页，不导航、不新建 profile、不提交完成。重复未结束显示请求复用原请求。
- 新窗口启动后同样恢复显示并读取窗口状态/页面可见性；显示未确认时保留原人工任务和页面，不允许据此重复开账号环境。
- 原生窗口恢复通过原 worker 的现有浏览器上下文完成。仅使用该上下文的原 target 获取/设置窗口 bounds 和 bring_to_front；不启用新的远程调试端口，不读取验证码或凭据，不进行身份核验或账号恢复。

## 实际部署

用户明确回复看不到窗口，并关闭 Edge 项目标签页，允许前端部署入口重新加载。一次性新部署桥仅绑定 PID34596/create-time、novel_account_02 owner/gen20 及原人工任务 `ea5c76e2849648e4ae5538196eb3fb91`，由原 owner 线程检查没有其他在途业务、其他人工或用户标签页，再保存原会话，发送原生 stop，确认返回0及全部原子进程退出。原任务记为 window_closed=true、identity_verified=false，旧窗口回执保留。未把“看不到窗口”改写成用户已完成验证。

旧后台在所有在途业务已结清且仅剩原队列等待的边界停止，已知空闲 owner 留审计后退出；未知旧记录、发布提交锁、原维护任务及调度游标保持。通过现有 Windows `AI_Douyin_Streamlit` InteractiveToken 任务启动新后台 PID34744，健康200。没有变更任务权限或任务触发器，没有从 Codex 受限终端再启动后台服务。

新原账号人工任务 `2fb93a16408346329d31a48ecc05c3ad` 由 gen21 打开；窗口显示回执 restored=true，Computer Use 正常桌面清单已出现 Chrome 窗口462596。当前后台页面已实际显示可点击的“重新显示原账号处理窗口”和“处理完成，继续运行”。真实点击前者得到显示请求 `8c332fce0ada4022b924a15ea8d27f0a` succeeded/restored=true，仍绑定上述 manual ID 与 `tab-f12f6acc55ed4883b3b744e6bdae7003-3`。没有点击完成。

novel_account_02 保持 paused/revision31；原维护 `bc9dced310624431a0b1f7d8446eb880` 继续原ID排队，未重派。其他账号旧人工任务/异常未处理，H3生成/持久监护及8190未干扰。旧 Codex 定时监控仍取消。

一次性 ARM 已归档 APPLIED_ARM.json，app.py 临时入口已移除。不要重跑旧/新部署脚本、关闭桥、已完成关窗动作或重新提交原发布。

## 验证和证据

证据目录：`data/development_checkpoints/manual_window_visibility_20261103/`，含根因、原owner关窗返回码/进程证明、后台部署与实际开窗/显示回执。查询新后台跨桌面线程名称未取得值，已保留空结果；新后台原生桌面门通过及正常桌面窗口清单是实际可见证据，不把空查询冒充桌面验证成功。

初轮109项通过；新增桌面门后完整套件129通过、2个旧伪浏览器测试因继承了真实隔离桌面而失败。只在这两个纯伪浏览器测试中模拟交互桌面，生产门不放宽；相关22项复测通过。最后移动显示确认至人工任务绑定之后，19项原owner/人工流程复测通过。最终完整报告见 `data/qa/manual_window_visibility_acceptance_20261103.xml`。各套件有交集，不简单累加。无模型、视频生成、发布或互动调用。
