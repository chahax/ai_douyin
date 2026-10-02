# 整片、表演与编译分工：真实试跑及未通过项（2026-10-03）

本轮已执行真实生产文本接口测试。**没有得到可采用的整片导演计划、逐镜表演或制作交接，最新完整剧本也未完成有效全文复审，不构成创作质量通过。** 下述完整模型稿、回执与离线案例都是诊断证据，不能当最终作品交付。

## 授权、预算及历史

用户本轮明确“行minmax额度直接使用不用申请”。新增MiniMax文本调用不逐次询问；保留MiniMax-M3创作、DeepSeek文本审查分工，累计承接原500000 total reported tokens上限。未授权媒体或发布，本轮均为0次。

规则矩阵结束时是42次、398343 tokens。本轮新增7次文本调用，其中MiniMax 4次、DeepSeek 3次，新增92570 tokens；共享累计**49次、490913 / 500000 tokens，剩9087，未知用量预留0**。金额、真实账单及降本收益未验证。16次批次上限是助手执行保护，不是用户新指定额度，不能用它扩展总token上限。

[新授权与继承预算](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/AUTHORIZATION.json)、[累计账本](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/CALL_LEDGER.json)、[当前回执汇总](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/RESULT.json)、[阶段停止记录](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/TEXT_STAGE_STOP_v1.json)。

旧父任务仍绑定v17、needs_attention，冻结state保留21/24及354328的历史值；原24次诊断、18次规则矩阵、v17/v23包和原源码快照均保留。不得从旧父state重新领取调用。[哈希与实际参考输入核对](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/FROZEN_EVIDENCE_VERIFICATION.json)验证全部7个实际请求完整包含原reference_pack，未截参考全文。资产输入只有静态定义，未选定真实图片，不能说实际图片已经回传导演。

## 已验证原因与推断分开

|类别|已验证证据|尚不能下结论|
|---|---|---|
|生成|43、45旧槽位稿在首句拒绝后再次写“说出拒绝”；45重复生成总长而合计不符。46/48线性合同解决重复排时表示及总长计算，但48仍有持笔、纸堆落点和“说着”的语义缺口。|不能由格式通过推导模型已掌握情绪、因果和全部物理状态；14拍或135秒本身不是错误。|
|接口|4次MiniMax均正常tool_calls返回，没有复现长分析；49 DeepSeek finish_reason=length，被明确分到RESPONSE_TRUNCATED/interface，原始32296字符正文及17941用量保存，无自动重发。|MiniMax历史长分析服务端原因仍未知。这些改变输入和合同的新测试不证明历史故障已修复。DeepSeek本次截断是不同故障。|
|状态契约|本地Schema及业务校验分别验收；boxed数组、中文代替路径等会拒绝。pending先记账、未知结果不重派、同键不再派发、回执与源码变动阻断。|工具Schema不是服务强制解码证明；本地只能拒绝错误结果，不能保证模型一定生成正确稿。|
|编译|旧合同“一叙事拍一镜”限制不适合实际多观察对象；45强拆出14拍且时长失配。事件摘要不能代替多个实际动作。v2桥接在已知不支持复杂steps时明确拒绝。|不能把多镜离线夹具或v3源引用投影当成生产状态编译通过。|
|审查|44缺本拍资产证据被挡住。47有真实摘要/正文不符，也有跨拍因果与空间风险误判。49除截断外，原始正文已出现9条数组证据引用。旧v6只在分镜阶段强制前后来源，剧本阶段缺该本地保障。|不能把零issues、partial story_preserved=true或程序证据校验当最终创作质量通过；图片和视频仍需用户审核。|

### 47审查意见的独立复核

- I01成立：B1只明确一次过去帮忙，B5“今晚又”是本次请求；B3实际便签只有任务短词，不能清楚证明过去多次替林屿加班。摘要称不同日期，实际steps无日期。
- I02部分成立：steps明确先目光和包带收紧、后请求，顺序不是未知，可表现预期压力；event/trigger却把它称为本次请求间的反应，摘要及实际步骤需一致。
- I03主要指控有反证：B7拒绝紧接B8停笔，B8 trigger已绑定拒绝；审查自身continuity也认可这一承接。无需为了过审增加解释性旁白或把反应强塞回同拍。
- I04未证实：正文已有从方澄桌边走到自己身后贴墙抽屉柜的动作，未发现与E03在林屿工位后方的明确冲突。“可能空间混乱”不足以列必修。

这些意见未手工从47删除。48由MiniMax根据有证据的问题和上述区分提交完整新稿，未拼接旧稿。

