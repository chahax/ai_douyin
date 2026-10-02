# 创作计划证据核对与最小修复（2026-10-03）

本轮完成代码核对、问题分类、最小修复与离线验证。工作目录以 v23 为基线，新增的是**未注册生产治理版本的离线修订**，不代表 v23 冻结包被更新或生产质量已通过。没有新增模型、图片、视频或发布调用；没有制作新的正式剧本。

用户本轮要解决的是可复用创作流程的可靠分工。完整作品仍须交付完整可制作剧本、导演安排、实际资产和后续媒体，不能以本报告、模型中间稿或测试统计代替。

## 旧任务与证据边界

任务：`data/production_trials/boundary_live_action_reference_v15_20261001/round_01`。

原 `state.json` 仍为 `needs_attention`，绑定 `20261001_v17_history_usage`：21/24 次调用，354328 reported tokens，内容返修4/5轮，契约修复7/8次。剩余3次调用；原回执估计完整新计划、计划复审、资产设计、联合复核至少4次，尚不足完成文本交付。本轮未重算为新增额度，reported tokens 不等于已核实费用。

[原生产复盘](../data/production_trials/boundary_live_action_reference_v15_20261001/round_01/AUTHORIZED_CONTINUATION_REVIEW_24.md)及[原调用汇总](../data/production_trials/boundary_live_action_reference_v15_20261001/round_01/AUTHORIZED_CONTINUATION_RESULT_24.json)均保留。原 `PRODUCTION_SCREENPLAY.md` 仍是中间稿，正式 `SCREENPLAY`、`STATE_PLAN`、`MEDIA_HANDOFF` 未完成。

本轮读取旧目录前记录全部87个文件哈希，结束再次核对：[冻结目录核对](../data/qa/creative_plan_repair_20261002/frozen_run_verification.json)。没有新增、删除或修改旧目录文件。v17、v23 治理包全部 manifest 产物哈希也保持一致。

## 分类：已验证原因与推断

| 分类 | 已验证的事实/原因 | 证据 | 尚未验证的判断 |
|---|---|---|---|
| 生成 | 第18、21次均 `finish_reason=length`，各消耗20000 completion tokens，没有完整计划 JSON；正文为长分析。第19次产出了完整工具JSON，但计划无效 | 两次原始响应、metadata、调用汇总；[离线重放](../data/qa/creative_plan_repair_20261002/after.json)核对4次原回执哈希 | 不能断言低温、上下文长度或整片计划负担就是原因；缩小上下文曾产出JSON，也再次发生length，没有隔离对照 |
| 接口 | 本地HTTP模拟已验证 thinking disabled、指定工具、schema、输出上限会被SDK序列化；`thinking_mode`仅记录请求意图。第18、21次供应商未返回工具调用 | 原 `MODEL_OUTPUT_PROTOCOL_DIAGNOSTIC.json`；`creative_workflow_roles.py` | 服务端是否执行 thinking 参数、兼容端问题或模型在正文中继续分析，均未知。未换接口、采样参数或模型 |
| 状态契约 | 第19次杯子P04的 holder=C02、location为桌中央，却要求C01 place；执行者C01没有先合法取得它，owner归属不能代替持有。动作组声明结束才生效，但旧投影允许同组串行take/place并净化中间变化 | 原第20次修复的 `error`；本轮无调用重放；新增边界测试修复前可复现 | owner/holder是否是模型错误的唯一心理原因不可证明；自然语言与状态一致仍需全文审查 |
| 编译 | 历史B2动作/hold占10.5秒，最低对白2.4秒，拍长11秒，差1.9秒；另一次B1动作占14秒，再加3秒对白，差3秒。原编译器正确拒绝，没有证据证明它“少算可用时间”。第19次B2—B4硬时长已收敛 | `history/failed_plan_v15_20261001/*contract_repair*.json`；原 `BOUNDED_RETRY_CALL19.json`；离线共享预算重算 | 硬语速上限通过不证明自然节奏或反应力度。一拍一镜及串行动作/对白对表达的限制是协议能力问题，不能靠排时器改剧情 |
| 审查 | 第18—21次都在MiniMax生成/修复链；本轮尚无合格计划，未到DeepSeek计划审查。原第20次补丁kind/value为数组，且operations父字段与子字段重叠；当前v2已能拒绝这些类型错误 | 原4次调用、补丁原文；before/after重放；既有typed patch测试 | 本轮不能评价DeepSeek是否漏报，也不能把结构通过当成情绪通过。本文没有新增人工质量判定 |

