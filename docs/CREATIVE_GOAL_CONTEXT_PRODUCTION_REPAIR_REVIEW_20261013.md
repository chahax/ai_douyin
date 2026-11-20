# 真实三份规划拒收与新合同修复

本轮按用户“生成新的、再次审核、不对继续修”运行了真实文本请求。531–533均由MiniMax-M3.1-Flash-Preview完整返回工具结果，HTTP200，结束和用量已知；没有生成完整正文。旧三份原生规划没有手改或拼接。

## 真实结果

| 调用 | 首次验收失败 | 此后全文检查确认的其他问题 |
|---|---|---|
|531|某拍漏strategy|三个人超出两人上限；手持道具support写成场景|
|532|非推断claim漏空basis_claim_refs数组|三个人；尚未形成的情况说明已有holder/support；手持support冲突|
|533|来源edge编号抄错一个字符|三个人；初态和承托关系冲突|

新增3次、74083 reported tokens；累计533次、10099695 reported tokens。历史未知70/160及93117预留继续保留。导演仍7/7；新媒体和发布均0。结果停在halt_goal_content_capacity_exhausted，不能把接口成功或失败计划视为可制作剧本。

字段缺失和错号有实际回执支持。内容初审另发现历史“个人原因、小林、人事”被重新放进通用目标，以及法律上下文夹带固定“先保留书面事实、核对性质”的角色策略；原生输出确实回到办理/留档路线。这个关联支持修正输入分类，但不能证明哪个字段单独导致内容平淡。

## 已完成的独立修复

- 平台来源使用21个短别名，Schema按真实目录枚举；目录保留原ID、实际path和对应内容。校验严格匹配，不纠正旧533错号。
- 用户目标使用已功能化text；8条历史source_quote原话、路径和SHA保留在本地manifest。法律6条facts、sources及所有适用条件完整保持；只把已识别的可选创作步骤移到本地，真实性底线继续进入请求。
- 两人上限进入characters.maxItems；非推断claim可省略空basis，推断必须提供有效前提。strategy、刺激、反应及场内变化保持必需。
- 道具原生声明presence_at_start；明确absent不得已有当前持有人和承托物，owner单独保留。全文审查追踪presence状态，不通过中文关键词猜道具存在。
- 一次汇总可确定的结构、引用、数量和状态问题。审查增加中心冲突检查，完整法律目录不要求逐条变成剧情争点。

新增goal_source_contract_v3、stage_context_v3、goal_context_workflow_v3、full_review_contract_v3。旧入口、冻结和账本不迁移。子agent实施了合同/上下文模块，主agent接线、补齐故障保护并审查；子agent后续独立复验受到模型容量错误影响，已如实保留，主agent完成本地验证。

## 实际请求预览与离线证据

目录：data/qa/goal_context_production_repair_20261013/request_preview_r1。

GOAL_PLAN_EXPECTED_WIRE.json是当前拟发送的实际接口参数；CONTEXT_MANIFEST.json记录输入取舍与原文；UNCHANGED_531_533_REPLAY.json记录旧原稿在新合同中的完整拒收诊断。REPAIR_INPUTS.json包含完整533原稿用于模型整版修订，不手填新字段。请求含R01完整2313字符一次，修订用户正文60969字符；这些字符数不是实际token测量，也不是质量证明。

16项合同、37项上下文、28项接线、43项全文审查回归通过，共124个独立离线用例。早期失败测试记录保留；最新证据为goal_contract_v3.xml、context_v3.xml、workflow_v3_r2.xml、review_v3_r3.xml。1164份旧冻结文件逐文件校验未变。新合同尚未得到真实完整新稿，不能写成生产或创作质量通过。

## 后续容量与恢复

本轮目标候选原3/3完整保留。给出最多追加1份的问题后，用户明确答复“minimax随便追加”，当前文本MiniMax追加不再逐次申请；这是新明确授权，不是改目录重领。新独立运行每阶段仍设3份安全上限，承接已用3份和累计533/10099695；DeepSeek保持少量必要审查，不新增导演、媒体或发布。授权见CREATIVE_MINIMAX_CONTINUING_AUTHORIZATION_20261013.md。