### 48的新问题及49的边界

48确实新增日期、加班对白和请求后反应，重复台词排时已改善；但同时引入：
1. B1对白后的action仍写“林屿说着”，与steps严格先后协议不一致，所需同时表演尚未表达。
2. B1签字笔明确搁在表上，B8又写成林屿手里的笔，缺恢复持有依据。不能由此发明“必须放笔”禁令。
3. B1将纸堆“递到方澄手边”，未交代是否接下及落点；B2方澄回工位、B14又从她手边挪回，纸堆所在桌面未锁清。

这些需要模型完整返修及全文复审，不能让局部模型补拿笔、搬纸掩盖正文缺口。49截断原文的B13对白检查引用script.beats.12.dialogue并给quote=[]，目标是数组，同类共9条，独立违反叶子证据合同；完整覆盖仅到B12，B13被截断、B14未完成。即使补齐JSON尾巴也不能直接采用。原响应未补括号、抽取半段或沿用开头true。

## 实际调用

输入 / 输出 / reported total，保留原服务回执：

|调用|模型|tokens|结束|实际结果|
|---|---|---|---|---|
|43|MiniMax-M3|7846 / 1599 / 9445|tool_calls|完整5拍新稿格式通过；实际重复说话与多镜编译缺口仍在。|
|44|deepseek-flash|7385 / 5499 / 12884|stop|审查证据合同失败：assets只引用全局资产；同时漏报重复说话。|
|45|MiniMax-M3|7819 / 2597 / 10416|tool_calls|完整14拍返修被拒：声明68秒、逐拍合计126秒，仍有重复说话。|
|46|MiniMax-M3|8583 / 3319 / 11902|tool_calls|线性steps新稿格式通过；14拍122秒，需全文审查。|
|47|deepseek-flash|9290 / 9134 / 18424|stop|完整84项审查通过证据合同，判4条问题；独立核对为2条成立或部分成立、2条未证实。|
|48|MiniMax-M3|8087 / 3471 / 11558|tool_calls|按证据重新生成完整14拍135秒新稿；有新的持笔与纸堆状态缺口，尚未采用。|
|49|deepseek-flash|6940 / 11001 / 17941|length|全文复审length截断；原文保留，接口拒绝，partial true不采用。|

所有请求固定temperature=0.4、thinking=disabled，MiniMax完整稿输出上限4096。49审查输出上限11000，服务reported completion为11001；不能据这1个token差异判定SDK或服务原因。49实际prompt降到6940，输出仍截断，说明只压输入不能解决反复输出84项覆盖及引用的增长。

[43完整稿](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/call_043_draft_v1.json)、[45失败整稿](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/call_045_draft_v2.json)、[46线性整稿](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/call_046_linear_draft_v3.json)、[47全文审查](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/call_047_linear_script_review_v4.json)、[48最新完整稿](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/call_048_linear_draft_v5.json)、[49原始截断审查](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/call_049_linear_script_review_v6.json)。

## 已落实的最小分工

|模块|负责什么|不能代替什么|
|---|---|---|
|整片创作与方向|完整故事、情绪弧、因果、结尾；叙事拍按意义组织，可含多镜。|不能同时强迫每拍等于一镜，不能让摘要代替实际步骤。|
|线性正文与局部表演|正文steps按实际顺序；导演只分配原步骤与观察对象；局部组绑定action_ref，对白引用原句。|不能修改原台词、删除必要画面，或补无来源动作修正文状态。|
|确定性编译|根据原对白位置派生slot、计算总长、检查状态前提与跨镜窗口、回读实际调度。|不决定情绪质量，不将未实现的物理绑定写成通过。|
|全文审查|复核全部实际正文及最终执行计划，逐项提供真实证据；有问题由生成模型完整新稿返修。|不能猜测禁令、靠手工删issue放行或把片段审查拼成最终通过。|

