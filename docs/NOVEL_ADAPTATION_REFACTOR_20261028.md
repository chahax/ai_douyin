# 小说改编重构工作记录

状态：进行中；用户授权作为长任务目标推进。未切换生产默认，未生成或发布媒体。

## 根因与职责

旧 v6 同时要求完整阅读报告、任意事实长文、原文逐字抄引和实体名称字面匹配。引用错误、身份建模、事实错误和场次连续性使用相似返修出口，导致重写范围过大。增加整篇思考轮数未解决这个问题。

新代码集中在 `src/content_factory/novel_adaptation/`，不再复制整套 serial vN。复用旧原生回执/用量/未知保护传输；旧冻结任务及源码保留。

| 职责 | 输入 | 保存内容 | 错误归属 |
|---|---|---|---|
| 原文 | 已获取完整章节 | 不可变正文、段号、SHA | source |
| 实体身份 | 完整原文 | 稳定ID、类型、显示名称、带原段的实际称呼 | identity |
| 人物事实 | 原文＋实体表 | 身份/关系/年龄/知情，时间层与明确度 | character |
| 环境事实 | 原文＋实体表 | 地点、空间、道具、环境，保留限定条件 | environment |
| 事件事实 | 原文＋实体表 | 主体、动作、对象及先后因果 | event |
| 影视设计 | 已核实约束 | 色彩、光线、布局、服装等补足，独立版本 | visual |
| 本场材料 | 明确依赖＋原文＋前场状态 | 人物/事实/视觉引用和原段 | packet |
| 屏幕连续性 | 人物地点ID、进出动作、前场位置 | 屏幕状态，不冒充原文居住关系 | continuity |

显示名称不再要求逐字命中原文；实际称呼才需要对应原段字面支持。同一个“哥哥”可以在不同上下文指不同人，不能全局唯一化。“同处卧室”不能自动推成“同住卧室”；原主/穿书者同身体表演角色与时间层身份分开处理。字面支持仅是结构核验，仍不证明实体归并和语义正确。

模型选择段号，程序附完整原段与SHA，不要求模型复写长引文。字段/来源错误批量返回地址。修复使用候选SHA、记录SHA、允许改动ID集合，仅替换选中记录，未选内容不动，原候选始终保留。

## 开源评估（读源码，无安装执行）

检查的仓库快照：

- Whalesong Studio `7dea9cf8e78a1d65783127d7568622dff62b9e6a`，package 0.1.2，LGPL-3.0-or-later；读取 context.ts、digest.ts、import.ts。其完整章窗口、核心世界设定＋相关人物、按文本hash复用记忆、上下文限定同名人物解析值得借鉴。实现依赖 DSH Project/NovelCore/角色调用及其文件结构，并非可直接嵌入本项目的 Python 库。暂不安装、不复制实现，先借鉴职责设计。
- dsh-novel-writer `5fd293c6a2e485511faffba1912d8c8a0489cec6`，package 6.9.0，MIT；读取 lib/brief.js、lib/fixplan.js。brief集中组织写作资料，fixplan只定位/排序/记录检查范围、不改写正文；“跳过检查≠问题解决”值得保留。主要针对风格、词汇、章节资料，不能直接解决本书称谓与条件语义错误。暂不引入 Node/MCP 运行依赖。

来源：
- https://github.com/xuhao1/whalesong-studio
- https://github.com/siweina/dsh-novel-writer

只读源码副本与Git树保存在 `data/research/novel_refactor_20261028/`。raw下载遇到TLS错误，已通过GitHub blob API按树中SHA取得相关源码；没有运行任何第三方脚本。未声称外部项目已通过本书测试。

## 验收层次与当前进度

