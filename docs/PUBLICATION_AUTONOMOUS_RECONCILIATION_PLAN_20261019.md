# 原作品自主核查与项目浏览器自动交还

用户最新原话：“我浏览器全部关闭了，你甚至可以自己无线核查自己杀掉浏览器进程”。结合前文逐次追加核查与关闭窗口的说明，本轮按“无限核查”解释：对当前原作品的只读核查不再设人工逐次批准或次数上限；允许助手为部署/恢复自行关闭或终止明确属于本项目账号环境的浏览器和后台进程。此授权不包含任意个人浏览器、再次上传/发布、修改原片、付费媒体重试或评论重复提交。原批准评论仍须准确作品及声明/标签/播放器核实后幂等提交一次。

## 当前事实与实施范围

原发布1582fcdcc9274211b3aedf4aa680b1bb和原核查169d537d48094d1992acb3d2f4df707f都保留outcome_unknown；后者原native终态为not_found，评论未提交。提交锁和原授权/未知快照/失败证据保留。当前后台40968/gen16，原profile的Chrome33512仍在其后代树；用户关闭UI不代表后台worker已经退出，不能凭PID或进程名直接结束其他浏览器。refresh a201f22b8c8e4df38826e820285c730f/maintenance0c749a24cb094863a8078b13531a8444仍在原unknown后排队，账号日34/控制active42，运行租约空。

先保存这次新授权和实际快照。独立新版本接入，不改旧授权上限、旧记录或历史SHA。原v1一次核查和旧日34完整保留。

1. 管控模块：新增当前原作品的持续核查授权及审计；只给绑定账号、原unknown、PREPARED/journal/lock、指定任务的read-only核查开放续行。每次核查仍串行且有轮询间隔/单轮超时，未知发布不阻塞这一只读核查，正常发布/后台保持原门。保留原每日累计，核查授权不扩展普通发布额度；运行锁仍有效。支持已知只读失败的后续核查及新owner精确交还，不伪造旧成功。实际评论未知必须停止重复写，后续可只读查评论，不能重发。
2. 服务与浏览器模块：部署已审的完整标题/简介规范化补丁，并保存实际失败卡片的有界原生DOM结构和原生交互资格，不能只凭截图补静态假设。同原owner/profile上通过UI识别准确作品链接；仅在界面明确绑定当前唯一作品时，使用其原生详情/链接或可证明的原生作品打开动作，禁止编辑/删除/发布及猜ID。核对发布后AI/虚构说明、五tag、播放器/审核，再处理原批准评论。失败保存原生结构与截图；不分析影片内容，不读平台API/网络内部状态。
3. 部署模块：在双库写栅栏内核原owner/绑定、完整未决集合、无在途操作/租约，记录并暂停尚未执行的本账号维护排队及其原调度游标，之后恢复。按PID+create_time+父子关系+原profile/worker绑定只结束已确认的本项目后台/浏览器；不结束无法归属的Chrome。原进程退出后再做新的受限交还与新代owner接续。用户此次已授权，无需再次要求关窗口。

按AGENTS要求模块交给子agent实施，主agent审真实接线及拒绝用例，最小必要测试后冻结部署。浏览器修复必须以新的真实DOM证据为依据，fixture只算回归。各模块接口先协调，普通v1授权/业务代码路径保持历史合同。生产只核查已发作品，未取得完整证据不能写验收成功；若平台出现必须人类完成的验证码，保留现场并说明真实阻塞。

实际新读发现旧refresh租约已于1792411593.9432592触发原调度暂停：控制paused/revision43，原refresh run为outcome_unknown；对应maintenance仍queued/ownerNone/cursorNone，尚未派发。前述active42仅是上一轮停点，不是当前值。首份新授权的42字段保留为过时基线，不登记使用；另冻USER_AUTHORIZATION_CURRENT_STATE.json，SHA9dbe372c8a4168d838791fa1b3437023beadb3d13045c9232686e25e88a66447，绑定完整paused43快照。仅允许该精确暂停上的原作品核查；普通业务仍暂停。完整发布核实后按原“发布优先后恢复后台”要求，以审计CAS43→44恢复active，其他暂停或版本变化均拒绝。原43暂停证据保留，不清除维护run未知历史。


