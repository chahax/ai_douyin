---
doc_status: current
doc_category: model_navigation
last_reviewed: 2026-10-20
runtime_scope: v23_baseline_with_independent_natural_director_v10
---

# 大模型项目分析与操作导航

2026-10-21：[渡口本地H3原生864×1536首段](H3_FERRY_S01_HIRES_REVIEW_20261021.md)已一次成功：175帧/24fps/约7.292秒/原生音轨，像素为576版2.25倍，服务47分12秒。原Seedance人物参考同字节，剧本/种子/12步保持，仅改输出尺寸与隔离路径；526旧文件和2日志前缀主审保持。交付data/video_generation/h3_ferry_s01_hires_20261021/deliverables/S01_ferry_864x1536_12step_with_audio.mp4，仍待用户审核清晰度和字幕，无看听/抽帧/ASR、续段或发布。

2026-10-21：[搜索与浏览器功能修复实测](SEARCH_BROWSER_FUNCTIONAL_REPAIR_20261021.md)：已修复新版搜索卡片、中文日期、失效worker、人工跳转超时、验证暂停原因覆盖及窗口轮询读取全量历史问题。内置搜索实际提取18条并点击核对ID；搜索组合72个不同用例通过，最后窗口管控组合79项通过，各报告有重叠不累加。原f4eafa4d未知窗口按用户授权保留审计并取消；原身份核验成功，但后台搜索与推荐流被平台验证阻挡，实际0条/0秒。完整离线快照核验后管控库转WAL，原库额外全量检查未完成，关键两表检查通过。最终PID20792/gen42已加载修复，health200、7组件新鲜；账号paused63/human_required，原6dbb0d77开窗任务因普通额度21/20等待，未擅自追加，不能称全部业务恢复。证据FINAL_RUNTIME_VERIFIED.json；监控automation-2保持暂停。

2026-10-20：[推荐流观看修复与验收](RECOMMENDATION_PLAYBACK_REPAIR_20261020.md)：用户选择直接浏览推荐流按相关性停留，随后取消纯观看每日次数限制。默认观看已从搜索流程分离；首轮111项及不限次补充49项通过（不同用例合计113），14732/gen38已部署。原身份f885核验成功、active58；推荐流afc3实测仍verification_ui_unconfirmed，0条0秒、无搜索/互动，不能称全部修复。验证详情持久化补丁71项通过但未部署，原smart c4e184仍在途且有间歇SQLite占锁，保留原任务等待明确终态。SMOKE_RESULT.json记录实际结果；监控automation-2本次读取为PAUSED，未恢复。

2026-10-20最新：[原身份核验超时修复与实测结果](IDENTITY_NAVIGATION_REPAIR_20261020.md)：数据库/管控修复105个不同回归用例通过，已部署PID13144/gen37。用户关闭确认后的d2f597核验成功；原12ad747作品刷新完成3条作品/3条评论。后续234e3智能运营同样同步成功，但相关视频0条、verification_ui_unconfirmed，账号再次paused56；新窗口d5cd60 waiting_human，可见页current_no_challenge，后台与可见会话差异未解决。当天播放3/3，无新成功观看，未追加核验/观看。监控曾短暂读取忙、后续可读且owner心跳新鲜，不能称全部自动化恢复。最终证据POST_TREND_FINAL.json。

2026-10-20：[渡口H3全量恢复完成](H3_FERRY_FULL_RECOVERY_REVIEW_20261020.md)：用户明确允许S05一次重跑后，独立恢复S05/S06各一次成功，复用S01—S04合成576×1024/24fps/约50.834秒六段审片版。1220原H264包按序保持、未重编码画面，连续AAC；原S05未知与旧claim不改，全部仍待人工审片，无看听/抽帧/ASR或发布。交付根data/video_generation/h3_ferry_full_recovery_576x1024_20261020/assembly/deliverables/full_ferry_review.mp4。

2026-10-20后续：用户明确“取消”后，误入测试46186a已按原快照审计取消，完整unknown及不确定性保留，gen34旧owner已交还；5项取消保护测试通过，21472健康200，仅余原账号paused48，未重派或恢复养号。见[取消记录](BROWSER_NAVIGATION_REPAIR_REVIEW_20261020.md)及data/browser_navigation_repair/20261020/CANCELLATION_VERIFIED.json。

2026-10-20最新：[浏览器超时修复及测试隔离](BROWSER_NAVIGATION_REPAIR_REVIEW_20261020.md)已部署PID21472，health200/7组件新鲜，最终有效112项不同测试通过。误入生产的两条排队测试已按原快照取消；另一条46186a原unknown及gen34 owner保持，账号paused48，实际观看尚未恢复。监控补查真实未决unknown，不能把网页健康当任务成功；处置提案尚未执行。

2026-10-20：[渡口H3全量批次中断核对](H3_FERRY_FULL_BATCH_INTERRUPTION_20261020.md)：同人物参考576×1024版本已保存S01—S04；S05原任务采样5/12后服务退出，原结果未知、无可恢复输出，S06未提交、整片未合成。411旧文件及2日志前缀主审保持，原claim/pending不改；用户已明确允许S05重跑一次并完成全片，正在准备独立恢复入口。

2026-10-20：[渡口同人物参考576×1024首段](H3_FERRY_REFERENCE_576_REVIEW_20261020.md)已一次REF2VA成功，使用Seedance原父女参考，约7.292秒/原生声音/服务13分6秒；361旧文件及活跃日志原前缀保持，待用户审片，无续段或重试。

2026-10-20：[渡口首段本地H3试片](H3_FERRY_S01_TRIAL_REVIEW_20261020.md)已一次成功：416×768、约7.292秒、原生音轨，服务约11分13秒。319份旧文件保持，待用户审片；无续段或重试，旧失败及文本停止保持。

2026-10-20新增[每日三时段随机养号与实际运行](PLAYBACK_RANDOM_DAILY_REVIEW_20261020.md)：account01按北京时间09–12、14–17、19–22各随机一次，持久时间不因重启重抽，原每日3次/禁点赞评论/互斥与暂停保持。用户验证关闭后原身份核验已成功；实际接续219a93在Page.goto超时停止，观看0，当前paused48，不能把随机设置启用当成正在成功养号。两次原记录保留，新服务及最终状态见data/playback_random_schedule/20261020/FINAL_STATE.json。

2026-10-20最新：[主机重启后服务与原任务恢复实测完成](SERVICE_REBOOT_MONITOR_20261020.md)。原Windows登录自启任务可启动服务，但旧owner曾堵队列；已修复只允许上一boot且无真实未决任务的审计交还，并优化正常读取避免展开大型历史审计。最终16项定向通过，原维护0c749 succeeded/refresh a201 completed/hold settled；最终PID5632健康200、七组件均新鲜正常、idle owner已释放、账号active。已启用当前会话10分钟只读监控automation-2，异常/恢复才通知；登录后自启，不是无人登录系统服务。最新实际状态data/service_startup_monitor/STATE.json。


2026-10-19最新：[原视频发布与原评论自主核查已完成](PUBLICATION_AUTONOMOUS_RECONCILIATION_REVIEW_20261019.md)。实际PID26920/gen31/health200，原发布1582与最终只读4fd94均succeeded；作品7698306800386379018、主动AI声明来源及展示、虚构说明、五标签、播放器及原173字符普法评论精确可见均确认。旧unknown/claim/native/发布锁保留，未重传或重发评论。账号原paused43已审计恢复active44/failures2保留；维护0c749/原run a201仍排队等普通每日额度（实际68/普通20），不当作后台已执行。当前完成状态见data/video_generation/h3_dense_office_full_20261018/publication/autonomous_reconciliation_20261019/EXECUTION_STATE.json；下文此前停点均为历史阶段。


2026-10-19用户明确允许当前原作品无限次自主核查及自行结束项目浏览器进程，已按[自主核查实际记录](PUBLICATION_AUTONOMOUS_RECONCILIATION_REVIEW_20261019.md)注册同一v2授权。共享scope36项、human1项、普通评论证据桥3项最终通过并主审，29156/gen23健康200/28源SHA核实。真实02265705ccda40949645ca55089d91e6准确绑定作品7698306800386379018，原AI主动声明来源+页面AI/fiction/5tag/player/审核全通过；尚余原授权评论：editor_unavailable、submittedFalse、无claim，整流程未完成。gen23已自主交还，正在只读控件诊断与精确已知未提交续行；未重传/再次发布/评论，未知与人工门、原锁、账本和普通20额度保持，不再要求用户关窗或逐次追加核查。

2026-10-19用户要求费用和合成，已完成[渡口六段完整审片版](FERRY_SIX_SEGMENT_ASSEMBLY_REVIEW_20261019.md)：49.250秒/720×1280/24fps，1182原视频包SHA同序、PTS全连续，原音轨按画面对齐为连续AAC，两轨起点0/时长49.25秒/DTS严格增。261旧文件SHA保持，0新模型调用；六段原价估24.47元、实扣未知，成片仍待用户审片，未看听/抽帧/ASR或发布，原失败及文本停点保持。

2026-10-19用户收到S05后“继续”，已完成[最后S06原尾续段及六段交接](S06_TIMING_V2_VIDEO_CONTINUATION_REVIEW_20261019.md)：一次原ID`cgt-20261019185534-lnmn4`，720×1280/8.096秒/原生音轨，服务142秒。229份旧文件SHA保持，六段文件共49.568秒、机器文件索引已保存；全部仍待用户审片，无重试、合成或发布，旧文本停点及失败2/10不变。

2026-10-19用户确认“已发布状态”，并明确要求“修复缺陷然后测试再生产测试”。已按[核查修复与实际生产结果](PUBLICATION_RECONCILIATION_REPAIR_REVIEW_20261019.md)完成主审、交还和后台40968/gen16部署，唯一核查169d537d48094d1992acb3d2f4df707f执行日33→34。管理页截图已显示本片17:22“已发布”，但准确标题发现候选0，未取得作品ID/URL，原发布及核查仍unknown；提交锁保持，未重传、未点击发布、未评论。19:37标题/简介组合显示及加载状态补丁已完成主审，最终19项本地测试通过，尚未部署/实平台复验，真实DOM及链接资格未知；不把页面展示或模拟DOM通过代替准确作品机器核验。本轮1次核查已用，未自动追加，原调度时间已恢复、refresh在unknown门后排队。

