# 对白、动作与空间的跨字段审核

本规则用于本项目的故事生成、定点修订、状态展开、摄影和最终双稿审核。它补上“每个字段单独合理、组合起来却矛盾”的检查，不改变已经保存的故事或代替用户审稿。完整阶段命令见 [双剧本工作流](SCRIPT_PAIR_WORKFLOW.md)。

## 审什么，以及如何处理

| 维度 | 必须对照的实际内容 | 不应新增的要求 |
| --- | --- | --- |
| 对白与动作 | 完整对白中的说话人、指代、物件、要求、承诺、主张与完成时序，对照本镜动作、初末态和相邻镜 | 提议不等于立即执行；被拒绝的方案不必先做一遍。放下工具不排除继续协商，收存意图不自动要求装包归档 |
| 冲突对象 | 核心、开场问题、人物目标、双方立场、转折和本片解决范围，对照全部实际对白 | 金额是多少、由谁付款、谁承担差额或责任是不同争议，不能以“增强冲突”为由在润色时偷换 |
| 声线与表演 | 稳定音色、音域、人物弧光、每镜表演和该角色全部对白 | 陈述也能有催促感；没有相应台词时不能为“常用反问”硬加句子，也不能只数问号。清楚咬字不等于拆字慢读 |
| 空间关系 | 场景位置、人物面向、视线对象、相机相对视线轴的位置、完整脸嘴与关键手区是否可见 | 相对而坐不等于面向镜头，不能让人物为露脸转头。固定机位与原始尾帧继承不能同时要求瞬间换机位 |

先读实际镜头，再核对表达计划和结果概括。对白与动作可以互补，但结果字段写成已经发生的事项须有实际依据；角色的单方主张也不能由概括升级为双方已确认的事实。

审核处理分为三类：

- **实质矛盾**：动作主体、物件身份或状态相反，对白与动作实际抵触，争议对象被换掉，人物面向与摄影要求无法同时成立。定位原文并退回产生问题的阶段。
- **影响执行的歧义**：指代、方位、手位或机位需要执行者在互斥方案中猜选。保持待修或待复核，消歧后再通过；不能用“摄影师会理解”放行。
- **可选风格**：同义措辞、语气强弱或个人句式偏好。明确标为建议，不强迫改稿，不为此追加动作或反复收束。互相兼容的坐标描述、可合理延续的轻微姿态不自动等于物体移动或连续性错误。

缺少实际审查、存在未解决的实质问题或执行歧义时，不填写通过。反过来，审核者也不能用输入未要求的归档、合屏、重复点头等条件否决已有完整结果。审核摘要若写错左右手或动作发生镜号，应回到候选原文核验；摘要不是新的制作指令。

## 两道门禁的版本与职责

| 工件或报告 | 当前 schema | 职责 |
| --- | --- | --- |
| 完整故事数据 | `script_screenplay/v1` | 原始人物、动作、对白、状态和引用；此版本没有因审核升级而改变 |
| 故事独立审核 | `screenplay_editorial_review/v2` | 原有九项加四项跨字段检查，实际通过后才能进入摄影 |
| 摄影数据 | `screenplay_production/v2` | 冻结已审故事，只补摄影、表演和解释；结构通过不等于语义通过 |
| 正式双稿审核 | `script_editorial_evidence_review/v2` | 对完整两版逐镜、逐角色、争议全过程及结局复核；所有最终生成入口共用 |

故事 v2 的纯校验入口是 `src/trend_intelligence/script_screenplay.py` 中的 `verify_story_review`。最终审核的校验与保存报告重验分别是 `src/trend_intelligence/script_pair.py` 中的 `validate_script_review_report` 和 `validate_saved_script_review_report`。它们检查实际内容绑定及证据覆盖，不自动产生编辑通过意见。

