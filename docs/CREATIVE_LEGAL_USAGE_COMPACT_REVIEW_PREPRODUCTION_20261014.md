# 法律实际使用与紧凑全文复审：主 agent 接线审查

本次“重试”继续此前无限总量文本授权，仍采用 MiniMax-M3.1-Flash-Preview 创作、deepseek-flash 必要文本审查。新增独立 producer v18 与 workflow v17；默认 v23 和旧冻结运行不迁移。本记录分开说明离线验收、实际模型接口和文本质量。

## 已核实的原停点

主 agent 只读复核 prior_guard 通过：旧 round_16 的591–601共11次回执完整承接，累计601次、12,004,575 reported tokens、599次已知用量；历史未知70/160及93,117预留保留。整片规划24份已用完、旧导演7/7，均不清零。601为HTTP200、完整外层响应、已知用量的length截断拒收，既不是完整全文审查，也不是可接着补完的报告。

594的CC6/G047把第三十八条描述为个人提出、个人承担后果的路径；原VL2/L002保留了法定适用条件与经济补偿衔接。595实际以“虚构人物台词”放行，596仅验证创作承诺兑现。旧报告、正文与消耗不回写。具体原句、调用链和30份原文件SHA保存在 `data/qa/creative_legal_usage_20261014/ROUND16_LEGAL_USAGE_AND_TRUNCATION_DIAGNOSIS_v2.json`；原v1诊断另存保留。完整证明本地冻结，首请求仅投影创作必需的原句、漏审理由和已绑定诊断SHA，不重复发送本地绝对路径和账本。

## 新职责与准入

- source原生包读取完整当前C/G无损视图及完整权威依据，逐位置提交法律使用扫描。来源类别和虚构声明不豁免实际法律含义；不覆盖或不确定保留unknown，不能由程序代判语义或填pass。
- 三个规划包分别核来源、创作承诺和戏剧因果。新bundle直接验证新source、focused及drama原生包；旧source合同和旧combined入口不能作为隐藏准入。首请求以完整594为整稿修订源，600正文不进入规划请求。
- 原生开场和完整正文均绑定同一新规划；完整正文仍需同源语义、物理两包全文复审。新v4仅减少重复来源常量和证据引文，保留全部检查职责、逐拍/逐句原生判断和未解决问题。确定性展开不新增判断，不转用旧601。
- 具体未兑现或不确定问题须由审查模型在unresolved_issues中指向当前原生检查行，状态必须一致；一般能力边界另记review_limitations。程序不能证明模型已找出全部具体缺陷。
- 新本地安全上限为2份完整规划、2份开场、初稿加2份完整正文返修、6次规划审查及6次全文审查。累计整片最多26来自已有持续授权。运输自动重试关闭，未知结果/用量、截断、缺工具仍保存并停止；不存在新增导演、媒体或发布授权。

## 当前主 agent 离线证据

新source合同81项独立复跑通过，见 `data/qa/creative_legal_usage_20261014/root_source_v1.xml`；包括原594/595故障、全位置覆盖、精确引文、权威身份与未知/失败阻断。实现者81项为另一份复验，不能相加称162种独立用例。

主 agent另独立复跑全文合同与workflow103项通过，见 `data/qa/creative_legal_usage_20261014/root_compact_workflow_v1.xml`。目前共184种新相关用例；实施者复跑不叠加计数。独立只读审查还将旧source/bundle/opening入口置为throw，确认新三包、开场、正文与全文两包请求构建无隐藏旧准入。来源、原生审查、编译视图和当前全文的SHA漂移会在派发前阻断。

实际600请求预览见 `data/qa/creative_legal_compact_review_20261014/ACTUAL600_WORKFLOW17_REQUEST_PREVIEWS_v1.json`：来源全170个C/G、完整法律与用户目标；语义包R01全文一次，物理包不重复参考。语义wire由186,149减到167,022字节；代表性新构造合成响应由65,461减到42,439字节，两份新表由53,038减到30,016字节。合成只测形状和同解释的重复成本，不采用601，也不证明语义接受；32,000输出上限未增加。

producer v18的55项主 agent独立复跑通过，180.59秒，见 `data/qa/creative_legal_usage_20261014/root_producer_v1.xml`。本轮主 agent共239种新相关用例通过（81+103+55）；覆盖完整原生失败返修、未知/截断/缺工具停止、无重复派发、父消耗保留、授权与实际预览身份漂移等。实现者另一份55项不相加计数。1444份父冻结文件在独立入口校验中保持。