2026-10-19用户“追加1次，部署并继续发布”的独立v8已注册并执行日32→33，见[实际提交与待核实停点](PUBLICATION_NATIVE_SCROLL_RESUME_REVIEW_20261019.md)。43940/gen15健康200/11源符合冻结，唯一1582fcdcc9274211b3aedf4aa680b1bb完成上传、五tag、AI主动声明原设置读回及虚构声明，17:22:09唯一发布点击正常返回并跳作品管理；17:23:03未取到准确作品ID而outcome_unknown/submission_unknown。保留提交锁，未评论/重传，等待用户核对管理页作品/审核链接。原生滚动分支本次因短暂success_marker先返回未被实平台执行，不冒称验收；旧v1-v7授权历史保持。

2026-10-19用户“追加”的独立v7一次31→32已执行：31972/gen14部署10源符合冻结，唯一9681ccee331040df9c4d946e9593ae16于16:46:53明确upload_failed，尚未进入标签/AI/提交或评论，无作品或新锁，原control active42保持。完整原生记录有bytes/cancel及检测中5%/9%，但重新上传候选usable=false，不能确认完成；按[上传可用性诊断](PUBLISH_UPLOAD_MISSED_STATE_DIAGNOSIS_20261019.md)继续离线分析修复，无第二次重传。离线有界原生滚动修复已由主agent审查，最终同源58项通过，尚未部署或再次上传，见[本轮结果与离线修复](PUBLICATION_SCOPED_POPUP_RESUME_REVIEW_20261019.md)。本轮原生终态保存于publication/resume_scoped_popup_publish_20261019/FINAL_STATE.json；c93声明修复已部署但此次未执行到，不称实平台通过。

2026-10-19最新[自动发布启动与监控实际结果](PUBLICATION_MONITORED_RESUME_REVIEW_20261019.md)：独立v6一次30→31已执行，40520/gen13健康200/9源符合冻结。唯一8fac1b26ff9e4d2e98bbf48bb42ed277上传和五tag稳定通过，16:20:57仍ai_declaration_unverified：原声明交互身份/确认关闭已绑定，但无关全页role弹层门阻塞。未提交/作品/评论/新锁；日31/active42保持。本轮没有第二次。已离线修复仅关联原声明container，33项最终通过、主审完成，helper c93d...尚未部署；原失败及本轮上限不改。监控跟踪至停点，随后工具确认automation-2不存在，未重建。下方正在运行/待最后测试均为此前阶段。

2026-10-19用户在旧三次明确停止后新要求“启动并监控”，并澄清“视频的自动发布流程”。本轮按新启动请求保守登记同片一次30→31，旧v5三次上限/账本不改，见[监控续发方案](PUBLICATION_MONITORED_RESUME_PLAN_20261019.md)。先补AI自定义label/value原交互和值变更证明，独立v6登记一次新key；原helper/原生记录与unknown保护保持。v6已部署40520/gen13健康200，唯一8fac1b26ff9e4d2e98bbf48bb42ed277消费30→31；上传五标签通过，16:20:57原AI设置身份与弹窗确认已绑定，但global弹层检查popupsClear=false导致ai_declaration_unverified，未submit/作品/评论/锁。正在离线将检查限于原声明弹窗，不把修复写成已真实发布；未新增第二次。监控已跟踪至此终态；automation-2随后工具确认不存在，未重建。

2026-10-19最新[本视频三次续发已执行并停止](PUBLICATION_BOUNDED_THREE_REVIEW_20261019.md)：用户批准最多3次均已用完，日27→30。前两次明确提交前标签失败，修复后第三次06b4c87f6a4343578774748c9a3b852d上传与五标签全部读回通过，但15:34:39停于ai_declaration_unverified；设置行截图显示AI生成，程序资格未确认，不替代回执或手改通过。未点击发布、无作品/评论/新锁；最终45996/gen12健康200，active42/failures2/空业务lease。8源符合冻结，所有旧记录与原片保持，未派第4次。下文“正在运行/剩1次”等均为此前阶段记录。

2026-10-19最新用户已明确批准同片最多3次、仅已知提交前失败修复后顺序续行，见[三次续发方案](PUBLICATION_BOUNDED_THREE_RESUME_PLAN_20261019.md)。独立v5五项真实SQLite/actor验证通过，原v4实际全链及handoff六项已核对；父授权已注册，原35960/gen9受控交还并自然退出，新40180/gen10健康200。slot1 82712ce9edb0409a8fc54749d0b2946e已消费27→28，实平台upload_complete，15:15:42因HashtagReadbackError在提交前明确failed，未AI/提交/评论，无作品ID/新锁。标签修复37项本地通过并部署14080/gen11后，slot2 461cc39d24dd45c28834a253e5a678a9消费28→29，上传完成，但15:23:45首个标签前因末尾caret不确认而明确failed/HashtagReadbackError；未AI/提交/评论，无作品/锁，剩1次。原失败页已关闭，历史无Selection证据；[标准DOM逻辑末尾修复](PUBLISH_HASHTAG_SELECTION_REPAIR_PLAN_20261019.md)已完成37同源过+修夹具8过（非一次45全绿），Windows命令28599及纯常量模块已核；不冒充原平台原因。slot3证明已注册，原14080/gen11双栅栏受控交还，45996/gen12健康200/8源SHA符合冻结。最后一次06b4c87f6a4343578774748c9a3b852d已派发运行，等待原生结果，未派第4次；先前两次明确未提交。三次承接27→最多30，无新增后台/媒体/恢复额度；下文“拟议、未授权”均为此前停点。

2026-10-19已完成[正式编辑页转换修复与最终主审](PUBLISH_UPLOAD_EDITOR_TRANSITION_REVIEW_20261019.md)：最终同源22项真实本地Chrome/worker通过、相关52项回归通过，原AI/单次点击不变；armed允许精确upload→editor流程，checking后才锁原document/节点，并保存安全结构诊断。另按原部署批准精确取消新排队refresh，3项SQLite通过，active42/failures2/日27保持。新v2尚未部署或真实平台验收，无再次上传或新授权。原64c924任务已知upload_failed、未发布/评论、无作品/新锁；后续最多3次仅为拟议范围，需用户另明确批准。

2026-10-19用户“允许”再次追加本视频发布1次后，已完成[快传修复部署与唯一实际续发](PUBLICATION_FAST_UPLOAD_RESUME_REVIEW_20261019.md)：v4授权4项、handoff8项和smart派发前取消3项真实SQLite通过，新服务35960/gen9健康200、8份源码符合冻结。唯一64c924271976403bb0f1e5921db446f3消耗26→27，14:39:53仍upload_failed：平台正常从upload跳post/video?enter_from=publish_page，而原节点门冻结过早、首次检查即拒绝导航。未AI声明/发布/评论、无作品或新锁；active42/failures2及旧历史保持。当前仅按[正式编辑页转换计划](PUBLISH_UPLOAD_EDITOR_TRANSITION_PLAN_20261019.md)离线修正，不重传或擅自追加。

2026-10-19用户在作品管理未找到后批准人工结清旧未知、归档提交锁并追加本视频发布一次，已完成[单次续发部署与实际执行](PUBLICATION_SINGLE_RETRY_REVIEW_20261019.md)：旧未知证据不改，新服务22452/健康200，最终AI声明与单次点击修复已部署，原账号active42保持。唯一新任务6730f85e9f9b45bc9c0520f2e23c5cd3消费25→26，13:20停在upload_failed，未AI声明/点击发布/评论、无新锁或作品ID。诊断已从检测中5%变为作品未见异常，但旧程序漏捕快传字节状态而不放行；[独立上传识别修复与主审](PUBLISH_UPLOAD_FAST_TRANSFER_REPAIR_REVIEW_20261019.md)最终12个真实Chrome用例、相关52项旧回归通过，尚未部署或证明实际平台原节点资格，未追加或重传。下方原unknown停点已由本次人工处置归档，不冒充服务器已知失败。

2026-10-19用户再次追加核验与发布各一次，已完成[第二份授权部署及实际上传](PUBLICATION_SECOND_TWO_RUN_REVIEW_20261019.md)：服务41264/健康200，原核验成功，视频上传、五标签及简介读回完成，日计数23→25。但AI单选回执误把未确认的非ARIA弹窗视为成功，发布按钮超时后原任务outcome_unknown，提交锁保留，无作品ID/评论。误判已纠正；最终弹窗修复主审59项+真实本地UI5案、单次点击修复30项+真实本地UI3案通过，尚未部署。未知后无新派发或重传，待原法律号作品管理核实结果；下方此前“未提交”是先前批次阶段记录。

2026-10-19按用户授权取消指定未知开窗并追加原账号核验、视频发布各一次，核验成功，发布完成上传与五标签读回后停于AI声明控件未确认，尚未提交或评论。已完成[AI声明状态提交修复和主审](AI_DECLARATION_COMMIT_REPAIR_REVIEW_20261019.md)：主助手44项回归、前修订5种真实本地UI案例和最终修订1种有界入口案例通过；修复尚未部署，原追加两次已耗尽，无第三次发布或恢复。不能把本地验证写成平台声明成功。

2026-10-19用户要求继续输出视频，已完成[S05十秒原尾续段](S05_TIMING_V2_VIDEO_CONTINUATION_REVIEW_20261019.md)：S04服务原尾同字节first_frame，一次原ID`cgt-20261019084426-rbmmn`，720×1280/10.080秒/原生音轨，服务127秒。198份旧文件SHA不变、评分null；S05待用户审片，尚余S06八秒，未自动续段、重试、合成或发布，旧文本停点及失败2/10保持。

2026-10-19确认[验证容器内容区分修复已部署](ACCOUNT_VERIFICATION_SURFACE_FIX_20261018.md)：实际服务PID43636于00:01:35启动，10份修复源码SHA与最终验收一致，HTTP200且七组件新鲜正常。原人工窗口已closed、runtime锁为空；账号仍paused/revision19、事件8保留，本次仅核实部署，未提交新处理完成请求或恢复播放。

