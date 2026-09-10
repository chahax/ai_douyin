# 短视频与长视频双剧本

原有直接生成入口每次返回两份独立完整的原创剧本，默认短版 45 秒、长版 180 秒，可在网页或命令行修改时长。另有下述显式分阶段 CLI：先审核实际故事，再展开摄影并交回正式双稿审核；它固定为 45/180 秒。网页默认流程尚未自动串联这些新阶段。原先固定 15 秒、3 镜头的模板不再用于这个生成入口。

2026-09-10 起，故事审核升级为 `screenplay_editorial_review/v2`，正式双稿审核也须执行新的跨字段检查，不能只核对动作或文件结构。网页与各 CLI 的最终生成入口共用最终审核规则；这不表示网页已经接入故事、状态、摄影的分阶段自动编排。旧稿仍可阅读，但旧协议报告不能自动视为满足新规。字段定义、待填写模板及旧稿复核方式见 [对白、动作与空间的跨字段审核](SCRIPT_CROSS_FIELD_REVIEW.md)。

## 已审故事 → 摄影 v2 → 正式双稿审核（2026-09-10）

这条流程使用 `scripts/run_screenplay_stage.py`、`script_screenplay.py` 和 `screenplay_bundle.py`，用于避免摄影模型重复描述故事时改错动作主语、物件状态或结局。故事和摄影仍由项目配置的文本模型生成；程序只校验、复制已审原文和派生固定字段，不手写替代动作或对白。早期 `plan_script_expression.py` 的提纲只有话语意图，不能替代这里有真实对白的故事稿或它的审核记录。

输入须来自本项目 `data/pre_video_scripts/_runs/<实际记录>/request.json`。工具核对并恢复该请求绑定的完整来源，至少20条均须有匹配的独立审核与媒体身份；聚焦少数详细参考不绕过全20条门槛。重复 `--reference-source-id` 只选择实际可引用的详细来源，保留全批概览与表达对照。各阶段输出目录必须在本项目 `data` 下且尚不存在，旧稿、旧响应和失败记录不覆盖。

以下命令中的引号内尖括号均为待替换值，**不是已经存在或已通过的稿件路径**。运行前填入当前任务的真实工件、账号、采集批次和参考 ID；不要照抄其他轮次的审核或 SHA。

### 可选：先写动作对白，按需定点修订，再展开状态

当长稿把创作与逐镜完整状态库存同时输出容易产生重复或漏项时，可用 `scripts/run_screenplay_drama.py` 替代下面的一次性故事生成。路径是：`draft` → 实际读稿 → 按需 `revise` 并重读 → `state` → 按需 `state-revise` → 完整故事独立审核 → `production` → 两版 bundle 与正式总审。`draft` 专注因果、动作、对白和时长，`revise` 只替换指定剧情文字，`state` 再补完整初末态，`state-revise` 仅校正已定位的状态文字。每个箭头都需显式推进；网页尚未自动串联这些阶段，原 `story` 默认流程不变。

先生成一版无状态剧情：

```powershell
.\.venv\Scripts\python.exe scripts/run_screenplay_drama.py --stage draft --kind long --workflow-request "<原_runs/request.json路径>" --editor-feedback-file "<本轮干净剧情要求.md路径>" --companion-screenplay "<同批已完成且实际审过的短故事screenplay.json>" --reference-source-id "<实际详细来源ID1>" --reference-source-id "<实际详细来源ID2>" --output-dir "<data下不存在的新剧情目录>"
```

输出 `drama.json`，schema 为 `script_drama/v1`：保留共同核心、两名角色、剧情元数据、道具定义，以及逐镜动作、对白、说话人、节拍和整数时长；不含 `initial_state` 和 `end_state`。它沿用45/180秒、镜数、六种有序节拍、每镜及全片对白上限、真实来源引用校验。输出只标 `candidate_pending_independent_review`，不会自动生成十三项故事通过报告。先实际读剧情，确认中段尝试及其后果、转折和当场结果，再由操作者显式启动状态阶段。

完整 companion 仍在本地验证同批工作流、来源和候选身份，记录原文件及其 `run.json` 的真实路径与字节 SHA。发送给编剧的 companion 仅投影共同 `core_message`、完整角色资料、`premise`/`dramatic_question`/`resolution` 三项摘要及 `short_shot_count`，不展开另一版的逐镜动作、对白或库存；反向生成短稿时提供 `long_shot_count`。输出后仍用原完整对象检查共同核心、姓名、身份以及长版至少多3镜，投影不放宽这些约束。未使用 companion 时省略该参数。

#### 只修已定位的文字问题（可选 revise）

若结构有效的 `drama.json` 只有可定位的文字问题，使用同一原工作流、同一参考选择和当前实际候选，重复 `--revise-field` 指定允许修改的字段。例如，以下只允许模型替换 S05 动作、第一名角色弧光及本版结局摘要，示例不表示这些字段已经有问题或修改后已通过：

```powershell
.\.venv\Scripts\python.exe scripts/run_screenplay_drama.py --stage revise --kind long --workflow-request "<同一原_runs/request.json路径>" --editor-feedback-file "<本轮具体返修意见.md路径>" --drama "<当前实际剧情目录/drama.json>" --drama-run-sha256 "<当前剧情目录run.json原始字节SHA256>" --reference-source-id "<与draft相同的详细来源ID1>" --reference-source-id "<与draft相同的详细来源ID2>" --revise-field /version/shots/4/action --revise-field /characters/0/performance_arc --revise-field /version/resolution --output-dir "<data下不存在的新剧情修订目录>"
```