首请求独立重建的prepared SHA为ccf4f9a1d63af6515c7f7d560b4ee41e8fc50c829c23d01522ef26f649255a21，与实施者报告一致。输入正文按原context测量为53,643字符/81,746字节，整条expected_wire紧凑序列化为66,689字符/94,820字节；两者不能混称。原生594、R01、权威法律与用户目标保持，诊断原证明本地留存。根 agent一次只读断言曾错误地把prepared hash和wire hash比较，未保存或派发，改为分别核对两种身份后通过；实际请求内容没有因此修改。证据见 `data/qa/creative_legal_usage_20261014/ROOT_ACTUAL_FIRST_REQUEST_RECHECK_v1.json`。

本记录完成时新运行尚未prepare或派发。离线审查无阻断，可在已有文本授权内登记独立新范围、冻结后运行一次。请求字符/字节测量不能保证token成本或服务必然完整返回。真实文本仍需核对双方当场目的、情绪交锋、因果和可见收束，离线通过不能充当创作质量通过。

## 真实准备阶段新增阻断

随后实际执行诊断核对及授权登记，首次prepare在证书构建阶段拒绝，尚未创建round_17或全局运行claim，0新增provider。原601的durable task为result_unknown/outcome unknown/result_known=false/complete_end=false，usage_known=true/complete=true/90,219 tokens；HTTP200完整outer及length截断原因已知。旧证书只接受正常结束的known任务，因此与原真实失败记录不相容。239项原离线检查覆盖业务和mock准备路径，没有证明真实含length的完整证书可构建；原通过证据保留，不能扩述为这条未测试边界已通过。

按已追加的开发计划新增独立verifier/guard v2，只核验原已关闭截断的字节与实际任务失败状态，既不改旧任务为completed，也不让任意unknown通过。新增真实原601证书及字段故障复验后才能再次prepare。具体本地失败记录见 `data/qa/creative_legal_usage_20261014/ROOT_ACTUAL_PREPARE_FAILURE_v1.json`。

上轮600全文保留于 `data/production_trials/goal_context_text_production_20261013/round_16/scripts/version_02/FULL_SCRIPT.md`，未获有效全文复审或用户采用，不作为新成品。可恢复副本仍为 `data/development_checkpoints/creative_scope_coverage_release_20261014_v17`；恢复不得覆盖原回执、清零消耗或取得旧额度。

## 截断继承与本次用户目标补充的主审进展

独立verifier/guard v2补齐原601的精确service身份：原SQL service_task_id=null、provider_id=请求模型，result.service_task_id=null；result_unknown/PENDING保留。实施者77项（含真实601证书建/读回）通过，主agent另复跑72项合成故障及正常回执边界通过，见 `root_lineage_v2_synthetic_v2.xml`，不与实施者次数叠加。首次根复验因默认临时目录无权限，72项均未执行；改用经过绝对路径检查的全新项目内临时目录后通过，原错误XML另存v1不覆盖。

本轮用户方向确认已完整保存到 `USER_STORY_DIRECTION_CONFIRMATION_v2.json`，原v1保留。只读核对确认首请求v1保留原用户情绪功能，但最新“继续超市老员工方向，强化情绪交锋”尚未单独进入。按新PLAN追加新用户来源行及actual request supplement；原授权、预览、父输入/正文不改。新生产尚无ROOT/CLAIM或模型调用。最终producer有此补充后，还须重新验证其准备、同源传递与最终证书；不能把原239或先前证书的代码身份扩述为这次新入口已通过。

## 最终独立入口主审通过与实际补充登记

producer与方向补充90项主agent复验通过，187.06秒，见 `root_producer_and_direction_v2.xml`。当前相关独立用例为81来源+103紧凑全文/workflow+72回执边界+90生产/方向，共346；原55项复跑不再加一次，实施者77/35同样不相加。最终producer SHA68ddf2cf8c1ca1e9054ff0369bb98c41d489b1d0a0d960b453b07bf9f7d9c7fc，verifier v2 SHA b065bc0c8f8bb56945083381aee6af1c0c34b0a3761141bb33919c3ad245f578。

主agent及只读审查已分别复验新版真实601证书final_v2，原DB/输入/授权/预览保持，601仍result_unknown。证据在 `ROOT_FINAL_LINEAGE_READBACK_v1.json`；这是消耗与失败身份证明，不是完整全文审查或重派资格。补充登记脚本已实际保存三个新绑定文件，主agent `ROOT_DIRECTION_SUPPLEMENT_READBACK_v1.json` 再核只有两用户行追加、完整594与R01相等、实际prepared SHA ed55d05ce7517e90a974ef610cadac08dd85a9613f5aba145fedfb31311e8384，wire紧凑95,994字节；旧v1保持。

source/drama/作者/语义全文请求显式发送新增完整目标；focused只读取覆盖全部用户来源ID的完整当前goal，物理包只负责完整同源goal/setup/script的动作状态，两者不重复外部用户全文。旧594缺两新增目标，不能直接准入新正文。新运行尚未创建时的此记录允许按已有授权prepare再run一次；不构成模型接口、有效新全文或审美/视频通过。
