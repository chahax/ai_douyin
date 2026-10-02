# 修复后的真实文本接口测试（2026-10-03）

本次实际调用了生产配置中的 MiniMax-M3，共3次。微型工具请求通过；两次真实整片规划均以完整工具调用结束，但新合同验收失败。没有得到可采用的整片导演计划、逐拍表演或制作交接，不构成创作质量通过。

用户本次明确要求“之前的修复方案落实后生产接口测试”。调用消费原任务剩余3次，未扩额。MiniMax创作、DeepSeek审查的原分工保留；因上游规划不合格，本次没有派发局部表演或DeepSeek全文复审。没有图片、视频、发布或音画审查调用。

## 真实调用与验收

|共享调用序号|实际请求|input / completion / total tokens|服务结果|本地验收|
|---|---|---|---|---|
|22|微型指定工具，输出上限1024|455 / 43 / 498|MiniMax-M3，tool_calls|结构与类型通过，仅接口样例|
|23|完整五拍剧本、静态资产清单、R01参考全文的整片规划，输出上限8000|7143 / 4377 / 11520|MiniMax-M3，tool_calls|MODULE_REQUIREMENT_SOURCE：刺激来源填写中文描述，而非源字段路径|
|24|同一全文、提示词、模型、温度、thinking和8000上限，仅约束工具Schema中的逐拍来源路径及事件关系|8912 / 3768 / 12680|MiniMax-M3，tool_calls|MODULE_SCHEMA_INVALID：所有五拍performance_requirements把数组写成了含item键的对象；还存在event/during不兼容关系|

调用23与24的messages和parameters逐值相同。工具Schema是这次对照唯一主动修改的请求部分，输入tokens的变化来自Schema体积变化。调用24由模型重新提交完整新规划，未拼接调用23内容，未手动替换来源、展开item或回填动作。

两次复杂请求都未到8000输出上限，本轮没有复现历史length长分析。这个结果不能解释调用18/21为何输出长篇分析，更不能证明服务端严格兑现thinking disabled。当前thinking_mode记录请求意图，客户端只保留成功工具参数和元数据，成功响应的完整content/reasoning envelope未保存；没有服务端内部日志。本次与历史请求的任务职责、Schema、上下文和输出上限也不同，不能把未复现当成历史根因已经解决。

本次直接证明：当前同一MiniMax-M3入口可以完成微型及较大的工具请求；带工具Schema、指定tool_choice和正常tool_calls结束，仍可能产生类型与条件不合格的参数。当前客户端未发送strict:true，不得把Schema描述宣称为服务端强制解码保证。

## 有证据的问题分类

- 生成：调用24的初态文字仍混入正在执行或已经完成的首拍动作；杯子P04的持有人、桌面落点和端回动作主体不一致，P06同时写持有与仍在未抽出的文件叠中。文本与字段的矛盾可直接观察，是否忠实源剧情及表演仍需正式全文复审，不能以离线格式检查认定创作质量。
- 接口合同：调用23发出的stimulus_source只有非空字符串约束，未提供本地要求的源码路径，属于已验证的合同表达遗漏。调用24增加路径约束后引用已合法，但数组形状及条件仍违约；远端是否支持严格Schema解码、是否忽略某种关键字、是否存在特定兼容接口缺陷，都仍是推断。
- 状态契约：实际调用24虚构S01/S02/S03座椅ID。用原稿的初态与空间配置只读投影到既有座椅校验，得到PLAN_SEAT_ACCESS_INVALID、spatial_contract.seats.0。没有改写原稿，投影仅用于检查固定场景身份。
- 编译：未派发局部表演，也没有真实跨拍编译通过。已证实的座椅身份错误应在整片规划时拦截，不能等消耗局部生成额度后再发现。对白反应窗口与跨拍状态仍只有原离线样例证据。
- 审查：上游合同失败，未调用DeepSeek全文复审。格式通过、接口成功、测试统计均不是制作通过。旧任务仍为needs_attention。