定点修改仅开放以下五类**现有字符串叶字段**；数字索引从0开始，S01对应 `/version/shots/0`。不接受 `01`、负数、转义、空格、越界索引或重复指针。

| 类别 | 可用字段路径 |
| --- | --- |
| 场内对白 | `/version/shots/<索引>/dialogue` |
| 可见动作 | `/version/shots/<索引>/action` |
| 剧情节拍 | `/version/shots/<索引>/beat`，仍须是合法枚举且全片有序覆盖 |
| 人物弧光 | `/characters/<索引>/performance_arc` |
| 本版文字摘要与场景说明 | `/version/` 下的 `title`、`premise`、`dramatic_question`、`goal`、`obstacle`、`stakes`、`resolution`、`legal_review_note`、`scene`、`spatial_layout` |

共同核心、schema、角色姓名/身份/外观/服装/声线、道具定义、镜数和镜号、每镜时长、说话人、来源及引用全部冻结。模型须返回一个键集合与本次指针**完全相同**的 JSON 对象，每个值为非空字符串；缺键、多键、空白值或非字符串均失败。程序只复制原对象后替换这些叶字段，原稿不变，其余字段不得被继承补丁顺便改写。初始稿与修订结果都接受完整剧情结构、时长、对白预算、节拍、真实引用和 companion 校验；格式失败的 `model_output.json` 不能当作 revise 输入。需要更换说话人、改时长/道具或清空对白时应回 `draft`，不能扩大这个接口的权限。

修订保存 `revision.json`、新的 `drama.json`、允许字段、父稿与父运行的路径/SHA、实际修订前后 SHA。后续读取修订稿时复验父链、重放每次已保存替换并比较整稿，不能仅凭 `unchanged_fields_preserved=true` 相信未改其他字段。父稿、父运行或替换记录缺失/变化，或重放结果不符，应拒绝进入下一阶段，不能改写旧 SHA 来迁就。循环或超过64个节点的父链也会拒绝。

`revise` 成功仍只是 `candidate_pending_independent_review`。必须重新读实际改文及关联动作、对白和结局；字段获准修改不代表内容正确，旧稿审核也不能覆盖新 SHA。需要再次修订时继续使用最新实际 `drama.json`，不要退回更早失败稿重生已修错误。它不自动启动 state、摄影、总审或视频，也不替代后面的完整故事审核。

对实际审读后的同批剧情展开状态：

```powershell
.\.venv\Scripts\python.exe scripts/run_screenplay_drama.py --stage state --kind long --workflow-request "<同一原_runs/request.json路径>" --editor-feedback-file "<本轮状态展开要求.md路径>" --drama "<上一步实际剧情目录/drama.json>" --drama-run-sha256 "<该剧情目录run.json原始字节SHA256>" --reference-source-id "<与draft相同的详细来源ID1>" --reference-source-id "<与draft相同的详细来源ID2>" --output-dir "<data下不存在的新状态目录>"
```

`state` 要求完整20条来源门禁仍通过，`--kind`、原工作流、完整来源 SHA 和参考选择顺序均与 draft 一致。它只接受同目录运行记录标记为已完成待审、候选字节 SHA 相符的 draft/revise `drama.json`；不能传失败响应或借用另一批次。`--drama-run-sha256` 可省略，此时仍记录本次读取的真实 run SHA；显式提供则额外要求逐字匹配。不要在 state 或 revise 重新传 `--companion-screenplay`，工具从父稿继承并复验完整 companion 文件和原运行 SHA。

模型只能返回 `initial_state` 与有序 `end_states`；每个状态必须完整列出两人和全部已定义道具，末态逐镜覆盖且不能重排。程序只合并这些状态，拒绝夹带动作、对白或其他剧情字段，不改原剧情任何字词。缺失或新增道具键、夹带改写字段会失败；状态文字是否暗藏新物件、人物动作与状态是否真的相符仍需读稿判断。剧情本身有错应按范围回 revise 或 draft 修新稿，不能在 state 偷补动作救场。

合并产物是标准 `script_screenplay/v1` 的 `screenplay.json`，通过 `validate_screenplay` 后仍为待独立审核。下一步必须按第2节对这个完整文件做实际逐镜审核并绑定新 SHA，通过 `verify_story_review` 后才能进入原摄影入口；之后 bundle 使用该 `screenplay.json`、它的真实故事审核和摄影工件，无需另一种 bundle 格式。无状态 drama 不可直接代替完整故事交给摄影或 bundle。

#### 只校正初末态中的文字（可选 state-revise）

如果完整故事的冻结动作与对白无须变化，只是某个初态或末态字符串写错，可对本工具实际 `state` 或 `state-revise` 产物定点修订。它不接受一次性 `story` 候选、失败输出或未绑定的外部文件。

```powershell
.\.venv\Scripts\python.exe scripts/run_screenplay_drama.py --stage state-revise --kind long --workflow-request "<同一原_runs/request.json路径>" --editor-feedback-file "<本轮具体状态纠错意见.md路径>" --screenplay "<当前实际状态目录/screenplay.json>" --reference-source-id "<与draft相同的详细来源ID1>" --reference-source-id "<与draft相同的详细来源ID2>" --revise-field "/version/initial_state/props/<既有道具ID>" --revise-field "/version/shots/4/end_state/people/<既有人名>" --output-dir "<data下不存在的新状态修订目录>"
```

