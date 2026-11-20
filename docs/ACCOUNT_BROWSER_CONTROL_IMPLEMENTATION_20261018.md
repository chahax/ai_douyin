# 浏览器管控实施合同

用户已确认：按管控层方案开发，发布优先后恢复后台。分析见ACCOUNT_BROWSER_CONTROL_ANALYSIS_20261018.md，代码检查点为data/development_checkpoints/account_browser_control_20261018（16个实际源码副本及SHA；无凭据/数据库更改）。

先增量接入并隔离测试，未知旧任务不接管，不中断当前窗口。正常部署须确认原业务与窗口交还；首版不能热接管旧协议worker。

## 模块边界与协作接口

1. 管控核心：`src/operations_accounts/browser_control.py`（新增）。持久SQLite命令、账号资源单owner与代次、心跳、幂等、只读snapshot、任务结果/未知状态。业务handler注册制，不在核心引入发布/采集实现。每账号串行，同一执行线程使用同一受管context。显式safe_point(cursor)保存后台进度后可嵌套处理优先发布，返回原后台；不在任意RPC中途抢占。失联与提交未知不自动重试。
2. 浏览器执行器：`browser_session.py`增量tab_id路由，创建/列出/选择/关闭标签页与短轮询窗口状态。旧默认Page保留兼容；新Page固定tab_id，locator继续携带此ID。借用者stop不关闭真实owner；原wait_for_close保留兼容，但新管控不使用长阻塞RPC。
3. 实际接线：新增`src/operations_accounts/browser_control_runtime.py`协调现有runtime、账号暂停门、业务handler与BrowserSession。后台、人工处理和发布入口逐一调用管理器；网页/CLI只提交持久请求或读状态。人工处理完成走原身份/阻断核验，不把开关窗口等同健康。原维护/播放配额及发布声明/提交锁仍由原业务执行器负责。

核心与接线agent在改动前共同确认公开API，并将精确API写入本文件的后续实施记录。浏览器agent先提供`new_tab(role)`返回绑定Page、`list_tabs()`、`close_tab(tab_id)`与`window_status()`；所有新方法通过原worker命令实现，不启用调试端口，不复制或输出cookie。具体名称变更须先通知其他agent。

actor只在业务明确可恢复的safe_point优先处理发布；无恢复能力的旧任务等整轮结束。开始执行前和实际外部派发前仍核对账号身份/绑定、授权、暂停与旧未知门。人工窗口需要保持可见时不被空闲回收。浏览器headless/可见切换不能伪装同进程复用。

## 验收

证明跨请求真实同context多tab、控制层单owner、优先任务插入后后台真实恢复、跨账号隔离、人工等待不阻塞状态/队列、未通过验证不发布、未知不重派、原锁与账本保留、所有接入路径不绕过。先离线，再隔离本地空白页实测；真实抖音发布另使用既有已授权完整片及原文案，仅在原窗口正常交还且部署检查通过后执行。