### 有界真实DOM诊断版本
另存publication_native_diagnostic_20261019检查点，原19项标题修复验收和原真实unknown不改。共享发现对唯一原标题label只读采集最多6层有界祖先的tag/role/可见性，及小范围原生anchor/button/rolebutton的短名称、title/aria、disabled/inert/viewport/hit-test等资格。有限HTML为白名单属性投影，移除input/编辑器、事件代码、URL查询/hash等；只保留原标题路径和控件壳，其他兄弟正文省略，含独立其他作品时不向外扩范围。此结构仅供确认真实界面，不作为新增点击权限或完成证据。原worker RPC已JSON透传完整diagnostic，service每次保存原回执；只接core提供的v1/v2输入router，不改浏览器启动串或core/runtime。新增1—3项本地Chrome故障DOM验证诊断有界/去密与pending不误点击，首次新生产仍需真实DOM回执，不把fixture当平台验收。

## 部署维护接续接口
独立scheduler.deployment_maintenance helper只接受这次尚未执行的原maintenance/refresh绑定，在双库写栅栏内以新部署hold审计保存原完整命令、refresh_runs和refresh_accounts游标，不改其原结果、原ID或原lease。account_refresh._gate见有效hold先暂缓新claim及过期判unknown；cron每轮先只读轮询同一原command，queued继续等待，已知真实终态才经原_finish结算同一refresh run。独立settling审计记录原终态和预期结果，使重启能识别已结算并只补审计、不再派发。未知/人工阻断不伪造成功，不新建第二维护命令。用户授权同片只读核查及精确项目进程结束，v2交还使用独立Store API与表，不改v1历史合同。

## 当前状态授权与同一授权的再次部署
实际冻结refresh run已为outcome_unknown，其对应maintenance仍queued且从未获得owner/cursor/result；旧等待超时已将控制改为paused43。旧active42授权保留，另用USER_AUTHORIZATION_CURRENT_STATE.json（9dbe372c…）冻结完整paused43。部署hold保存这一个原unknown run而不改结果；完整作品核验前普通业务保持paused43，后续核验后的43→44由core的独立精确CAS执行。
同一v2授权再次部署时，从core原生v2审计row读取当前new_owner_id/new_generation/new_owner_create_time，重新核精确PID、创建时间、树、源码和profile；未决集只接受core已验证_allowed_unresolved中的原两项及同授权带原生终态证据的只读尝试，保存所有完整快照SHA。每日计数仅记录实际day_key/daily_runs，不重置或硬写34。相同授权、原维护命令、run和cursor全等的hold只幂等复用，禁止覆盖不同任务。hold先持久化，再重新获得scheduler写栅栏并复核全部门；之后只结束精确backend父进程，由EOF关闭同profile可见/无头context，未自然退出不释放owner。


### 实际DIV卡片第二诊断
新owner34140/gen17首轮eee9954e80e54f998c680129e7197cb5的discovery-6原生回执已取得：唯一标题匹配，祖先均DIV；depth3/4/5分别96/102/103后代，a/button/role控件均为空，仍independent_card_unbound。此证据证明原诊断语义控件集合不足，不证明封面可点击或具体目标ID。
独立保存原文件及SHA，只改shared helper诊断：在既有≤160节点、最多6祖先范围补最多64个可见DIV/SPAN/IMG等局部节点的安全class token、data-e2e/aria/alt、短自身文字、矩形及pointer/hit/tabindex/img子项；优先保留图片与pointer候选。HTML投影加入已观察的短操作文字及图片alt占位，不读src/媒体、不输出查询参数，不猜class或新增任何点击规则。服务/core/runtime原冻结不改，旧11项及原native回执保留。新增1个真实Chrome DIV案例只验诊断、去密和无点击，最终仍需新生产DOM才能设计实际作品打开动作。


### 基于第二真实DOM的原生封面单次打开
原fe45c6827686444b97f518e5c801c066/discovery-8已独立保存SHA；八次同结构。原内容祖先video-card-content-Xt386b（102后代）、外卡video-card-sfaSzz/video-card-new-e033na/video-card-v2-AelUxA（103后代），同卡唯一标题、已发布与编辑/权限/置顶/删除标识；封面DIV video-card-cover-QkeRHf为pointer且可见可命中，120×160，包含原top/bottom子项，无IMG。此证据来自原生DOM，不从背景图片/网络取ID。
最小新增仅针对该已观察卡片形态的只读封面打开：同原document唯一完整标题绑定独立原卡、唯一video-card-cover-前缀DIV及原top/bottom结构、已发布/操作标识，原生pointer/visible/hit/disabled/inert/nonform门齐全并在click前复核原label/card/cover身份，才native click cover一次；绝不点top/bottom、编辑、统计或发布。无论点击结果，用原Page WeakKeyDictionary记录已派发，不能再次点击。仅同页或唯一新页准确canonical /video URL作为发现证据；非canonical仍pending，保存安全最终URL（去query/hash）及有界当前dialog/原生link/button结构，禁止猜ID/造URL/API。服务/worker/core/runtime不改。最小本地DOM案覆盖原观察类原生导航、错卡/多cover/编辑伪装拒绝及未知结果只一次；平台实际打开结果仍须新生产原生回执确认。