网页、`pre_video_script.py`、研究入口的双稿生成，以及 staged bundle 的正式最终审核，共用最终规则。网页分阶段自动编排仍未接入：不能把“最终审核规则共用”描述成网页已经自动完成剧情、状态、摄影各阶段。分阶段 CLI 仍需显式推进。

## 故事审核 v2 的准确字段

`checks` 必须恰好包含以下十三项，全部是布尔值。只有实际通过的完整报告才可把全部值置为 `true`：

`core_and_scope`、`conflict_and_turn`、`ending_complete`、`prop_continuity`、`speaker_and_no_narration`、`pace_and_duration`、`source_fidelity`、`legal_boundaries`、`version_value`、`dialogue_action_alignment`、`conflict_focus`、`character_delivery_grounded`、`spatial_alignment`。

| 字段 | 绑定或覆盖要求 |
| --- | --- |
| `candidate_sha256` | 当前 `screenplay.json` 原始字节 SHA-256 |
| `workflow_request_sha256` | 本轮原工作流请求文件原始字节 SHA-256 |
| `source_evidence_sha256` | 该故事阶段绑定的完整来源文件原始字节 SHA-256 |
| `shot_reviews` | 与原镜头顺序、镜号完全一致，每镜一项 |
| 每镜 `action_quote` / `finding` | 当前动作的非空真实原文引文及实际结论；建议保留完整相关动作，不能编造引文 |
| 每镜 `dialogue_quote` | 完整对白，逐字等于原字段，不能仅摘安全半句；静默镜为原有空字符串 |
| 每镜三个专项结论 | 非空的 `dialogue_action_finding`、`conflict_focus_finding`、`spatial_finding`，分别写实际核验结果 |
| `result_review` | 真实完成结果的镜号、该镜动作引文及结论；不能只引元数据或对白替代动作 |
| `focus_review` | 完整的 `core_quote`、`question_quote`、`goal_quote` 分别等于当前核心、问题、目标；`spoken_shot_ids` 按序覆盖全部实际非空对白镜，并写 `finding` |
| `spatial_review` | `layout_quote` 逐字等于完整 `spatial_layout`；`finding` 对照逐镜人物状态，不能只说“空间一致” |
| `character_reviews` | 按原角色顺序完整覆盖，每项 `name` 不变；完整 `voice_quote`、`performance_arc_quote` 逐字匹配；`dialogue_quotes` 是按镜头顺序排列的 `{shot_id, quote}` 列表，覆盖该角色全部实际非空对白，并写 `finding` |

没有对白的角色，其 `dialogue_quotes` 为 `[]`；仍须审查其原始人物设定。静默镜仍在 `shot_reviews` 中，并说明动作、焦点和空间核验，不能漏镜。

推进条件为总体、全部镜头、结果、焦点、空间、人物条目的 `decision` 均为 `passed`，十三项均为真正的布尔 `true`，`unresolved_issues=[]`，且绑定和覆盖校验通过。`false`、`null`、未知判断或缺项不能当作通过。`blocked_for_script_generation=true` 同样阻止推进。

### 故事审核 v2 待填写模板

下面是**待审模板**，不是可直接用于摄影的审批。故意使用 `pending`、`null` 和未解决项，复制后不会通过门禁。先按真实候选展开全部镜头和角色，复制实际原文，再由独立审核者逐项判断；不能运行脚本把这些值统一改成通过。示例两镜不代表任何真实稿件，也不满足本项目短长稿镜数要求。