2026-10-18用户批准“发布优先后恢复后台”，已实施并部署[账号浏览器管控](ACCOUNT_BROWSER_CONTROL_PRIMARY_REVIEW_20261018.md)：同账号单owner/context、任务固定标签页、持久队列、播放安全点保存/发布/原循环恢复、保留人工验证页及原完成核验、指标及官方管理入口兼容。最终受影响150项通过、真实Chrome本地组合15/15，配额增量2项通过；旧完整趋势页历史日志读取超时仍保留。原窗口正常结束且运行锁为空后完成首次部署，配额补丁在证明queued-only边界交还后切至PID43636/第2代owner、health200。已授权60秒成片入队55c79f0c86b8485ab95318b26dac1aec，仍受原human_required及原20次配额周期上限阻挡，未上传/发布/评论；不得把队列或本地实测当平台成功。

2026-10-18用户再次指出暗色搜索页无可操作验证码并要求继续修，已完成[验证容器内容就绪区分](ACCOUNT_VERIFICATION_SURFACE_FIX_20261018.md)：新增worker只读框内内容探测，空白/加载失败/不可读归verification_ui_unconfirmed持久暂停，已识别提示及实际控件才归human_required。480项回归和23种隔离DOM通过；原事件8窗口仍持锁，新版尚待正常关窗后部署，未恢复真实播放。

2026-10-18用户收到S03后再次“继续”，已完成[S04十一秒原尾续段](S04_TIMING_V2_VIDEO_CONTINUATION_REVIEW_20261018.md)：S03服务原尾同字节first_frame，一次原ID`cgt-20261018231100-d6kjb`，720×1280/11.104秒/原生音轨，服务112秒。166份旧文件SHA不变、评分null；当前待用户审片，无S05、重试、合成或发布，旧文本停点及失败2/10保持。

2026-10-18用户提供正常装修合同截图并授权关窗后部署，已完成[验证检测证据修复与真实恢复核验](ACCOUNT_CHALLENGE_EVIDENCE_FIX_20261018.md)：452项回归及13种隔离DOM场景通过，23:09部署实际PID39488；23:10原身份核验通过，23:11新搜索仍有380×384可交互验证iframe连续两次确认，排除另一个隐藏框。新事件8暂停，播放0条0秒；23:12原账号处理窗口自动打开，等待人工核对，不能写成已恢复观看。

2026-10-18用户收到S02后再次“继续”，已完成[S03六秒原尾续段](S03_TIMING_V2_VIDEO_CONTINUATION_REVIEW_20261018.md)：S02服务原尾同字节first_frame，一次原ID`cgt-20261018225609-tf9hb`，720×1280/6.080秒/原生音轨，服务91秒。107份旧文件SHA不变，父receipt不改、质量评分null；当前待用户审片，无S04、重试、合成或发布，旧文本停止及失败2/10保持。

2026-10-18用户在新标准S01后“继续”，已完成[S02原生尾帧续段](S02_TIMING_V2_VIDEO_CONTINUATION_REVIEW_20261018.md)：原S01服务尾图同字节接first_frame，一次原ID`cgt-20261018222555-js2z2`，720×1280/7.104秒/原生音轨，服务143秒。文件SHA/包及82份旧文件核对，父回执不改、继续侧记单列；当前待用户审片，不续S03、重试或发布，旧文本停止及失败2/10保持。

2026-10-18用户选择“先合成完整片”，已完成[H3四段合成审片版](H3_DENSE_OFFICE_ASSEMBLY_20261018.md)：《这份申请，我没提》S01—S04合成60.334秒，768×416/24fps，1448个视频包逐包SHA保持原样；AAC按画面时长对齐处理起始延迟，输出起点与DTS核验通过。最终aligned_v3文件与来源回执已保存，仍awaiting_human_review；未观看听音、调用模型或发布，硬件测试片未混入，旧稿/原视频/失败3/10保持。

2026-10-18用户纠正验证码异常应直接显示网页、不需点击，已按[正常静默、验证异常自动开窗](ACCOUNT_EXCEPTION_AUTO_WINDOW_PLAN_20261018.md)更新项目后台：15秒本地扫描当前human_required，原任务/锁门通过后每事件仅自动打开一次原账号窗口；失败/关闭/未知/重启不重开，恢复仍须关闭后点击完成核验。381项组合通过，22:19部署PID26916；真实事件6已自动登记job并收到法律搜索页on_opened回执，当前等待人工，不等于播放成功。此要求取代下方此前“仅点击开窗”说明；助手监控保持删除。

2026-10-18用户要求实际试游戏与模型并发，已完成[游戏与H3硬件实测](H3_GAME_CONCURRENT_TEST_20261018.md)：游戏VampireSurvivors原PID保持，15秒768×416/12步/原生音轨H3一次生成成功，服务22分19.6秒。131样本游戏均存活，显存采样峰15.27GiB/最少余358MiB、可用RAM最低6.38GiB；用户反馈正常可玩。未测FPS，不把采样或主观反馈写成全程帧率保证。主助手核原文件/实际图与raw-summary；测试片待内容审核，不是S05，旧四段/失败3不变，无环境改动、重试或发布。

2026-10-18用户明确生成新标准首段，已完成[七秒首段实际视频与主审](S01_TIMING_V2_VIDEO_TRIAL_REVIEW_20261018.md)：已核对v4编辑候选一次提交Seedance Mini，原ID`cgt-20261018220732-5czvf`，720×1280/7.104秒/原生音轨，服务112秒；文件、SHA和容器包完整保存，待用户审片。旧59份证据及2/10保持，媒体152100 tokens单列，0新文本调用；不冒称新文本/视频通过，不使用旧尾图，不续段或重试。

2026-10-18用户取消助手监控并要求静默运行，已删除Codex账号监控account01，项目自身到期调度保留。已补[后台静默与静音运行](ACCOUNT_SILENT_BACKGROUND_PLAN_20261018.md)：Windows worker隐藏控制台，仅无界面浏览器静音，显式人工窗口保持可见，前端说明异常暂停/点击处理。227项分组通过及隔离真实无界面空白页启动/退出完成；服务PID7744健康200、五组件新鲜正常，原paused13/异常6及业务记录保持。没有真实养号通过，验证码仍须人工处理。

2026-10-18用户要求把新设置交模型重出首段，已完成[首段v2真实测试及主审](S01_TIMING_V2_MODEL_TRIAL_REVIEW_20261018.md)：MiniMax输出7秒，DeepSeek整理pass而实际SDK最终revise；主审另发现取票初态和完成时点歧义，当前仅待修候选，未生成视频。本次3次/78101，同源累计20次/383259，原20次上限用完，旧十轮停止与旧稿保持；新原生账本、纠正及STOP单列，不按删去0.1秒冒充审核完成。

2026-10-18用户点击完成后再次暂停，已核实21:31:19原身份核验成功、21:32:11搜索产生新事件5，并完成[搜索人工处理停点与加载误判修复](ACCOUNT_SEARCH_HANDLING_CONTEXT_FIX_20261018.md)：新阻塞查询/分类贯穿采集、研究和维护回执；旧smart研究停点不再误开主页，明确非精确关键词；加载期普通登录文案有界等待，真实可见验证仍暂停。主agent424项组合通过，21:41:53受控部署，新PID38780及五组件新鲜正常；原paused10、事件5和已完成请求保留，实际播放仍0，须人工核对对应搜索再申请继续。

2026-10-18用户关闭Chrome后前端仍等待，已完成[异步人工窗口与关闭状态轮询修复](ACCOUNT_MANUAL_WINDOW_ASYNC_FIX_20261018.md)：真实21:08:55关闭及锁释放证据保留，窗口操作移出Streamlit同步fragment，持久job轮询、跨会话复用原ID、重启未知不重派；全页rerun同步选中账号，唯一账号首次默认选择，绑定指标计后台暂停。主agent253项最终组合通过，21:27受控部署后五组件新鲜正常；原暂停/历史/完成请求0保持，用户刷新后无需再开旧窗口，可直接点击完成并交后台核验。

2026-10-18用户进一步要求缩短反应并核对不同说话状态的字数/秒数，已完成[逐句对白与反应v2实施和主审](PERFORMANCE_TIMING_V2_REVIEW_20261018.md)。新来源准备默认v2：声音与互动窗分开、话后额外反应默认0，完整规范进入五个文本载荷；旧硬范围与冻结不补写。主agent120项相关回归通过，渡口另存18句149汉字、6段49秒完整编辑候选与六份SDK预览；未新模型验收、录音测量或生成媒体。下方v1/60秒为此前阶段记录。

2026-10-18用户收到S03后继续，已完成[最后S04原尾帧续段](H3_DENSE_OFFICE_S04_RUN_20261018.md)：原始尾图接FL2VA，768×416/12步/24fps/15.083秒原生音轨；4项必要离线门及实际原生校验通过。唯一原ID`dc36ab8c-0587-4307-a155-0588ef9df3ae`已保存，服务13分5.7秒，主助手独立核请求/图/原文件副本SHA及容器包。四段文件齐备、1448帧约60.33秒，原尾输入谱系已记录；内容仍awaiting_human_review，无重试、额外段、合成、改剪或发布，旧失败3/10保持。

2026-10-18用户要求其他段同步处理及动作/情绪参考时长，已完成[表演估时规范、新任务接线与完整候选主审](PERFORMANCE_TIMING_REFERENCE_REVIEW_20261018.md)：项目参考区间和并行/依赖规则随brief进入五个文本阶段，旧硬范围、预算与运行不补写。主agent97项、子agent11项离线验证通过。渡口完整助手编辑候选已重排6段60秒并编译全部纯文本SDK预览；尚未新模型验收或生成媒体，不冒充正式制作交接，旧10.08秒片及反馈保留。

2026-10-18用户反馈人工窗口卡在启动，已按[启动超时及后台数据库争用修复](ACCOUNT_WINDOW_STARTUP_HANG_FIX_20261018.md)改专用轻量worker、真实打开阶段回执、BUSY/LOCKED下次定时扫描和显式离线WAL。主agent325项组合通过，隔离可见空白页42.4秒实际打开并退出；不访问真实账号，不认定平台验证已解决。19:21备份后受控部署，账号暂停和历史保持，实际服务健康以该记录验收为准。

2026-10-18用户收到S02后要求“继续”，已完成[S03原始尾帧续段](H3_DENSE_OFFICE_S03_RUN_20261018.md)：沿用S02服务原尾PNG接入FL2VA，768×416/12步/24fps/15.083秒原生音轨；主助手亲自投影对白、4项必要离线门及原生校验通过，唯一原ID`e99f734e-75fb-4b14-a5af-8110a96ea1be`已保存，服务16分4.5秒。主助手独立核实际请求/原ID历史图/原文件副本SHA及容器包，内容仍awaiting_human_review，未续S04、重试、合成或发布；旧稿/回执/失败3/10保留。

