# 法律片第二回合：材料递交与发现个人原因（2026-10-10）

用户在交付FILM380_OPEN01后要求“继续”。已完成下一回合完整演法、确定性编译、同源全文复审和独立验收；计划13秒，视频尚未提交。上一段仍为awaiting_human_review，人审问题已提出，不能把“继续”直接记成媒体approved。

## 当前内容与边界

沿用380《不签的字》，canonical SHA为`078b0bcee752062edb348f6a29a2bd2ad229a9333c8e2a934643bd5ab050c75e`。正文人工采用没有伪记；本次只覆盖B1.S04–S07：

- 周姐：嗯，是公司这边的决定。手续总要走的，你看一下这份材料。
- 周姐把申请和笔一起由自己侧一次送到小林近桌沿，纸停稳后手收回。
- 小林：“因个人原因”……这写的是我自己的意思？
- 小林不碰笔，继续看原因栏。

新增信息是口头承认公司决定与书面个人原因之间的矛盾。小林的反问由看清材料触发，不提前摆拒签反应；当前不演B2统一格式、流程压力、拒签及后续离开。

起态承接前段计划：文件夹已开、纸笔在周姐側、两人坐着、工牌已戴。终态纸笔在小林近桌沿，未签字、小林未碰笔，其余不变。助手未检查实际尾帧画面，状态承接是计划及后续人工审核要求。

## 完整新演法与审查

|调用|结果与处置|
|---|---|
|392 MiniMax|格式/编译有效；完整演法含“反问由低音量逐字推高”|
|393 DeepSeek|同源全文复审issues为空；原回执保留|
|独立文本门|发现逐字音量规则与自然互动目标冲突，1项必修，不因393零问题放行|
|394 MiniMax|读取392完整稿和具体必修，提交完整六字段新稿，消除逐字音量递增；未手改或拼接|
|395 DeepSeek与独立门|读取完整正文/R01/394/编译/提示词，0未决必修；实际媒体质量待人审|

“逐字推高”是已核实的请求设计问题，不是已证明的视频服务僵硬根因。摄影观察转向周姐、持续看字与抬问的视线、反问后1.2秒承载和真实语气仍保留为媒体验证风险，没有声称实际自然度改善。

## 合同分工与实际来源

新独立合同`src/content_factory/creative_film_material_exchange_v1.py`复用六字段演法协议；旧开场v3及其冻结记录未修改。局部创作实际消费S04–S07、起态、电影方法、完整R01；未来380全文留给复审。394额外读取392完整原稿和独立门必修证据，实际消费核对见round_02/ACTUAL_CONTEXT_CHECK.json。

确定性编译让一次2秒推纸与周姐当前句末段重叠，纸到位且该句结束后才读。38发音字按3.3字/秒规划11.515152秒，加模型选择1.2秒为12.715152秒，服务原生13秒，无fit、提速或截断。S07作为持续状态与读字重叠，不另堆固定凝视耗时；这些都是规划假设，未测量实际表演或音频。

[完整当前交接](../data/production_revisions/legal_film_material_exchange_20261010/round_02/DELIVERABLE_material/CURRENT_EXCHANGE_READABLE.md)保留原生完整稿、原正文、编译、全文复审、独立门、资产反馈和授权。与前段S01–S03交接合计覆盖B1七步文本，不等于B1媒体通过或整片导演/表演交付。

当前文本入口`scripts/run_legal_film_material_performance_v2_20261010.py`，视频入口`scripts/run_legal_film_material_sample_v2_20261010.py`。已保存13秒[PROMPT未提交预览](../data/video_generation/legal_film_material_exchange_20261010/material_v2/PROMPT.preapproval.txt)及`REQUEST.preapproval.preview.json`，dispatch_allowed=false，未执行provider_create。

## 验证、账本与批准门