```json
{
  "schema": "screenplay_editorial_review/v2",
  "reviewer": "<实际独立审核者>",
  "reviewed_at": "<实际审核时间，包含+08:00>",
  "candidate_sha256": "<当前screenplay.json字节SHA256>",
  "workflow_request_sha256": "<原工作流请求字节SHA256>",
  "source_evidence_sha256": "<本阶段完整来源文件字节SHA256>",
  "decision": "pending",
  "checks": {
    "core_and_scope": null,
    "conflict_and_turn": null,
    "ending_complete": null,
    "prop_continuity": null,
    "speaker_and_no_narration": null,
    "pace_and_duration": null,
    "source_fidelity": null,
    "legal_boundaries": null,
    "version_value": null,
    "dialogue_action_alignment": null,
    "conflict_focus": null,
    "character_delivery_grounded": null,
    "spatial_alignment": null
  },
  "unresolved_issues": ["待实际逐项审核；不得据此模板推进"],
  "shot_reviews": [
    {
      "shot_id": "S01",
      "decision": "pending",
      "action_quote": "<当前S01的真实动作原文>",
      "dialogue_quote": "<当前S01完整对白；静默则填写空字符串>",
      "finding": "<实际动作、状态及其他检查结论>",
      "dialogue_action_finding": "<指代、要求/主张/完成时序与动作的实际核对>",
      "conflict_focus_finding": "<本镜是否保持当前争议对象及其依据>",
      "spatial_finding": "<本镜位置、面向、视线、手部与原布局的核对>"
    },
    {
      "shot_id": "S02",
      "decision": "pending",
      "action_quote": "<当前S02的真实动作原文；按实际镜数继续添加条目>",
      "dialogue_quote": "<当前S02完整对白>",
      "finding": "<实际检查结论>",
      "dialogue_action_finding": "<实际检查结论>",
      "conflict_focus_finding": "<实际检查结论>",
      "spatial_finding": "<实际检查结论>"
    }
  ],
  "result_review": {
    "shot_id": "<真正完成本片结果的镜号>",
    "decision": "pending",
    "action_quote": "<该镜实际完成动作原文>",
    "finding": "<结果发生在哪一步、回答什么问题，以及未解决的范围>"
  },
  "focus_review": {
    "decision": "pending",
    "core_quote": "<完整core_message>",
    "question_quote": "<完整version.dramatic_question>",
    "goal_quote": "<完整version.goal>",
    "spoken_shot_ids": ["<依原顺序列出全部非空对白镜号>"],
    "finding": "<对照全部对白后的冲突对象、转折和结果范围结论>"
  },
  "spatial_review": {
    "decision": "pending",
    "layout_quote": "<完整version.spatial_layout>",
    "finding": "<固定位置/面向/视线轴与所有镜头状态的实际核对>"
  },
  "character_reviews": [
    {
      "name": "<characters第一人的原名>",
      "decision": "pending",
      "voice_quote": "<该角色完整voice>",
      "performance_arc_quote": "<该角色完整performance_arc>",
      "dialogue_quotes": [
        {"shot_id": "<该角色第一个有对白镜号>", "quote": "<该镜完整对白；继续列全本角色对白>"}
      ],
      "finding": "<以该角色全部对白和实际动作核对声线/句式/弧光的结论>"
    },
    {
      "name": "<characters第二人的原名>",
      "decision": "pending",
      "voice_quote": "<该角色完整voice>",
      "performance_arc_quote": "<该角色完整performance_arc>",
      "dialogue_quotes": [
        {"shot_id": "<该角色第一个有对白镜号>", "quote": "<该镜完整对白；无对白角色使用空数组>"}
      ],
      "finding": "<实际检查结论>"
    }
  ],
  "scope": "<实际阅读的候选、来源及核验范围>",
  "limitations": ["本报告只审故事文本；尚未生成的摄影和视频声画不在通过范围"]
}
```

报告可记录实际时戳和范围，但不能用文件修改时间推断任务完成。人工填写的审核说明必须与原文一致；复制引文、算 SHA 或生成模板都不等于完成审核。

## 正式双稿审核 v2 的证据覆盖

模型原始报告只返回 `checks`、`issues`、`summary`、`candidate_sha256`、`evidence_sha256`、`shot_audit`、`result_audit`、`character_audit`、`conflict_audit` 九个顶层字段。原始响应不自行增加 `schema` 或 `passed`；校验器重验后写入保存报告的 `script_editorial_evidence_review/v2` 与计算出的 `passed`。