2026-10-18用户指出平台页面正常仍显示旧调度待办，已完成[后台故障提示区分与无工作写锁修复](ACCOUNT_INCIDENT_PRESENTATION_FIX_20261018.md)：经维护核查仅关闭旧issue4，平台历史issue3和账号暂停保持；后台事件须有事件后新鲜正常回执才称恢复，不引导去浏览器修数据库。暂停及无恢复请求的空检查只读拒绝，原写事务门保留，172项最终组合通过，部署验收见记录。

2026-10-18用户指出票约7秒推完后多余停留，已接入[按有效内容收尾的新任务设置](CONTENT_END_PACING_REVIEW_20261018.md)：编剧、全文审查、自然导演、整理及最终请求复审共享冻结brief，普通反应并行、内容完成即收段，参考总长不用于凑秒；旧硬范围和v9/v10冻结运行器保持。主agent86项组合、子agent14项离线验证通过。当前独立7秒S01仅候选与SDK预览，本轮0文本服务/媒体提交；旧10.08秒原片和用户反馈保留，未批准尾帧续段。

2026-10-18用户反馈“前往处理此账号”无作用，已修正为[直接打开原账号处理窗口](ACCOUNT_HANDLING_BUTTON_FIX_20261018.md)，共享服务核对原环境与互斥，打开失败前端显示；主agent194项组合回归、后台补充31项通过，18:42受控重启后五组件健康。部署前发现旧服务数据库写锁及扫描覆盖暂停原因，已补暂停原因保护；持锁来源未确定，原待办及暂停保持，0真实完成请求。

2026-10-18用户收到压缩稿S01后要求“下一段”，已完成[S02原始尾帧续段](H3_DENSE_OFFICE_S02_RUN_20261018.md)：以S01服务原尾PNG同字节连接FL2VA首帧，768×416/12步/24fps/15.083秒原生音轨；4项必要离线门及原生校验通过。唯一原ID`31321927-2197-4053-8536-609ea4035501`已保存，服务18分52.8秒，主助手独立核实际请求/历史图/原文件副本SHA和容器包。内容仍awaiting_human_review，原S01回执不改，继续接受旁录与具体质量判定区分；同故事3/10不重置，未续S03、重试或发布。

2026-10-18 用户明确“按这个开发”，已完成[后台异常人工处理后点击完成继续](ACCOUNT_MANUAL_HANDLING_CONTINUATION_REVIEW_20261018.md)：全局、账号登录和日志统一“处理完成，继续运行”；原身份核验通过后安排已知停止运营任务接续，未知ID/锁、暂停和策略变更门保留。344项分批验证通过，18:13最终部署；当前account01原安全验证待办与暂停保持、0真实完成请求，须用户处理后点击，不因部署自动恢复。

2026-10-18用户选择移除CORRIDOR_SIDE后的室内五视图并要求生成，已完成[完整室内首帧与压缩稿S01实测](H3_DENSE_OFFICE_FIRST_FRAME_RUN_20261018.md)：内置imagegen一次准备完整双人开场图，原生FL2VA单首帧工作流20节点、4项离线门和实际原生校验通过，唯一任务`9045f35d-ce0a-4487-b5e3-a85a988ba964`已保存；768×416、12步、15.083秒原生声音，服务17分45秒。主助手核实际图/原ID/原文件副本SHA及容器包，内容仍awaiting_human_review。新图/来源加入37项资产库，旧稿/失败3/10保留，未续S02、无自动重试或发布。

2026-10-18 用户再次强调异常应在前端显示人工处理，已补[各页面顶部全局待办](ACCOUNT_GLOBAL_EXCEPTION_NOTICE_REVIEW_20261018.md)：登录后每15秒更新所有账号未关闭异常、账号原因及处理入口；人工关闭仅处理本条，新事件重新展示。71项相关验证通过，17:38部署；原account01人工安全验证暂停与原播放ID保持，0新增平台请求。

2026-10-18 用户要求养号按设置自动启动，已完成[自动播放接线与真实启动](ACCOUNT_AUTOMATIC_PLAYBACK_REVIEW_20261018.md)：按账号持久设置、后台每分钟扫描、有界异步播放及共享异常/未知任务门，212项组合验证通过。仅 account01 启用24小时/20条/90秒/20分钟，自动点赞评论关闭。17:28实际自动派发，原登录身份核验通过，但相关搜索触发人工安全验证，17:29账号已持久暂停，实际播放0；前端有待处理异常，须人工处理再申请恢复，不能把服务心跳正常写成养号已完成。

2026-10-18用户要求查找人物各方位/细节图及环境多方位图，已找回[五张完整设定及场景原图](../data/visual_asset_library/reference_recovery_20261018/README.md)：两张原人物设定板、旧六格空间板及后续办公室/走廊样板。旧六格板后来明确退回；原两人物身份服装和后续室内/走廊的确认范围各自保留。当前超市完整多视角包在所查来源中未找到，不把旧办公室或单张H3走廊图冒充其已齐备。只检索展示，未更换试片真实输入或新增媒体。

2026-10-18 用户退回低清试片后，已按实际请求展示三张原始参考图，主助手完成[约60秒4段的新压缩稿](H3_DENSE_SCREENPLAY_REVISION_20261018.md)：缩减重复交锋，增加关键神情近景与每拍信息变化，明确桌椅/两人/纸笔初态及交接。环境原图是走廊机位，与室内桌边开场不一致；本轮仅修稿与展示，0新媒体调用，旧片人工退回独立保存，同故事已知3/10。新稿未进入旧12段编译入口，后续须重新核对定帧及实际输入。

2026-10-18 用户要求“再来一段试试”后，已完成[新稿H3低清单段真实实测](H3_POSITIVE_SPEED_TRIAL_RESULT_20261018.md)：S01一次、768×416、12步、原生带声音约15秒；服务执行40分47.9秒，对照旧段中位88.21分钟，观察耗时减少53.7%。完整文件已保存待人工审片，未续第二段，未改变环境或加载Turbo；具体原ID、授权、哈希与回执见独立试片目录，不重启旧整片批次。

2026-10-18账号后台与登录会话复用已接入，见[实施与恢复记录](ACCOUNT_AUTOMATION_RECOVERY_REVIEW_20261018.md)：原会话核验、持久异常暂停、前端自动状态更新、人工环境互斥与恢复探测。account01先前异常暂停完整保留；同日16:59后后台复用原登录核验同一绑定身份通过，恢复active及原定时计划，无重新扫码，不自动换绑、播放互动或新增媒体/发布。当前以最新后台及实际回执为准，不能只看网页健康判断账号登录。

2026-10-18按用户“改造重新输出一版给我”及“可以再测试5轮+5”接入独立[自然导演与实际请求整包流程v10](NATURAL_DIRECTOR_V10_REVIEW_20261018.md)：新小说/原创共用MiniMax完整自然创作、DeepSeek忠实整理、实际SDK编译及最终全文整包审核，新来源另接v11单次证据恢复协调器。渡口第3轮文本通过，19段132秒；225项新离线回归通过。10轮已用完并停止：家庭5轮、新职场2轮仍未通过完整导演，通用流程不能写成全通过，实际调用26次/284946 tokens。旧v8/v9失败、未决和消耗保持，不迁移或清零；旧账号选题、素材/尾帧与新媒体POST未迁移，新视频0次。下方v9/v7等为此前阶段记录。

2026-10-18 用户人工退回超市 H3 成片后，主助手亲自重写《这份申请是谁提的》，并完成独立正向内容编译与实际输入核对，见[H3 新稿与输入修订](H3_POSITIVE_SCREENPLAY_REVISION_20261018.md)。12 段约 3 分钟，21 项离线测试和 S01 原生工作流校验通过；仅准备新稿、提示词、参考映射及工作流预览，0 新媒体提交，不能恢复旧批次冒充本轮已生成或通过。

2026-10-18 小说改编新任务默认进入独立 v7，见[全流程开发、主审与真实测试](NOVEL_FULL_FLOW_REVIEW_20261018.md)。正文采集/导入、MiniMax 完整创作、DeepSeek 同稿场记/九维审核/问题核实、程序门、有界返修、导演分段和导演全文复审已接入同一原生账本及实际 LangGraph/SQLite。最终组合离线回归1061项与独立复验3项通过；真实结果和适用范围以该报告及原生文件为准。旧v3/v5/v6停点不追改通过，旧书20次/310301、剩余0保持；视频人工审核和发布规则保持。下方10月17日的“待接线/网页v3”等文字是当时阶段记录。

2026-10-17按用户“你验证开发”完成独立[小说逻辑 P0/P1 核心与主审](NOVEL_LOGIC_P0_P1_REVIEW_20261017.md)：场记状态候选、问题核实/去重、原生 pass 程序门、只读容量及独立离线 CLI；真实旧三稿三审只读回放，不改原结论。构造规则案例不代表自由文本语义质量；当前网页仍 v3，LangGraph/新原生派发接线与真实新稿尚待 P2/P3。本书20次/310301及容量0停点不改，无新模型或媒体调用。

2026-10-17已完成[Claude Code文档交叉核对与主审取舍](NOVEL_TO_VIDEO_SCREENPLAY_CLAUDE_REVIEW_20261017.md)：用户明确同意仅发送方案文档，实际工具Claude Code 2.1.91/DeepSeek-V4-Pro。首轮提出六项架构缺口，主agent修成v1.1，第二轮认为可进入P0/P1、无阻断问题；保留四项实施清单。两轮文档审查实际5个服务响应，独立记账；本书20次/310301及停点不改，未开发新生产模块或生成媒体。

小说改编分支的目的、总体架构、主要设计和阶段路线，优先读[小说转视频剧本架构方案](NOVEL_TO_VIDEO_SCREENPLAY_ARCHITECTURE_20261017.md)。该文区分当前v3、拟增场记/问题核实、导演分段与后续媒体闭环；属于方案，不代表新图或生产质量已完成。

2026-10-17保存[小说专用Agent与现实逻辑修复方案](NOVEL_AGENT_LOGIC_WORKFLOW_PLAN_20261017.md)：拟增场记事件/状态账与问题核实/去重，参考LangGraph编排和FilmAgent协作机制。区分段首概述与同一动作展开、合理改编与实质新增事实；记录此前主审确定性过强的补正。当前为官方资料核实及方案，未安装/实现新图、无新模型/媒体调用，不改变原20次/310301停点。

