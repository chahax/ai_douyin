# 文本响应接收与故障隔离修复（2026-10-05）

本次落实客户端修复，离线验收通过；未新增生产模型、媒体或发布请求。旧第70次导演返修的结果与用量仍未知，不能用新代码补造旧响应，也不能据此重发。S6完整剧本保持原稿，导演安排、实际表演窗口、编译和制作交接尚未完成。

## 已证实的问题与修复

| 已复现的问题 | 新行为 | 仍不能证明的事项 |
|---|---|---|
| HTTP错误被包装成普通RuntimeError，丢失状态码和请求ID，误入“没有响应”分支 | 保存HTTP状态、允许保存的响应头、请求ID和错误正文，分类为已收到的接口错误 | HTTP错误不代表免费；缺真实用量仍保留未知预留并阻止新派发 |
| 已有ID和usage，但工具字段畸形导致SDK后续解析异常，元信息丢失 | 完整原正文先保存，随后严格解析原JSON；在检查工具之前保存ID、模型、usage和服务状态 | 这不是第70次故障根因证明 |
| 只有派发前pending记录，不能定位是否收到了响应头或正文 | 分阶段追加证据：准备、客户端配置、派发尝试、HTTP头、完整正文、元信息、解析结果 | “派发尝试”不是服务收到或执行请求的确认 |
| 本地解析前退出，无法重新取得已收到的原响应 | 完整正文与清单存在且SHA核对通过时，仅本地恢复解析、验收和计账视图 | 未保存完整正文的旧请求不能用此方法恢复 |

长分析耗尽输出的服务端原因、第70次进程消失及服务端是否执行/计费仍未查明。本次修复针对已经用模拟服务复现的客户端缺陷，不归因于模型能力或服务端故障。

## 实际代码与职责

- [creative_call_evidence_v1.py](../scripts/creative_call_evidence_v1.py)：逐调用追加式证据、原响应字节及SHA清单；先写临时文件并flush/fsync，再不覆盖地发布文件。只保存允许的响应头，凭据回显时脱敏并禁止采用该正文。
- [creative_evidenced_role_clients_v1.py](../scripts/creative_evidenced_role_clients_v1.py)：保留原模型、endpoint、温度、thinking、上限与工具请求；取得HTTP正文之后才执行本地JSON和工具检查，异常携带结构化元信息。
- [creative_resume_dispatch_v3.py](../scripts/creative_resume_dispatch_v3.py)：接入新客户端、证据和故障分类；未知结果或未知用量继续阻止新派发。显式本地恢复形成新恢复记录和派生视图，不改原回执或调用账本，不自动重试。
- [prepare_creative_call_evidence_repair_v1.py](../scripts/prepare_creative_call_evidence_repair_v1.py)：只读核对原记录与冻结源码，保存新候选绑定与快照。不会建立AUTHORIZATION/CALL_LEDGER、调用SDK或派发生产请求。

新客户端使用OpenAI SDK的 `with_streaming_response` 延后本地解析，实际请求没有新增 `stream: true`。这不改变服务端同步非流式请求，也不声称有异步历史结果查询。实测SDK版本为2.37.0。

工具请求仍是原 `submit_creative_json` 与指定 `tool_choice`，没有新增未经验证的strict或response_format参数。工具选择已发送不等于服务强制生成；原导演传输工具只有payload_json字符串，内部导演Schema继续由本地完整验收。

## 分支验收

| 模拟情形 | 验收分支与后续 |
|---|---|
| HTTP 400/401/429/500 | interface_rejected；状态、请求ID与原正文保留；用量缺失时保留预留 |
| length截断，同时缺工具 | 先识别RESPONSE_TRUNCATED，不用正文兜底 |
| 完成但缺工具/工具容器或function类型错误 | interface_rejected，保留响应ID和真实usage，不进入正文合同 |
| 工具内数组写成对象 | contract_rejected / MODULE_SCHEMA_INVALID，不手改模型结果 |
| 无HTTP响应的超时或连接异常 | outcome_unknown；相同请求返回原回执，不同新请求被阻止 |
| 收到响应头但正文中断 | response_received=true、provider_outcome_known=false；保留HTTP ID，不假装完整成功 |
| 缺usage、字符串/布尔/负数usage | 不能当0用量，未知预留与门禁保留 |
| 客户端配置或证据目录创建失败 | blocked_before_dispatch，无HTTP请求；原启动登记不清零 |
| 正文已保存、清单完整，解析前模拟进程退出 | 本地恢复；HTTP请求总数仍1，原回执和账本字节保持 |
| 恢复记录保存后、索引登记前退出 | 核对既有恢复记录与原正文后续办，不重复派发 |
| 原正文或恢复记录SHA不符、重复响应ID | 停止恢复/派发，不能覆盖证据或重复计账 |
| 响应阶段/HTTP错误保存失败 | 已取得的HTTP身份继续保留；正文不完整或用量未知时仍不放行 |

完整响应与用量是两个事实。例如收到HTTP错误可以确定有错误响应，但不能自行确定收费；收到有效文本但没有usage也不解除用量对账门禁。只有服务原响应明确报告的非负整数才作为reported tokens。

## 离线产物与验证

- [最终修复测试](../data/qa/creative_call_evidence_repair_20261005/TEST_ATTEMPT_05.txt)：49项通过，真实OpenAI SDK配合内存httpx.MockTransport；没有真实服务连接。
- [原绑定代码回归](../data/qa/creative_call_evidence_repair_20261005/UNCHANGED_BOUND_CODE_REGRESSION.txt)：98项通过。
- [验收记录](../data/qa/creative_call_evidence_repair_20261005/VALIDATION.json)：记录测试、原25份记录与144个源码SHA、新149源码快照、费用与质量范围。
- [新候选绑定](../data/qa/creative_call_evidence_repair_20261005/CANDIDATE_BINDING.json)：offline_binding_prepared_production_blocked，dispatch_enabled=false，不是新执行任务、平台v24或旧任务迁移。

保留全部测试尝试：第一次测试临时目录设置失败；第二次35项通过；第三次45项通过；第四次48项通过、1项新快照父目录缺失；修正目录创建后第五次49项全部通过。临时测试目录只供本地复现，不作为成片或创作交付。

截至本次验收，真实账本仍为70次启动、69次已知用量、709272 reported tokens，未知预留64010；文本总硬限null，旧500000授权和历史消耗不变，媒体调用0。新候选不会清除旧70，也未登记新调用。原冻结入口v4仍使用原派发器v2，不能称旧任务已安装新修复；后续在旧70得到有效对账证据后，需独立核对新源码与继承消耗，再明确采用新绑定和运行入口。

## 下一步与制作状态

先取得原70的可核实服务记录/原响应及真实用量，完成对账；若服务只能证明结果不存在，也须保留该真实证据并处理计费未知，不能靠进程不存在推断。新生产入口采用前还需要实际接口验收，本轮离线成功不能替代它。

之后继续S6完整导演返修、实际局部表演与对白前中后/听者反应窗口、跨镜状态编译和全文审查。方澄拒绝、林屿接回工作、她赴电影之约的内容保持；任何内容返修由MiniMax完整重交，DeepSeek按需全文复审。没有可采用导演稿前不进入媒体生成。