1. 已实现：实体/事实/设计分离合同、程序原文绑定、局部记录补丁、本场依赖包、显式进出场位置核验、四类独立模型提取入口。
2. 已通过11项离线/模拟检查，含真实缺陷反例（人物无退出消失、名称字面误拦截）、未选记录保持、第二种称谓上下文、四任务隔离及原文无损编号。证据 `data/qa/novel_adaptation_20261028_b.xml`。
3. 首次新资料任务HTTP前容量超限，0调用；重复原文与含hash全量目录已改为只发送一次无损编号全文。旧失败目录 `20261028_adaptation_cards_v1` 保留。
4. `20261028_adaptation_cards_v1b` 真实前三章 MiniMax xhigh 提取执行中，每类最多一次结构记录返修，总工程上界8次。最终状态以目录STATE/RESULT为准，不把启动当成功。

## 后续必须完成

- 主助手逐卡对照完整原文，确认提取遗漏和新增错误，错误意见不得自动当真。
- 对问题记录进行定向核对与最小修订，保留逐卡验收状态；结构通过不是语义通过。
- 实现并测试视觉设计/本场材料与剧本入口的实际衔接；当前只有合同，未冒称上线。
- 有效串联至少一集可读剧本与连续场次，再进行原文/时长/视觉连续性核验。
- 扩展留出章节与跨集测试；全69章尚未验收。


## 本轮真实结果更新

v1b 已以结构问题停止：2 次 / 41,508 tokens；v2 改为实体只选来源段号后，4 次 / 91,347 tokens 得到身份40、人物82、环境41、事件58条。结构通过但存在语义错误和分类越界，未验收。

定向返修新任务 20261028_adaptation_cards_targeted：1 次 / 29,765 tokens，pending=null；仅替换11条指定记录、追加2个地点。未选记录逐项相等。钱款拒收、未来职业、条件句及眼伤时间线已改善；F035时间锚、E010内心/说话表述与资料过度复述仍需处理，详见 PRIMARY_REVIEW.json。不是整体语义通过。

当前资料试验工程上界8次，已用7次，剩1次；本轮共162,620 reported tokens。本书累计167次启动，包含2条历史未知，未重派。19项离线/模拟用例通过，证据 data/qa/novel_adaptation_20261028_e.xml。

后续重点是按场依赖和验收状态选择资料、接入真实剧本与连续性验证。没有切换生产默认，没有生成视频或发布。长目标未完成。


## 逐场衔接实现（2026-10-28 后续）

新增 novel_adaptation/scenes.py、patching.py、render.py。逐条审核绑定记录SHA和原文SHA；逐场入口只选择本场依赖，保持完整章节作理解上下文。人物开场位置改为固定人物键对象，避免重复位置。逐beat检查有序进出、全部在场人物、道具实例持有人、交接来源、对白人物/时间/语速，并计算下一场前态。旁白不登记为人物。模型补丁只选择记录ID，SHA由程序绑定；原生失败保留。可读稿由原生字段排版，不手改正文。

真实新场次里程碑上界8次，与原资料试验7/8分列，不重置旧任务。首设计1次17650 tokens因老六重复初态终止；新design_repair继承余7，实际4次125200 tokens，设计和两场原生稿均已返回；第二场语速/道具问题被拦，记录级返修因模型抄错SHA仍未通过。两目录pending均null，旧失败不改。首场机械检查通过但主助手发现正文放下面包而状态未更新、开场旁白过长，不能称内容通过。

当前scoped_repair使用上述两场已知原生结果，精确绑定原请求候选后重建程序SHA，不更改替换记录内容；接续原剩3次进行指定beat修复与独立审核。实际终态须读该目录STATE；此处不预先宣称成功。完整书/跨集尚未验收，默认CLI/网页/账号服务没有迁移。

已明确限制：状态表检查不能从任意自由文本保证没有漏报动作，正文与状态仍需独立核对；目前并未实现完整人物知情状态引擎。本轮修复版不能当作无人放行保障。


## 本轮阶段结论

真实第一章两场142秒稿、状态推进与独立MiniMax审核均已完成；机械检查通过，内容仍needs_revision，详见 final_checks/PRIMARY_REVIEW.json。共8次MiniMax/241083 reported tokens，全为已知终态pending=null；本书累计175启动，历史2未知未动。没有待返回请求。

