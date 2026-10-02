# MiniMax 小上下文规则三轮真实对比（2026-10-03）

18 次新增授权调用全部完成。基础 Schema 组的业务合同通过率为 0/3；补充中文业务约定后，五种版本各 3/3。模型在这个小任务中能够按明确规则输出，现有证据不支持“模型完全无法识别限制规则”。

基础组也有 3/3 通过它实际收到的 Schema：数组、对象及基础类型均正确。它失败于本地要求的人物编号、规范源路径和关系词，其中部分约定没有在基础组请求中说明。因此这里首先暴露的是合同表达缺口，不能把这三次概括为模型违背了已经明确提供的全部规则。

本次产物是规则实验、原始回执、验收记录和离线回归，不是完整剧本、导演计划或制作交接。旧任务的创作质量仍未通过。

## 对照条件与实际输入

使用现有国内 OpenAI 兼容接口、MiniMax-M3，温度 0.4、thinking=disabled、max_completion_tokens=1024，强制指定 submit_creative_json 工具。没有换模型、换接口或调用 DeepSeek。

固定合成上下文序列化后 300 字符，只有甲 C01、乙 C02 和一拍 B1：
甲把杯子放到桌面；乙说“今晚我自己弄，你先走”。目标是提交两项要求：先在放杯事件结束后观察甲两秒，再在乙的对白期间观察甲两秒。

六组的 system/user messages 完全相同；唯一变化部分是 tools[0].function.parameters。中文说明和示例放在工具 Schema 的 description 内，仍然属于模型实际请求。上下文、请求、源码版本均保存哈希，三轮每次都是独立请求，无聊天历史、失败回填或自动重试。

目标合同要求 subject=C01，来源依次为 script.beats.0.event、script.beats.0.dialogue.0.text，关系依次为 after、during。两个 ID 必须不同，minimum_seconds 均为数值 2。验收同时检查数组结构、源路径、源与关系兼容、任务值及顺序，不解开错误包装，不回填任何字段。

| 组 | 相对前组的变化 | 本组 Schema 通过 | 业务合同通过 | 三轮 completion tokens |
|---|---|---:|---:|---|
| A | 仅基础对象、数组、类型约束 | 3/3 | 0/3 | 227 / 202 / 193 |
| B | A 加简短中文编号、路径与关系说明 | 3/3 | 3/3 | 199 / 193 / 191 |
| C | B 加另一场景的完整结构示例 | 3/3 | 3/3 | 196 / 201 / 205 |
| D | B 加拍编号、人物、路径、关系的简单枚举 | 3/3 | 3/3 | 193 / 193 / 199 |
| E | D 的单拍数组改为等价 prefixItems 形式 | 3/3 | 3/3 | 193 / 199 / 193 |
| F | E 加 event 来源只能 before/after 的 if/then 条件 | 3/3 | 3/3 | 193 / 195 / 193 |

顺序分别为 ABCDEF、FEDCBA、CDAFEB。C 的示例使用不同场景、人物、路径和数值，未把正确答案直接给模型；三次没有复制示例值。D 是枚举整体对照，不能单独归因于源路径 enum。D/E 在长度固定为一拍时的合法输出集合等价；这不等于验证多拍 prefixItems 的全部行为。

## 基础组具体返回了什么

| 字段 | A 首轮实际值 | B 首轮实际值 |
|---|---|---|
| subject | 甲 | C01 |
| 事件来源 | script.beats[B1].event | script.beats.0.event |
| 事件关系 | 放杯事件结束后观察甲两秒 | after |
| 对白来源 | script.beats[B1].dialogue[0] | script.beats.0.dialogue.0.text |
| 对白关系 | 乙说这句对白期间观察甲两秒 | during |

A 第二轮仍用名字、另一种路径表示和中文关系。第三轮已正确返回 after/during，但仍用“甲”、script.beats[0].event 和 script.beats[0].dialogue[0]，后者缺少 .text，未符合本地规范路径。

A 收到的基础 Schema 把 subject、stimulus_source、relation 规定为非空字符串，没有规定必须用人物编号、点号路径和英语关系词。B 明确补上这些表示约定后，三个样本都通过。这个差别说明业务字段不能只靠名字和 string 类型让模型推测。

## 响应与故障分类证据

18 次均返回 MiniMax-M3、finish_reason=tool_calls、恰好一个 submit_creative_json；完整安全响应 envelope 的 content、reasoning_content 均为 null。工具原 arguments 与 response_text、解析后的 output 完全一致，usage 与元数据一致，18 个 response ID 均唯一。输出使用 191–227 completion tokens，未触及 1024 上限。

三次 A 归为 rule_rejected，其余十五次为 probe_contract_valid。没有缺工具、截断、类型错误或结果未知。Schema 合法与业务合同合法分别记录，不能把 A 的格式正确写成业务通过。历史回执与模拟服务的故障分流继续由离线测试覆盖，本轮正常返回不能代替异常分支验收。

这些观测只能证明本轮未返回分析正文或 reasoning_content，不能证明服务内部没有推理，也不能确定历史长分析耗尽输出的服务端原因。历史故障未在本轮复现，根因仍未知。

## 可以采用的结论与限制