### 原生个人页作品modal路由的有界解析
979e9c3a8a9e46dbbf2630dc34b1a6f1/discovery-2已保存原字节与SHA：实际封面qualified、native click一次、1新页并清理成功；新页安全URL为https://www.douyin.com/user/self，query_removed=true、title空、仅导航控件，1秒读可能过早。现证据没有保存实际query键，不能宣称已观察modal_id。
仅对本次原生封面产生的唯一新popup增加总12秒以内只读UI等待，诊断保留去敏查询键名及严格数值modal_id字段。只有运行时实际URL为精确https://www.douyin.com/user/self且唯一modal_id纯数字、无重复/冲突作品字段时，才将这一原生ID作为公开/video/<ID>候选并只导航该新增页。必须最终实际URL落于该canonical、原生DOM唯一显式ID匹配且同scope唯一完整原标题caption匹配，才识别作品；query本身不是发布成功，未知路由/缺字段/错caption继续pending。普通_is_final_video_url不接受queryID，服务全部AI/虚构/tag/播放器/审核/评论门保持。
仍同Page once、只清理本次唯一新增page、原页和已有tabs不动；safe诊断不存token值/任意query数字、不读API/网络/媒体。新增2—3本地Chrome路由/DOM案，真实modal字段与最终公开DOM仍待新生产原生回执，不用fixture宣称平台通过。

本版安全验证收口：精确native安全提示使popup解析human_required/block_discovery，保留本次challenge新页，service保存回执后human_required，不评论；现v2handler停止自动续查并保留人工现场，不修改core。正常唯一新增页仍在返回前清理。公开身份scope沿原inspect：≤12可见显式ID候选且当前ID恰1，或唯一semantic article，scope内唯一video/caption并匹配原标题；返回前再核canonical与同scope身份，避免异步改路由后错关联。


### 公开作品页真实DOM缺口：只增结构诊断
已保存gen20/40920的cbf0b53617fb4a91bd9d67f1bb526225/discovery-2原生回执与SHA：实际modal_id7698306800386379018、canonical/video同ID已到达，document_title匹配本片；但当前显式ID候选0、semantic article候选0，因此仍pending。页面title不作为作品scope或发布完成证据。
仅对_MODAL_IDENTITY_JS补有界原生渲染结构诊断：最多12个实际可见video/完整原标题候选，沿各原节点最多8层祖先记录tag/安全class token/role/data-e2e、最多12个直接子项结构与视频/caption数量，遇过大容器止步。不存任意HTML/正文、input、src、链接query/token或内部状态，不听看媒体。所有既有身份/标题/canonical/human门逐字保持；新增1个真实Chrome未知DIV布局fixture只证明诊断可用且仍拒绝。实际布局后续须从新原生回执确定，不能预先假设class放行。
只读核对现门：publish_verification以唯一semantic article+video或≤12显式ID候选中匹配当前ID唯一容器为scope，caption限figcaption/[data-e2e=video-desc]；publication_comment还要求唯一HTML article。此步不放宽、不改这两个模块，将来若依据真实DOM共用新scope须同时核查评论门，不借document.title绕过。


### 实际H1与播放器共同scope：第二公开结构诊断
fdc0864f3aea46e995d84399ab43f38e/discovery-2真实回执已保存SHA：DOMcomplete，video总2/可见1、标题leaf1、无登录提示；leaf沿7层SPAN到实际H1.p0KxhPuQ，video在xgplayer祖先depth2因>240后代被旧诊断截断。现证据是结构选择器缺口，不能继续称未加载，也不据此放作品资格。
仅增强诊断：优先以匹配leaf最近H1为种子，video/H1祖先各最多8层；大容器只记desc计数/truncated而不立即中止，直接孩子仍≤12安全形状。唯一匹配H1+唯一可见video时记录最近共同非body祖先及至多2父层，含desc计数、H1/可见video计数和固定AI/虚构/审核枚举可见数量。无任意正文/HTML/内部状态，所有原资格门保持。新增1个本地Chrome深SPAN/H1与大播放器诊断回归，真实scope需下一原生回执确认后再设计共用资格。