随后针对真实新缺陷继续修改：模型不再重写世界事实，只选择已审核fact ID，由程序原样组装；视觉设计只负责补足。移除无依据3道具限制，允许原文有据的现金等实例。程序派生每beat在场和持物，制作视图排除历史返修说明，但原稿与审核完整保留。新增人物知情通道检查helper（旁白、他人内心不能被当成听到），尚未接入真实生成。

最新38项离线测试通过（novel_adaptation_scene_h_20261028.xml）。这些最新职责修改尚未再做真实模型验收，不能把此前142秒稿冒充其产物。长目标仍active；后续需要最新路线真实验证、知情集成和留出/跨集测试，未切生产默认。


# 音轨锚点调度与原文事件门接线（2026-10-28，目标 active）

进出/交接新增phase=after_audio和after_audio_index，必须有合法索引，缺失/越界拦截。共享play_beat驱动检查与生产视图，按每句计算在场与可听信息；晚入场者不会被记为听见之前的对白。视图保留逐音轨人物表。视觉补丁只改已选条目的description，原文事实和其他设计不可变。审核统一明确影视改编允许忠实口语化/内心表达，原文无逐字台词不自动成立must_fix。

真实visual_anchor 4次/51253，camera_cleanup 3次/53334，均终态pending=null，两个原生全文审分别revise/pass，主助手最终needs_revision。实际解决灯具、闭眼倒影、重复起身、跪地应答、双胞胎先后入场、甩镜与部分返修说明。当前累计场次31次/651989 reported tokens，本书198启动含旧2未知不动，窗口32尚余1。旧失败保持不重跑。

剩余：sc01-b03镜头误称坐起的孩子（实际苏墨坐起、孩子站立）；sc01-b04第一人称挨我打及sc02-b05旁白应明确原主旧行为；视觉衣物需写清已知破洞；b05时序说明改可拍动作。并不采纳审核将扶地上瓶/跨两拍擦药强判重复的推断，证据引用不等于逐段都要演出。

fresh workflow已接可选已审核原文事件合同及已知design_checkpoint；require_source_events可阻止未审核事件前进入场次；状态自洽但漏交接会走仅状态字段的定向返修。缺门时candidate显式not_executed，不宣称完整门验收。58项针对性离线通过data/qa/adaptation_source_gate_20261028.xml；新fresh接线尚未真实模型运行，跨集/留出仍未验收。

本轮主助手记录data/corpus_production_trials/20261028_owned_repair_camera_cleanup/PRIMARY_REVIEW.json，原生候选/审核/补丁均保留。无媒体/账号服务操作/默认迁移，目标不可complete。



# 首章文本小样验收与首次生成入口复测（2026-10-28，目标 active）

新增指定音轨text补丁，程序只替换选定beat/index文字，保留其他音轨、说话人、类型和时间；后续必要排时另记。资料分类pipeline原有让模型抄before_sha256已改为程序bind_patches，相关实现纳入快照。61项针对回归通过data/qa/adaptation_information_refs_20261028.xml（原全仓独立失败未冒称解决）。

真实attribution 5次/67302、positive_design 2次/37338，两个run均终态pending=null。最新positive_design PRIMARY_REVIEW=accepted_text_pilot：仅第一章两场约145秒文本及连续性小样，非无人放行、非全书/跨集/媒体验收。解决原主归属、站立孩子机位、服装破洞及视觉返修禁令。原模型建议中的哥哥自称误读/钱款交接和新增学费来源均未采纳。所有原稿不手改；完整小样data/corpus_production_trials/20261028_owned_repair_positive_design/EPISODE_UNACCEPTED.md的自动文件名仍未改，验收以独立PRIMARY_REVIEW为准。

为检验首次生成而不是只修旧稿，新增fresh_reviewed_events用已核对设计与3条事件合同重新生成，不提供旧完整稿；1次/20171后因把E006事实编号填入requires_information而停止，pending=null，未通过。已将模型Schema的音轨引用限定为该人物真实前态音轨枚举；没有前态音轨时列表仅可为空。首段输出先按实际模型Schema校验，不再只靠宽泛状态Schema。

