# 法律片直白正文返修（2026-10-09）

当前产物为《桌上一张纸》完整新稿，已经全文复审，等待用户采用。旧成片仍为用户拒绝状态，本轮未生成新视频。

## 用户原要求与内容变化

用户补充：最后几秒两人都持续走出办公室；劳动合同方向可以，但剧情要更白，不再使用“省心”“*心”“对不上不签”“核对”这种表达。该陈述记录在 [新反馈](../data/video_generation/legal_trend_20261008/remaining_batch_v1/human_feedback_20261009/PLAIN_LANGUAGE_AND_ENDING_FEEDBACK.json)，与上一轮重复对白、戴工牌、场景和字幕反馈并存。视频观察来自用户，助手未抽帧、听看、ASR或调用媒体审核。

新稿从两人坐定直接开始：公司要求小林离开，却递来个人原因自愿离职申请；小林看清后提问，周姐一次具体催签；小林迟疑但拒签，周姐停住收回未签纸；仅周姐离开，小林留坐，门关后才放松。四拍、14条正文步骤、五句对白，不继承旧230.4秒、11镜或25个服务段。工牌保持佩戴，无摘戴、水杯、工位过场、第三人。屏幕字幕取消；剧情纸张的必要印刷字另由资产和导演定义。

完整新稿由MiniMax提交，未手动改正文、回填动作或拼接旧稿。对白原文如下：

- 周姐（虚构人事主管）：小林，公司那边今天决定了，让你离开。
- 小林（虚构劳动者）：这上面写的是个人原因……是我自己要辞职？
- 周姐（虚构人事主管）：先把字签了，今天不签，手续就停在这。
- 小林（虚构劳动者）：周姐，我没有辞职，是公司要我走，这张纸我不签。
- 周姐（虚构人事主管）：那我先走了。

## 正式文件与模型来源

- [完整剧本](../data/production_revisions/legal_plain_revision_20261009/round_05/DELIVERABLE_r3/FULL_SCRIPT.md) / [原始JSON](../data/production_revisions/legal_plain_revision_20261009/round_05/DELIVERABLE_r3/FULL_SCRIPT.json)
- [全文复审](../data/production_revisions/legal_plain_revision_20261009/round_05/DELIVERABLE_r3/FULL_TEXT_REVIEW.json)
- [原审查317与资格校准](../data/production_revisions/legal_plain_revision_20261009/round_05/DELIVERABLE_r3/QUALIFICATION_EVIDENCE.json)
- [制作前交接状态](../data/production_revisions/legal_plain_revision_20261009/round_05/DELIVERABLE_r3/HANDOFF.json) / [交付哈希及账本核验](../data/production_revisions/legal_plain_revision_20261009/round_05/DELIVERABLE_r3/DELIVERY_EVIDENCE.json)

| 调用 | 模型与阶段 | 实际结果 |
|---|---|---|
|312|MiniMax-M3 完整第一稿|格式有效；多余过场及重复解释，后续全文审查要求返修|
|313|DeepSeek-flash 全文审查|实际全文必修问题；原报告保留，部分规则措辞需限定|
|314|MiniMax-M3 完整第二稿|五句对白，仍有手在膝上推纸等状态问题|
|315|DeepSeek-flash 全文审查|要求催签反应和后果更明确；原报告保留|
|316|MiniMax-M3 完整第三稿|正式交付的同一全文，四拍、五句对白，状态顺序已调整|
|317|DeepSeek-flash 全文审查|四项异议，原记录不变|
|318|DeepSeek-flash 同稿全文重审及逐项资格判断|四项原异议逐条以当前正文证据判为unsupported_objection，当前必修0；不是用户质量批准|

317要求“收纸必须与拒签同拍”“B1就揭示B2信息”等，涉及额外分拍要求；318依据全片连续因果重新判断。未由助手删原问题或改审查结论。真实正文和每条原异议都进入318请求。318审查文字误称六到八句，逐steps计数实际五句，原审查文字仍保留。

R01完整参考与六项教学表达准则进入实际创作与审查messages；参考全文SHA256为e4d3a8a375b10717825f3c865040edd7444588746b4c12fe451066dbbdc3ff98。本轮仍使用MiniMax-M3创作、DeepSeek-flash审查，temperature=0.4、thinking=disabled，单次输出上限8000，没有更换模型或HTTP自动重试。

## 代码与离线验证

实际入口：[第三稿生成与复审](../scripts/run_legal_plain_script_revision_v4_20261009.py)、[同稿资格重审与交付](../scripts/run_legal_plain_script_qualification_v5_20261009.py)。先前v1空调用原型及v2/v3记录冻结保留，后续独立继承实际消耗，未篡改旧记录。四拍Schema仅本次简化新稿适用，不作为全项目通用时长/拍数模板。

相关离线检查62项，审查资格规则8项，共70项通过；pytest缓存权限警告不影响测试结果。每次实际派发前验证完整参考、原稿、全文审查、角色模型、Schema及累积账本；最终交付与316原始模型JSON严格相同，旧r8正文和旧成片SHA256亦未改变。离线通过不证明视频表演、声音或创作质量。

## 消耗与未完成项

本轮新增7次文本调用（3次创作、4次全文审查/重审），101412 reported tokens。承接累计318次、5437185 reported tokens；旧70结果未知、70/160用量未知及93117预留仍保留。文本无总token硬限来自2026-10-04授权；不重置旧账本、不做Codex余额监控。新增媒体0、发布0。

新正文状态为complete_reviewed_text_awaiting_human_adoption。用户采用后，必须按新14条步骤重新生成整片导演、逐拍表演窗口及确定性编译；旧导演和SOURCE_STATE_OBLIGATIONS不能套入新正文。后续服务提示只发当前步骤真实对白与有效表演，不把整拍摘要、其他对白片段、未来工牌/离场动作塞进当前段。

当前v3视频请求合同仍是离线原型，production_ready=false；声线绑定、场景与两人身份连续仍未由新视频验证。旧法律片整批审核例外不能自动授权新稿整批生成。视频仍由用户人工审核，助手只验证接口与文件保存，未审媒体记awaiting_human_review；不发布。