仅允许 `/version/initial_state/(people|props)/<既有键>` 和 `/version/shots/<既有索引>/end_state/(people|props)/<既有键>`。这里 `(people|props)` 表示二选一，并非要原样填写。键中原本有 `~` 或 `/` 时分别按 RFC 6901 编码为 `~0`、`~1`；其余路径必须规范且真实存在。不能替换整个状态对象、添加人物或道具键，也不能使用 `/initial_state` 等根级别别名。动作、对白、说话人、节拍、时长、镜号、角色、道具定义、所有剧情摘要和引用全部冻结。

模型返回的键集合仍须与 `--revise-field` 精确一致，每项非空字符串。工具记录 `state_revision.json`、修订前后 SHA 和新 `screenplay.json`，整稿重新通过结构、来源与 companion 校验后仍为待审。原 drama、companion 和父状态工件自动继承；不要另传 `--drama`、`--drama-run-sha256` 或 `--companion-screenplay`。工具沿状态父链重放到原始 `states.json` 与其绑定 drama，比较完整对象；不能靠自报 `non_state_fields_preserved=true` 绕过冻结字段检查。

状态文字即使结构合法，也可能声称冻结动作从未发生的签署、移动或视线变化。必须逐镜对照真实动作、相邻状态与物件来源重新审核，并为新的完整 `screenplay.json` 绑定审核 SHA；旧故事审核不能直接复用。若需要改变动作才能使状态成立，应回剧情修订，再重新展开受影响的状态，而不是用状态文字补造动作。这个阶段同样不自动启动摄影、总审或视频。

四个阶段都保存原始工作流、完整来源、反馈、提示词、请求、模型输出与响应元数据、输入/输出 SHA、实际北京时间与调用数；状态阶段另存 `states.json` 和冻结剧情的身份。`model_output.json` 是提供方经过思考块/JSON包装清洗后返回的文本，**不是原HTTP响应的逐字副本**。新响应元数据用 `content_processing`、`content_is_raw_http_response=false` 明示处理方式；若SDK提供，则记录实际响应模型、响应ID、`finish_reason` 和 token 用量计数（含缓存/推理计数），不保存推理正文。缺失用量不等于零，`stop` 不代表内容通过，`length` 不应误报为超时。历史记录未保存的字段不能追补成已知值。

新目录不可覆盖，一次调用不自动重试；预检失败保留 `preflight_rejected` 与零调用，发出调用后失败保留 `failed` 与真实次数、错误及起止北京时间。导出检查材料、结构校验、父链重放和人工显式运行下一阶段都不等于自动 drama 审批；本入口不上传音轨，也不生成视频。

### 1. 每次生成一版实际故事

```powershell
.\.venv\Scripts\python.exe scripts/run_screenplay_stage.py --stage story --kind short --workflow-request "<原_runs/request.json路径>" --editor-feedback-file "<本轮故事要求.md路径>" --reference-source-id "<实际详细来源ID1>" --reference-source-id "<实际详细来源ID2>" --output-dir "<data下不存在的新短故事目录>"
```

输出 `screenplay.json` 的 schema 为 `script_screenplay/v1`：两名角色的身份、外观、服装、固定声线，以及本版目标、阻碍、结局、场景、空间关系、道具清单、完整初态和逐镜动作/对白/末态。短版6—9镜、单镜4—15整数秒，共45秒；长版9—30镜、单镜3—20整数秒，共180秒。六种节拍按顺序分段覆盖，单镜对白最多每秒5字、全片最多每秒4字，标点计入。普通镜可以静默，末镜须有实际收束对白，以兼容正式双稿的 `closing_line`。

结构合格只得到 `candidate_pending_independent_review`。工具保留 `model_output.json`、真实请求、反馈、完整来源副本及 `run.json` 中的 SHA、模型参数和北京时间起止时间；预检拒绝记录 `model_calls=0`。一次显式阶段调用不会因失败自行重跑模型。时间来自运行记录，不使用文件修改时间。

有效故事候选需要返修时，向同一原工作流提供新的具体反馈，并追加 `--previous-screenplay "<上一版有效故事候选的screenplay.json>"`，输出到新目录。关联稿必须有同目录 `run.json`，与原工作流、完整来源、版本及候选字节 SHA 一致。只有格式失败的 `model_output.json` 不能冒充有效故事候选；保留其失败依据，在新的故事阶段处理。

短稿实际审过后，用其模型原稿约束长稿的共同核心与人物，仍需单独审长稿：

```powershell
.\.venv\Scripts\python.exe scripts/run_screenplay_stage.py --stage story --kind long --workflow-request "<同一原_runs/request.json路径>" --editor-feedback-file "<本轮长故事要求.md路径>" --companion-screenplay "<同一批次已完成且实际审过的短故事screenplay.json>" --reference-source-id "<实际详细来源ID1>" --reference-source-id "<实际详细来源ID2>" --output-dir "<data下不存在的新长故事目录>"
```

`--companion-screenplay` 验证相反版本候选的来源和运行绑定，不自动授予审核通过。两版必须保持相同核心、人物姓名和身份；长版至少比短版多3镜，并有实际增量。

### 2. 保存有原文证据的故事审核

独立审核者实际逐镜阅读动作、完整对白、初末态、人物表现设定、核心与空间关系、引用和结局，另存 `screenplay_editorial_review/v2` 报告；没有“一键生成通过报告”的步骤。故事数据本身仍是 `script_screenplay/v1`，不要将故事 schema 与审核报告 schema 混淆。`verify_story_review` 检查：