补充发现两处可离线证实的实现问题：v2 schema 的动作 `performance`、对白 `dialogue_performance`、group ID、reaction 文本曾共用字符串对象，后一次说明覆盖前一次，实际原修复请求中也出现了说明串写；补丁工具生成schema时绑定了完整manifest，但合并时重新从旧计划推测schema，只枚举旧计划已有座椅，可能拒绝工具schema允许的真实场景元素。

这些问题能解释具体约束失真，不能据此证明它们导致了第18、21次长分析。

## 最小方案与已经落地的修复

1. **隔离字段schema。** 只在v2对动作与对白表演字段做独立复制；保留准确字段说明。未增加提示词段落，未改旧v1生成规则。
2. **动作组前提一致。** 新增 `check_group_operation_preconditions`：同组所有操作读组开始状态，独立变化在组结束提交；同一道具take/place链、同一视线双写等必须由模型拆组。编译器不替模型增加拿取、不推测holder、不删除剧情。不同人物、不同状态字段的并行动作仍可表达。排时回执保留具体检查路径。
3. **补丁沿用冻结输入schema。** 工具生成、实际合并、依赖重查都使用同一份manifest绑定schema，继续保留原模型补丁、源哈希与合并产物。完整编译及内容复审仍必须执行。
4. **内容返修采用完整新计划。** v2导演内容意见不再自动建立 `plan_patch_base`；模型提交完整新计划，整体采用并对全部拍复审。物理前提、切点、空间或排时错误同样要求完整计划重建；只有 `PLAN_SCHEMA_INVALID` 结构错误沿原预算走typed patch。旧v1历史补丁路径保留。源剧本如需内容修改，仍走已有完整新稿返修及全文复审入口。
5. **可重复只读审计。** 新增 [audit_creative_plan_offline.py](../scripts/audit_creative_plan_offline.py)，针对本次第18—21次回执，输出用量/哈希、失败重放、补丁重叠、共享时长及真实请求中的参考文本绑定。输出禁止落入旧run；不派发、不恢复run、不写内容批准。

改动源码：`creative_action_plan_v2.py`、`creative_plan_patch.py`、`creative_workflow.py`、`creative_segmented_director.py`。原源码快照和逐文件diff在 [QA目录](../data/qa/creative_plan_repair_20261002/)。新增 [边界测试](../tests/test_creative_plan_repair_boundaries.py)；治理集成测试改用独立测试包和源副本，不修改生产治理包或全局默认值。

## 整片规划、逐拍表演、结构编译的分工判断

现有合理部分是：锁定完整剧本 → MiniMax导演计划 → 程序插入原对白、排时、推导首尾 → DeepSeek全文审查 → 已核实交接。程序已经拥有排时、状态投影和提示编译，继续让它承担这些确定性工作，不能让它创造内容或证明审美。

问题是当前 `generate_reviewed_state_plan` 实际用一次整片调用同时决定全部镜头叙事、表演组、初态、空间前提和类型化操作；schema虽分字段，生成职责仍集中。现有逐拍分镜入口已保留完整未来正文和上一镜终态，但尚不能直接证明与整片动作计划合同兼容，也不能仅凭减少输出量保证创作质量。

建议后续使用**显式新协议**做以下分工；本轮不增加生产阶段或付费调用，也不把旧任务改绑：

| 责任 | 应输入/输出什么 | 不应替其他层决定什么 |
|---|---|---|
| 完整剧本/整片观察安排 | 主题、关系、观众感受、参考表达机制；完整因果故事与结尾。规划每个观察单元的新信息、观察对象、刺激、反应及切镜理由，允许一拍多镜和浮动总长 | 不把所有动作秒点和首尾状态重复生成多份，不为沿尾帧强制全片一个景别 |
| 逐拍表演调度 | 已锁全文、整片安排、当前拍、上一单元实际终态及未来动作前提；当前单元可见表演、动作来源、对白内表演和刺激后的反应窗口 | 不修改全文主题/对白，不提前执行后拍，不为修初态堆无作用动作 |
| 结构编译 | 原对白锁、动作组、状态、时长策略、实际资产ID；确定性输出状态、时间轴、prompt和字段来源 | 不猜自然语言动作、不自动补拿取/起身、不用压缩对白或新增尾部静止替代情绪反应 |
| DeepSeek全文审查 | 完整新稿、完整安排、编译时间轴与最终请求；对照刺激反应、物理状态、可读性和源要求 | 不因JSON/连续性正确宣称观众感受通过；涉及上游内容则退回完整新稿 |