fresh_audio_refs是新真实复测，当前最后已确认exec session 8494仍在运行，STATE calls_started=40/pending=40，尚无首段响应，不得当失败重派。累计场次39个已知调用776800 tokens，另第40次在途消耗未知；本书207启动含历史2未知+当前在途，不记未知用量0。窗口沿46上界继续：fresh首轮38→46，第二轮携39余7至46，无重置。后续必须先读该run/STATE并poll同一进程。此前全部已结束run不重跑。

完整目标仍未达成：新入口实测、留出章节/跨集承接尚需完成。要求审计data/qa/adaptation_goal_requirements_20261028.json。无媒体/发布/服务重启/默认迁移。



# 首次生成正文复核与跨集状态接线（2026-10-28，目标 active）

fresh_audio_refs已结束，真实4次/99164 reported tokens，累计场次43次/875964；本书210启动含历史2未知未动，新增pending=null。session8494已完成，不得重派。新音轨引用约束有效，但完整稿PRIMARY_REVIEW needs_revision：后悔收钱与原文相反、前场交出的面包在后场正文重复出现、传单代替钱款、兄弟误写兄妹、放碘酒缺状态登记。MiniMax本次准确抓到前2硬伤；不因此宣称其余意见全正确。窗口46余3，未重置。

新增prop_uses可见持物声明，模型必填，按start/end/after_audio检查持有人与在场；明确只是检查已声明使用，不能保证模型未漏报正文道具，尚无新真实生成验证。旧稿保留、未手改正文。新增handoff模块及export_adaptation_handoff.py：必须主助手验收绑定候选与原文SHA，跨集保留位置、道具和按episode命名的信息历史，书籍/时间线/重复集/登记身份改变/开场重置均拒绝。已接workflow与CLI --handoff，71项针对回归通过data/qa/adaptation_handoff_entry_20261028.xml。

基于此前accepted_text_pilot真实保存稿导出E01状态，并做真实状态回放：data/corpus_production_trials/20261028_accepted_episode_handoff/{E01.json,REPLAY.json}。这是已有数据的程序回放，不是第二集真实模型生成。还发现跨集资产细化需求：第2章原文大半袋土豆，旧视觉实例小半袋，需有据登记修订机制，不能偷偷改旧快照或冒称第二集已验收。首次生成质量、正文漏报使用、留出/第二集仍未完成，目标active。



# 跨集资产细化与第二章开场真实测试（2026-10-28，目标 active）

新增refine_registry：外观修订须原文SHA、旧handoff SHA、提案SHA与独立验收绑定，只改props/places的description；旧版本、人物/道具状态不变。真实完整描述修订1次/9252加入未发生的剜芽而否决；新增description_span后真实1次/9085只把小半袋改大半袋，其他字符逐字保持，PRIMARY_REVIEW accepted，生成独立REFINED_HANDOFF。首次runner快照变量笔误HTTP前失败0调用，PREPARE_ERROR保留，后续用新目录，不改旧失败。

第二章开场30秒真实2次/52542，使用原生已核对E020/E022、上一集真实验收快照和修订资产，四次袋/土豆交接、人物位置和命名空间信息承接通过程序；PRIMARY_REVIEW needs_revision，非完整第二集。末段袋子放凳未登记、滚落个体土豆无实例拆分、条件句错成月底一定空，MiniMax审核漏掉条件错误；双手接袋仍握碘酒为调度不清，不能夸大为绝对人体不可能。旧标题未更新也留证。未手改稿。

本轮新增4次/70879；累计场次47次/946843 reported tokens，本书214启动含历史2未知不动，全部新pending=null。当前窗口48余1，不重跑任何已结束run。真实目录registry_quantity_refinement_v2、registry_quantity_span、second_episode_opening（均20261028前缀）。资产小样与跨集机械通过不能升级为整链内容通过。