1. 已验证：小任务中，明确人物编号、规范源路径、关系词及映射后，模型能够遵守；“目前模型不能识别任何这些规则”的判断不成立。
2. 已验证：基础类型不足以表达业务约定。本地验收需要把格式错误与规则错误分开，并在请求内明确规范表示。
3. 本轮未观察到：示例、枚举、prefixItems、if/then 相比 B 带来额外成功率收益，或使这个小任务变差。每组仅三个样本，不能估计长期稳定性。
4. 尚未验证：服务是否做硬约束解码；复杂关键字是否被执行、仅当提示阅读或部分忽略。F 的正确答案本就满足条件，正例通过不等于证明条件被强制执行。
5. 尚未验证：五拍以上、跨拍状态、完整故事因果和逐拍表演的真实稳定性。先前 call23/24 的全文请求失败仍保留，不能用本轮通过覆盖它们，也不能直接把旧失败归因于 prefixItems 或 if/then。

官网说明支持 tools/tool_choice，但本次阅读的公开文档没有找到 strict、prefixItems、if/then 对 MiniMax-M3 的硬约束保证；没有找到保证并不证明服务不支持。来源：[MiniMax OpenAI 兼容调用](https://platform.minimax.io/docs/api-reference/text-openai-api)、[Anthropic 兼容调用](https://platform.minimax.io/docs/api-reference/text-anthropic-api)。实验实际请求已冻结，未增加未经确认的 strict 参数。

下一步设计应优先保持整片规划、局部表演、确定性编译的分工：生成端采用简短明确的字段合同，复杂状态与时序关系继续由本地验证/编译负责。若内容或合同不合格，仍由生成模型提交完整新稿并全文复审；不要手动拼接或用转换包装采用旧稿。本轮没有把实验结果直接替换进旧生产任务，也没有注册新治理包。

后续真实创作验证宜按单拍、相邻两拍、整片逐级扩大输入，以定位复杂度变化的触发点。此为后续建议，本次新增调用授权已全部使用，尚未执行这些新调用。

## 代码、离线验证与历史保护

- scripts/prepare_minimax_rule_probe.py：生成不可变六组请求、独立规则验收和离线样例；没有网络调用。
- scripts/run_minimax_rule_probe.py：18 个不同样本键顺序派发，先保存 pending 与预留再调用；已有样本返回原回执，未知结果阻止新派发；没有自动重试或修稿。
- creative_workflow_roles.py：RoleResult 增加可选安全 response_payload，成功响应也能保存 content/reasoning/tool arguments/usage；请求体和模型分工未改，不含密钥或请求头。
- 相关离线回归 581 项通过，网络模型调用 0。覆盖缺工具、截断、类型、未知结果、18 次上限、原预算承接、重复样本阻止派发，以及跨拍状态/对白窗口/下游失效等已有合同。

父任务 87 文件逐 SHA 完全一致；v17/v23 冻结清单分别 47/55 个产物无变化。旧 call22–24、原授权、状态及旧诊断账本哈希均一致。新实验四个源码文件与派发快照一致，未在三轮之间更改规则或验收。独立只读代理复核与主验收相符。

## 实际授权与预算

用户明确回复“允许新增最多18次，完成三轮对比”。新授权将共享累计调用上限从 24 提高至 42，仅用于本规则实验；原 500000 总 token 上限不变。

| 项目 | 实际值 |
|---|---:|
| 本轮新增调用 | 18/18（全局序号 25–42） |
| 本轮 reported tokens | 19317 |
| 共享累计调用 | 42/42 |
| 共享累计 reported tokens | 398343/500000 |
| 剩余调用 | 0 |
| 剩余 token | 101657 |
| 未知预留 | 0 |

父冻结 state 仍是 21/24、354328 tokens；原诊断记录仍是累计 24/24、379026 tokens。它们是原时间点记录，不能从任意单个旧文件计算当前剩余预算。当前实际累计应读取本实验 RESULT.json，并核对它承接的原证据。没有重置账本、自动迁移、扩大 token 上限、视频/图片生成或发布。

## 产物入口

- [三轮机器汇总](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/rule_probe_matrix_v3/RESULT.json)
- [实际授权](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/rule_probe_matrix_v3/AUTHORIZATION.json)与[调用账本](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/rule_probe_matrix_v3/CALL_LEDGER.json)
- [冻结六组请求](../data/qa/minimax_rule_probe_20261003/matrix_v3/TEST_PLAN.json)。其 prepared_pending_new_call_budget 状态记录准备时事实；实际执行授权在上述独立 AUTHORIZATION.json 内，未回写准备记录。
- [逐回执验收与冻结保护](../data/qa/minimax_rule_probe_20261003/matrix_v3/VERIFICATION.json)
- [581 项回归范围](../data/qa/minimax_rule_probe_20261003/matrix_v3/REGRESSION_RESULT.json)与[原始输出](../data/qa/minimax_rule_probe_20261003/matrix_v3/REGRESSION.txt)
- 原始回执目录中 call_025_r1_A.json 至 call_042_r3_B.json 保存每次完整请求、原始安全响应、用量和分层校验；source_at_dispatch 保存派发时源码。
