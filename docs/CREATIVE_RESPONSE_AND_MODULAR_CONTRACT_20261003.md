# 响应验收与模块创作合同（2026-10-03）

本轮按用户批准执行两步：调整响应验收与故障分类；设计“整片规划 → 局部表演 → 确定性编译”合同，并离线验证。没有真实模型、图片、视频或发布调用，没有迁移任务、重置预算或注册生产治理版本。工作目录是v23基线上的未注册修订。本文和编译样例是工程材料，不是正式剧本或制作交付。

## 响应验收与故障分流

新增 creative_response_contract.py，主阶段、结构修复和格式修复共同使用。验收顺序为：截断/结束状态 → 模型与工具协议 → 非空输出 → 结构/类型 → 状态/排时 → 全文审查。缺工具正文即使含完整JSON，也不作为正式结构结果。

客户端保存失败响应正文、reasoning_content（若服务返回）、工具名/参数、结束原因、模型、响应ID及可用usage；不保存认证头或API异常请求正文。

| 代码/问题 | 分类与下一步 | 自动再派发 |
|---|---|---|
| RESPONSE_TRUNCATED | 接口，diagnose_output_protocol | 否 |
| REQUIRED_TOOL_MISSING / UNEXPECTED_TOOL_CALL | 接口，diagnose_output_protocol | 否 |
| EMPTY_RESPONSE / NO_RESPONSE_CHOICES / MODEL_MISMATCH / RESPONSE_NOT_COMPLETED | 接口，diagnose_output_protocol | 否 |
| OUTCOME_UNKNOWN，包括pending、无ID连接失败、529无ID | 接口/对账，reconcile_original_request；缺ID不等于没收到请求 | 否 |
| PLAN_SCHEMA_INVALID | 状态契约/类型，原共享预算内typed修复后全文校验 | 原有有界修复，非运输重试 |
| 物理、空间、切点错误 | 状态契约，模型完整新计划、编译和复审 | 原有预算约束 |
| 表达不支持、排时冲突 | 编译/表达合同，核对能力或完整新计划 | 不由本地补动作或压缩反应 |
| 其他validator错误 | 保守标记validation，保留原有有界修复 | 未声称完成全部旧校验器细分 |

主阶段、结构修复和格式修复不再自动重派截断、缺工具、空正文及未知结果。恢复同一阶段会再次停止。旧 --retry-unconfirmed-transport 参数保留解析兼容，不能放行未知结果；CLI帮助已更新。本轮没有实现诊断完成后的专用重试操作，不能删回执绕过。

另修复结构修复命名问题：旧代码先比较repair_protocol、后确定实际协议，可能换一个hash文件名再调用。现在先核对同源未决请求；身份初筛不使用尚未确定的repair_protocol，成功修复也能复用。

已有response_id继续用于usage去重；新失败响应无ID时使用本任务call_ordinal，避免阶段回执与失败usage回执计两次。calls_started、预留、修复次数、返修次数和token上限不重置，不补失败额度，不把未知费用写成0。

## 模块合同：显式离线版本

实现：creative_modular_contract.py。协议名 modular_direction_performance_offline_v1，未接生产运行器、未改变默认分镜协议；这是可执行合同与编译适配器，不是已验证的多次模型链。

context包含完整已锁剧本、static_visual_manifest、参考全文和选定资产引用。整份context哈希绑定输入，当前拍不能脱离全文与未来因果。

| 层 | 拥有字段 | 不重复拥有 |
|---|---|---|
| whole_film_direction_offline_v1 | 全片情绪走向、因果链、结尾意图；每拍目的、新信息、观察对象、刺激、观众感受、构图、摄影、切镜理由、表演要求；一次性初态和空间前提 | 局部动作组、每动作秒点、派生首尾态 |
| local_performance_offline_v1 | 当前拍动作组、对白伴随表演、反应锚、源事件锚、表演窗口映射、局部时长和唯一切点 | 原对白、整片purpose/camera、initial_state、start_state、end_state |
| 确定性编译 | 前提校验、跨拍状态、时间轴、原对白窗口、制作提示与来源身份 | 新剧情、补拿取/起身、审美判定 |
| 后续DeepSeek全文审查 | 完整新稿/计划、全部局部安排、编译结果、实际参考与资产 | 不能把结构与时间通过当成创作质量通过 |