此处两项 SHA 绑定的是**本次实际送审的 scripts/evidence 规范 JSON**，不是随意选择的某个草稿文件字节。它与故事阶段的三项字节 SHA 用途不同；使用入口生成的真实绑定，不能把两种摘要直接替换。重新读取保存报告时仍重算、重验，不能信任历史 `passed` 标志。

### 每镜与结果

`shot_audit` 覆盖两版全部真实镜头，每项只能包含：

- `script`、`shot_id`、`decision`、`action_evidence`、`continuity_note`、`voice_note`。
- 新增的 `cross_field_evidence`、`cross_checks`、`dialogue_action_note`。

`cross_field_evidence` 必须恰好包含八项原文：`dialogue`、`audio`、`emotion_and_performance`、`blocking`、`camera_angle`、`composition`、`start_frame`、`end_frame`。其中 `dialogue`、`audio`、`camera_angle` 要**全文逐字匹配**；其他项须为对应字段真实的非空连续引文，不能用摘要。静默镜的 `dialogue` 允许原始空字符串；不能给它补一句话。

`cross_checks` 恰好是 `dialogue_action`、`voice_performance`、`spatial` 三项，各为 `passed` 或 `failed`。它们与镜头总体判断共同检查，不能用 `unknown`、缺项或总分覆盖未完成的专项核验。

`result_audit` 恰好覆盖 short/long 各自的 `resolution`、`ending`，每项含 `script`、`target`、`decision`、`action_evidence`、`explanation`。每镜审核至少引用本镜真实 action；结果审核至少引用本版真实 action。真实引文不意味着解释必然正确：放下动作与随后维持放下状态、不同角色的左右手，仍须实读区分。

稿件引文格式为 `{script, shot_id, field, quote}`；来源引文格式为 `{source_id, evidence_id, quote}`。来源未在本次实际证据投影中提供、字段或镜号错误、编造引文，均不能作为审核依据。

### 每个角色

`character_audit` 逐版覆盖所有实际角色，短长版本即使同名也分别审核。每项字段为：

`script`、`character_name`、`decision`、`spoken_shot_ids`、`performance_arc_quote`、`dialogue_quotes`、`voice_quote`、`performance_quotes`、`assessment`。

- `spoken_shot_ids` 按原顺序覆盖该角色全部发声镜。
- `dialogue_quotes` 是 `{镜号: 完整对白}` 对象，逐字覆盖该角色全部实际对白。注意它与故事 v2 中的引文列表结构不同。
- `performance_arc_quote` 是该角色完整人物弧光；`voice_quote` 是该角色**首个发声镜的完整 audio 字段**，不是自行摘出的声线短句。无对白角色的引文对象为空、`voice_quote` 为空字符串。
- `performance_quotes` 用 `{镜号: 表演原文引文}` 覆盖该角色首个、末个入画镜的 `emotion_and_performance`；只有一个入画镜时不重复键。实际判断仍需结合逐镜完整审核，不能只看两个端点。
- `assessment` 对照全部对白和原表演说明，说明设定是否有依据。问号数量不能证明有无反问，角色在其他场合的习惯也不能自动改写本片台词。

### 两版各自的争议全过程

`conflict_audit` 每版一项，字段为：

`script`、`decision`、`conflict_object`、`disputed_property`、`positions`、`turn`、`closure_scope`、`evidence`。

除 `evidence` 外各叙述项为非空字符串，分别说明物件/事情、争议属性、双方立场、实际转折和本次结束范围。证据按以下四组引用本版真实镜头：

| evidence 键 | 允许的 story_beats |
| --- | --- |
| `opening` | `setup` |
| `dispute` | `conflict`、`escalation` |
| `turn` | `turn` |
| `ending` | `resolution`、`closure` |

每组必须引用该组实际 action；该组存在对白时还必须引用该组实际 dialogue。不能用另一版、另一阶段、来源摘要或计划元数据代替。对白是否从核对金额漂移成付款人或责任争议，需要基于这些真实前后文判断。