生产接线另发现法律上下文投影后审查SHA仍绑定原对象的问题，已在派发前修正为绑定审查真正收到的法律对象；所有事实和条件保持。共153个独立离线用例的最终分支通过。producer_v4.xml中旧6项失败保留，修正后的6项及新增准备继承测试见producer_v4_repaired_branches_r2.xml；其中两项测试误放SQL尾部断言又在producer_v4_approval_guards_r3.xml修正复验。actual_review_context_binding_r3.xml验证实际wire、Schema和验收对象相同。

round_03已准备，starting_spend=533/10099695、known531、历史未知70/160及93117预留不变；534完整规划已开始，暂未返回。不是已得到新剧本，后续结论需以本轮STATE和原始回执为准。

如果后续内容不满意，可恢复开发前v8、v9_r2或旧入口的独立副本；不覆盖账本、冻结回执、凭据和媒体，也不重派旧请求。

## round_03实际终止及审查引用修复

534/535为已知完整规划合同失败，分别为未存在道具的承托关系，以及缺少必需空数组。536原生规划首次通过结构验收；537 DeepSeek全25claim/7goal完整返回，但自由字段路径、非原文汇总引文及pass的非空返修字段被本地正确拒收。round_03状态halt_goal_audit_contract_requires_pipeline_diagnosis，4新调用118920 reported tokens；累计537/10218615、known535，70/160及93117历史未决保留。没有正文、导演或媒体通过。

具体修复见CREATIVE_GOAL_AUDIT_CITATION_REPAIR_PLAN_20261013.md：新增citation_contract_v1/workflow_v4/producer_v5，引用原文及路径由程序按当前原生SHA编译，模型选择实际短编号并提交判断；请求Schema直接约束pass返修空串。复用536需原始回执output完全一致、状态/模型/阶段已核实，每次guard复核。首次正文移除规划返修上下文，后续返修只传实际完整原生正文。完整规划审查明确检查跨拍离场/返回、材料来源、末拍与结尾一致和背景人物/声音，不只数characters表。

根因区别：535仍为服务未遵守数组约束，不能宣称服务端强制保障；537则有已验证的Schema与本地验收不对齐。修复不把旧正文/审查转换为通过。

### 538接口与语义漏判，以及分离审查接线

round_04新增538完整DeepSeek响应，用量28992已知；多出不存在的CC_PREMISE_DUP、两项引用超8，本地拒收。审查还把b07离场后b08继续说话/收物描述成无断裂，将背景推车人/人影当不计入完整人数。不能从删除多项和引用裁剪制造通过。累计538/10247607、known536；原6份规划、未知70/160和93117不变，正文/媒体0。

新workflow_v5/producer_v6按CREATIVE_SPLIT_GOAL_AUDIT_REPAIR_PLAN_20261013.md分开来源与戏剧审查；两份原生判定各自绑定上下文和同一规划SHA，均通过才进入正文。引用目录只传路径，完整原文仍在规划内，本地只编译证据元数据。实际536预览source约26785字符、drama约23941字符，原单审约5.6万字符；减少竞争是设计依据，未证明长上下文单独导致漏判。新运行先让MiniMax提交完整新规划，536只作返修原稿，诊断未提供替代台词动作。

workflow新增30个不同离线用例通过，独立复验48项通过；producer_v6的10项控制通过，独立关键2项通过。第一轮合成测试固定response_id造成7项失败，账本正确拒绝重复响应，fixture修为逐ordinal唯一后复验通过。独立adapter_v4按2个候选允许至多4次来源/戏剧审查，旧v3上限不改；旧冻结链/预算不重置，未知分支停止。round_05按原“minimax随便追加”授权进行0调用准备，实际状态后续以该目录STATE/原始回执为准。

