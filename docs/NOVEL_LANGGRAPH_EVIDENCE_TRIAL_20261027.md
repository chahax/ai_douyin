# LangGraph小说证据核对试验

用户授权按MiniMax套餐继续使用、可采用或更换开源agent框架。本轮不再将旧400次计划当作新MiniMax试验的购买额度；保留每项试验的工程停止边界、实际调用记录和原未知任务。来源仍为原获授权小说前5章，仅文本，无媒体、发布或账号后台重启。

## 框架选择与实现

选择LangGraph显式节点和SQLite checkpoint，配合Pydantic合同和现有原生调用账本。PydanticAI可提供结构化输出/校验，但格式校验并不能解决语义支持问题，因此本轮重点是图节点职责、证据和独立检查，而非再套一个自动重试agent。

参考官方文档：
- https://docs.langchain.com/oss/python/langgraph/workflows-agents
- https://docs.langchain.com/oss/python/langgraph/persistence
- https://pydantic.dev/docs/ai/core-concepts/output/

在D盘新建.venv-novel-agent，生产.venv没有安装或升级包。试验依赖见requirements-novel-agent.txt。该环境通过system-site-packages/只读追加原.venv依赖运行，不能称完全封闭的独立依赖环境；首次安装检测到系统langgraph元数据但导入失败，已将实际所需包安装到新环境。pip报告系统既有gradio/datasets等不相关依赖冲突，未修改这些环境。框架及SQLite依赖本机实际导入测试通过。新版OpenAI SDK与旧SDK不同，本轮不能称只换框架的严格单变量对照。所有runner禁用LangSmith/LangChain远程追踪；仅配置的MiniMax端点接收文本。

实现文件：novel_evidence_graph_v1.py、novel_evidence_protocol_v2.py、novel_evidence_guards_v1.py及v2；scripts/run_novel_evidence_graph_trial.py、run_novel_evidence_graph_v2_trial.py、run_novel_evidence_guard_trial.py及v2。

流程：完整原文目录（程序生成段ID）→关键命题提取→每批最多3条，逐条拆解主张核对原文→独立时间/因果/确定性门→独立完整性门→仍需独立内容验收。模型不复制原文引句，只选择真实目录ID，程序核验ID；ID存在仍不等于证据支持，因此保留语义复核。任何一部分未支持，整条不得自动算通过。

SQLite记录了节点状态；当前CLI故意拒绝已有run，不提供自动跨进程重派。测试证明checkpoint能读取，不代表任意未知调用可以安全恢复。旧20261027_serial_understanding_audit仍outcome_unknown/pending=1，本轮未重派。

## 程序测试

12项相关测试通过：原文ID保留空行位置、重复/漏主张/不存在来源拦截、部分错误主张不放行、传输错误不自动重试、目标章绑定、SQLite重开读取、数组Schema内联、独立检查阻断、阶段kind与Schema一致。XML：data/qa/langgraph_evidence_guardv2_20261027.xml。

## 真实测试

1. 从旧原生输出选15条实际主张，含8条有问题、7条可支持项。预期结论只保存在本地，未发送模型。v1先执行2次，第二次把atoms数组写成item对象，Pydantic拒收。没有手动改原生答案。
2. v2把Schema的$defs展开，明确数组格式，保留第1批原生SHA验证结果；第2批为已知格式失败的显式返修，再执行余批。新4次，共与旧2次形成完整15条检查。12/15整条判断与助手预期一致：抓到父亲亡故、老五年龄/最小、钱款交接等；误拒1条，漏过2条。不是统计显著准确率，不是全书泛化结果。首次正确not_stated“父亲亡故”的reason仍无据称父母尚在，说明标签正确也可能理由错误。
3. 新原生第一章提取18条，6批审核全部判支持，共7次。助手复核发现C05/C07/C08的原书未来限定不完整，且上限18条导致章末关系/事件未充分保留；机器全pass不升级成人工验收。
4. 增加关系与完整性两个专门门。v1第一次返回关系门不允许的missing_event；原因包含提示限定而共享Schema仍放行类型的程序缺陷。旧结果保留，新v2将阶段enum与验证要求统一，并增加正反测试。
5. v2两个门真实运行：完整性门指出老大提出辍学换老六入学、老二此前试过挨打、双胞胎回家、兄弟互护等遗漏，正确阻止下游；关系门却将“醒来”当作“睁眼”判时序倒置，主助手不采纳这一硬伤判断。关系门仍未可靠抓住原书未来混入过去的风险。完整性门“隐藏身份”动机也超出直接证据，不能照单返修。

## 实际调用和结论

| 新任务 | 调用 | reported tokens | pending |
|---|---:|---:|---|
| langgraph_benchmark | 2 | 37247 | null |
| langgraph_v2_benchmark | 4 | 71900 | null |
| langgraph_v2_fresh | 7 | 116081 | null |
| langgraph_guards | 1 | 9100 | null |
| langgraph_guards_v2 | 2 | 12558 | null |
| 本轮合计 | 16 | 246886 | 全部null |

原本书此前29次已启动含1未知，本轮后累计45次已启动，旧未知用量仍未知，不与reported用量混为零。本轮全部MiniMax-M3.1-Flash，DeepSeek/Qwen0，完整剧本/媒体/发布0。

结论：开源框架已实际接入并执行，按主张分批检查和完整性门有明确价值，但模型语义误判并未被框架自动解决。当前needs_revision，不能自动生成剧本或替换网页默认。保留此框架继续完善原文时间层级、限定词核验、覆盖充分性和审核意见有效性。不要盲目再换框架、无限重复相同提示，或将机器18/18支持冒称产稿验收。