- `candidate_sha256` 绑定当前 `screenplay.json` 原始字节，`workflow_request_sha256` 绑定原 `_runs/request.json` 原始字节，`source_evidence_sha256` 绑定阶段保存的完整来源文件原始字节。
- `checks` 的键集合必须恰好为十三项：原有 `core_and_scope`、`conflict_and_turn`、`ending_complete`、`prop_continuity`、`speaker_and_no_narration`、`pace_and_duration`、`source_fidelity`、`legal_boundaries`、`version_value`，加上 `dialogue_action_alignment`、`conflict_focus`、`character_delivery_grounded`、`spatial_alignment`。只有实际审过且全部为布尔 `true` 才能推进；缺项、`false`、`null` 或字符串不能代替。
- `shot_reviews` 按原顺序完整覆盖每镜。每项保留真实 `action_quote`、完整且逐字相等的 `dialogue_quote`、`finding`，并分别写 `dialogue_action_finding`、`conflict_focus_finding`、`spatial_finding`。静默镜的 `dialogue_quote` 必须是原来的空字符串，不能为了报告完整补对白。
- `focus_review` 完整引用当前 `core_message`、`dramatic_question`、`goal`，并按顺序列出全部实际有对白镜号 `spoken_shot_ids`，给出真实焦点核验结论；不能把金额差异、付款人和责任归属当成同一问题。
- `spatial_review.layout_quote` 完整引用当前 `spatial_layout`，说明它与逐镜人物位置、面向、视线及手部状态是否一致。故事阶段不替尚未生成的摄影方案作出通过结论。
- `character_reviews` 按角色原顺序覆盖全部人物，逐字保留每人的完整 `voice_quote` 和 `performance_arc_quote`；`dialogue_quotes` 按镜头顺序列出该角色全部实际对白及镜号，有声对白不能漏掉，无对白角色保持空数组。不能用另一角色台词、问号数量或泛泛语气描述代替实际核验。
- `result_review` 引用真正完成结果的镜头动作，并说明检查结论；元数据承诺不能代替已发生动作。总体、每镜、结果、焦点、空间及人物条目都须实际通过，且 `unresolved_issues=[]`、SHA 匹配，摄影入口才接受。
- 旧 `screenplay_editorial_review/v1` 报告即使原来通过，当前摄影门禁也不接受。实际复核后另存 v2 报告，不能只改版本号、补全 `true` 或复制旧判断。故事字节改变后另需绑定新 SHA，旧报告保留为历史证据。