新增模型source_ids仅限本场selected_facts支持原段，完整章节只是理解上下文，防止自由扩写未分配背景；已接workflow，尚未新模型验证。74项针对回归通过data/qa/adaptation_selected_evidence_retry_20261028.xml；首次新测试字符串换行语法错误保留原失败XML。正文动作与状态重复表达仍可不一致，需继续收敛动作/道具表达及真实生成；目标active、默认不切、无媒体/发布/账号服务操作。


# 顺序动作解释器与真实第二章开场（2026-10-29，目标 active）

新增opt-in typed blocking：动作枚举编译文字及状态，action_order逐事件执行；同phase保持原数组顺序，phase按实际时间排序。每动作必须且只能执行一次，生产视图复用相同解释器并保留动作顺序。旧legacy按原逻辑；默认网页/CLI未迁移。82项针对回归通过data/qa/adaptation_ordered_blocking_final_20261029.xml，含先展示再交接通过、反序拒绝、三种phase、完整唯一覆盖、生产视图一致。首次pytest因系统临时目录权限81项setup失败保留，改D盘新临时目录后通过。

先前typed_blocking_opening真实1次26590，终态needs_attention/pending=null；原生确实先交袋再由旧持有人展示，新引擎原样本地重放仍拒绝，证据data/qa/adaptation_ordered_native_replay_20261029.json。未手改原稿。

新ordered_blocking_opening真实2次62677，原小说第二章30秒开场、既有已验收E01快照和独立细化资产；动作顺序、四次原文交接、人物及信息承接通过，MiniMax终审pass。主助手PRIMARY_REVIEW仍needs_revision：袋与内含土豆被分别演成移交、旧显示名混入烂菜叶、重复旁白拖慢信息、audit-only adaptation_detail仍另写镜头与动作。不能冒称整链内容通过。模型建议中强迫旁白先于已演出的动作、每次持物必填prop_uses、把OFFSCREEN改为虚构位置均不照单执行。

最新累计场次50次1036110 reported tokens，本书217启动含历史2未知未动，新增全部pending=null。窗口50已结束，不重跑旧run；新工程工作须继续累计不能重置。session29965 exit0，无活跃调用。默认/账号服务/媒体/发布不变。下一步容器与内含物的实体关系和继承归属、简洁显示名与生成端资料分离、节奏规划；完整第二集和留出章节仍未验收。


# 容器归属、原文事件与真实重放（2026-10-29，目标 active）

新增containers模块：显式内含物→容器关系，校验未知/循环/归属冲突，整容器交接递归更新有效持有人；内含物不再独立交接。容器关系须源文、旧handoff与提案SHA绑定的独立审查才能细化，旧快照和原有效归属不改。跨集不得抹掉关系；原文事件门可由容器递交满足内容物归属变化。取出/放入内容物的动作合同尚未实现，明确拒绝，不能称通用道具行为完备。

真实container_opening一调用26900，模型仍单独递交土豆，正确拦截；根因提示约束尚未反映在Schema。新增typed transfer只能选顶层道具，生成载荷标出inherited_from_container_transfer，原已审事件合同保持不变。container_schema_opening再一调用26301，不再直接递土豆，但最后静默段省略audio被旧必填拦截。定义typed省略audio等于空音轨，程序填默认、不改原生；known_replay按原SHA本地编译与状态/原文事件重放通过，0新模型调用，旧失败全部保留。

主助手仍needs_revision：最后21.5—30秒静态全景、无音轨且重复点头/注视/微笑，不符合快信息节奏；旧显示名混入来源与错误括注仍需解耦；adaptation_detail为audit-only且仍另写镜头动作。容器机械通过不等于内容验收，完整第二集/留出未完成。证据20261029_container_known_replay/PRIMARY_REVIEW.json及REPLAY.json。

92项针对回归通过data/qa/adaptation_containers_final_20261029.xml，覆盖嵌套容器、一动作多归属、原文事件门、防跨集关系重置、审查SHA、Schema拒直接递内含物、静默默认不增音轨。真实新增共2次53201 reported tokens，累计场次52次1089311，本书219启动含历史2未知不动。两run均needs_attention/pending=null，session21147与61937均exit0；没有活跃调用。工程窗口52延至53（第二run携51余2，仅增1容量），剩1未用，不重跑终态。默认/账号/媒体/发布未动。


