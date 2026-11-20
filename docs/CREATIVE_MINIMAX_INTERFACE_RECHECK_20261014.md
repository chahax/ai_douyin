# MiniMax接口复核与本轮类型失败的证据边界

2026-10-14复核官方[OpenAI SDK文档](https://platform.minimax.cn/docs/api-reference/text-openai-api)及[MiniMax官方M3格式校验清单](https://github.com/MiniMax-AI/MiniMax-Provider-Verifier/blob/main/m3_format_check/docs/m3_text_cases.md)。未运行该清单的付费测试，没有改模型或生产参数。

官方SDK文档列出MiniMax-M3.1-Flash-Preview、tools、adaptive thinking及reasoning_effort档位。当前writer采用同模型、adaptive和medium；未关闭强制思考。文档提醒旧max_tokens包含思考消耗，并建议新接入使用max_completion_tokens。精确旧服务为何分配大量分析不能从这一说明确定；本地实际wire、原usage/finish_reason仍是具体请求的证据，不能把官方说明当成旧故障已经查明。

本轮614/615已经有完整HTTP、tool_call、JSON和已知消耗；失败明确发生在orientation的对象/空字符串与本地string/null合同不符。没有证据证明SDK擅自替模型写入了错误的null值，也不能把该现象解释成没有收到响应。本轮最小修复是模型原生的显式状态对象，保留编译职责，不将失败旧响应手改为合格。

官方工具说明和格式校验用例是兼容性核对线索，不证明所有动态JSON Schema均能严格遵守。当前MiniMax普通tools没有因文档阅读升级为服务严格约束，本地原生完整验收仍必须执行。新setup-v4尚待离线及真实请求分别验证；语义与视频质量另行记录。