当前协议明确不支持关键动作与对白同时发生。必须保留 `EXPRESSION_UNSUPPORTED` 边界，后续若增加并行需新的可验证表示与测试，不能偷改 `during` 语义。B3正文同时提到中近景和手部近景，当前一拍单连续镜头能否忠实呈现两者仍须导演判断，本文未伪判已解决。

时长可浮动应发生在完整新稿/新协议规划阶段。当前排时器仍尊重已冻结的每拍时长，不能擅自伸长旧计划或重写原稿。必要动作与自然对白放不进时，交给模型完整新稿返修或显式协议调整。

## 参考与资产：确认了什么

读取的是已有参考片及四课教学分析汇总 `data/reference_reviews/reusable_expression_20261001/EXPRESSION_REFERENCE.md`，没有重新抽帧、听看或ASR。

本轮直接检查真实 `request.messages`，确认初始分析、writer_script、完整writer_revise、最终导演计划都含R01参考正文及表达约束；参考正文哈希与 `materials.json.reference_adaptation` 冻结值一致。编剧请求还包含 `analysis.reference_use`。证明参考实际送入了模型，**不证明模型已有效学会这些机制或成片情绪达标**。详细路径、文本哈希和比对见 [after.json](../data/qa/creative_plan_repair_20261002/after.json)。

当前旧任务未产生画风样板或人物/场景图片；导演计划尚未通过，也未进入资产设计和联合复核。现有 `director_production_design` 收到的是asset_catalog、script和storyboard，不能把目录存在或文本资产建议解释成“已选图片回传导演”。

后续流程应在少量样板确定审美后冻结实际选图ID、文件/服务来源及哈希；把选定图片与相应可见空间证据回传导演，完整调整安排并复审。此链还需要实际回执验证。本轮没有新增图片调用、观看或批准任何视频。

## 离线验证与生产边界

- 修改前既有目标回归74项通过。新增前7个用例失败复现：schema说明串写、同组状态串行、manifest schema未传入合并，以及内容新稿被误当补丁。另一个检查“新增检查回执”属于输出契约断言，不计独立生产缺陷。
- 修复后新增边界测试10项通过，覆盖完整新计划采用、物理错误完整重建、结构补丁、manifest合并与完整复审上下文；审查夹具明确为离线假服务，不能计生产质量批准。
- 首次扩展回归413项通过、15项被冻结v23源码哈希保护阻断。隔离测试包后重新运行，最终447项通过、0项失败，结果见 [final_regression_tests.txt](../data/qa/creative_plan_repair_20261002/final_regression_tests.txt)。没有通过改写生产manifest或屏蔽生产验证获得通过。
- 原第19次仍因真实持物错误拒绝，第20次仍因错误类型和重叠补丁不可采用。不存在“离线修复出一份合格生产稿”的交付。
- [生产绑定门禁](../data/qa/creative_plan_repair_20261002/production_binding_gate.json)验证：v17和v23冻结产物均完整，当前源码与其冻结绑定不符，新增派发应停止。全局默认仍为v23，没有创建/激活新生产治理包，没有迁移任何任务。

本次可离线修复已完成。生产前仍须明确版本登记/原环境恢复边界，携带原任务预算与历史；随后在允许的授权与足够剩余额度内隔离验证MiniMax输出协议，再验证新的创作分工。不能继续把提高token上限、堆提示词、离线通过或临时测试包解释为真实创作质量通过。

所有新视频仍只核对接口与文件完整保存，记 `awaiting_human_review`，待用户明确批准原片和服务原始尾帧才续段。该要求与本轮文本离线验证分别记录。

## 复现入口

从仓库根执行；以下只读旧任务并在独立QA目录写报告：

```powershell
.\.venv\Scripts\python.exe scripts/audit_creative_plan_offline.py `
  data/production_trials/boundary_live_action_reference_v15_20261001/round_01 `
  --output data/qa/creative_plan_repair_20261002/replay.json
```

最终回归的完整文件清单、退出码、源码哈希和冻结目录核对见QA目录的 `verification_summary.json`。测试用临时治理包仅服务假客户端测试，不能用于真实任务恢复或发布。