build_local_input只读编译已有前缀，提供完整context/direction、当前拍ID、后续拍ID、程序推导start_state及前缀编译身份。局部输出必须回带该输入hash，不能自行改状态或对白；未来方向、参考、资产变化同样使hash变化。

compile_complete要求全片覆盖、顺序一致，并逐次从原输入编译前缀。局部duration_seconds仅改变派生timing_script，原对象不回填。该浮动时长规则只属于新离线协议，不允许擅自伸长旧冻结计划。

## 表演窗口与失效范围

整片层为每项重要表演填写唯一ID、观察人物、刺激来源（本拍event或具体对白文本路径）、before/during/after关系和最低秒数；局部层绑定真实动作/保持组或dialogue_N。

程序检查每项要求恰好覆盖一次、来源与锚有效、before结束不晚于刺激开始、during绑定实际对白、after开始不早于刺激结束、窗口达到最低时长、保持人物匹配。匿名镜尾余量不能替代显式反应窗口。动作仍接受v2的持物、位置、朝向和组开始前提检查。

时间正确不证明表情可读或感染力。结果保留face_readability=requires_full_semantic_review及semantic_approval=false。

| 变化 | 可复用 | 必须失效 |
|---|---|---|
| 剧本、参考、选图、整片direction或初态 | 原历史 | 全部局部输入、编译、完整计划审查、交接、媒体预览 |
| 第N拍局部变化，包括只改文字/状态不变 | N之前局部前缀 | N及以后输入与编译、完整审查、交接和预览 |
| 编译器变化 | direction和原历史 | 前缀编译证明、局部输入、完整编译/审查/交接/预览 |

invalidation_scope只返回范围，不写旧状态，不删视频或人工决定，不重置预算。正式内容返修仍需MiniMax提交完整新稿/完整新计划并全文复审；离线前缀拼装不能代替模型完整新稿。

## 验证产物与复现

QA目录：data/qa/creative_response_and_modules_20261003/。

- modular_fixture_input.json明确为fixture_only；参考句和资产ID/hash为模拟输入，不是实际选图或模型请求回执。
- offline_verification/direction_schema.json、local_schemas.json、local_inputs.json展示真实字段与绑定。
- compiled_fixture.json包含两拍编译、对白前中后窗口、跨拍持物状态与来源归属；仅测试样例。
- report.json包含五个拒绝案例、第18—21次真实回执分类、下游失效及既有参考实际请求证据。
- regression_final.txt、verification_summary.json记录回归、源码hash和冻结边界。

旧第18、21次仍归入接口截断，第19次持物前提拒绝，第20次数组类型错误及重叠补丁仍拒绝。分类输出独立保存，不改写旧回执。原任务仍为v17、needs_attention、21/24次、354328 reported tokens。

复现（零模型调用，仓库根运行）：

~~~powershell
.\.venv\Scripts\python.exe scripts/verify_creative_response_modules_offline.py --fixture data/qa/creative_response_and_modules_20261003/modular_fixture_input.json --evidence-run data/production_trials/boundary_live_action_reference_v15_20261001/round_01 --output data/qa/creative_response_and_modules_20261003/offline_verification
~~~

## 未解决及生产边界

1. MiniMax长分析的服务端根因仍未知。严格验收防止误采用与误重试，不能阻止首次生成消耗。
2. 适配器复用v2，仍是一拍一镜、关键动作与对白串行。明确并行要求返回EXPRESSION_UNSUPPORTED；多镜观察与并行表示需后续合同，不能靠删动作迁就。
3. 少量审美样板、真实选图、图片内容装载回传导演、模型多阶段生成和DeepSeek整体复审未生产验证。本轮只证明绑定和离线计算。
4. 分模块可能增加调用数，生产接入须测算全链及返修预算；旧任务只剩3次，本轮零调用不是补额度。
5. 未安装agent框架、未换模型。未来治理源码清单加入响应合同和角色客户端；本轮仅测试夹具使用，未创建或激活生产包。v17/v23源码门禁继续阻止不匹配派发。
6. 视频由用户人工审核；接口成功与完整保存只记awaiting_human_review，未批准原片和服务原始尾帧不能续段。

回归通过不表示创作质量通过，本文不替代完整作品交付。
