# 新法律来源的完整文本后台测试计划

用户已确认“采集法律号新数据后跑完整流程”，授权后台执行文本测试。本轮采用真实新采集批次与新故事，不复用512正文作为新成果，也不重新领取512故事已耗尽的7/7导演候选。旧累计520次、7,964,215 reported tokens及70/160未知、93,117预留完整承接。

新链路为：法律号元数据采集 → 标签族/关系图谱 → MiniMax完整主题与制作简报 → MiniMax完整源行动计划 → MiniMax完整正文 → DeepSeek同稿全文审查 → 已有通用整片导演协调器 → 局部表演 → 确定性编译 → 全文制作复审与交接。生成阶段真实请求必须包含R01全文与适用表达标准；元数据仅选题，不能当法律依据或原片音画分析。

子agent负责新增纯模块 `src/content_factory/creative_fresh_legal_text_pipeline_v1.py` 与专属测试。模块注入 `invoke(label, request, validator)`、`persist_state(state)`，没有客户端、采集、凭据、网络、媒体或发布操作。主题简报、源计划和正文均由模型完整提交。人物外观、服装、场景、道具外观与显式起态由简报原生合同声明；编译器只确定性投影到现有shared manifest及initial，不猜画中人、不手填创作动作。

主agent负责新采集任务、来源真实性/新鲜度、法律一手材料核实、新授权、新冻结与实际SDK/账本、后台进程、完整制作协调器接线和独立代码审查。现有v15冷起与专项v4/v5准备函数不直接复用，因为它们绑定旧故事和旧失败，v15另有九次以上审查链。新模块仅复用可泛化合同和编译器。

默认界限分别为主题简报最多3份、完整源计划最多3份、完整正文初稿加2份整稿返修。一次DeepSeek同稿全文审查整合规划与来源义务、实际初态、逐步言语功能、法律主张、语言、刺激反应、情绪和结尾，要求实际正文证据。具体fail才有界完整返修；unknown停止，不以空issues或一个总体pass覆盖细项。规划语义失败返修完整计划并重生成完整正文，正文失败只重生成完整正文，已经使用的版本计数不重置。

SDK运输重试关闭。HTTP/明确结束/完整响应/非负整数用量及来源身份不全时停止相应运行，保存原claim与回执。完整已知缺工具可按既有同源同阶段最多一次格式恢复授权，必须先持久登记新恢复身份；恢复失败停止，不能把旧普通正文回填成工具结果。新模块生成的是请求与模型产物，接口成功、文本机器验收、创作质量和人审分层记录。

新source machine合格后输出generic完整正文、完整原生简报与计划、确定性manifest/initial及真实writer/review绑定，可交给 `EndpointFeedbackCoordinator`。新故事导演限额由新授权独立登记3份，旧512限额保留。正式人物资产/声线及真实视频质量可能仍待核实，本次文本后台测试不生成视频，不抽帧、听看、ASR或发布。

开发前后恢复副本保留。若用户反馈新流程内容不满意，主动提醒可从 `data/development_checkpoints/creative_studio_baseline_20261012` 恢复独立旧版工作副本；不得覆盖旧账本、冻结回执、媒体或凭据。


## 纯来源准备模块边界

新增 creative_fresh_legal_source_v1.py 只读 SQLite mode=ro，复用 export_source、legal_tag_graph 和 legal_tag_graph_bridge，不构造迁移仓库，不联网/采集/生成。输入本轮真实 COLLECTION_RESULT、LIVE_IDENTITY_CHECK、数据库、R01全文、六项表达标准、另行核实法律上下文及本轮 requested_after 时间。

仅 completed/exit0 且样本门通过的精确新 run 可进入；partial、human_required、异常、跨账号/旧策略、未来/过期时间、旧 opportunity、混批 observations、范围不足等拒绝。活动账号策略及身份绑定从当前 profile DB核对，身份检查必须在本轮运行前完成；不能把上轮登录记录假作新身份回执。

在该批现存 candidate opportunity 中以机会分数确定排序，候选 selected_item_ids 必须全部属于该批，且创建时间不早于本次采集。原 opportunity 提供账号/批次溯源，具体核心由本批标签图的实际支持决定，劳动法律族优先。其他族只有提供明确对应法律上下文覆盖时可采用；活动标签/泛词/地域/创作者不会成为核心。metadata不证明法条、剧情或当前全站排名。

派生 graph/packet/核心及 direction wire 都保存完整源和字节哈希。输出保持未派发、不继承或伪造人类方向批准。写文件只新建或逐字相同重放，任何冲突先停止，不改旧数据库、账本、freeze或素材。

兼容补充：研究链的 awaiting_media_analysis/exit1 若元数据明确返回、精确新 collection_run 已 completed 且样本门通过，可进入原创文本来源准备；原研究状态和原片音画未完成记录保留，不伪写 completed。其余 partial/human_required/未知分支仍停止。源视频音画分析不是本轮原创文本的前置条件。

来源模块实施完成：prepare_source_bundle 返回完整 source/graph/packet/selected_core/direction_wire/manifest 及待保存字节；write_source_bundle 先核对清单和全部字节哈希，再只新建或逐字相同重放。41项最终专属离线验证通过，报告位于 data/qa/creative_studio_production_preflight_20261012/fresh_source_pytest_04.xml。覆盖已知完整元数据待音画、未知/partial/人验、错账号/布尔版本/旧策略/禁止格式、旧批/未来时间/样本不足、旧候选/混批/假分数/泛词、最高候选与具体核心、参考全文实际入请求、写前篡改和不可变冲突。没有实际采集、生成、媒体、预算重置或旧记录修改；真实新来源仍由主agent提供。