2026-10-17按用户新要求完成[小说原生文本流程与真实试跑](NOVEL_PLAINTEXT_PIPELINE_REVIEW_20261017.md)：新建“小说改编”任务默认独立v3，MiniMax直接完整文本→DeepSeek同源全文审核，不再按引用排版或writer工具交稿退稿。279项相关离线验证通过；实际3份完整稿和3次全文审查均完整返回，本轮6次/81788，累计20次/310301；内容仍revise，达到两轮整稿返修及调用上限，未交付通过稿或媒体。最新未通过稿、实际审核过严与漏检问题见交接，旧v1/v2冻结保持。

2026-10-17用户明确要求后已进行[小说新路线真实生产验收](NOVEL_ADAPTATION_PRODUCTION_ACCEPTANCE_REVIEW_20261017.md)：独立production/v2只豁免精确授权旧停点，承接旧11次/180079；本次MiniMax实际3次/48434，累计14次/228513。分析阶段两轮引用合同失败，最后缺工具停止，尚无合格剧本或全文复审。原停止及154文件未变，无媒体；离线147项通过不表示本轮真实验收通过。

2026-10-17新增独立[小说改编路线](NOVEL_ADAPTATION_ROUTE_REVIEW_20261017.md)：后台侧栏“小说改编”或`scripts/run_novel_adaptation_v1.py`，支持正文采集/导入、背景角色主线高潮分析、选角与改编规划、完整剧本和同稿全文审查/有界整稿返修。对白允许改写，引用与身份由程序管理。147项离线组合验收通过；本轮无真实模型/媒体调用，旧小说11次/180079 tokens截断停止不迁移、不重领。

2026-10-16新增独立[账号选题到目标小说完整创作](ACCOUNT_NOVEL_CREATION_REVIEW_20261016.md)：当前选题页的小说账号分支接入本地选书、实际章节正文冻结、MiniMax完整创作/DeepSeek审查、最多两轮整稿返修和原任务恢复。CLI为 `scripts/run_account_novel_creation_v1.py prepare/preview/execute/inspect`。机器文本完成与用户采用分开；本轮只有离线验收，不迁移v23/旧任务，不自动采集新书、生成媒体或发布。

2026-10-16用户要求的[番茄直取真实试跑与事件稿修复](NOVEL_PLATFORM_TEXT_EVENT_REPAIR_REVIEW_20261016.md)已完成选书/第一章实际采集，独立事件续行32项离线验证通过；真实执行累计11次/180079 tokens，在第二份新稿输出截断处按规则停止，尚无通过的完整剧本或同稿全文复审。旧9次账本与新续行关联保留，持久接管门禁止旧入口分叉；这不表示账号运营/媒体链路已闭环。

2026-10-15新增[项目自有资产库](PERSONAL_ASSET_LIBRARY_PLAN_20261015.md)：统一检索入口`data/visual_asset_library/personal_catalog_v1`记录现有人物、场景、版本、文件身份与历史审核范围。准备参考图先查该入口；原生产兼容库`reusable_assets.json`及资格/审核门保持，入库不代表当前选角或视频批准。

2026-10-12新增[可恢复组合工作台交接](CREATIVE_STUDIO_COMPOSITION_REVIEW_20261012.md)与[长期上下文](CREATIVE_STUDIO_PERSISTENT_CONTEXT.md)：空间白模、实际导演图像/媒体载荷区分、SQLite持久DAG、MCP Schema能力门和独立CLI已组合。进入新工作台先读这两份；默认v23与原生产冻结不迁移。当前导演仍7/7、剩余0，新入口只做离线准备和原ID恢复建议，不能把本地编译或白模当有效导演/视频质量通过。基线及恢复工具见交接。

2026-10-12当前停点已更新为[自主接入、真实文本测试与诊断修复交接](CREATIVE_CAPABILITY_PRODUCTION_ADAPTER_REVIEW_20261012.md)：SDK能力预检、原素材索引和独立v5生产入口已接通，生产前354项主agent回归与179项独立复核通过。518–520三份MiniMax整片导演完整返回但排时合同拒绝，累计7/7、无新表演/交接/媒体。已证实的诊断丢失正通过新适配器与子类离线修复；新请求只读预览不派发，旧冻结及默认v23不迁移。此前[能力优先计划](CREATIVE_CAPABILITY_FIRST_IMPLEMENTATION_PLAN_20261012.md)和[263项阶段交接](CREATIVE_CAPABILITY_FIRST_REVIEW_20261012.md)保留为本轮前一阶段证据。

2026-10-12已补充[模型能力与环境核对](CREATIVE_PROVIDER_ENVIRONMENT_AUDIT_20261012.md)：官网支持、通用客户端、实际制作入口、真实接口和人工内容批准分五层记录。涉及模型/模式/素材或接口故障时，先核对该文的能力注册表与只读审计命令；不能等待用户发现能力后才查，也不能凭技能安装或文档示例放行生产。已有冻结版本不因此迁移。

此前独立v3真实测试通过新v4冻结入口执行：517工具响应完整，但整片来源遗漏/重复，原任务仍在4/4候选上限停止，尚无新表演、交接或媒体。见[真实测试记录](CREATIVE_COMPLETE_WORKFLOW_PRODUCTION_TEST_20261012.md)。旧冻结v1和默认v23不迁移。

2026-10-12共用人物完整制作链的独立v3补齐及当前实际停点，见[完整流程补齐记录](CREATIVE_COMPLETE_WORKFLOW_COMPLETION_20261012.md)。其协调器已接离线模拟服务，当前真实候选门remaining=0、0新增调用；未迁移默认v23、未形成新的生产导演或媒体交接。

本页供进入仓库的大模型或开发助手定位项目、分析任务并选择现有执行入口。核心目标是
AI 剧本与视频制作，重点支持文本阶段和视频片段的暂停、查看、返修及恢复。
本页提供导航和证据核对方法；具体授权、规则和合同仍来自用户、任务绑定及下面的权威入口。

## 最小阅读包

| 顺序 | 阅读内容 | 要解决的问题 |
|---|---|---|
| 1 | [AGENTS.md](../AGENTS.md)与当前会话 | 用户允许做什么，视频与发布审核如何执行 |
| 2 | [项目介绍](PROJECT_INTRO.md) | 产品当前以什么为核心，研究/运营处于什么位置 |
| 3 | [方向报告](../data/qa/creative_platform_refactor_20261002/direction_report.html) | 重构目标与用户的分段调试需求 |
| 4 | [当前实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md) | 已实现合同、治理版本、门禁和 F01–F07 状态 |
| 5 | [系统架构](SYSTEM_ARCHITECTURE.md)与本页的代码表 | 到哪些模块核对实际行为 |
| 6 | 目标任务的 state.json、materials.json、阶段/媒体回执 | 本次任务实际绑定什么、停在哪里、哪些结果可复用 |

若只分析项目，先读前五项并核对相应代码；未指定具体任务时不要随意选一个历史 run 当作当前任务。
若恢复任务，先读第六项再决定命令，不凭最新文档推断旧任务采用了新规则。

最新用户要求与既有有效授权优先。冲突时查清日期、任务范围和冻结身份，并把无法核实的部分记为未知。
当前实现描述工作目录；治理包和 run 中保存的合同、请求及审核决定描述它们各自的版本。
单片特许、历史方案、目录名与旧通过记录都不能扩大当前权限或替代本次证据。

## 产品方向与完成范围

主链为：创作简报/故事来源 → 完整剧本与复审 → 导演安排与分段分镜 → 实际请求预览 →
明确生成当前段 → 用户审核 → 批准原尾帧续段 → 合成 → 用户整片审核 → 独立发布及核验。

核心流程与已发现 P1 问题已有离线闭环。v23 修复在途反馈被保存覆盖：通过短状态提交锁、不可变命令、
派发门和实际消费反馈 ID 解决；新反馈继续待修，原调用、token、返修及失败预算不重置。

F02 页面完整操作链/文本派发前预览、F03 执行锁及旧环境恢复、F04 核心责任拆分和 F05 显式字段来源
仍待完善；F06 人工质量和 F07 真实服务/媒体格式/浏览器链路仍待验收。当前包 28 候选、0 人工金标、
0 合格留出，不能宣称创作质量或收益提升。后续状态只在证据到位后更新[当前实现](CREATIVE_WORKFLOW_IMPLEMENTATION.md)。

## 2026-10-03 离线计划修订

选定487稿的单次缺工具恢复使用独立入口，见[2026-10-11完整缺工具响应恢复](CREATIVE_BOUNDED_FORMAT_RECOVERY_20261011.md)。不迁移v23默认或旧冻结任务；实际生产结果查新入口的不可变回执。

v23基线之后新增了状态组前提、schema字段隔离、manifest绑定补丁校验与完整计划内容返修修复，
见[证据分类、最小修复及分工评估](CREATIVE_PLAN_EVIDENCE_AND_REPAIR_20261003.md)。
这些改动尚未注册为新的生产治理包；默认目录仍为冻结v23。当前源码与v17/v23绑定不符时，
调用前门禁必须停止，不能改写冻结哈希或静默迁移。测试使用独立假服务治理夹具，
离线通过不表示真实创作质量通过。旧任务仍为needs_attention，预算及历史不变。

## 版本与默认值

- 当前新治理任务默认注册目录为 `data/creative_governance/20261002_v23_feedback_consistency`。
  这是治理包版本，不是所有任务的提示词或审核版本。
- [运行入口](../scripts/run_creative_workflow.py)的普通新原创默认模型分工为创作/审查配置，文本审核通常是 v5；
  [核心运行器](../src/content_factory/creative_workflow.py)的生产协议未显式指定时仍可为 legacy。
- 新治理任务必须显式采用 `--production-protocol governed_production_v1` 与
  `--review-policy-version evidence_review_v6`，并满足对应模型/编剧配置约束。当前页面不提供完整协议选择。
- 恢复旧任务沿用 `model_profile`、`writer_prompt_version`、`review_policy_version`、`production_protocol`、
  `rule_registry_binding`、材料和预算；不能因仓库现在是 v23 就补写新绑定。
- 新任务 CLI 的预算取 [v5 配置](../config/creative_workflow_budget_v5.json)：20 次调用、500000 reported tokens、
  8 次结构修复、5 轮共享内容返修。旧任务继承原值；内容返修与全文复审均占调用预算。