## 本次代码和离线修复

1. 新增共享文本诊断总账和只读门禁。按父任务绝对路径统一账本，派发前写pending与22—24序号，使用共享锁；重复同一测试仅读取原回执。未知结果保留token预留并停止，SDK和流程都不自动重试。
2. 生产运行器在预算预留和最终派发前检查共享诊断消耗。存在任何预留就阻断仅凭冻结state继续调用，避免历史21/24被误读为仍有3次。
3. 把已测的逐拍源字段枚举及event关系约束接入核心build_direction_schema。核心发布的工具Schema与调用24实际Schema逐值相同，但该Schema尚未通过真实生产验收。保留本地原语义错误码，未加提示词补丁。
4. MODULE_*故障改归state_contract，要求生成模型提交完整新稿后全文复审，关闭自动重试；未将失败稿手工修为有效稿。调用23原历史故障分类保留，当前分类器的离线重放结果另存。
5. 整片规划验收新增固定座椅身份前置检查。只投影配置到已有确定性校验器，不产生动作、不修持物、位置或朝向、不更改原剧本。

测试时源码与追加Schema驱动已逐文件归档。真实请求全部完成后才接入核心并调整分类/座椅门禁，这次后续源码变化明确记录在verification.json。原诊断CALL_LEDGER.json的source_manifest未覆写；原诊断驱动在当前源码下会因绑定变更拒绝再派发。没有新注册或迁移旧v17/v23生产协议。

最终相关离线回归547项全部通过；py_compile与git diff --check通过。真实回执及失败稿逐SHA保留；离线通过只证明本地保护和合同检查，不证明生产创作质量。

## 预算与冻结保护

原父任务：
data/production_trials/boundary_live_action_reference_v15_20261001/round_01

原冻结state仍为21/24次、354328 reported tokens，needs_attention，绑定20261001_v17_history_usage。87个冻结文件逐SHA保持一致。

共享实际总计为24/24次、379026/500000 reported tokens。本次新增24698 tokens，未知预留0。token报告额度仍余120974，但调用额度为0，不能继续生产或审查。原内容返修4/5、合同修复7/8未重置。

原v17及现有v23的源码门禁仍拒绝当前源码；冻结治理artifact未改。新增诊断合同仅承担这三次显式文本接口测试，不代表旧任务恢复、当前生产版本注册或完整交接通过。

## 实际产物

- [真实回执及共享总账](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/CALL_LEDGER.json)
- [三次实际结果](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/RESULT.json)
- [最后一次原始请求与响应参数](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/call_024_direction_source_enum.json)
- [测试时完整源码摘要与归档位置](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/source_snapshot_manifest.json)
- [冻结核验、当前失败重放及生产门禁](../data/qa/creative_production_interface_20261003/verification.json)
- [最终相关离线回归](../data/qa/creative_production_interface_20261003/regression_after_seat_gate_result.json)

R01实际请求全文2259字符，文本SHA256为5f98e1122524a5d2ee4ef3f8849660a974c25c723e1e225a6804fd7ea9186479，与原冻结请求一致。磁盘原文2261字符，项目材料读取只去除首尾空白；两个哈希均保留。参考实际进入请求不等于模型已正确借鉴表达机制。

## 未解决与后续最小方向

当前整片规划无法进入局部表演；生产接口合同未通过。历史长分析服务端根因仍未知。逐拍表演、真实跨拍状态/对白反应编译、真实图片回传导演及DeepSeek全文复审未执行。

新模块应先收缩并明确机器合同边界：固定资产身份由清单约束，源字段引用由合同列出，状态与时间由编译器推导，生成模型承担完整叙事和表演草稿；返回类型仍由本地严格拒绝。复杂prefixItems/allOf在该服务上的严格支持没有得到证明，不宜以更长提示词或通用Agent框架替代这一验证。

后续真实验证需新的明确调用额度与新的显式生产合同绑定。本次未新增额度，未生成或交付可制作成片。
