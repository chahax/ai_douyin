# 自然文本导演与5+5轮真实测试

用户授权原文：“可以再测试5轮+5”。本轮先5轮、再5轮，所有来源共享最多10个自然导演候选，每5轮复盘，达到目标提前结束。每轮最多MiniMax完整自然导演、DeepSeek忠实整理审核、DeepSeek独立整包审核共3次文本调用。没有新媒体或发布授权。

## 为什么改流程

v8/v9实际6份导演结果都未通过，其中一份截断停止。已通过的完整编剧文本保留。旧导演重复表达performance和beats，长失败JSON进入返修后明显增大请求，重复身份、秒数和对白也增加冲突。具体原生审计在`data/qa/natural_director_v10/SIX_NATIVE_REDUNDANCY_AUDIT.json`。不以放宽内容标准解决问题。

## 可复用新路线

完整来源冻结 → MiniMax完整自然剧本 → DeepSeek同源全文审核及有界完整返修 → MiniMax全新自然导演 → DeepSeek忠实整理并审核 → SDK逐段编译 → DeepSeek对完整来源、完整剧本、自然导演和全部实际SDK请求独立审核 → 机器文本交接。

导演完整表达世界框架、角色映射、每段秒数及累计时间、所有在场者的动作神情、视线转移、身体朝向、说话对象、听者反应、摄影可见性和首尾因果。对白、动作和反应自然并行，避免空等和过快念词。保留合理避视与有目的的沉默。

MiniMax不用JSON、工具或逐句引文交稿。DeepSeek只能忠实整理，不能替导演编造缺失台词、镜头或改秒数；缺失或实质问题返回明确反馈给完整新导演。正文责任的实质问题停止在上游，不通过下游改写迁就。

新来源入口锁内只允许编剧和同稿全文审核，不会进入旧重JSON导演。已知完整失败的当前渡口/家庭来源可承接v9通过的完整编剧及原生全文审查；办公室来源原生截断和pending保留，拒绝续行。旧v8/v9入口和冻结不迁移。

## 计数、预算与停止

共享campaign授权及独占轮锁位于`data/narrative_quality_production/20261018_v10/campaign`。每个自然导演派发前写不可变ROUND claim，每5轮需要绑定实际原生结果的复盘。轮数不等于调用次数、测试数或子agent数。

沿用每来源原总20次调用/500000 reported tokens，继承实际原账本。当前渡口承接9次/181043，家庭承接4次/95563；“5+5”不自动增加总预算。保留所有旧失败、费用和冻结，不通过新目录重领。SDK运输自动重试关闭；未知结果、未知用量、截断必须停止保存，不把推理或部分正文当完整结果。

交接和只读检查都重读三阶段原生请求/响应，核对来源与正文、协议、参数、响应模型、明确stop、实际用量、审核原生派生及全部SDK请求。手写verified或pass不能放行。测试中构造的假响应不计生产通过。

## 新实现及验收

- `src/content_factory/natural_director_contracts_v10.py`：自然创作、忠实整理、全文整包审核与原生交接门。
- `src/content_factory/natural_director_role_clients_v10.py`：MiniMax原生文本；DeepSeek显式JSON Output，完整响应保存，0运输重试。
- `src/content_factory/natural_director_pipeline_v10.py`：持久执行、原生账本、共享轮数、原预算继承及新来源writer-only。
- `scripts/run_natural_director_v10.py`及对应网页面板：准备、预览、执行、原任务恢复。

模型能力与实际调用分开记录。DeepSeek官方create-chat-completion支持response_format=json_object，要求消息显式指定JSON；本轮整理请求16000 max_tokens。参考：[官方API](https://api-docs.deepseek.com/api/create-chat-completion/)、[模型表](https://api-docs.deepseek.com/quick_start/pricing/)。新适配器仍须通过实际请求验证，JSON输出能力不证明内容正确。

完成后保存每次真实结果和独立验收报告；交付完整剧本、自然导演、全部分段实际提示词及审查判词。未通过时明确具体停点。本文是本轮开发和测试计划，不宣称已真实通过，媒体仍等待用户人工审核。