2026-10-19 21:59补充：真实公共页complete且2总video/1可见video/唯一标题leaf，无登录提示。leaf经多层span到H1.p0KxhPuQ；播放器为XG-VIDEO-CONTAINER，xgplayer父级desc>240，原诊断先止步，尚未观测共同作用域。仅增强诊断为标题最近H1和video祖先及共同非body容器形状，保留所有原资格。取得实际scope后，应在共享作用域校验、发布声明检查和原授权评论前置中统一接线，避免发现已修而下游仍只认article。评论仍须同账号/原文/同作品完整证明与唯一提交锁，绝不把已点击未知评论重试。


### 根据真实e2e/原生作品ID统一发现、核验与评论scope
ce8b75c28e4b4beba5485f551e6bcd93/discovery-1原生结构已独立保存SHA。唯一video-detail1592后代，其左共同容器1188后代含player-container精确video_7698306800386379018、detail-video-info唯一H1，1video/1H1；AI/fiction可见枚举各1、审核标记0。不绑定任何hashedclass。
新增共享只读scope模块：唯一video-detail≤3000后代，唯一player-container含精确video_<expectedId>且无冲突ID，唯一detail-video-info/H1完整原标题；最近非body共同容器≤2000后代、1video/1H1。原article/显式ID路径保留。发现旧门不识别时用共享实际scope核身份，最后再核；publish_verification新路径同scope读取H1简介/全AI/虚构/精确tags/播放器/审核，全部必须通过。共享报告只证明实际DOM展示；AI主动来源仍原journal。
将冻结prepared.title/tags显式传至comment并与evidence.expected_title/expected_hashtags核同源，不能猜document.title。新路径评论新页先有界完整作品验证，原控件选择/已有评论读回限唯一video-detail；fill后和sole-click前再核canonical+scope+标题及原文。控件marker脚本必须实际root限定，不把更换调用locator当限定；多控件/外部假控件拒绝。旧article兼容缺新title字段，不能让新布局借旧path无title放行。原claim/收据/原文/一次click保留，有claim未知不重试；known-not-submitted无claim按原流程可继续，不擦除历史检查点。新增实际布局fixture走发现/核验/评论一次幂等、错ID/重复scope/错title/外部标签拒绝，少量相关旧回归；不改worker/core/runtime/上传/AI声明/发布click、不生产。


### 全部发布证明已通过后的评论编辑器诊断
gen23/29156的02265705ccda40949645ca55089d91e6原native完整证明已通过：准确作品7698306800386379018、post/AI展示/虚构/tag/播放器/原主动AI/审核clear全部true；评论原native返回comment_editor_unavailable、submittedFalse、无claim。原完整evidence及native receipt另存副本与SHA，不回写原失败为成功。
仅增强comment文件的_SCOPED_EDITOR_JS foundFalse诊断，不更改选择器资格/点击：记录整页与唯一detail内可见编辑器数量、其他dialog关系；最多12个编辑器/明确评论tab或原生按钮候选，安全tag/class/e2e/role/aria/placeholder/contenteditable与可见几何，最多3层祖先和各层8直接子项。不读input值/任意正文/内部状态，不点评论tab或新入口。foundFalse把原生诊断persist至native receipt/evidence，submittedFalse且无claim保持；core另agent负责严格known-not-submitted续行，已有claim未知绝不重发。新增1真实Chrome诊断fixture后冻结，下一真实回执仍需据实际DOM决定控件支持。

本诊断另记录页面/原detail内“登录后评论、登录后发表评论、登录后即可评论、登录后发评论、登录”的精确可见数量，导航普通登录只统计，不提前改变human分类或点击登录。最终单fixture证明自带comment-input的编辑器/其他dialog/入口与登录计数均可保存且未fill/click/claim。


### 实际评论区下方可见性与一次滚动挂载验证
c00519990026408d8471118d6abf2eec实际完整作品证明仍全true，native评论诊断page/detail editor0、登录计数0。唯一comment-list CSS可见802×346，附近有112高兄弟；root仅检查UI截图发现评论在viewport下方、社交行“抢首评”，懒挂载是待验证假设，不冒称根因已证实。原evidence/native receipt副本及SHA保存；gen24已受控交还。
已授权在ID-qualified唯一video-detail内，原完整身份核实后，对唯一[data-e2e=comment-list]执行一次标准DOM scrollIntoView UI滚动（当前Page/Locator无native scrollAPI，不改worker），不以CSS is_visible等同viewport。滚动前后复核canonical/原生作品ID/标题/全证明；最多8次/20秒等待原唯一editor挂载，多editor立即停，未知/改ID不提交。仍无editor保存现有最终诊断，可追加固定“抢首评”叶与pointer祖先只读结构，不点击它或其他入口，不点赞/分享/submit。
仅comment模块改动，所有claim/soleclick/回读/原文与未知禁止重试保留。1真实Chrome IntersectionObserver懒挂载fixture证明实际滚动后editor出现及once提交，复验原双editor与fill后改ID负例；实际平台是否因此挂载仍待下一原生回执，不把fixture当生产验收。

