# 小说改编路线开发合同（2026-10-17）

## 用户要求与本轮范围

用户确认路线为：获取正文 → 分析背景、人物与故事线 → 选择角色与冲突/情绪高潮 → 改编规划 → 完整剧本 → 全文审查与有界整稿返修 → 后续分镜和视频。用户明确允许符合小说主线的部分修改，并要求子agent开发、主agent审查。

本轮完成独立可复用文本路线、CLI/网页入口、离线故障验证与开发交接。既有采集服务负责获取正文；路线接收真实已保存正文或采集回执，明确已获取章节范围。文本验收可提供导演交接包，不能把它写成已有分镜或实际视频。开发验证不派发真实模型、媒体或发布。

旧v1/v2、默认v23、历史来源、失败、接管门、累计11次/180079 tokens均不改写。旧试跑的截断停止与候选耗尽不因新版本重领；本轮旧样本只做本地输入预览，若请求旧任务execute，必须在派发前拒绝并说明实际停止依据。普通新任务也须同故事唯一登记，未知调用/截断/缺用量不自动重发。

## 模块与接口（分工边界）

1. `src/content_factory/novel_adaptation_contracts_v1.py`：纯合同、提示、聚合校验和确定性阅读稿投影，不调用服务/写任务。导出 `VERSION`、`STAGES = ("analysis", "adaptation_plan", "screenplay")`、`SCHEMAS`、`PROMPTS`、`REVIEW_SCHEMA`、`REVIEW_PROMPT`、`validate_stage(stage, value, context) -> list[dict]`、`validate_review(value, context) -> list[dict]`、`render_screenplay(value) -> str`。context含 `source`、已接受的 `analysis` / `adaptation_plan` / `screenplay`。source为程序对象 `binding_id, book_id, title, text, scope, full_source_sha256, excerpt_sha256, start_character, end_character`。
2. `src/content_factory/novel_adaptation_pipeline_v1.py`：独立可恢复阶段执行器，导出 `prepare(run_dir, *, source_path=None, acquisition_receipt=None, title=None, book_id=None, scope=None, registry_dir=None, max_calls=20, max_total_tokens=500000, max_revisions=2, legacy_parent=None) -> dict`、`preview(run_dir)`、`inspect(run_dir)`、`execute(run_dir, *, clients=None)`。prepare/preview/inspect零模型；execute注入或使用既有CreativeRoleClients。前3阶段writer、全文审查director。程序管理来源和稿件身份，不要求模型生成/回传SHA。
3. `scripts/run_novel_adaptation_v1.py`：对应prepare/preview/inspect/execute；`src/web/novel_adaptation_panel_v1.py`提供独立直接小说路线面板，接入真实可达页面（不依赖账号选题卡），复用上述API。不更改旧任务按钮的执行语义。面板清楚展示各阶段、来源章节、失败、产物与后台日志。来源只读选择/回执，媒体无提交入口。

首步的实际采集桥接由入口agent在独立`novel_adaptation_acquisition_v1.py`实现：显式CLI fetch/网页获取正文委托已有FanqiePromotionService.fetch_book，每次独立目录、保存真实成功/失败回执；默认1章且可选择，不启动推广申请或视频。需要登录/验证或采集失败即停止，不推测正文、不复用独立Chrome登录态、不复制凭据。已有采集服务维护本身不在本轮替换范围。开发测试只注入fake服务。

## 创作标准与各阶段产物

- analysis：世界框架（时代、日常环境、空间和前情）；有出处的角色卡（身份/性格/处境/目标/关系）；主线因果、关键转折；多个冲突/悬念/反转/情绪高潮候选和选择理由。仅分析取得的正文，未知背景明示未交代。
- adaptation_plan：明确选择的角色、选段和高潮候选；起止状态、铺垫→刺激→反应→升级→收束/悬念的因果顺序；必须保留的动机/主线事实；改编变更及理由、对主线影响；目标时长。允许重写对白、合并场景、压缩支线、调整叙述顺序，不以逐字引用对白作为质量门。
- screenplay：一份完整原生结构化稿，包含世界与本稿角色卡、逐场timeline/time/location、所有在场者的动作/表情/视线、首尾状态、顺序表演事件（action/dialogue/reaction/voiceover）与时长。重要刺激与反应保留可见表演窗口；动作/对白自然推进。引用仅绑定关键主线依据与改编说明，不要求每句对白逐字等于小说。
- review：读取同一冻结正文、分析、改编计划及完整稿，审查主线/动机、因果、角色身份、空间/视线/动作、情绪窗口、对白自然程度、可拍性、完整性及时间预算。程序证据与语义审查分开，全部问题一次聚合；major/blocking触发完整新稿，默认全运行合计最多2轮已知内容返修，不做句子补丁。分析/计划问题应回到责任阶段，不允许改源迎合正文。

## 技术标准

- 使用现有MiniMax创作/DeepSeek必要全文审查客户端，SDK自动重试0。冻结实际协议、提示/schema、代码、源文件与回执；每次派发前复验。每次请求写独占claim、pending和原生请求/响应/usage。严格核对原生与元数据用量、模型、结束、工具载荷；完整已知内容错误可有界返修，length/unknown/缺工具等停止。
- 一个原生完整JSON是正文权威；SCREENPLAY.md由确定性投影生成，输出不重复要求模型撰写同样正文，不手工补全失败稿。原文SHA与选段SHA区分，身份由程序封装。review同稿身份由请求/回执SHA绑定，而非模型猜SHA。
- 总时长与事件时长求和一致；对白/旁白与分配时间作保守可读性校验，规则公开，不把估算当真实音频时长。结构校验不能代替语义全文审查。所有角色引用/场次/事件ID唯一、存在，非法NaN/负数/缺字段、残缺终态不放行。
- 输入超长时派发前明确停止，不静默截文。修订请求只包含一份前稿与聚合诊断，不重复发送原始响应和等价全文。
- 输出完整背景、角色、分析、选段计划、阅读剧本、全文复审及来源/回执绑定的文本导演交接清单；状态`text_ready_for_director`且`human_approved=false`，不伪写用户采用或视频通过。
- 同故事登记、运行锁、不可变证据、重入零重复派发；完成态inspect必须复验产物和审查绑定。实际来源/代码/状态异常不能通过只改状态绕过未决claim。独立入口不自动迁移旧冻结。

## 验收

子agent各自模块测试；主agent检查实际CLI/网页可达接线、提示和上下游身份，另做独立故障测试。重点覆盖改写对白可接受、主线改动被审查阻止、缺铺垫/反应、角色/时长/完整性聚合问题、全文同稿审查、有界整稿重写、截断与用量未知零重发、登记与并发门、源/回执/产物篡改、旧试跑阻断、prepare/preview零服务调用。所有结果区分离线模拟与真实生产。