- 默认同稿视频失败上限为 10，技术失败和用户拒绝按现行媒体账本累计。新故事使用既有登记入口，
  同稿不能通过换目录、改焦点、删登记或改状态重领额度。
- 源码/规则绑定不符时在调用前停止。旧环境恢复或只读的边界见 [MIGRATION.md](../data/creative_governance/20261002_v23_feedback_consistency/MIGRATION.md)。

## 代码定位

| 问题或责任 | 先读实现 |
|---|---|
| 来源、简报、任务登记和预算参数 | [run_creative_workflow.py](../scripts/run_creative_workflow.py)、[creative_workflow_inputs.py](../src/content_factory/creative_workflow_inputs.py) |
| 核心文本编排与模型调用 | [creative_workflow.py](../src/content_factory/creative_workflow.py) |
| 完整新稿返修 | [creative_full_script_revision.py](../src/content_factory/creative_full_script_revision.py) |
| 导演与分段安排 | [creative_segmented_director.py](../src/content_factory/creative_segmented_director.py) |
| 自动/断点/单步阶段控制 | [creative_stage_runtime.py](../src/content_factory/creative_stage_runtime.py) |
| 冻结输入、结果与字段投影 | [creative_stage_contracts.py](../src/content_factory/creative_stage_contracts.py) |
| 当前/历史版本、反馈与 resolution | [creative_stage_debug.py](../src/content_factory/creative_stage_debug.py) |
| 在途反馈、停止及派发顺序 | [creative_state_store.py](../src/content_factory/creative_state_store.py)、[creative_execution_control.py](../src/content_factory/creative_execution_control.py) |
| 文本复核证据与交接门 | [creative_review_gate.py](../src/content_factory/creative_review_gate.py)、[creative_governed_runtime.py](../src/content_factory/creative_governed_runtime.py) |
| 预览、候选、责任反馈及合成 | [creative_media_workbench.py](../src/content_factory/creative_media_workbench.py) |
| 单段提交、原 ID 查询与失败账本 | [creative_segment_execution.py](../src/content_factory/creative_segment_execution.py) |
| 用户媒体决定和批准身份校验 | [media_review_policy.py](../src/content_factory/media_review_policy.py) |
| 成片交付、发布核验与运营回接 | [creative_delivery.py](../src/content_factory/creative_delivery.py)、[douyin_adapter.py](../src/platform_adapter/douyin_adapter.py) |
| 人工样本、留出、评分和费用 | [creative_quality_evidence.py](../src/content_factory/creative_quality_evidence.py)、[creative_evaluation.py](../src/content_factory/creative_evaluation.py) |
| 创作页面 | [creative_workflow_dashboard.py](../src/web/creative_workflow_dashboard.py)、[creative_workbench_panel.py](../src/web/creative_workbench_panel.py) |
| 队列和迁移就绪 | [queue.py](../src/scheduler/queue.py)、[runner.py](../src/scheduler/runner.py)、[migration.py](../src/shared/migration.py) |

用 `rg` 按字段、函数或错误定位，再读相关调用链；核心 runner 较大，避免一开始加载整个文件和全部 QA 目录。
模型角色、模板和默认配置应沿实际调用的导入路径核对，不能根据文件名猜测正在使用哪个版本。

## 执行入口与副作用

所有脚本路径相对仓库根目录；命令参数以该版本的 `--help` 和绑定回执为准。
下面是操作导航，不自动授予外部调用权限。用户已授权的范围持续有效，执行前核对该范围及预算即可。

| 入口与操作 | 行为及副作用 |
|---|---|
| [debug_creative_workflow.py](../scripts/debug_creative_workflow.py) RUN inspect / compare | 本地只读阶段、版本和差异，不调用模型 |
| 同入口 feedback / stop / resume | 记录本地命令；feedback 传所见双哈希，resume 只解除停止意图 |
| [run_creative_workflow.py](../scripts/run_creative_workflow.py) --next-stage / --stop-after-stage | 执行文本模型并可能付费；按原参数恢复，同一运行器保留预算 |
| [compile_creative_seedance_segments.py](../scripts/compile_creative_seedance_segments.py) RUN OUTPUT | 本地编译并冻结预览；返修交接按实际情况使用 --revised |
| [creative_workbench.py](../scripts/creative_workbench.py) RUN prepare-segment | 本地准备单段计划，绑定实际首帧/前段批准原尾帧 |
| [run_creative_seedance_segment.py](../scripts/run_creative_seedance_segment.py) preview PLAN --output-dir DIR | 本地生成实际请求预览并写预览回执，不提交生成任务 |
| 同入口 submit | 明确提交当前段，可能付费；pending 反馈、未知任务、待审或额度门阻止新提交 |
| 同入口 query | 续查已记录原 ID 并更新本地回执，不创建替代任务 |
| creative_workbench.py RUN inspect-media / register-candidate | 本地核对或登记已有候选及来源 |
| 同入口 review-media 或 [review_media_candidate.py](../scripts/review_media_candidate.py) | 按用户实际决定写人工回执；工作台路径还可登记秒点与责任证据 |
| creative_workbench.py RUN assembly-chain / assemble --execute | 核对批准链，显式运行本地 FFmpeg 合成；输出仍待整片人工审核 |
| 同入口 prepare-delivery | 本地生成已批准完整成片的发布预览 |
| 同入口 publish --execute | 对绑定账号执行浏览器发布，产生外部提交及锁 |
| 同入口 verify-publish / collect-operations | 访问原账号/作品核验或取指标，写对应本地回执，不重传 |
| 同入口 collect-quality-case / annotate-quality / freeze-quality / quality-report | 本地采集与评分；人工标签只能引用真实人工判定 |

### 分析任务的安全起点

以下示例只检查本地已有任务。路径及 stage_id 必须替换成实际值：

```powershell
$runDir = 'D:/IT/ai_douyin/data/creative_workflows/实际任务目录'
& '.venv/Scripts/python.exe' 'scripts/debug_creative_workflow.py' $runDir inspect
& '.venv/Scripts/python.exe' 'scripts/debug_creative_workflow.py' $runDir compare --stage writer_script
& '.venv/Scripts/python.exe' 'scripts/creative_workbench.py' $runDir inspect-media
```

不要把分析请求解释为授权新模型调用、视频生成或发布。需要执行时使用当前服务/CLI，并保存实际回执，
不要手写成功状态、人工批准、resolution、状态索引或预算账本。

## 任务证据读取顺序

默认创作目录在 `data/creative_workflows/`；实际目录以逻辑任务登记和用户指定为准。

1. `materials.json` 与 `state.json`：来源身份、协议、模型/提示版本、预算、调用、停点和待办反馈。
2. 对应 `<stage_id>.json`：真实请求、原响应、技术校验和输出；已归档记录用于核对历史。
3. `.creative_debug/inputs/`、`results/`、`artifacts/`、`index.json`：冻结输入/结果、不可变版本和索引。
4. `.creative_debug/feedback/` 与 `.creative_debug/state_commands/`：用户原话、精确版本、resolution 和命令顺序。
5. `.creative_debug/dispatch_permits/` 及审核包/决定：派发许可、消费反馈、文本核实与交接依据。
6. 媒体 `receipt.json`、用户审核回执、源版本链、原视频/原始尾帧：原任务 ID、技术/内容状态和批准身份。
7. 交付目录的发布回执、原声明操作证据、作品核验和运营文件：核对准确账号、作品与未决状态。

记录 schema、来源路径、哈希、阶段和时间。目录叫 final、passed、complete 或截图存在都不自动证明对应验收完成。
不要批量读取无关真实任务、认证信息或所有样片；报告中只保留必要证据，密钥和会话凭据不写入文档。

## 状态如何处理

| 状态或条件 | 正确下一步 |
|---|---|
| debug_breakpoint | 正常断点；按原目录、材料和预算运行下一阶段 |
| user_stop / execution_control.action=stop | 保留在途结果；resume 后再按原入口恢复执行 |
| debug_revision_required / pending must_fix | 先返修最早责任阶段，下游不得新增调用；在途响应保留 |
| script_review_pending 或聚焦审核待核实 | 阅读当前全文/证据包，按现有核实合同记录真实判断，不手写放行 |
| needs_attention | 查看 last_error、回执及绑定，先定位具体原因 |
| outcome_unknown 或未知外部调用 | 有 ID 续查原任务；无 ID 对账，不自动重试或换目录 |
| blocked_before_dispatch / blocked_before_submit | 核对是否确未派发及保留的预留；按实现恢复，不删除记录补额度 |
| media_handoff_pending_capability / reviewed_revision_media_handoff_pending_capability | 已形成文本交接；核对能力、源版本、文本门及计划后再准备媒体 |
| technical_status=succeeded + awaiting_human_review | 用户审查视频，助手只核对服务和文件；不写内容 passed |
| approved / rejected | 核对真实用户决定和原片/尾帧身份；拒绝回到有证据的责任阶段 |
| post_publish_verification_pending / awaiting_verification | 核验原作品并保留提交锁，不能重传 |
| 源码/规则/输入哈希不符，预算耗尽或遗留执行锁 | 在新增调用前停止，核对原绑定、进程、原 ID 和回执，按恢复边界处理 |

停止不是取消远程调用。短提交锁的系统释放不等于文本/媒体执行锁可以直接删除。
F03 工具未完成前，对未知外部副作用不做盲重发；也不能用 `--retry-unconfirmed-transport` 自动绕过未决结果。

## 内容和发布不可跨越的边界

- 视频内容由用户人工审核。助手不主动抽帧、听看、ASR 或调用音画审核模型，不从技术成功推断通过。
- 用户明确批准当前原片和服务原始尾帧后才续下一段，身份变化使批准失效。历史单片声音待审特许不推广。
- 文本返修保持主题与用户要求，采用本次完整新稿并复审；不把旧拍与新拍拼接伪装成模型完整输出。
- 文本验证只证明明确合同和证据，不能把情绪标签、反应窗口字段或连续性自动解释为实际表演效果。
- 合成后仍须用户整片批准，发布必须引用当前批准的完整成片。
- 发布采用浏览器，主动选择并读回平台“内容由AI生成”；话题、文案及平台自动标签不替代主动声明证据。
- 虚构剧情简介首部为“剧情虚构，非真实事件。”；真实纪实需显式关闭 fictional_story，仍执行实际适用的声明要求。
- 发布待核验不记最终完成，不解除锁或重传；仅回接绑定账号与准确作品，缺失指标为 null。

