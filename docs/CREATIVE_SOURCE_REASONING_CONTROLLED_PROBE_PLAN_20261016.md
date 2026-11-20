# 来源语义推理模式受控诊断：第29轮

685已完整返回，接口、严格工具JSON及逐字覆盖有效，但88单元均未拆分；请求/承诺可能被归入goal/state。两条未决来自程序对刺激/触发字段的temporal none守卫，不能将其说成服务端结果未知，也不能只删守卫就采用685。

本轮先保持来源语义合同不变，作一次独立真实接口对照。固定685原messages、structured_schema、service Schema、来源全文、模型DeepSeek-flash、temperature=.4和max_tokens=16000；仅thinking=enabled、tool_choice=auto。官方文档说明思考模式不支持required/named，temperature会忽略，所以这是兼容配置组合对照，不宣称单因果实验。reasoning与正文共享输出上限；截断直接保留并停止，不提上限重试。原685不改、不采用，不把诊断通过计创作质量。

官方来源：
- https://api-docs.deepseek.com/api/create-chat-completion/
- https://api-docs.deepseek.com/guides/thinking_mode/

实现分工：B新增固定selector与685已知结果消耗锚，复用strict5真实运输而不复制SDK发送；C新增仅一review的独立诊断协调器、预览/冻结/原生验收及原SDK/SQL证据；A独立诊断来源职责及模型分类失败。主agent审查真实wire、参数差异、失败分支和计数后执行一次。

旧strict v1、A4、WF8、C12及所有冻结源码保持字节不变。新selector通过新provenance和selection/effective-policy记录auto，不把旧shared client_configured静态named模板当实际请求；真实SDK序列化body为调用方式依据。仍只有一次POST、SDK retries=0、无redirect、无正文转工具、无补JSON。auto可能不产tool：按缺工具停止，不自动恢复。未知结果/用量、截断、重复工具或不合法合同均停止。

消耗承接：685累计685次/14896550 reported tokens/683已知，历史70/160与93117未知预留保留。原选中正文15一份+6review余额，正文16延后未用；本诊断最多用其中1review，结束剩1body15+5review。它不自动授权后续缺额，也不重领原685或684额度。一次视频AUTH未用，未达合格完整文本、导演与实际表演门之前不派发媒体。

验收分层：离线线参/未知/截断/缺工具/一次派发/原字节篡改拒绝 → 实际接口及用量 → 使用原A4合同核验原生输出 → 独立比较分解、施为、内容形式、时序未决。不得输出或依赖私有推理链解释；仅检查最终工具产物、推理token数（若服务提供）与原始响应完整性。诊断不能手改原生标签，也不能替代同源全文审查。

下一步由真实对照证据选择：若仍吞并义项，修改来源职责/直接证据审查设计；若显著改善，再新版本接线并作有界完整稿验证。两个选择均须先记录，不能同时更改来源分片而将效果归于thinking。
