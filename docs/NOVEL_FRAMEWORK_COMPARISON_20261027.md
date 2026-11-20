# 五框架小说理解对照：没有语义验收胜者

本轮实际运行 LangGraph、PydanticAI、DSPy、CrewAI、AutoGen，统一 MiniMax-M3.1-Flash / adaptive-medium / 16384 输出上限。使用原授权小说《你敢惹我？我有六个反派儿子》完整第6—8章，先盲读再核对六条固定主张。预期标签不发给模型，题目包含三真三假；这是新章节构造留出题，不是全章自然产稿验收。

| 框架 | 原生调用 | reported tokens | 两步模型耗时 | 六题标签 | 内容复核 |
|---|---:|---:|---:|---|---|
| LangGraph 1.1.0 | 2 | 24,925 | 51.391秒 | 6/6 | 钱款动作反转；厨房与学校场景拼接 |
| PydanticAI 2.62.0 | 2 | 23,783 | 38.219秒 | 6/6 | 钱款动作反转；跟随与带路的主客体混淆 |
| DSPy 3.4.1 | 2 | 23,489 | 38.219秒 | 6/6 | 把在家等候的叶西决列入学校在场人物；同条自相矛盾 |
| CrewAI 1.15.30 | 2 | 27,294 | 63.047秒 | 6/6 | 钱款动作反转；把“张玉刚说完”误切为姓名“张玉刚” |
| AutoGen AgentChat 0.7.5 | 2 | 26,004 | 51.812秒 | 6/6 | “相当于五天工资”变成“已上班五天”；新增老师推脱动机 |

合计 **10次、125,495 reported tokens**，全部有原生回执、pending=null。未用DeepSeek/Qwen，未生成剧本、视频或发布。本书历史累计77次启动（包括旧1次未知）；旧未知任务没有重派。耗时是各框架两次原生请求耗时相加，不含安装、框架启动和人工复核；并发、缓存与随机输出影响观测，不能据此宣称框架普遍提速。

## 重要实验限制

1. 本轮实际用各框架的图/Agent/Predict/Crew运行接口，但共享本地原生MiniMax工具调用适配器、Schema和Pydantic校验。模型请求中保留框架生成的提示包装；SDK输出由适配器转换为各自的结果结构，不改模型文本内容。AutoGen回调的usage占位为0，真实用量只按保存的供应商native usage统计。这是受控集成比较，不能冒称各框架供应商客户端或全部能力评测。
2. **DSPy没有运行提示优化器；CrewAI/AutoGen没有多角色辩论。** 因此不能以这轮否定优化器或复杂协作的潜力，也不能声称这些能力已经验收。
3. 最初盲读Schema设置了无内容依据的30条上限。LangGraph/PydanticAI/AutoGen实际返回31/31/42条后被原校验拒收。原失败不改；新`*_continued`任务采用已有原生响应，验证除数量上限外的字段与来源，保存响应SHA和采用记录，再各执行一次核查。没有删材料、重新生成或解锁原失败。该上限缺陷不算框架内容能力差。
4. 六条候选的标签全部正确，**不代表盲读材料全部准确，更不代表理由完全可靠**。每套的PRIMARY_REVIEW都为needs_revision。例如LangGraph还把父亲规矩错引到另一章，多个理由把“没证据证明去世”加强成“确定在世”。
5. 只有一个模型、一次三章样本，缺少重复运行、优化器训练/独立测试、多集生成与自动返修比较，无法给出稳定质量排名。

## 选择建议

- **当前主流程继续保留LangGraph。** 本轮没有证据表明替换调度框架能解决钱款归属、人物在场或时间限定错误。保留既有调用账本和未知保护，避免为换框架引入新的运行风险。
- **下一项优先研究DSPy的提示优化与独立评测**，以动作主客体、身份切词、比较句、场景跨越作为训练问题，另取未见章节测试。此为建议，未在本轮运行优化器。官方：[DSPy优化器](https://dspy.ai/3.4.1/diving-deeper/optimizers/)。
- **PydanticAI作为类型化阶段接口的备选**；严格类型能发现格式问题，不能自行保证语义正确。本轮已有Pydantic校验，尚无证据值得因此整体迁移。官方：[FunctionModel接口](https://pydantic.dev/docs/ai/api/models/function/)。
- **CrewAI与AutoGen暂不替换主流程**：本轮没有语义收益证据，依赖和适配工作更多。AutoGen官方仓库另有迁移至Microsoft Agent Framework的建议，若未来选择微软路线需再评估维护方向：[官方仓库](https://github.com/microsoft/autogen)。

## 环境、测试及证据

独立D盘Python3.12.13及`.venv-framework-bench`，生产`.venv`未安装这些依赖，默认网页/CLI未迁移，账号服务未重启。Python3.14初次解析CrewAI选到古老版本，已终止安装；新的3.12环境安装175个依赖。官方源慢，后改用清华镜像完成；失败安装日志保留。

远程tracing/telemetry关闭。CrewAI关闭tracing仍在导入时初始化凭据存储，实验适配层把空凭据存储定向D盘，不读取用户CrewAI登录。`CREWAI_STORAGE_DIR`也定向D盘。未修改第三方安装源码或系统环境变量。

6项传输与合同保护测试通过；五框架各一次本地fake接口样例通过。CrewAI早期两次C盘路径失败及后续修复记录保留。fake样例不算模型质量测试。

- 入口：`scripts/framework_bench_20261027.py`
- 已知回执续测：`scripts/framework_continue_20261027.py`
- 实验目录：`data/corpus_production_trials/20261027_framework_compare`
- 总表：实验目录`COMPARISON.json`
- 每套：`REQUEST_*`、`RESPONSE_*`、`READING`、`VERDICTS`、`SCORE`、`PRIMARY_REVIEW`
- 原数量校验失败：三个原目录`RESULT.json`；新采用证据：三个续测目录`ADOPTION.json`
- 测试：`data/qa/framework_contract_final_20261027.log`及`framework_smoke_*`
- 环境：`data/qa/framework_bench_requirements_20261027.txt`

所有真实实验均已结束，不重跑这些目录。最终结论：集成可行，六题判断通过，**材料语义仍未验收，无全链生产通过**。
