# 浏览器执行器多标签增量与本地验收

本模块只落实账号管控计划中的浏览器执行层，不持有业务优先级、身份批准或发布权限。生产账号、窗口、数据库与服务未启动或迁移。开发前源码保留在 `data/development_checkpoints/account_browser_control_20261018/sources`，相对该检查点的准确增量为 `BROWSER_TABS_CHANGE.patch`，当前文件绑定为 `BROWSER_TABS_REVIEW.json`。

## 公开接口

| 接口 | 返回与语义 |
|---|---|
| `session.new_tab(role: str) -> Page` | 在同一 owner 的 persistent context 新建页，返回固定 `page.tab_id`；role 非空、最长80字符。按需首次启动 owner。 |
| `session.get_page(tab_id: str \| None = None) -> Page` | 获取原固定页；默认原启动页，已关闭或未知 handle 拒绝，不替换为其他页。 |
| `session.list_tabs() -> list[dict]` | 不启动新 worker，返回已登记 `{tab_id, role, closed, url}`；URL 去凭据、query、fragment。关闭记录保留。 |
| `session.close_tab(tab_id: str) -> dict` | 只关闭指定页；同 owner 已关闭页可重复确认，未知 handle 拒绝。 |
| `session.window_status() -> dict` | 短 RPC 返回 `open, closed, context_closed, tab_count, tabs`；没有存活 worker/响应未知时抛错，不能当已关闭。transport 上限5秒。 |

`closed` 表示没有打开的标签页；`context_closed` 独立表示 Playwright context 的关闭事件。零标签时 context 仍可能存在，由管控 owner 决定回收。

每个 handle 包含随机 worker namespace，跨账号/重启旧 handle 不能命中新页。原 worker 单页协议和长 `wait_for_close` 保持兼容，新管控不使用该长等待。新协议不能接管已经运行的旧 worker。

Page/Locator 全部转发操作固定携带 tab_id，`first()`/`nth()`继续继承。`Page(session)` 按显式 tab_id、借用 session.tab_id、owner 原启动页的顺序绑定；借用者生命周期由 runtime wrapper 控制，归还不能调用 owner.stop。context 级 API request/状态保存继续操作原 context。

## 验证

63项相关回归通过：原启动/状态/下载53项与本轮10项。命令和绑定见 `BROWSER_TABS_REVIEW.json`。pytest临时目录明确放在D盘，本机默认C盘pytest路径无访问权限的初次环境错误已用独立D盘目录解决。

本地真实Chrome测试使用两个全新隔离profile，仅访问项目CLI创建的loopback HTML，无平台页、真实账号、凭据读取或debug端口。14项实际验收通过，回执在 `browser_tabs_local_acceptance_03/RESULT.json`：同worker双页共享context存储、固定locator与借用页隔离、跨context不共享存储、跨owner handle拒绝、关一页保留另一页、闭页handle不回退默认页、短轮询与零页状态。短状态实测约0.002秒。测试名中的manual page仅指被保留的本地测试页，不是实际验证码人工窗口验收。

保留先前两次本地试验失败回执：01暴露原Locator.evaluate默认index=-1错走Page.evaluate，已改为非空selector走元素evaluate；02第二个隔离context的5秒goto超时。第三次只将fixture导航timeout调整为15秒后通过，没有放宽生产命令或增加自动重试。

生产身份/验证码、优先发布恢复和所有业务入口接线由主agent及管控模块另行验收；这些本地结果不证明视频已上传或发布。

## 实际管控与浏览器组合验收

进一步使用 `scripts/verify_browser_control_local.py` 一次跑通真实 `BrowserControlStore`、`BrowserControlActor`、`AccountBrowserResource`、`BorrowedSession`、`BrowserSession` 与Chrome worker组合。隔离测试15项通过，证据为 `browser_control_combined_local_01/RESULT.json`，组件当时SHA记录在 `BROWSER_TABS_REVIEW.json`。

实际顺序为后台任务在自己的Page填写第一项、设置同context存储；提交优先发布fixture；safe_point将原命令置paused并保存完成项/下一项cursor；优先任务读取到该持久cursor，在同worker另一Page读到共享localStorage；它归还只关闭自己的标签页；后台随后使用原locator读回第一项并填写第二项。最终两个原ID均各执行一次并成功、保存cursor保留，所有handler同线程，resume与每次IO准入均有记录。

这里明确注入隔离账号、admission策略和loopback业务handler，未调用生产身份/暂停策略或真实发布handler。它验证管控/资源/worker实际接合与可恢复步骤，不替代平台发布验收。运行期间既有共享Loguru的agent.log轮换出现WinError32（文件被其他进程使用），没有影响上述结果；未据此修改日志配置或停止现有服务，生产日志争用不属于本次浏览器执行层验收通过范围。
