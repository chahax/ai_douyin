# 小说改编全流程开发、主审与真实测试

日期：2026-10-18。承接用户“直接全流程开发测试”。本轮由子 agent 分模块开发，主 agent 审查实际接线、故障证据与真实结果，另有独立 agent 复验。

## 实际结果

独立 v7 已真实跑通**正文冻结 → MiniMax 完整创作 → DeepSeek 同源同稿全文审查/场记/问题核实 → 程序决定 → 导演分段 → DeepSeek 全文导演审查 → 制作文本交接**。

当前状态 `text_ready_for_production`、`stage=complete`、`pending_call=null`。完整稿原生审核与导演原生审核均 pass；导演覆盖 11 个事件、11 段。最终生成 `SCREENPLAY.md`、`PRODUCTION_HANDOFF.json`、`OUTPUT_MANIFEST.json`，逐文件和原生全文证据复验通过。完成后实际重入新增调用为 0。

本次真实源为独立原创单章《渡口的单程票》，正文1326字/字符，完整分析与创作稿3457字符；**本轮没有重新采集番茄小说，不代表整本长篇已改编**。旧番茄《婚礼现场，我和全家断绝关系！》20次/310301 reported tokens、剩余调用0及旧失败不变。

### 尚有的内容差距

导演累计预计240秒，冻结测试目标180秒未改。DeepSeek完整审查明确记为一项 `timing/minor`，建议在导演层压缩或合并反应/过渡，原生 verdict 仍为 pass。**这不是已达到180秒的验收，也不是实际视频时长证明**；本轮没有继续派新导演或手工缩稿。

主 agent 与独立 agent 本地核对认为主线、父女动机、船票和告别因果成立；完整稿还有“对坐”概述与站坐表演不一致、红笔动作的隐含衔接和个别量词等轻微瑕疵，未因此要求整稿重写。机器文本通过不表示没有瑕疵或用户审美采用。

## 已实现的接线

- 网页“小说改编”默认 `novel_agent_panel_v7.py`，CLI `scripts/run_novel_agent_v7.py`。支持番茄采集器接线、已有采集记录/本地正文导入、来源与范围冻结、只读预览、执行、状态查看及明确的本地恢复。
- MiniMax 直接提交完整原生文本：背景、角色选择、主线/高潮、改编规划和完整剧本。没有writer工具、双份JSON或逐句原文/排版硬门。
- DeepSeek 对照冻结完整来源审同一完整稿，合并返回场记、九维全文审查和问题核实。程序仍独立保存、复现并检查这些派生物，不能靠调用方布尔值绕过原生 pass。
- 规则区分概述、同事件展开与实际演出；明确物理矛盾可给出候选，候选必须核实。重大或可能重大的未知问题不放行；已知完整实质失败才有界整稿返修。
- 导演包包含世界框架、全部在场者的动作/神情/视线/对白/反应、前后状态、情绪窗口、事件覆盖、预计时长依据及资产需求。导演层问题留在本层，不能借机改写已通过完整稿。
- 原生请求、唯一claim、响应、用量和检查点由同一运行器管理；未知、截断、用量未知停止。LangGraph节点没有自动重试，SQLite保存引用，不产生第二份预算。真实完成结果和本地状态可验证恢复，不能重新派发旧请求。
- 自有资产目录已进入实际导演请求和交接。此次需求仍为pending，未伪写选角、声线或服务资格绑定。

## 两次真实接口修复及保留记录

1. **v5场记状态表示过窄。**真实DeepSeek已全文pass，但before/after写自然语言而被typed fact合同拒绝。独立v6将字符串逐字保留为unknown描述，不推断人物位置、姿态或持有者，原生结论不变；原有typed明确物理冲突仍拒绝。v5仍保持原needs_attention。
2. **v6把时间线ID别名当内容矛盾。**两份完整导演分别写T1、T1_present_ferryhall，实际都指冻结场记present；原反馈没有expected ID，耗完一轮导演返修仍被拒绝。独立v7按已知event_id唯一源时间线绑定，保留原生标签、映射和原文SHA；未知事件、混时间线、同别名跨线或已知源ID冲突仍拒绝。动作、对白、状态及240秒估时均不改。v6仍保持director_revision_exhausted。

新派生版本不重标旧稿通过，不重领调用或导演返修次数。v7承接全链4次/71224 tokens，只允许一次新的DeepSeek导演全文审查；通过后才创建本版本机器文本交接。

计划分别见[全流程开发](NOVEL_FULL_FLOW_IMPLEMENTATION_PLAN_20261017.md)、[状态描述兼容](NOVEL_NATIVE_STATE_PROJECTION_V6_PLAN_20261018.md)、[导演时间线身份编译](NOVEL_DIRECTOR_TIMELINE_BINDING_V7_PLAN_20261018.md)。原架构v1.1及Claude Code仅方案文档审查记录保持原样；本轮未把源码发送给Claude Code配置的服务。

## 真实调用与容量