# 内容决定时长、显示名称与音轨显式化（2026-10-29，目标 active）

新增presentation.display_names仅投影展示名末尾括注，保留原实体/来源/身份；若投影造成同名冲突保留原限定，不能把原主与穿越者合并。blocking及Markdown使用相同投影，各run保存DISPLAY_NAMES。新增pacing可配置上限与纯静默反应限制，明确只是工程编辑约束不是语义证明。内容主导brief中current_scene不传必须填满的秒数，30秒为上限；镜头已演出接袋/微笑/摸头不逐句旁白重述。96项针对回归通过data/qa/adaptation_pacing_audio_20261029.xml。

真实pacing_opening一调用26663：15.5秒却全部省略audio，把说话写进adaptation_detail，长静默被拦截，PRIMARY_REVIEW拒绝。此前允许省略audio的生成合同过松；现生成明确必填audio（确实静默填[]），已知静默旧稿的本地重放仅可显式allow_silent_omission=True，不更改旧回执与失败。

真实pacing_explicit_audio一调用26157：15秒，两句关键对白明确、袋子仅交两次、结尾反应2.4秒；但老六requires_information编造了E01:sc02:sc02-b01:a1，此ID不在任何人物继承历史，schema正确拒绝。未编译最终稿/未进终审。下一步按原生SHA只修该信息引用，不整场重生成、不直接删引用迎合规则；开头旁白仍重复动作，audit-only补充说明还需处理。

本轮新增2次52820，累计场次54次1142131 reported tokens，本书221启动含历史2未知未动；两个run均终态needs_attention/pending=null，session89422/70846 exit0。窗口从53延到54再55，均延续实际累计，尚余1未调用。旧run不重跑。目标active、第二章开场尚未验收，更不代表完整第二集/留出章节；无默认迁移/媒体/发布/账号服务操作。


# 信息引用定点返修与审核输入分层（2026-10-29，目标 active）

新增reference_repair和repair_adaptation_references.py：只枚举无效引用，该人物真实音轨历史内选编号；修复限定beat/index/event_id，不许删除、改人物或改其他正文，无合适对应则uncertain停止。checkpoint绑定原稿/来源/设计/前态SHA，新run复用已知修后原生场，不重生成或重派未知。全部原记录保留。

真实reference_repair两调用37477：a1改成已存在的a0（叶嫣儿问老六疼吗），逐字段验证其余原生对白/动作/镜头不变。机械、容器原文事件、节奏检查通过；程序排时15.2秒，MiniMax全文revise。主助手区分真实输出与审计注释：原审核把audit-only的昨天/重复摸头当视频指令，又未接收开场范围而追问整章覆盖；也不能因模型改正编号就认可它把疼吗强解释为笑看土豆的因果。PRIMARY_REVIEW needs_revision，未宣布整集通过。

新增review_projection：实际输出字段保留，adaptation_detail只保留排除字段SHA，原候选不可变；带明确brief objective与来源章范围，来源章节不等于整章必须覆盖。已接workflow并准备NEXT_REVIEW_PROJECTION_PREPARED，尚未用新投影真实复审。108项针对回归通过data/qa/adaptation_reference_projection_20261029.xml，含拒删/越界/杜撰/旧SHA、原稿不变与排除审计文字。

累计场次56次1179608 reported tokens，本书223启动含历史2未知未动；新pending=null，session70381 exit0。窗口55追加1到56已用完，未重置次数。原稿通用容器标签、画面动作重复旁白、机位/动作覆盖仍待改；完整第二集和留出章节未验收。目标active，无默认/账号/媒体/发布操作。


# 道具显示名、局部镜头与跨集开场验收（2026-10-29，目标 active）

新增presentation_labels独立于实体身份/来源/外观/持有人；模型仅选定prop ID生成短名，程序校验范围/来源/唯一性，编译展示时应用，handoff保留presentation登记防后集悄改。refine_adaptation_presentation支持标签及限定shot/source_ids/fact_ids补丁两种互斥模式，原生动作音轨不变；114项针对回归通过data/qa/adaptation_labels_20261029.xml，脚本py_compile通过。