本版等待后仍editor不可用时，原receipt目录固定key.comment-ui.png保存当前发布UI并在receipt记录路径；截图失败只记error_type，known submittedFalse不改。此为UI排查，非视频内容审核。3定向案通过后补截图，单独复验双editor案及PNG落盘；不冒称最终3案全量重跑。


## 评论输入激活（gen25实际停点）

26b15b5b2bfa4201b197354077cc8551原作品所有证明通过，但一次comment-list滚动后5读/20.134秒仍无editor，无claim/submit。保留原receipt/UI证据，独立checkpoint为publication_comment_activation_20261019。最小修复仅评论：优先唯一comment-list直接父panel内、list外的原生叶“留下你的精彩评论吧”，资格不足才选唯一已观察pointer叶“抢首评”；同准确作品、完整scope证明、document/url/timeOrigin守卫，原生点击最多一次，未知不换目标/重试。继续原8读/20秒等待；双编辑器、双候选、错ID拒绝，不改原评论提交claim/唯一点击。真实UI只证明提示外壳，DOM资格必须运行时核验；本地fixture不冒充平台验收。


## Draft评论编辑器适配（gen26原生依据）

dbcfd739be7f43e6b8c89619ade47fde原placeholder激活成功；editor从0变为1但旧选择器qualifying0。实际DIV.public-DraftEditor-content[role=combobox][contenteditable=true]，父DraftEditor-editorContainer、祖父DraftEditor-root，与唯一comment-list同父panel且list外。独立checkpoint publication_comment_draft_editor_20261019保存原native/receipt/UI副本SHA。仅在该严格panel内追加真实Draft候选，仍唯一、可见、非禁用。新Draft的发送区域限定同panel/list外；原路径保持。原生按钮或exact叶DIV“发送/发布”须同panel、唯一、可用，DIV额外pointer/viewport/hit、排除正文/list/输入区。无可确认submit则保存有界结构诊断和UI，不claim、不点击。全部原准确作品/原文/唯一提交锁门保持；本地fixture不当平台验收。


## 图标发送控件原生诊断（gen27）

faf8e6915288447a9110f8f69809e786已Draft输入及原文读回通过，2读7.773秒；submit候选0，无claim/submit。原生UI显示粉色圆形上箭头SVG，没有发送/发布文字。独立checkpoint publication_comment_icon_diagnostic_20261019保存原native/receipt/UI及SHA。只增强同ID-qualified唯一Draft评论panel且list外的有界SVG/icon/button原生结构诊断（≤12种子，祖先≤2，安全aria/title/e2e/class、viewBox、fragment use、有限path形状），不读正文/input/internal state，不按颜色/坐标或未知图标点击。明确命名若无既有严格资格则仍submittedFalse并保存UI，拿到实际DOM后再适配。仅comment/tests。

主审补充批准：已有明确data-e2e=comment-submit语义的纯图标不再强制发送文字，仍同panel/list外/唯一/可见/viewport/hit/非禁用；未知图标继续诊断。最终本地3案13.04秒通过，所有Python函数AST不变；冻结见该checkpoint SOURCE_SHA/REVIEW，未平台验收。


## 原生发送SVG固定版本适配（gen28实证）

2fc628f81264434c87e69f0d5146a594实际同评论panel图标为@/emoji/send三个SVG；发送图标viewBox/width/height=0 0 36 36/36/36，两个原完整path281+194字符，无use；父SPAN与SVG均pointer/visible/viewport/hit，祖父DIV含3个可见SVG。独立checkpoint publication_comment_native_send_svg_20261019保存原native/receipt/UI SHA及FROZEN_ICON。仅当原命名/e2e候选为0，按精确ordered完整path+viewBox/尺寸+pathcount2/use0、同active Draft、同panel/list外、可操作父SPAN和3-icon组且唯一signature识别；不绑hash/颜色/坐标/右most。命中只标记实际SPAN，由原唯一claim后sole submit点击。错误/多个/禁用/外部signature仅诊断，仍不claim/不点；全部原ID/title/text门保持，成功receipt可记录版本来源。