| 运行 | 实际阶段 | reported tokens | 实际结果 |
| --- | --- | ---: | --- |
| v5 / 001 | MiniMax完整创作 | 4128 | 完整原生文本 |
| v5 / 002 | DeepSeek同稿场记/全文审核 | 8554 | 原生pass，旧辅助合同拒绝 |
| v6 / 001 | MiniMax完整导演 | 25283 | 完整返回，旧时间线ID合同拒绝 |
| v6 / 002 | MiniMax完整导演修订 | 33259 | 完整返回，旧时间线ID合同拒绝 |
| v7 / 001 | DeepSeek完整导演审核 | 17138 | 原生pass，1项minor排时差距 |
| 合计 | 5个实际服务请求 | **88362** | 均明确stop、用量已知 |

原上限20次/500000 tokens不变，剩余15次/411638 tokens；导演返修仍已用1/1，v7续审的一次额度已用完。剩余总额不自动赋予新导演候选或再次审查权限。没有未决请求、运输重试、媒体或发布调用。

实际模型为冻结配置中的MiniMax-M3与deepseek-flash；全部请求、响应、服务ID及用量可从检查点追溯。Claude方案核对是另一份历史服务账，不混入此故事5次账本。

## 测试与主审证据

最终组合 **1061 passed**，独立反例另 **3 passed**，合计1064个不同测试；无失败、错误或skip。1061已包含旧路线回归，不能再把此前706/847等阶段数相加。覆盖真实LangGraph/SQLite配合fake服务、主导航、CLI、Streamlit AppTest、完整链条、整稿/导演返修、核实、原生证据、共享来源登记、唯一续行、准备中断、状态恢复、预算耗尽和未知停止。

最终独立3项特别验证：v5→v6→v7只新增一次导演审查即交接，改派生对白不能通过原生重解析，换请求内容也不能重领唯一审核。测试服务均fake，不冒充真实模型；真实5次调用单独列于上表。13项上游LangSmith异步函数deprecation warning不影响当前运行。

- [最终组合JUnit](../data/qa/novel_full_flow_v5_20261017/V7_FINAL_COMBINED_TESTS.xml)
- [独立复验JUnit](../data/qa/novel_full_flow_v5_20261017/INDEPENDENT_V7_TESTS.xml)
- [最终验收检查点](../data/qa/novel_full_flow_v5_20261017/FINAL_ACCEPTANCE_CHECKPOINT.json)：643个唯一旧文件/冻结文件SHA核对无变化，真实完成后重入0派发。
- [导演原生回放](../data/qa/novel_full_v7_20261018/V6_NATIVE_DIRECTOR_REPLAY.json)：两份旧稿全部非timeline字段不变。

框架在项目data下隔离安装，未替换旧venv。实际LangGraph1.2.16、SQLite checkpoint3.1.2，依赖清单见`data/qa/novel_full_flow_v5_20261017/LANGGRAPH_DEPENDENCY_LOCK.json`，tracing关闭。正式CLI使用新进程；测试设置`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，避免旧测试插件预加载legacy LangSmith。参考官方[图API](https://docs.langchain.com/oss/python/langgraph/graph-api)及[持久化](https://docs.langchain.com/oss/python/langgraph/persistence)。

## 入口与实际文件

```powershell
.venv\Scripts\python.exe scripts/run_novel_agent_v7.py fetch --output-dir 新采集目录 --book-name 书名 --chapters 1
.venv\Scripts\python.exe scripts/run_novel_agent_v7.py prepare --run-dir 新任务目录 --source-path 正文路径 --title 书名 --scope 已获取范围 --target-duration-seconds 180
.venv\Scripts\python.exe scripts/run_novel_agent_v7.py preview --run-dir 新任务目录
.venv\Scripts\python.exe scripts/run_novel_agent_v7.py execute --run-dir 新任务目录 --engine langgraph
.venv\Scripts\python.exe scripts/run_novel_agent_v7.py inspect --run-dir 新任务目录
```

fetch遇登录或验证保存停点；同源已登记不能换目录重领。prepare/preview/inspect不发模型。目标时长60–900秒。旧v5场记格式续行仍用原v6明确入口；v7的`prepare-director-continuation`只接本报告所述已知完整v6导演停点，无预算覆盖参数。`recover-projection`只恢复核实过的本地状态，不派请求，不解除未知pending。

实际产物根目录：

```text
D:\IT\ai_douyin\data\novel_agent_production\20261018_original_trial_v7
```

- [完整分析及剧本](../data/novel_agent_production/20261018_original_trial_v7/run/SCREENPLAY.md)
- [11段导演阅读稿](../data/novel_agent_production/20261018_original_trial_v7/DIRECTOR_READING.md)：源JSON逐字段展示，未增加创作内容。
- [机器制作交接](../data/novel_agent_production/20261018_original_trial_v7/run/PRODUCTION_HANDOFF.json)
- [输出完整性清单](../data/novel_agent_production/20261018_original_trial_v7/run/OUTPUT_MANIFEST.json)

## 本轮没有证明的范围

这是一个原创完整单章的真实模型验收，不能推出番茄长篇、多线多人物或所有小说的自动改编质量均可靠。采集器已接线且有离线验收，本轮没有新的登录/验证及番茄正文实采。网页通过AppTest，未宣称现场浏览器全按钮操作验收。

机器文本交接没有执行正式素材/声线绑定、媒体能力编译、图片、声音、视频、用户审片或抖音发布；也不补齐推广账号选题/书库授权及运营转化闭环。视频内容仍由用户人工审核。当前`human_approved=false`、`media_generated=false`，原媒体及发布规则不变。