## 验证与分析输出

反馈边界先看 [test_creative_feedback_consistency.py](../tests/test_creative_feedback_consistency.py)；
版本/重放、媒体/交付和治理分别看 [test_creative_stage_debug.py](../tests/test_creative_stage_debug.py)、
[test_creative_remaining_refactor.py](../tests/test_creative_remaining_refactor.py)和
[test_creative_governed_protocol.py](../tests/test_creative_governed_protocol.py)。

执行离线验证时使用独立数据库、Mock/FakeClients、断网环境和新 QA 输出目录，保留作者原回执。
测试应覆盖实际触发及阻断/恢复行为。文档更新核对链接、入口参数和冻结哈希即可，通常无需重跑模型或全部业务回归。

[v23 作者回执](../data/qa/creative_platform_refactor_20261002/feedback_consistency_v23/acceptance_report.html)
含 756 项通过；[独立复核](../data/qa/creative_platform_refactor_20261002/v23_confirmation/confirmation.json)
另运行 18 项边界，未全量重跑。历史 real receipt replay 未在该验收执行或计通过；
保留的兼容限制以验收报告为准。不要把不同人的计数相加，或把夹具的人为批准计入质量金标。

分析结论应先给当前核心功能/停点，再分开列实证缺陷、实现缺口、架构改善和真实证据缺口。
每项注明触发条件、源文件/回执、影响、建议及验收标准；已验证与推断在对应条目内标清。

交接时至少保存：用户目标与授权、run 路径、任务/协议版本、当前阶段及待修反馈、原外部 ID、累计预算、
改动文件、已运行检查、未运行内容和下一步。源码/规则改动按治理约束新建版本，冻结旧包不改。
本导航及工作目录说明可以更新，但不能将文档变更伪装成旧任务已经迁移或功能已完成。


## 2026-10-03 响应验收与模块合同离线修订

已实现统一响应故障分流；缺工具、截断、空正文及未知结果不再自动重派，原响应与用量保留。
新增整片规划/局部表演/确定性编译的显式离线合同，检查跨拍状态、对白表演窗口及下游失效。
见[实现、合同与验证边界](CREATIVE_RESPONSE_AND_MODULAR_CONTRACT_20261003.md)。
新合同未接生产派发，未注册生产治理包，旧任务绑定、预算和历史不变。
旧运输重试参数保留解析兼容，不再绕过未知请求对账；测试通过不表示创作质量通过。


### 修复后真实文本接口测试（2026-10-03）

真实调用3次已使用原任务剩余额度：共享实际24/24、379026 reported tokens，父冻结state仍保持21/24。微型工具通过，两次整片规划合同失败；局部表演、全文复审和制作交接未完成。不得只读父state再次使用3次额度。详细证据、源码演进和离线修复见 [生产接口测试报告](CREATIVE_PRODUCTION_INTERFACE_TEST_20261003.md)。旧v17/v23绑定未迁移。


### 六组小上下文规则三轮真实对比（2026-10-03，新增授权18次）

用户明确授权新增最多18次后，按冻结矩阵执行三轮。基础Schema业务合同0/3；中文编号/路径/关系说明及其四种增强版本各3/3，全部正常工具返回。只证明该小任务的规则遵守，未形成整片导演计划、局部表演或制作交接，也不证明服务严格解码或创作质量通过。

该规则矩阵结束时共享实际累计42/42、398343/500000 reported tokens，剩余调用0；原父state及原24次诊断记录保持历史值，不能从它们重新领额度。未迁移v17/v23或重置账本。本轮成功安全envelope已保存，历史长分析服务端原因仍未知。详见[规则对比报告与产物](MINIMAX_SMALL_CONTEXT_RULE_TEST_20261003.md)，离线回归581项通过。

### 模块分工真实试跑与停止位置（2026-10-03）

用户已明确新增MiniMax文本调用不逐次申请；保留原累计500000 reported tokens上限。
矩阵结束后的新增7次真实文本调用，使共享累计达到49次、490913/500000，剩9087。
最新完整新稿尚未完成有效全文复审：DeepSeek在11000输出上限处截断，响应被拒绝且没有自动重发。
没有可采用的整片导演计划、逐镜物理表演或制作交接，不能记创作质量通过。
线性steps及多镜源引用合同已离线验证，物理编译适配仍待完成；旧v17/v23、预算和回执未迁移或重置。
详见[实际回执、原因分类、183项验证与下一最小改动](CREATIVE_MODULAR_BD_TRIAL_20261003.md)。


### 2026-10-04 明确恢复后的文本续行

用户授权后续文本暂不设总token硬限；旧49次/490913与原500000上限保留为冻结历史。新增物理适配v4、无损审查传输v8及独立续行入口，旧v17/v23不迁移。当前离线316项及7个subtests通过，不构成整片质量通过。见[续行合同、产物与验证边界](CREATIVE_TEXT_CONTINUATION_20261004.md)。


### 《这次我先走》S6制作版本记录（2026-10-05）

当前完整剧本、冻结代码、停点和后续确认见[版本与制作流程记录](THIS_TIME_I_LEAVE_S6_PRODUCTION_RECORD_20261005.md)。当前仅采用为导演输入，原70请求未知；保存文档不解除派发门禁。

## 2026-10-05 S6完整实际表演与文本制作交接

独立S6任务已得到第77次整片导演规划、九份源核对的完整局部实际表演、91.442857秒确定性编译及第158次有效全文审查。[完整正文](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/resume_20261005_v15/DELIVERABLE_s6_d6/CREATIVE_REVIEW_COPY.md)与[后续制作交接](../data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/resume_20261005_v15/DELIVERABLE_s6_d6/MEDIA_HANDOFF_REQUIREMENTS.md)现可直接审阅，详见[版本与实际执行记录](THIS_TIME_I_LEAVE_S6_PRODUCTION_RECORD_20261005.md)。状态为等待用户内容/审美确认，不代表实际声画或用户质量通过。

`python scripts/show_s6_text_handoff_v16.py`仅本地重验并幂等保存完整交接，不派发模型或媒体。生产独立v15冻结183源码，保存器v16单独SHA记录；默认平台v23和旧任务未迁移。完整原稿/R01仍进入实际模型请求，MiniMax创作、DeepSeek全文审查未换模型；旧70结果未知及64010预留保持，旧账本未重置。

当前媒体0，实际图片0；后续按少量样板确认、选定实图回传导演、核对长句段长承载、逐段生成并等待用户人工审核推进。助手不主动抽帧/听看/ASR或音画审核模型。问题分类与验证边界见[交接证据说明](CREATIVE_S6_HANDOFF_EVIDENCE_20261005.md)。


## 2026-10-06 S7完整文本交接

[完整导演与表演阅读稿](../data/production_revisions/this_time_i_leave_s7_review_evidence_repair_20261006/DELIVERABLE_s7_d1/CREATIVE_REVIEW_COPY_READABLE.md)现包含十镜62.26秒与完整原稿、资产及制作条件。265全文审查有效，0未决必修问题；这是文本交接完成，仍待用户内容/审美与实际声画确认。过程和故障分流见[实际记录](THIS_TIME_I_LEAVE_S7_REVISION_20261005.md)。

独立v45通过原导演上下文/当前执行排时分离、共用表演范围及工具格式/本地业务验收分离完成，旧冻结v17/v23与源码回执不改。机械当前动作翻译仅消费真实当前原动作和起态，明确不携带R01全文；创作、导演和实际表演请求确实消费完整S7/R01。累计消耗完整承接，无自动重试，0媒体。用户实际确认后记录原话与交接SHA；少量样板选定并回传导演后再核对媒体授权与段长。


## 法律核心标签获取与分析（2026-10-07）

法律号采用一个核心检索词及多个有来源支持的关联议题。当前新入口、开源工具取舍、离线证据与真实登录验证阻塞见[法律核心获取与分析](LEGAL_CORE_TAG_COLLECTION_20261007.md)。计划准备：`scripts/prepare_legal_core_collection.py`；真实元数据执行：`scripts/run_account_video_research.py --legal-core-plan`。计划页数不等于实际访问数；旧关系不证明当前热度；本入口不派发编剧、媒体或发布。


## 2026-10-07 登录恢复后的新批测试

法律号原绑定身份与登录态已恢复，新批154个去重视频通过样本门槛。真实故事方向测试发现口播配置与叙事目标冲突，以及必填字段遗漏；完整结果、来源和未解决问题见[法律新批与文本真实测试](LEGAL_FRESH_BATCH_TEXT_TRIAL_20261007.md)。历史登录阻塞及离线结果保留，不能将其当最新状态。


## 2026-10-08 法律标签族与图谱输入

新增[法律标签族、共现图谱与创作接线](LEGAL_TAG_FAMILIES_GRAPH_20261008.md)：使用既有154视频批次生成实际成员、847条标签共现、角色隔离和有限选题邻域，并准备MiniMax/DeepSeek传输格式；本轮只做离线分析和模拟接线，没有付费调用或完整新剧本。原研究音画门禁、旧任务来源与账本不迁移。


## 2026-10-08 完整法律正文续行

用户已明确要求继续生成剧本，实际指令绑定此前披露的修正冲突。完整正文、全文返修、证据编号审查、短事件链与标签建议隔离的真实过程见[完整法律剧本制作记录](LEGAL_COMPLETE_SCRIPT_PRODUCTION_20261008.md)。原方向、旧账本与冻结记录保留，正文质量与接口/离线验证分开记；导演、表演和媒体不继承为本稿已完成。


### 2026-10-08 最新完整法律正文停点

298/300形成[完整四拍法律剧本](../data/production_revisions/legal_trend_text_trial_20261008/round_11/DELIVERABLE_r8/FULL_SCRIPT.md)及有效同稿全文复审，当前0未决必修、四项情绪要求均satisfied，待用户实际采用正文。审查原六条意见由模型有据重新归类，原记录和正文不改；186离线回归通过，本轮21文本/351888 reported tokens，媒体0。导演输入仅离线准备，新导演、表演、编译与交接未完成。全过程、审查局限和账本见[实际记录](LEGAL_COMPLETE_SCRIPT_PRODUCTION_20261008.md)。


### 2026-10-08 法律正文已采用、导演与实际表演完成