13引用合同、15生产控制及6接线用例最终通过，共34个独立用例；最新新增criteria接线/控制20项通过。独立agent发现的536来源绑定缺口已修复并复验，最终实际prepare独立单测通过，0派发。早期系统Temp权限及并发编辑触发冻结失败的证据保持，不作为实现通过。生产前预览v3真实包含R01全文一次、完整法律/功能目标、536未改原生全文、准确G引用目录与7项功能检查标准。下一独立round_04承接537及6份规划，seed审查加至多两份完整规划内容修订，正文初稿加两轮完整返修；不是重领旧预算。

## round_05实际结果与新分工

539/540新增2次60761 reported tokens，HTTP200/tool_calls且用量已知。539拒收absent道具support={}；540拒收三条inference漏空origin_ids，同时原文仍把中段带入的结算单写为开场已持有。没有把旧全文补null或空数组转换成通过。round_05 terminal=halt_goal_content_capacity_exhausted；累计540/10308368、known538，8份完整规划，正文0。

问题分类：服务已完整返回，不是未知或截断；服务未强制schema仍是接口能力边界。重复所有权/持有/未来引入混淆是已知合同失败；把整片规划和所有开场物理状态放在同一对象，是有实际重复证据支持的分工问题。新静态规划与独立setup能否提升真实创作质量尚需新生产验证，不能从离线结果推断。

详见CREATIVE_PLAN_SETUP_SEPARATION_PLAN_20261013.md。子agent实现goal_source_v4/opening_setup_v1/workflow_v6，主agent新增producer_v7和adapter_v5并审查；独立接线复验发现并修复全文审查传入brief/plan可篡改但SHA不变的漏洞。72项新合同、31项接线、12项独立接线通过，旧v5的30项回归保持。全部未证明实际文本质量。新初态不能未知现存无持有人道具位置；人物起态不可迁就正文；新原生规划及setup都进入正文与全文请求。

另外，已验证旧生产guard每层重复4次，一次v6 guard产生约148425次直接SHA操作；祖先文件并集只有1201。性能诊断详见CREATIVE_LINEAGE_GUARD_PERFORMANCE_DIAGNOSIS_20261013.md，独立flat证书首次执行完整旧guard认证，后续每周期重新读取全依赖SHA及来源时效，不常驻缓存。独立复验发现来源门返回未知与否定文件依赖遗漏，当前修复复验中；未通过前不派发。

当前540终止及新0付费预览已持久记录，历史未决70/160与93117、旧导演7/7、所有冻结回执不改。既有MiniMax自主追加授权继续有效，DS只必要审查。仍无可采用新完整剧本。可恢复creative_goal_context_release_20261013_v10独立代码副本，不覆盖消耗或媒体，不重派旧claim。
# round_06实际完整正文与审查拒收

2026-10-13：独立producer_v7准备并通过父谱系全量校验，首次真实出站与冻结预览逐值一致。541规划、542来源、543戏剧、544开场、545完整正文、546全文审查均完整返回，用量已知；新增6次/149339 reported tokens，累计546/10457707、known544，历史70/160及93117保留，无媒体或发布。

完整正文为《夜班名单上少了一个名字》，保存于 `data/production_trials/goal_context_text_production_20261013/round_06/scripts/version_01/FULL_SCRIPT.md`，不是最终采用稿。546在turn_function=statement的封闭枚举上拒收，运行停止在 `halt_full_review_contract_requires_pipeline_diagnosis`。541/545还存在重复撕页、无副本形成、先回应后出现的威胁、关柜后取物和笔身份混淆；546全pass不能证明内容无误。三个独立读稿结论一致，旧审查和正文不转换通过。

独立修复计划为 [实际全文漏判后的独立修复](CREATIVE_CAUSAL_VERIFICATION_REPAIR_PLAN_20261013.md)：typed开场位置、非控制元注与原生初态证据、戏剧反例比较和完整新规划。开发中，未增加新模型派发。已核实旧状态检查本来有前序引用/原句校验，546被Schema先阻断，不能把该门称为本轮首次新增。

v11恢复副本81成员SHA及压缩包独立复验通过，位置 `data/development_checkpoints/creative_goal_context_release_20261013_v11`。需要恢复时在独立目录恢复代码，不能回滚实际消耗、冻结记录或重派旧claim。