审核应保留具体检查范围和未验证事项。这里检查文字剧情与制作要求，不表示已看过尚未生成的视频、完成口型检查或法律专业审核。完整的 [v2 待填写模板](SCRIPT_CROSS_FIELD_REVIEW.md#故事审核-v2-待填写模板) 默认待审，不能直接作为生产审批使用。程序只能验证绑定、覆盖、引文及必要结论存在，无法保证语义永不漏检；实质矛盾或影响执行的歧义必须修正并复核，不能靠填齐字段放行，同义措辞和可选风格也不应被扩成强制加戏。

### 3. 冻结故事，生成摄影 v2

每版分别运行；`--kind` 必须与故事匹配。摄影阶段不能混用 `--previous-screenplay` 或 `--companion-screenplay`：

```powershell
.\.venv\Scripts\python.exe scripts/run_screenplay_stage.py --stage production --kind short --workflow-request "<同一原_runs/request.json路径>" --editor-feedback-file "<本轮摄影要求.md路径>" --screenplay "<实际短故事screenplay.json路径>" --story-review "<绑定该故事且实际通过的审核JSON路径>" --reference-source-id "<实际详细来源ID1>" --reference-source-id "<实际详细来源ID2>" --output-dir "<data下不存在的新短摄影目录>"
```

长版使用同一命令的 `--kind long`，替换为真实长故事及其审核文件，输出到另一个新目录。只有该版故事实际通过后才进入摄影。

当前摄影提示词要求 `screenplay_production/v2`，只接受：

- `scene_design`：一次定义 composition、lighting、shot_size、camera_angle、camera_movement。
- `shots`：原镜号、composition、emotion_and_performance，可选 participants。短版逐镜禁止再次填写相机字段，始终双人入画并共享固定机位；长版通常可覆盖景别、机位和运镜，省略时继承场景设置。本次若要求连续固定机位或原始尾帧直接继承，长版也须保持相机方位与景别承接；可选字段不代表允许跳机位。现有最终结构要求每镜至少一名可见角色，发声人须入画，嘴部和关键手区的实际可见性仍需摄影审核。
- `interpretation`：presentation_mode、account_fit、source_pattern_rationale、protagonist 四项；主角必须是原角色，来源解释仍须按原证据复核。

模型不能返回 blocking、transition、action、dialogue、state、expression_plan 或 story_beats。编译器直接取原 `spatial_layout` 作为 blocking、原 scene 作为场景，原固定 voice 与说话人组成音频说明；不增加台词或音效。每镜首态机械继承前镜已审末态；转场只描述该状态继承，末镜在既定时长内结束，不追加静止尾巴。

表达计划与节拍也由已审故事投影：逐组保留实际 action 原文及组末态，转折对应所有 turn 镜，结局引用末镜动作/末态与原 resolution。`because` 首组取 premise，后组取前一组最后一句实际对白，静默时取其动作。程序不再次编造人物主语、因果或完成事实。旧无 schema 的摄影工件仍可兼容读取，新调用使用 v2。

输出 `production.json`、`compiled_version.json` 及经过提供方清洗的模型输出，仍标记待独立审核。构图和表演描述是否暗藏新动作、是否拍得到关键手部与说话人、来源解释是否忠实，仍须实际读稿；编译成功不等于摄影内容通过。

#### 摄影局部返修：production-revise

摄影方案整体成立、只剩明确的字符串问题时，用 `production-revise` 精确替换指定字段。故事本身未改时，继续提供同一份完整故事及其实际通过的审核；入口重新执行 `verify_story_review` 和完整来源门禁，不因是局部返修而跳过。若机位方案整体需要重做，仍使用前述 `production`，并保留重做依据。

```powershell
.\.venv\Scripts\python.exe scripts/run_screenplay_stage.py --stage production-revise --kind long --workflow-request "<同一原_runs/request.json路径>" --screenplay "<实际已审长故事screenplay.json路径>" --story-review "<绑定该故事且实际通过的审核JSON路径>" --previous-production "<同批有效父摄影目录/production.json>" --editor-feedback-file "<本轮摄影定点问题.md路径>" --reference-source-id "<与父摄影相同的详细来源ID1>" --reference-source-id "<与父摄影相同的详细来源ID2>" --revise-field "/scene_design/camera_angle" --revise-field "/shots/6/composition" --output-dir "<data下不存在的新摄影修订目录>"
```

重复 `--revise-field` 指定实际 JSON pointer；数组索引从0开始，示例 `/shots/6/composition` 对应第7镜。只能修改 `screenplay_production/v2` 中已经存在的字符串叶子：

- `scene_design` 的 composition、lighting、shot_size、camera_angle、camera_movement。
- 各镜 composition、emotion_and_performance，以及该镜已经存在的 shot_size、camera_angle、camera_movement；不得为短版或当前未定义的逐镜相机字段新增键。
- `interpretation` 的 presentation_mode、account_fit、source_pattern_rationale、protagonist。

模型只返回“指针 → 非空完整字符串”的 JSON 对象，键集合必须恰好等于本轮请求；缺值、多键、对象替换、假路径或重复路径均拒绝。schema、shot_id、participants、所有未指定摄影字段及全部故事内容冻结。精确替换后重新运行 `compile_screenplay`，仍检查合法相机值、原人物主角和完整故事映射；构图或表演文字是否暗藏新动作，须另由实际审核判断。

`--previous-production` 只能来自同一工作流、来源选择、当前故事及当前故事审核的已完成待审 `production` 或 `production-revise` 候选。读取时核对父摄影与 `run.json` 的真实路径和字节 SHA、原请求、模型输出及编译稿；修订链逐层重读父稿、核对补丁并重放，比对完整摄影对象。循环引用或超过64个节点的链条拒绝；不能只改运行记录里的“未变”标志或 SHA 来掩盖其他字段变化。失败运行的响应不能冒充有效父候选。

新目录保存 `production_revision.json`、完整 `production.json`、`compiled_version.json`、本轮请求及模型输出，以及父工件/运行 SHA、允许字段和修订前后 SHA。原文件不覆盖，失败不自动重试，候选仍为 `candidate_pending_independent_review`。修订后须完成新摄影稿的独立审核，再用新摄影工件进入完整双稿审核；局部替换或编译成功不等于摄影、双稿或视频通过，也不生成视频。

### 4. 绑定两版工件，进入正式最终审核

两版故事、各自实际审核和摄影工件准备好后，创建 `staged_screenplay_bundle/v1` JSON。以下仅为结构示意，不是一份可直接运行或已通过的清单：

```json
{
  "schema": "staged_screenplay_bundle/v1",
  "workflow_request_path": "<真实原_runs/request.json路径>",
  "workflow_request_sha256": "<该文件原始字节SHA256>",
  "source_evidence_path": "<真实完整source_evidence.full.json路径>",
  "source_evidence_sha256": "<该文件原始字节SHA256>",
  "reference_source_ids": ["<实际详细来源ID1>", "<实际详细来源ID2>"],
  "short": {
    "screenplay_path": "<真实短故事screenplay.json路径>",
    "screenplay_sha256": "<该文件原始字节SHA256>",
    "review_path": "<真实短故事审核JSON路径>",
    "review_sha256": "<该文件原始字节SHA256>",
    "production_path": "<真实短摄影production.json路径>",
    "production_sha256": "<该文件原始字节SHA256>"
  },
  "long": {
    "screenplay_path": "<真实长故事screenplay.json路径>",
    "screenplay_sha256": "<该文件原始字节SHA256>",
    "review_path": "<真实长故事审核JSON路径>",
    "review_sha256": "<该文件原始字节SHA256>",
    "production_path": "<真实长摄影production.json路径>",
    "production_sha256": "<该文件原始字节SHA256>"
  }
}
```

所有路径（包括 bundle 本身）须解析到本项目 `data` 内，SHA 使用真实文件原始字节的小写64位十六进制值。可读取 `(Get-FileHash -LiteralPath "<实际文件路径>" -Algorithm SHA256).Hash.ToLowerInvariant()`；哈希计算只证明文件身份，不产生审核通过。

在原账号、原采集批次和相同来源选择下交回正式入口：

```powershell
.\.venv\Scripts\python.exe scripts/pre_video_script.py --account-key "<原账号key>" --collection-run-id "<原采集批次ID>" --recent-video-types "<该选集真实展示类型，逗号分隔>" --short-seconds 45 --long-seconds 180 --script-reference-source-id "<实际详细来源ID1>" --script-reference-source-id "<实际详细来源ID2>" --staged-screenplay-bundle "<data内实际bundle.json路径>"
```

原请求若设置了相关度或发布时间筛选，继续使用其真实筛选条件。bundle 的参考 ID 顺序必须与本次 `--script-reference-source-id` 完全一致；各阶段未聚焦时，bundle 保持空数组，最终入口也不传这些参数。注意阶段命令用 `--reference-source-id`，正式双稿命令用 `--script-reference-source-id`。

也可在已有 `scripts/run_account_video_research.py` 续批次命令中同时使用 `--generate-script-pair --staged-screenplay-bundle "<实际bundle路径>"`，并传相同参考选择；该入口先保留原来源门禁。bundle 不能与 baseline/resume/revision 参数混用。`--check-sources-only` 仅验证来源准备程度，不验证 bundle，也不执行最终内容审稿。

loader 逐文件验证字节 SHA、原请求与完整来源绑定，再要求完整来源与当前20条证据规范 JSON 相同、账号定位一致、45/180时长一致、参考选择一致。它重新检查两版故事及故事审核，再编译成完整 pair；不得把外部 `compiled_version.json` 当成已通过的最终稿直接导入。

随后仍必须经过现有 `parse_pair` 和 `review_pair`。正式报告为 `script_editorial_evidence_review/v2`，绑定本次实际送审稿件与证据规范 JSON 的 SHA。它保留十五项总 `checks`，并在完整逐镜 `shot_audit` 中增加 `cross_field_evidence`、`cross_checks` 和 `dialogue_action_note`：八项对应字段原文中，`dialogue`、`audio`、`camera_angle` 必须全文匹配；每镜另判 `dialogue_action`、`voice_performance`、`spatial` 三项。两版各有 `resolution`/`ending` 的 `result_audit`，还须完整填写逐版逐角色 `character_audit` 与每版一个 `conflict_audit`。任一专项失败都独立阻止通过，不能靠总检查为真覆盖。字段和证据范围详见 [正式双稿审核 v2](SCRIPT_CROSS_FIELD_REVIEW.md#正式双稿审核-v2-的证据覆盖)。

故事审核的十三项与正式双稿的十五项总检查是两个不同协议，不合并成十九项。新最终规则同时用于网页、直接生成、续稿与 staged bundle 的正式审核；保存报告仍须用 `validate_saved_script_review_report` 对当前稿件和实际证据重验，旧 v1 不自动迁移。模型审稿格式失败仅按既有规则修复审稿格式，不改写故事。

此入口只作最终复核，`generation.method=staged_screenplay_bundle`、`generation_api_calls=0` 表示本次没有调用编剧，**不表示没有调用审稿模型**。它不运行作者补丁、自动调时或重写首态；`bundle.provenance.json`、编译稿、最终审稿与失败尝试记录均保留。两版同时通过才由原 service 写出正式 Markdown、JSON、来源审计和双稿清单，之后仍需代理实际复核并交用户审核。

### 失败回到产生问题的阶段

故事动机、对白、动作对象、道具状态、法律边界或结局不合格，回故事阶段生成新候选、重新实际审核，再据新 SHA 展开摄影。仅摄影机位、构图、表演有错，则保留未变的已审故事与审核，修摄影反馈后运行新摄影目录。来源引用或归纳本身有问题，先回来源分析与语义复核，再重建受影响的阶段绑定。最终审核不通过只保存问题并退出，不在 bundle 入口偷偷改已审稿。

返修按事实分类：对白指代或完成时序抵触实际动作、润色偷换争议对象、语气设定无台词支持、人物面向与机位互斥，属于需定位处理的内容或执行问题；普通近义用词、个人句式偏好属于可选建议。提议不一定要立即执行，工具放下后仍可继续协商，收存意图不自动要求装包。审核概括不能成为新的动作脚本；若报告误述左右手或把某镜结果提前，回到候选原文和相关状态核验，不因报告一句概括改写正确剧情。

生成、审核与写出双稿都不提交视频任务，不向音频理解接口上传音轨。来源阶段仍是本地抽帧观察和本地 ASR，文本阶段仅发送已有观察、转写和剧本文字。正式清单继续记录 `paused_at=before_video_generation`；故事或摄影通过不能当作视频通过。后续若执行视频，须另按 [视频制作流程](SCRIPT_VIDEO_RUN.md) 逐段生成、实际抽帧和听看审核，通过后才取原始尾帧衔接下一段；未检查的声线、口型或连续性不能标通过。

## 原有直接生成与定点修订入口

编剧提示词维护在 `src/trend_intelligence/prompts/script_pair.md`，生成时实时读取，审计中记录提示词版本、内容哈希、实际模型和提供方。

当前结构仍为 `detailed_video_script/v4`，2026-09-09 起增加带音画证据的表达计划和来源使用记录，来源审计升级为 v3。禁止旁白、画外解说、解说配音、内心独白；角色表、声音模式、说话人、动作、表演及声音说明均有相关校验。人物改名包装解说等语义问题由独立审稿继续检查。现场对白要求人物入画；设备传声须指定已定义角色与场内声源；允许没有人声和字幕的静默动作镜头。

编剧与审稿使用独立模型客户端，`SCRIPT_LLM_TIMEOUT_SECONDS` 默认 600 秒，以容纳完整分镜长文本；不修改其他模型调用的 120 秒默认值。该客户端关闭 SDK 自动请求重试，连接失败或空响应按请求故障记录并停止，避免与内容不合格的三轮改稿混淆。

`SCRIPT_LLM_MODEL` 指定编剧与修订模型，留空沿用通用模型；`SCRIPT_REVIEW_LLM_MODEL` 可指定独立审稿模型。`SCRIPT_LLM_THINKING` 留空沿用服务默认；仅 MiniMax-M3 支持在编剧入口设置 `disabled` 或 `adaptive`，请求参数进入生成审计。具体支持方式已按 [MiniMax 官方 OpenAI 兼容接口说明](https://platform.minimaxi.com/docs/api-reference/text-openai-api)核对；模型须来自已连接服务实际返回的模型列表，不能猜测可用型号。

该客户端的输出上限由 `SCRIPT_LLM_MAX_TOKENS` 配置，默认 32768。格式损坏但非空的回复保留到草稿文件，作为内容格式问题进入修正；响应结束原因单独记入 `response_n.json`，便于区分截断、连接失败和结构缺陷。预检汇总缺字段、编号、声音约束和台词预算，避免每轮只报告最先遇到的字段。

已获得可定位镜头的有效 JSON 后，改稿模型只返回需要修改的字段和镜头；程序保持其余字段原文不变。修订不能偷偷新增或重复镜头，合并后仍对整组短、长剧本进行全部结构检查与独立审稿，不能局部通过就交付。保存 `call_n.json` 实际模型请求、`revision_n.json` 模型原始修订与 `draft_n.json` 合并稿，区分模型修改和程序合并。结构不足以定位镜头的初稿才要求完整重写。

修订阶段使用独立系统提示，返回扁平 `changes` 列表（script、shot_id、field、value），避免“全量双剧本 JSON”与“只改局部字段”两种输出要求冲突。对保存稿进行实际读稿后，可同时传入 `--resume-draft` 和 `--revision-feedback-file`：原账号、样本与原始输入仍必须匹配，新意见单独保存和记录哈希，强制交回模型修改后重新完整审稿，不能直接把旧稿重新标记通过。

`--resume-revision` 可以续用工作流已保存的模型修改，必须与 `--resume-draft` 位于同一原始记录目录，且修订请求中的 `current_pair` 与指定草稿逐项相同。仍完整校验和审稿，失败后才请求模型继续修改。共同 core_message 若被模型误标为 short 或 long 作用域，可统一到共享字段；多个值冲突时拒绝，不自行选择内容。

单人镜头的 participants 如果误写为一个已定义角色名字符串，可规范成单元素数组；不拆分未知名字、不补造角色。原始形状保存在 `model_shape_n.json`，规范化记录进入审计，随后仍核对说话人是否入画。

审稿是独立只读阶段，不执行编辑材料里遗留的改稿输出指令。审稿返回格式损坏时只重试一次审稿；再次失败则保留剧本、记录审稿失败，不能把它当成剧情错误而触发改稿。实际审稿请求、原始响应及格式重试次数均保存。人物“指示另一人做事”与“另一人已经做完”须按实际动作主语区分，不能混为重复动作。

审稿输入沿用完整分镜的规范字段名（包括 narrative_purpose、dialogue_speaker、start_seconds），不再改名为 purpose 等别名而造成缺字段误判。一个连续镜头允许顺接或同时发生的简洁动作链，不能只因动作数量多于一项就要求拆镜。

每条审稿问题须附当前剧本字段的原文引用，程序校验版本、镜头、字段和引文逐字匹配。引用不存在或来自其他镜头时属于审稿失败，先重新审稿，不能把凭空推断的问题送去改稿。跨镜连续性同时参考首尾画面与 continuity，正常反打期间保持不动的道具无需在每镜重新入画证明。

若模型给出的时间线本身连续、镜头均在3—20秒范围内、总时长正确，只是个别镜头台词需要稍多时间，编排器可从其他镜头的空余时长挪用秒数。全片台词预算及单镜上限不放宽，不改对白和镜头数量；无法在原总时长容纳时仍退回模型。原始时间线保存在 `model_timeline_n.json`，调整逐项进入审计，最终仍接受完整审稿。

每镜必填画面构图、光源方向与质感、景别、机位、运镜、站位视线、首帧、连续动作、尾帧、表演、对白、声音、剪辑衔接和连续性。一个镜头只允许一个景别和一种运镜；摄影摘要由结构字段生成，避免“正反打”与“内部不切镜”互相矛盾。完整视觉字段进入独立模型审稿，新增无旁白、视觉可执行性、镜头连续性三项检查。程序检查结构不代表语义一定正确，仍需实际读稿。

工作流额外自动导出 `.pair.review.md` 双剧本完整分镜审核稿，并在清单记录 `review_path`。网页直接展示构图、光线等全部分镜字段，将供后续视频制作使用的提示词放入折叠区。审核导出和网页展示共用剧本数据，不再人工摘录动作与对白而遗漏摄影信息。

每版必须明确唯一核心、人物目标、具体阻碍、有意义的行动和本片可见的结果，以及实际出现在最后镜头中的收尾台词。表达方式从原片音画证据和同批高表现表达对照中选取，结合账号受众与服务范围，优先采用实物演示、人物目标受阻、行动对照与冲突推进；不能把“法律内容”自动转成律师问答。冲突可以是人物意见、目标和现实阻碍，也可以是实物操作证明某个错误判断，不等于凭空安排争吵或编造胜诉。去掉解释台词后应仍有至少两步改变情境的行动；点头翻页陪衬讲课不算。长版增加有效行动、事实对照和人物变化，不能复制短版拖长。保留法律条件，不以“未完待续”或准备咨询替代结局。

进入编剧前必须通过 `source_media_gate/v1`：所选同批至少20条来源均有原片哈希、带实际时间的抽帧清单、完成的图像分析、全音轨转写（或有依据的无语音确认），以及绑定证据ID的核心表达与表达方式。只有标题、授权标志、旧摘要或部分帧分析不算通过。文件变化后须重分析；失败停止并保存逐条缺失清单，不能静默降级再写稿。`scripts/pre_video_script.py --check-sources-only` 仅检查来源，不调用编剧或视频模型。网页显示与生成入口相同的已选来源覆盖口径。

本地图像能力由 Qwen3-VL-4B 处理按时间抽样的所有帧批次，音轨由 Paraformer + VAD 转写，再结合帧观察和转写文本提取表达。源证据含通道、时间、观察内容；抽帧不能证明未观察到的连续动作，ASR不能证明声线、语气或口型。原生音频不上传外部音频理解接口。搜索采集器只取得元数据；另设原片获取节点，用真实播放器或已观察详情响应绑定来源身份、下载二进制、验证时长和SHA并保存回执。没有原片的来源保持待分析，不能把下载完成当作音画分析通过。已有原片通过绑定账号、采集批次、item_id、video_id的 `research_local_media/v1` 清单接入研究入口，详见 [音画来源与表达分析](SOURCE_EXPRESSION_ANALYSIS.md)。

高表现对照按同一种明确指标分别计算：同批筛选出的来源集合内，点赞或播放值的上四分位（包含并列）与其他样本对照，记录表达方式支持条数、来源ID及中位指标。点赞与播放不混加，不能由点赞推断完播、转化或因果。采样对数得分仅用于检索排序，不再归一化为创作参考占比。

每版的 `generation.expression_plan` 保存呈现方式、账号适配、目标/阻碍、行动链、转折和结局；`generation.reference_usage` 保存源ID、实际证据ID、借鉴的抽象方式、原创改编和对应镜头。解析器校验源/证据/镜头ID、时间范围并保留证据快照，拒绝虚构贡献比例。独立审稿新增 `expression_source_fit`、`action_drives_story`、`conflict_turn_payoff` 和 `source_semantic_fidelity`，判断实际镜头是否落实表达方式、是否忠实于来源原句与画面。归纳改变条件或拼接因果时须停止修来源，不能只靠计划字段齐全判通过。

两版都通过结构校验和独立模型审稿后才保存产物。结构校验包括镜头时间连续、总时长、角色、台词长度、节拍覆盖和结尾台词实际落地。审稿另用 `script_pair_review.md` 检查领域适配、核心、问题回答、结尾、推理、口语节奏、证据诚实和长版增量；不通过则带着问题修订，完整结构存在时只改相关字段，最多三轮。审稿记录进入来源审计。模型编辑审稿不能替代人工法律核验，最终仍须代理实际读稿后交用户审核；不能仅因格式完整就标记“OK”。未配置真实模型时不会使用模拟模板冒充结果。

每版各保存 Markdown、JSON 和来源审计；另保存双剧本清单，其中 `paused_at=before_video_generation`。网页分别展示两版并提供下载。不会提交任何视频生成任务。

单独生成双剧本：

```powershell
.\.venv\Scripts\python.exe scripts/pre_video_script.py --account-key account01 --recent-video-types mixed,talking_head --short-seconds 45 --long-seconds 180
```

采集研究脚本增加 `--generate-script-pair`，在本次研究达标后使用同一采集批次生成两版，并停在生成视频前。分析前的 20 个不同视频、至少 2 个主要标签、已确认点赞数或明确播放量按单一口径合计 100 万的门槛保持生效；实际剧本来源也须达标。使用 `--resume-collection-run <run_id>` 可续跑已保存批次，保留原始采集时间，不重新打开采集浏览器。确认记录随研究日志和剧本审计保存。

默认以同批采集作为时间范围；仅在显式提供 `--window-days` 时按发布时间筛选。发布时间和表现形式未知的来源如实标记，不能用文件时间代替发布时间，也不据元数据声称已观看源视频。

人工验证可使用 `--wait-for-verification 600`。仅在有界面模式等待用户完成验证码，在同一采集窗口显示视频结果后直接继续，不重开登录助手、不自动破解验证码。保存状态只读取已有页面，不通过创建临时页面导出状态。

实际读稿后的意见可通过 `--editor-feedback-file <path>` 交回编剧模型；这不是手写替代稿。每轮原始草稿、结构问题和模型审稿保存在输出目录的 `_runs/<id>`，未通过的草稿不会写成正式双剧本。45 秒短版只回答一个问题，台词以每秒 3—4 字为目标，硬上限每秒 5 字；错误反馈包含具体镜头和字数预算。研究结束、编剧开始和编剧结束分别记时。网页可读取命令行生成的最近一组正式双剧本，按记录中的时间排序，不使用文件修改时间。

使用 `--resume-draft <_runs/id/draft_n.json>` 可续审工作流已保存的真实模型稿；其原始输入必须与本次账号定位、样本、时长、提示词及编辑意见逐项一致。此时仍执行全部结构检查和独立模型审稿，并记录续审路径及本次实际编写 API 调用次数；不通过时才调用编剧修改。校验一次汇总多个台词预算问题，整片台词上限为时长乘 4，单镜头上限为时长乘 5。说话人括号内的表演说明归入声音说明，不改动对白，也不豁免无旁白约束。模型审稿收到程序已验证的结构结果，不应误要求两版结尾逐字相同。

代理实际读稿未通过的产物在清单中标记 `agent_review.status=needs_revision`，页面不将其作为最近审核稿展示；模型通过不等于代理或用户通过。
