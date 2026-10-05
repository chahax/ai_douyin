# MiniMax调用方式与当前阻断核对

这是调用协议与客户端证据审计，不是第70次服务结果恢复或导演产物。

## 当前怎样调用

OpenAI Python SDK → 原MiniMax国内兼容地址https://api.minimaxi.com/v1 → 同步POST /chat/completions → 等待完整响应 → 从submit_creative_json工具参数读取payload_json → 本地严格解析和验收。M3、max_completion_tokens=8000、temperature=0.4、thinking disabled、600秒客户端超时、max_retries=0；未显式stream，因此不是流式。

[官方OpenAI SDK说明](https://platform.minimax.io/docs/api-reference/text-openai-api)支持这条SDK路线。[中文接口合同](https://platform.minimax.cn/docs/api-reference/text-chat-openai)明确支持M3、disabled thinking、正数max_completion_tokens、function tools及非流式响应。当前中文示例域名api.minimax.cn不同于原配置，完整旧域名兼容承诺尚未查到；原通路67/69真实返回支持其此前可用，不能直接归因或静默改址。

## 三类问题应分开

1. **原70未知结果**：没有ID、响应、用量或异常回执。服务收到/完成/计费及进程中断原因均未知。未证明是参数错误或服务故障。
2. **工具与内层格式限制**：原请求发送指定function对象tool_choice，但当前已查Chat Completions文档没有明确写出强制执行和strict生成保证。过去收到该工具不证明硬约束生效。工具本身只约束payload_json为字符串；导演完整内层Schema在消息里，仍需本地全文验证。69正常tool_calls、5021 completion低于8000，但内层合同失败；这种内容失败与70失联不同。
3. **已验证本地缺陷**：HTTP400/request_id被包装成普通RuntimeError，结构化字段丢失并被归UNKNOWN；模拟收到id/usage后快照解析异常，同样未保留元信息。客户端也缺少分阶段落盘，pending先于网络调用，原JSON在解析后才向调用方返回。

[两项离线假服务证据](OFFLINE_CLIENT_EVIDENCE.json)均0真实调用，只证明代码缺陷，不证明70走了这两条异常分支。

## 最小改进方向

先补结构化错误身份与原响应先落盘、后解析，保留安全HTTP头/请求ID/服务错误字段和准确阶段事件。服务已报错不等于已知用量；用量未知继续阻止自动重派。流式是官方支持的后续候选，可提高途中证据保留，但不能承诺一定能取回完整结果或最终用量。

原70继续对账，旧记录及64010预留保持；任何源码修复采用新绑定，继承累计消耗，不改原冻结144文件。本次没有改生产代码、派发模型或生成媒体。

[详细核对](OFFICIAL_CALL_METHOD_REVIEW.json)。