真实presentation_review两次31789：标签发黄白色塑料袋符合既有美术描述；新review_projection复审不再按全章追问开场范围或混入audit-only昨天错误。模型建议补充交袋/摸头画面主体，主助手仅认可为清晰度改进，不能从主体未列断言人在屋外。随后shot_review两次34306，只修b02构图与E022/CH2-P011关联，其他原生字段逐字段相等；模型pass。主助手PRIMARY_REVIEW accepted_text_pilot，限CH2前段约15.2秒，实际E01状态衔接、关键对白、两次袋交接及土豆继承、人物在场通过。保留旁白重复/视觉揭示延迟等非阻断编辑建议，非实测音视频或无人全链验收。

导出shot_review/ACCEPTED_OPENING_HANDOFF.json，可供后续厨房/饭桌承接，不抹旧失败。完整第2章已逐段阅读，材料准备审计在20261029_shot_scope_prepared/FULL_CHAPTER_2_MATERIAL_AUDIT.json：E021条件句错误、E030孩子主观预期归属、E034抬高音量时点需修清；不能直接称全部旧材料已验收。完整后续还缺取出/放入、加工/分份语义或经审查的省略转场，以及完整场次计划和新依赖核对。

本轮真实4次66095，累计场次60次1245703 reported tokens，本书227启动含历史2未知未动。两个run终态episode_awaiting_primary_review/pending=null，独立PRIMARY_REVIEW为最终局部结论；session47731/44725均exit0，无活跃调用。工程窗口56→58→60，实际累计保持。旧默认/账号服务/媒体/发布未改，完整第二集/留出章节及首次生成稳定性未完成，目标active。


# 完整第二章续写设计继承与实测（2026-10-29，目标 active）

新增inherit_design、opening_delta_schema/bind_opening_delta：续写模型只提出新增地点/道具与局部设计，旧登记和画风由程序逐字段复制，旧人物/持有人不进入可写开场schema；同ID重定义即使内容相同也拒绝。export_handoff新增保留visual_design。workflow已接真实设计入口；design-only只生成设计/开场并停在design_awaiting_primary_review，不运行场次/不冒称原文事件门通过。119项针对回归通过data/qa/adaptation_continuation_design_final_20261029.xml。

真实chapter2_cards_repair一调用8200，仅改E021/E030/E034 statement：恢复米袋条件句与原主归属、孩子主观肉份预期、提高音量只在第二句。主助手对照完整原第2章通过此材料补丁；其他字段/旧记录不动。full_chapter2_prepared保存原生资料与选中依赖审查，原first-three章来源SHA不变；重新从已验收开场导出带原画风的handoff，新文件不覆盖旧。

真实full_chapter2_design两调用55037，规划完整CH2-P013—P145剩余三场：厨房误解赶出、做饭与往事、饭桌冲突，已非反复15秒开场。旧资产/人物位置/持物/画风严格继承通过；PRIMARY_REVIEW needs_revision：固定厨房场却包含门外对白，成品炖菜在制作前已登记开场存在，结尾凭空接下一集清晨（第3章实为饭桌争论直接继续），叶嫣儿不想与哥哥姐姐分开的概括暗示不存在的姐姐。保留模型设计，不手改，未进入编剧/终审。

本轮实际3次63237，累计场次63次1308940 reported tokens，本书230启动含历史2未知未动。cards状态awaiting_primary_material_review，独立PRIMARY_REVIEW=accepted_material_patch；design状态design_awaiting_primary_review，独立PRIMARY_REVIEW=needs_revision。新pending=null，session23718/21266均exit0，无活跃调用。窗口60→61→63累计保持，未迁移默认/重启账号/调用媒体发布。

后续必须解决场次跨地点划分和道具生命周期（未生成/存在/加工，及容器取出/放入）或明确经审查的省略转场，再跑完整后续剧本；不能用已验收开场替代完整第二集/留出/首次生成质量目标。