用户实际采用298完整正文后，完成304整片导演、306–309四拍实际表演和311有效全片文本复审，11镜230.4秒的[完整导演/表演/制作交接](../data/production_revisions/legal_director_performance_20261008/round_06/DELIVERABLE_d1/DIRECTOR_PERFORMANCE_READABLE.md)现可审阅。原步骤23/对白16保持，0未决必修，89必要离线检查通过；原稿已采用，具体导演与审美/媒体尚待确认。原对照表与具名对象修复、310引用不足拒绝及审查局限、实际账本见[制作记录](LEGAL_DIRECTOR_PERFORMANCE_20261008.md)。本轮11文本/314511 reported tokens，累计311/5335773，媒体0；旧账本、未知请求与默认v23不改。人物/背景实图及真实声画未完成，不是视频生成或质量通过。


## 2026年10月9日文案反馈台账

处理后续剧本返修、导演和表演时，先核对[文案问题统计与验收记录](SCRIPT_COPY_ISSUE_LEDGER_20261009.md)：10类文案表演、5类制作关联、3项待确认或创作取舍，包含三版法律全文可复算对比。该记录汇总现有证据，不授予调用，不替代正文采用或人工视频审核；当前339正文仍待采用。


## 2026-10-09 专业对白与来源身份分工

351完整《桌上那张纸》及352有效同稿全文复审、独立正文检查已完成，当前待用户采用。编剧使用通俗事实，专业七项用于审查；旧错误全文从v5起明确留在本地而不喂回编剧，完整R01/教学/人类反馈十二次真实请求均核实。v8来源ID归确定性编译器，创作字段原样；349零问题漏已知移纸后新增当前源交付门。新导演、实际表演、物理排时和媒体0，不能继承旧源。过程、实际全文、故障分类、离线与累计账本见[专业对白持续返修记录](LEGAL_DIALOGUE_PROFESSIONAL_REFINEMENT_20261009.md)。默认v23、旧失败和账本未重置。

### 2026-10-09 结尾收束返修与同源审查资格复核

用户指出351结尾突兀后，已完成354完整模型新稿、356同稿全文复审及独立正文检查，待用户采用。[全文与返修记录](LEGAL_ENDING_CLOSURE_REVISION_20261009.md)保存策略失败后的可演反应、未签材料带走及局部缓压；355原两条意见未删，356是资格校准后的一次全文复核，354正文未变。8项必要离线检查及真实来源/账本核对完成，累计356次/6047025 reported tokens；新媒体0，新导演、窗口与用户质量未完成。默认v23与旧预算冻结不改。


## 2026-10-09 开场信息首次出现与最小全文返修

当前362完整新稿、364同稿全文复核与独立Gate0未决必修，待用户采用。[完整正文](../data/production_revisions/legal_dialogue_refinement_20261009/round_20/DELIVERABLE/FULL_SCRIPT.md)已在实际对白明确公司结束小林工作，再递表并质问个人原因。默认治理v23不迁移；隔离编剧旧派生核对/暂缓与泛法律资料，完整R01、六教学、原反馈保留实际输入。工具简化和本地显式四拍验收、整稿另写引入新缺陷、回可靠全文作最小开场修订、一次有据资格复核及未改原意见，见[实际记录](LEGAL_OPENING_INFORMATION_REVISION_20261009.md)。本轮8文本/105358，累计364/6152383，未知/预留不变，新媒体0；新导演、表演窗口及交接未重建，不表示创作或视频质量通过。


## 2026-10-10 当前自然表演修复小样

387完整当前通知问答、388全文源复审和独立文本门已完成；单次Seedance Mini 480p修复视频8.096秒已保存，仍awaiting_human_review。局部创作移除未来全文，仅消费当前源/起态/目标及R01，全文审查仍读取全文；18项离线通过不证明演技或口型。仅当前交互，不是完整B1/全片导演交接，未迁移默认v23。见[实际过程与当前产物](LEGAL_NATURAL_PERFORMANCE_REPAIR_20261010.md)。


## 2026-10-10 电影导演 skill 适配与当前法律片应用

已核对现有comfy-director、社区导演skill及作者公开表演方法，复用既有20项标准，补充当前380的“目的—对手策略—刺激后的变化—观察—切出条件”具体分析。见[参考与当前正文应用](FILM_SKILL_ADAPTATION_20261010.md)。这是导演方法审阅记录，未生成完整新导演或接入生产合同；新增模型/媒体0，社区软件未安装执行，当前8.096秒样片仍awaiting_human_review。原正文、387/388、媒体回执及默认v23保持原绑定。


## 2026-10-10 电影方法当前开场实际制作

用户要求交接并生成同一开场一段后，完成390完整新演法、391同源全文复审、独立文本门及当前通知问答制作交接。一次Seedance Mini 480p视频已保存9.088秒，仍awaiting_human_review；原始尾帧未批准，未续段。见[实际制作与交接](LEGAL_FILM_OPENING_SAMPLE_20261010.md)。9项断网验证、实际请求和16项来源核对不证明真实演技；仅B1.S01–S03，不是完整B1/全片导演交付。旧预算/账本和默认v23未迁移。


## 2026-10-10 当前材料回合文本交接

394完整S04–S07新演法、395同源全文复审和独立门0未决必修已交接，规划13秒。392逐字音量规则及393零问题原回执保留，由完整新稿修复；18+5项断网验证不证明真实演技。见[第二回合制作记录](LEGAL_FILM_MATERIAL_EXCHANGE_20261010.md)。实际请求预览已准备但未提交，新媒体0；须先获得FILM380_OPEN01明确人工批准，再以其原生尾帧first_frame续本段。前后合计覆盖B1文本，整片导演/表演仍未交付，旧预算和默认v23不变。


### 2026-10-10 材料回合单次视频交付

用户“提交视频请求”仅授权已展示13秒S04–S07请求；前段内容未伪记通过，默认逐段批准规则未改。独立v3入口已执行一次，任务cgt-20261010181003-hkxkh保存13.088秒视频，awaiting_human_review。详情见[材料回合记录](LEGAL_FILM_MATERIAL_EXCHANGE_20261010.md)和`data/video_generation/legal_film_material_exchange_20261010/material_v2/DELIVERY_REPORT.md`。19项离线分支通过、实际接口成功和文件保存均不表示创作质量通过；同故事媒体账本37→38，无预算重置或自动续段。


## 2026-10-11 第三段人数与空间连续返修

487稿第三段已按用户反馈记rejected：人物位置改变、多出人物。已确认原批准尾帧没有漏传，但文字模型自行声明屏幕布局，原审查漏核其来源，实际prompt缺闭合演员名单。独立合同v5/v6和执行入口v6/v7已修闭合人物场景、原帧机位权威、全字段无来源布局验收及审查提醒与必修改分离，22+19项必要离线检查通过。真实507/508新稿被验收阻断；509完整响应抄错顶层源SHA而拒收，两轮内容返修已满，本次新视频0。累计509次/7,772,480 reported tokens，未知历史和媒体失败预算承接。后续机械身份由编译器绑定的合同v7仅离线，不采用旧509，不把测试算成创作/视频质量通过。实际请求、人工反馈、生产停点与继续范围见[返修记录](CREATIVE_CONTINUATION_SPATIAL_REPAIR_20261011.md)。默认v23、旧冻结记录和逐段人工审核规则不迁移。


### 2026-10-11 新协议续行生产结果

用户明确续行后，metadata合同v7已由独立runner v8接入487第三段测试，旧509停止与消耗保留。510完整新演法、511当前段同源全文复审通过；第三段third_v8已完整保存，12.096秒，awaiting_human_review。实际产物与scope见[第三段空间返修记录](CREATIVE_CONTINUATION_SPATIAL_REPAIR_20261011.md)，不将原487或整片质量改为通过。


### 2026-10-12 共用身份合同审计与当前拒绝

third_v8已按用户“性别改变、人物没对齐”反馈记rejected。开场/第二/第三实际请求同源且原尾输入正确，但角色只定义ID/称呼/剧情职责，缺性别外貌服装声线及角色到画中人的映射；旧资产身份服装仍待定，当前十项门未检查完整共用身份与投影覆盖。见[全片共用制作元素审计](CREATIVE_SHARED_PRODUCTION_ELEMENTS_AUDIT_20261011.md)。本轮新增模型/媒体0，不观看媒体、不修改冻结代码；新共享manifest尚未部署，不从已拒尾帧续段。旧awaiting_human_review为交付时历史快照。


## 2026-10-12 新法律来源完整文本后台测试

用户已确认先采集法律号新数据后跑完整流程。新独立接线与后台已启动，首次实际搜索触发human_required，0新样本、0模型/媒体；当前待用户在已开的验证窗口完成提示。范围、合同、离线/独立证据与实际停点见 [新来源后台实施与停点](CREATIVE_FRESH_LEGAL_BACKGROUND_REVIEW_20261012.md)。旧512导演7/7、累计520/7964215及历史未知完整保留；新批次不能重领同故事额度，不盲重启原RUN_CLAIM。只在新批样本门通过后进入完整文本/导演/表演/制作交接，本次不生成媒体或发布。


## 2026-10-15 世界框架、逐场情境与全体人物表演

用户新增要求已进入独立通用合同，规范见[世界/场次/表演说明](CREATIVE_WORLD_SCENE_WORKFLOW_GUIDE_20261015.md)，接线计划见[通用流程接入](CREATIVE_WORLD_SCENE_INTEGRATION_PLAN_20261015.md)。本会话负责通用代码和离线验证，当前样片实际重写及视频生成由另一会话推进；不要混用双方的产物和消耗。

独立world_scene_context/v1与workflow28不静默迁移默认v23/旧冻结入口。完整世界/场次/ensemble需要进入实际生成、原规划四审、同源全文审查及下游上下文；旧正文缺新字段直接拒收，不由渲染补写。正文排列序不作完成时间，动作对白可并行，动作前提仍需原生初态或有据先后。当前新入口为无网络preview/Mock，真实接口、创作质量与视频人工批准各自验收，最终接线状态以本轮实际交接为准。

本轮已完成通用合同与离线接线验收，实际入口/证据/未接入生产范围见[最终交接](CREATIVE_WORLD_SCENE_WORKFLOW_REVIEW_20261015.md)。源码及文档增量副本另存creative_world_scene_release_20261015_v1，旧入口和账本保留。
