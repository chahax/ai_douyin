# 官方工具调用与固定证据编号小样

用户授权先参考开源框架部分试试，并询问DSH接MiniMax或MiniMax相关工具。已核实DSH的pi-ai适配器支持自定义模型端点；主机有Node 24.14.0，但未发现dsh命令。MiniMax官方提供Mini-Agent和MiniMax Code；此次选择直接使用官方Tool Use接口，不安装桌面/Agent运行时。

参考：
- https://github.com/anywhere-labs/dsh-desktop
- https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/llm/llm-pi-ai/README.md
- https://github.com/MiniMax-AI/Mini-Agent
- https://github.com/MiniMax-AI/minimax-code
- https://platform.minimax.io/docs/guides/text-m3-function-call

本次不是调用DSH或Mini-Agent的实测，也不是PydanticAI安装试验。借鉴其类型化工具接口：使用现有OpenAI兼容SDK向原MiniMax端点发送function tools，接收submit_result.arguments，jsonschema和额外程序校验固定编号、题目覆盖、说话人、时间连续性。未用response_format或strict schema参数，不声称供应商强制保证结构正确。没有shell/文件/浏览器工具授权给模型，submit_result仅保存文本结果。

## 真实执行

独立目录data/corpus_production_trials/20261026_minimax_tools，原合成《两把钥匙》三章399字符及4道构造证据题；无真实小说外发。最多3次，实际3次MiniMax-M3.1-Flash、adaptive/medium、16384输出上限、11843 reported tokens，原生finish_reason全部tool_calls。请求无自动重试，pending=null。

1. 固定证据ID判断：时间相容、空值信息不足、明确空间矛盾、开信动作无原文依据，4/4符合预期。预期答案保存本地未发送；但空值的unknown语义定义明确放入输入，因此是接口可行性小样，不是盲测泛化准确率。
2. 生成《铜钥匙的一天》，8场、规划60秒，原生JSON映射为可读Markdown，非助手手改。不是现有整条分层生产流程产稿。
3. MiniMax独立上下文审查给pass及2条建议；主助手退回，见PRIMARY_REVIEW.json。存在院外写院中、画面人物未登记、内心音轨类型缺失、信息推进慢和动作计时待核等问题。机器pass保留，不冒充DeepSeek终审或成片通过。

4项离线合同检查通过：合法引用/空值、跨题引用拒绝、虚构编号拒绝、重复题目拒绝。只覆盖小样合同，不等同生产全回归。原MiniMax审核试验所有文件SHA未变。

## 结论

本次固定ID消除了让模型手写路径和复制空值的任务，工具提交成功，但仍有语义漏检。与原试验相比同时改变提示、证据呈现、输出接口及任务范围，不能把改善单独归因于Tool Use，也不能称整链通过。

建议保留此输出接口设计，再在独立新版本中接回框架一致性审核，并补充真实旧失败样本、空值/未知反例、场景人物与音轨类型验证。DSH可后续独立接入对照；本次没有修改生产默认、账号服务、自启、安装依赖或生成媒体。

RUN_TRIAL.py prepare/execute均已完成，不可重跑；旧失败、审批及用量保持。完整INPUT/PLAN/CALL/RESPONSE/RESULT与剧本小样在试验目录。