最终 v2 保留十五项全局 `checks`，不新增成十九项：`domain_fit`、`core_clear`、`opening_answered`、`ending_complete`、`reasoning_coherent`、`spoken_fit`、`evidence_honest`、`long_adds_value`、`no_narration`、`visual_complete`、`shot_continuity`、`expression_source_fit`、`action_drives_story`、`conflict_turn_payoff`、`source_semantic_fidelity`。它们与故事 v2 的十三项是独立协议。

最终通过要求全量 `checks` 与代码 `REVIEW_CHECKS` 完全一致、各值为布尔值；全部总检查为 `true`、`issues=[]`、所有镜头/结果/人物/争议条目及镜内三个 `cross_checks` 均通过。新增的专项判断独立否决，不能被总检查通过覆盖。格式错误、漏引、旧 SHA 或旧 schema 的报告不能沿用。

## 视频入口的当前审核检查

`scripts/run_script_video.py` 对 `generation.method` 为 `llm_script_pair` 或 `staged_screenplay_bundle` 的项目双稿执行当前审核检查：

- `prepare` 锁定稿件前，从原始 JSON 所在目录恢复唯一绑定它的双稿清单，检查两版实际稿件、原送审内容、完整来源绑定、当前审核协议和提示词，以及保存报告与真实模型响应的一致性。
- 每次非 `preview` 的 `submit` 在付费创建任务之前重新检查，不信任 `prepare` 时缓存的通过记录。锁定稿仍须通过原有 SHA 检查，并与当前原始稿件对象一致；原稿变化、当前报告失效或稿件被退回时，不能继续付费提交。
- 已有的失败重试路径最终仍调用同一个 `submit`，不会因曾经准备成功而跳过当前审核。

这项检查只针对上述项目双稿来源。自定义的非 pair 脚本沿用原有脚本、空间计划和提交校验，不被宣称为经过本项目双稿审核。请求预览、查询任务、查看或处理旧视频不因这项**当前双稿审核**检查被阻断；它们仍须满足各自原有的锁定稿、文件身份或媒体校验。预览成功不表示已获得付费提交资格。

原始双稿恢复入口是 `require_current_saved_script_review`；网页读取使用的 `current_saved_script_review` 在记录缺失或过时时返回待复核状态，保留历史内容可读。视频入口是前者的调用方，不能仅凭旧稿中的通过标志或视频运行清单里缓存的一份审核摘要放行。

## 旧稿与校验能力的边界

旧稿、旧报告和失败尝试均保留，不自动改写历史。旧故事审核 v1 不能进入当前摄影门禁；旧正式双稿审核 v1 不能作为新规通过记录。网页可继续读取历史稿件，但应区分“可阅读”和“已通过当前规则”，提示需要新规复核。只改 schema、补 `true`、复制现有引文或沿用旧结论都不是实际复核。

对旧稿重新审核不等于必须重写：先按当前规则实读，发现真正问题才回对应上游阶段；只有风格建议时不能强制修改已成立的故事。改动剧情后须用新候选 SHA 重新审核，受影响的状态、摄影及 bundle 绑定也要更新；仅摄影问题不要回写正确剧情。

程序可以验证字段完整、角色和镜号覆盖、原文匹配、SHA 绑定、判断值及保存报告的一致性，**不能保证语义永不漏检**。具备完整引文的模型仍可能误解主张与事实、左右手或先后顺序，审核者仍须独立读实际内容。任何已知实质矛盾或影响执行的歧义都保持待修/待复核，不能因为机器校验成功就交付为合格稿。

通过这些门禁只表示相应文字阶段完成。它不代表人工法律专业审核，不证明实际视频的声线、语速、口型和切点连续性，也不会自动生成视频。视频任务仍按 [视频制作流程](SCRIPT_VIDEO_RUN.md) 逐段实际抽帧及听看，合格后才用原始尾帧衔接下一段。