第一版合同/入口18项断网模拟检查通过，v2完整返修与批准门5项通过；无测试付费调用，旧测试/合同保持。证据位于`data/qa/legal_film_material_exchange_20261010/`。离线和文本验收不证明实际创作质量。

本次4次文本、26447 reported tokens；累计395次、6456309 reported tokens。70结果未知、70/160用量未知与93117预留保持，旧账本与上限不重置。新增媒体0，同故事媒体登记仍37次。

上一段FILM380_OPEN01任务`cgt-20261010170430-j94sb`，视频SHA`e89e5585f0515e391d9360f6347cdb5811141c81ecc01865df45c206561c71d9`，服务原生尾帧SHA`d3146ccd39e3e11abed9311d2b454adb711bdec16a635a036c6689620e210943`。批准门必须核对该原视频和尾帧的人审回执，再把尾帧作为first_frame；不能改用reference_image或未批准旧尾帧。

[AGENTS.md](../AGENTS.md)要求“用户明确反馈某段通过后”才用原始尾帧续段。当前确认问题待答复；确认后只生成这一个材料回合，不自动续其他段、不重试或发布。成功保存仍记awaiting_human_review，由用户判断动作、语言、表情、口型与镜头效果。

## 最新单次提交指令（2026-10-10）

用户随后明确要求“提交视频请求”。本次仅将已展示的13秒材料回合及指定原生尾帧作为一个具体请求执行，不把这句话写成上一段内容通过。旧USER_SCOPE、HANDOFF及未提交预览保持原样；新增SINGLE_REQUEST_AUTHORIZATION.json绑定实际内层请求SHA `89de0df9d2040768777d64fb46423f6deade27760bdfc0d3a09087766f2e8f4b`、394/395、380正文与编译SHA、前任务/视频/原尾帧。

独立入口`scripts/run_legal_film_material_submit_v3_20261010.py`只覆盖这个请求的等待门，默认`validate_approved_tail`及其他任务规则未改动。前段仍awaiting_human_review、human_decision=null；没有生成虚假的批准回执，也不授权下一段、整批、重试或发布。前任务receipt允许未来真实人工审核更新，因此冻结不可变PREDECESSOR_TECHNICAL_SNAPSHOT，而不把可变receipt纳入来源文件哈希；每次提交仍核对前任务身份、原视频/尾帧字节并拒绝已被否决的前段。

请求已离线核对并冻结为PLAN.json、REQUEST.preview.json及PROMPT.txt：13秒、Seedance 2.0 Mini、480p、9:16、原生声音、字节一致的first_frame。提交前同故事媒体登记37次、失败上限10，旧账本和93117未知文本预留不重置。当前尚未调用create；提交与保存结果另附回执，成功保存后仍待用户人工审核。

## 单次生产结果与交付（2026-10-10）

任务`cgt-20261010181003-hkxkh`成功生成并保存[FILM380_MATERIAL02.mp4](../data/video_generation/legal_film_material_exchange_20261010/material_v2/FILM380_MATERIAL02.mp4)：13.088秒、496×864、1视频流/1音频流、3721355字节。当前`awaiting_human_review`；服务原始尾帧已保存但未批准。助手没有观看、听取、抽帧、ASR或音画审核，不作内容通过结论。

v3单次授权、原尾帧身份、防重复及未知结果分支离线19项通过；生产实际请求与此前预览89de…完全一致。全部冻结来源与7份受保护历史文件哈希一致，前段receipt仍待人审、human_decision=null，没有被改成通过。新文本0、新媒体1，同故事媒体登记37→38；服务reported video tokens 130990单独保留，文本395次/6456309及未知预留93117未变化。

[交付记录](../data/video_generation/legal_film_material_exchange_20261010/material_v2/DELIVERY_REPORT.md)、`DELIVERY_VERIFICATION.json`、`receipt.json`、`SINGLE_REQUEST_AUTHORIZATION.json`、`PROMPT.txt`保存完整来源、授权、实际请求和技术结果。当前停在本段人工审核；下一段未授权派发。