- [线性合同脚本](../scripts/creative_linear_script_v2.py)：模型仅填写每拍秒数及有序action/dialogue steps；总长程序求和。兼容槽位只是原步骤的确定性投影，Markdown保持原顺序，不增删动作或对白。
- [简化工具导出](../src/content_factory/creative_modular_tool_export.py)：中文字段关系＋普通数组/简单枚举，核心业务约束留本地校验，减少对复杂工具Schema关键字的依赖。
- [多镜v2原型](../scripts/modular_shot_bridge_v2.py)：2拍4镜夹具通过真实v2调度，跨镜反应窗口3—5秒及9—11秒。只支持完整原子事件、完整对白、独立hold，复杂steps在构建工具前返回BRIDGE_UNSUPPORTED。
- [步骤引用v3合同](../scripts/modular_step_shot_contract_v3.py)：原action→dialogue→反应action→action跨两镜保持原文和顺序；每步恰好覆盖一次，导演不能改text/speaker。状态为source_order_valid_pending_physical_binding，物理、动作语义、反应时长、production_ready均false。
- [剧本前后来源候选v7门禁](../scripts/creative_script_review_sources_v7.py)：先运行原v6，再要求非首拍continuity同时引用本拍和前拍真实正文叶子。覆盖乱序按实际script顺序判断，首拍及joint行为保持；未改旧验证器、注册表或追改旧回执，未接旧生产任务。它只保证来源齐备，不能证明持笔等语义状态正确。
- [48与导演合同实际兼容核对](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/DIRECTOR_COMPATIBILITY_v5.json)：29个实际源步骤可建立v3引用目录，旧event-owner编译不能承接；未盲发付费导演计划。

源改变使绑定该源的方向与全部局部输入失效；局部改变后，其后编译首态需重算，原已验证前缀只在实际消费输入不变时可复用。v3目前证明源覆盖与顺序，尚未实现物理首态及完整的逐镜后缀重算。已有旧模块合同覆盖这些失效边界，不能混淆成新v3已全部接线。

## 离线验证与实际产物

[本轮最终回归](../data/qa/modular_bd_probe_20261003/final_with_script_sources_v7/REGRESSION.txt)：13个相关测试文件共**183项通过**，网络调用0。覆盖故障分流、预算继承、未知结果阻断、同键不重派、完整替换、防篡改、原顺序、跨镜状态和窗口、下游失效、原证据审核门禁。

[2拍4镜编译夹具](../data/qa/modular_shot_bridge_v2_20261003_final/compiled.json)、[单拍两镜源步骤投影](../data/qa/modular_step_shot_contract_v3_20261003/source_projection.json)只属离线案例；未拿旧失败稿转换来冒充新交付。历史581项回归及18次规则对比仍是各自历史验收，不替代本轮真实整片质量。

候选门禁另与原v6及ID规则定向回归18项通过。独立产物：[v7门禁清单](../data/qa/modular_bd_probe_20261003/offline_script_review_sources_v7/GATE_MANIFEST.json)、[47证据ID离线回放](../data/qa/modular_bd_probe_20261003/offline_script_review_sources_v7/ID_REPLAY_47_QA.json)、[49截断及正文诊断](../data/qa/modular_bd_probe_20261003/offline_script_review_sources_v7/RESPONSE_49_DIAGNOSTIC_QA.json)。47在原v6下的历史有效/false仍保留，候选v7缺前拍来源的另行判断未追改历史状态。

冻结派发后不改原driver、adapter或核心src。新增操作器另存源码、哈希与不可变绑定，真实请求引用它们。全文审查请求省去重复screenplay_markdown，保留实际全部动作、对白与参考；49的wrapper只以SHA引用完整provenance，服务messages和参数未变，未降低输出上限或验收合同。

## 下一项最小修改

先补审查源引用及跨拍状态保障，再优化证据传输，不继续堆提示词。剧本前后来源候选v7已离线完成；真正的持物、位置和动作前提仍需步骤绑定的状态编译。

已有evidence_ids_v1也完成47有效回执的纯离线模拟：68条引用映射及机械展开后原v6复验通过，14拍84项和I01—I04、false、reason/status全部保持；48/49的新上下文拒绝旧ID。compact UTF8输出24785→19882字节（约19.8%下降），但198项目录使输入prompt增加12553字符、19105 UTF8字节，展开输出31883字节。**ID没有证明净降本，也不是实际模型ID调用通过**。下一传输优化须同时核对完整输入目录及输出预算，不能只看输出缩短；实际错误、遗漏或截断仍由完整验收拒绝。

随后补v3到现有物理编译器的适配：程序依据每镜原对白位置派生script_slot；生成模型按action_ref提交有来源的typed operations；编译器核对动作前提和状态，并回读真实排程证明原steps顺序不变。无法表达的并行必须明确合同处理，不能把“说着”偷偷排成对白后。

先完成这两处合同验证、再修48的真实正文缺口并全文复审；只有有效整稿、全片方向、逐镜物理表演和全文联合审查都完成，才登记制作交接。旧治理任务继续保持原绑定。MiniMax新增文本无需逐次申请，未来派发仍核对原累计token限制及未知/失败响应；本轮不扩大500000总token上限。
