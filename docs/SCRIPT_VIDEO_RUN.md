# 指定短版剧本的实际视频生成

## 用户长期要求：生成后必须抽帧检查

2026-09-08 用户明确要求“之后生成视频你抽帧检查”。此要求适用于后续每次视频生成和重生成，助手负责完成检查，不能只把成片交给用户找问题。

1. 每镜下载后自动提取真实首帧、末帧和每 0.5 秒画面，图片标注解码帧号与视频时间。检查人物身份、座位/视线、手和道具、动作速度及口型。快速或可疑动作应额外加密抽帧，不能只看一张代表图。
2. 合并及字幕处理后重新提取成片画面，每个切点检查前后 0.5 秒；核对前镜末状态与后镜开场状态。换机位不要求像素相同，但人物位置、视线、道具状态和动作必须连续。
3. 抽帧无法判断声线和语速。必须同步听看原视频，逐镜确认谁在说话、声线是否属于该角色、嘴是否对应对白、语速是否合适；ASR 文字正确不等于声画正确。
4. 保存每项观察的秒数和证据。发现错配或衔接错误就标为未通过；检查未完成应明确记录待检查，禁止自动填写全部通过。交付时说明已检查的范围和未解决问题。检查不自动触发付费重生成。

`query` 下载成功、`merge` 合并和字幕版渲染都会自动生成 `review_packets/<视频名>/<内容标识>/packet.json`，包含时间标注抽帧、首尾对照、切点对照、切点带声音片段、音轨和待填写审核模板。旧视频可以只做本地抽帧：

```powershell
.venv\Scripts\python.exe scripts/run_script_video.py review-packet --run-dir <批次> --shot S04
.venv\Scripts\python.exe scripts/run_script_video.py review-packet --run-dir <批次>
```

抽帧产物按原视频、剧本和切点记录绑定哈希，重复运行不覆盖原有审核。检查图片是派生材料，不能当作方舟可接受的原始肖像参考上传。`review.template.json` 初始检查项均为未填写；工具没有自动视觉、声线或质量判定能力。

## 逐段生成、审核与累计停止

2026-09-09 更新了上游剧本生成门槛：新稿须先完成同批至少20条原视频的音画表达分析，再结合高表现表达对照和账号定位创作；不再由标题摘要直接生成法律问答。具体见 [音画来源与表达分析](SOURCE_EXPRESSION_ANALYSIS.md) 和 [双剧本流程](SCRIPT_PAIR_WORKFLOW.md)。现有生成原片及审核记录保留，不补造其来源分析；这项改动不自动触发付费视频重生成。

用户明确的顺序：第一段生成 → 本地抽帧并查看原视频 → 审核通过 → 取本段平台返回的原始尾帧作为下一段首帧 → 生成下一段并审核。发现缺陷先修对应剧本、分镜与提示词，重生成当前段，不能把不合格片段的尾帧继续传下去。音轨上传不是这个衔接流程的前置条件，也不是首帧生成请求的必需输入；外部音频理解是可选审核辅助服务，未单独授权不上传。声线、语速和口型仍须检查，未能确认的项目如实保留为待检查。

当前用户已授权的连续制作任务保存在 `data/video_generation/sequential_workflow_20260908/campaign.json`。每个修订批次放在该目录下，在第一次提交前绑定同一 campaign；不能为每次失败另建 campaign 来重置计数。

素材采集与视频生成分别记录状态：抖音网页采集可能需要用户完成人机验证，方舟视频生成通过 API 调用。对已有剧本的修订和视频续做，确认该剧本绑定的同批次来源样本已达标后，可沿用该来源；新的网页采集失败不应作为已有剧本生成视频的阻塞条件。必须保留真实来源批次、采集时间及新采集失败记录，不能把沿用样本写成新采集完成。用户明确要求使用新素材的任务仍须先取得新一批达标样本。

```powershell
.venv\Scripts\python.exe scripts/run_script_video.py attach-campaign --run-dir <campaign目录内的制作批次> --campaign <campaign.json>
.venv\Scripts\python.exe scripts/run_script_video.py review-segment --run-dir <制作批次> --shot S01 --review-file <实际审核.json>
```

审核 JSON 沿用检查模板中的视频和剧本哈希，`decision` 为 `passed`、`failed` 或 `pending`。八项 checks 使用 true（已检查通过）、false（已发现问题）、null（尚未检查）。只要已有确定缺陷即可记录失败并回到上游修订，无须先完成其他检查；无缺陷但仍有未检查项则为 pending，不能生成下一段；全部检查通过才能放行。`observations` 覆盖已有结论的检查项，每条包含 `check`、本镜 `time_seconds`、具体 `notes`、`evidence`（制作批次内证据文件的相对路径数组）。例如一个声线问题应记录原视频或本地音频检查依据、实际秒数和画面中发声者，不能只填“通过”。每次检查保存在 `quality_review_history` 中，补查不会抹去先前记录。

规则：上一段审核完成前禁止提交下一段；仅允许生成下一个未通过镜头；下一段首帧必须是紧邻已通过片段的原始尾帧。失败后先经项目编剧模型定点修订，再准备新批次并保留旧产物。已有任务结果不明时先查清，不重复提交。已确认在创建前被拒绝的请求不算“生成了一个不合格视频”。累计第 10 个生成输出失败时保存 `HUMAN_REVIEW_REQUIRED.json` 并停止后续提交，重试、换镜头和换修订目录均不重置计数。所有片段通过后才能合并，合并成片仍需重新检查每个衔接与声音。

编剧入口新增 `--baseline-draft <项目 _runs 中的完整双剧本>` 和 `--revision-feedback-file <具体问题>`，用于在新输入下定点修改已有稿。它与要求输入完全一致的 `--resume-draft` 分开记录；保存原稿与原始请求哈希、新证据请求、模型字段补丁和完整审稿结果，不覆盖旧请求伪装成同一次生成。不得混用这两种模式。

本次连续短片同时使用 `--continuous-short`：程序将下一镜 `start_frame` 绑定为前镜模型所写的 `end_frame`，保留原模型描述与逐项绑定记录，动作和对白不自动改写。随后检查短版每镜都有两个既有角色、固定同一景别/机位/光源、4—15整数秒及绑定后的连续状态。审稿和实际读稿须确认 action 能从继承状态执行，不能因绑定成功就放行跳过拿放的动作。此检查不代表模型实际生成画面已经连续，仍需检查原视频。

`SCRIPT_REVIEW_LLM_MODEL` 可以为只读审稿指定独立模型，审计分别记录编剧与审稿型号。当前项目编剧使用 MiniMax-M3，独立复核使用已有的 MiniMax-M2.7。`--review-only --resume-draft <同输入原稿>` 只做结构与编辑复核；失败保存审稿结果并返回，不调用编剧改写。审稿必须引用当前稿件的真实原句，引用不匹配就拒绝该审稿结果，不能拿它来修改正确稿件。

`scripts/run_script_video.py` 使用项目现有 `DreaminaCLIClient`，将用户指定的 v4 短版分镜保存为不可变快照。该入口只生成待审核候选，不启用已退役的旧视频管线，不发布。

步骤为准备执行分镜 → prepare → 按镜 submit → query 下载 → 逐镜检查 → review-reference → 后续镜头 → merge → 成片审核。submit 在调用服务前持久化回执；网络错误或结果不明也保留回执，重复执行会拒绝再次消费，应根据已保存任务 ID 查询。参考视频限制为本批实际文件，逐项记录哈希；台词来自锁定剧本，双人对话的画面提示由执行计划重新编译。

实际参数为项目已配置的 Seedance 2.5、480p、9:16，保留模型原生对白。首镜建立人物与场景，后续镜头接入前面实际生成的参考视频。跨镜一致性需要看片核实，不因附加参考素材就自动判通过。

清单 `production.json`、镜头回执、原始视频、媒体探测和审核记录写入 `data/video_generation/<批次>`，由现有制作页面读取。提交、查询和完成时间分别记录，显示为北京时间；不使用文件修改时间推断完成时间。

合并保留实际音轨及内容，不把生成偏差裁掉、不用冻结画面补齐时长。目标时长与实际时长分别记录。生成视频仅为候选，终审未完成前不标记可发布。

## 双人隔桌对话的空间与动作计划

本入口的双人片需要先通过 `scripts/prepare_conversation_direction.py` 调用项目配置的剧本模型，生成 `conversation_direction/v1` 计划。固定人物分别处于桌子南北侧、所有摄影机在西侧；双人景和两种单人景有明确机位，不把“画面左/右”当成人物可移动的座位。该计划适用于两人隔桌坐谈，其他调度需要另外的执行方案。

模型只改动作、首末帧和表演节奏，原台词、人物、六镜数量及时间线保持锁定。要求首帧启动动作、0.5 秒以内接话，短促动作与对白并行。编译时替换旧画面提示，不追加两套互相矛盾的机位。剧情创作和修订仍由项目模型完成，请求、原始回复、来源哈希和反馈哈希均留档。

```powershell
.venv\Scripts\python.exe scripts/prepare_conversation_direction.py <剧本.json> <计划输出目录> --north-person 律师 --south-person 客户
.venv\Scripts\python.exe scripts/run_script_video.py prepare --run-dir data/video_generation/<新批次> --script <剧本.json> --direction-plan <计划输出目录>/direction_plan.json --authorization <已获得的生成授权>
```

结构校验不能代替执行审阅。发现跨桌触碰、道具换手、长时间单次动作等问题时，保存具体意见文件，再用 `--draft <已有direction_plan.json> --feedback-file <意见.txt>` 调用模型修订，输出到新目录。不要手工篡改模型回复或已提交镜头的提示词。

首镜下载后实际检查隔桌关系、身份、动作速度和说话人入画。审核输入 JSON 包含 `checks`（`spatial_layout`、`identity`、`action_pace`、`speaker_visibility` 四个布尔值）、具体 `notes`、`evidence`（本批目录内真实抽帧或检查文件的相对路径）。运行：

```powershell
.venv\Scripts\python.exe scripts/run_script_video.py review-reference --run-dir data/video_generation/<批次> --shot S01 --review-file <检查.json>
```

后续 submit 的所有参考视频必须有与当前视频哈希、当前执行计划哈希一致且四项均通过的审核记录。缺少审核、审核失败或素材/计划变化时，在调用生成服务前拦截。审核结果必须来自实际看片；自动检查只验证记录与证据完整性，不自动判断视觉语义。原有完成批次仍可预览、查询和合并；缺少执行计划的旧双人批次不能继续付费提交。

## 现有素材的节奏对比

```powershell
.venv\Scripts\python.exe scripts/run_script_video.py pace-preview --run-dir data/video_generation/<已完成批次>
```

需要各镜真实本地 ASR 时间戳。仅将第一个识别字开始前、预留 0.2 秒余量的动作段加速 1.5 倍，对白部分保持原速；不删台词、不覆盖原视频，不提交视频生成。输出 `pacing_preview.mp4`、实际时长及逐镜变速审计，在制作页面“合并成片”与原版并列展示。ASR 起点可能有误差，预览仍需核对声音。

2026-09-07 合同短版的预览为 41.307 秒。它只比较动作节奏，原来的座位关系和字幕错误仍然存在；新执行计划是否能落实，需要另行生成首镜并实际验收，不能由计划校验通过推断成片通过。

单段对白已接近要求、用户要求再小幅加快时，可以本地生成声画同步变速预览：

```powershell
.venv\Scripts\python.exe scripts/run_script_video.py speed-preview --run-dir <批次> --shot S05 --speed 1.08 --authorization "用户要求这一版再快一点"
```

输出独立的 `S05.speed_1p08.mp4`，完整保留帧序列，画面与声音按同一倍率加快，声音使用保音调的 `atempo` 处理。保存原片与预览哈希、实际时长、用户要求和新的抽帧审核包；重复执行核对已有产物，不覆盖原片。此步骤不调用生成或音频理解接口，不自动通过审核、不选择成片素材，也不放行下一段。预览获认可后须明确记录交付版本并适配合并及切点时间，不能将预览获认可写成原速语音已经通过。下一段参考仍来自经审核的原始平台尾帧。

变速版完成实际检查及用户声音确认后，`review-segment` 的审核文件将 `source_sha256` 绑定变速视频，补充 `source_original_sha256` 与 `delivery_preview`（本批已登记的变速审计 JSON 绝对路径），观察秒数使用变速版时间。审核通过后 campaign 同时保存原片来源哈希与获准交付版哈希；合并及切点检查自动使用获准交付版和实际时长。继续生成仍强制使用原片的平台尾帧。原始回执、此前待检查记录与变速产物的生成审计保持不变。

用户明确要求整体节奏试听时，可执行 `scripts/run_script_video.py assembly-speed-preview --run-dir <批次> --speed 1.05 --authorization <用户要求>`，把当前各镜交付版本再同步提速5%，输出独立的完整预览。此本地编辑允许包含已登记、无已知失败检查项的待确认交付版，保留其 pending 状态；不能借此放行下一段付费生成或标为正式合格成片。已失败、来源变化、未登记的待审镜头仍拦截。保存各镜实际输入哈希、叠加倍率、完整帧数及 FFmpeg 返回的真实切点时间，重新导出五处衔接和全片抽帧供检查。此次用户要求的整片预览不改变累计失败次数、原逐段审核或既有字幕保留决定。

用户明确指出整片某处无动作、无对白的停留或段落语速不一致时，使用 `assembly-rhythm-preview --run-dir <批次> --edit-plan <本批编辑计划.json> --authorization <用户反馈>` 做局部修正。计划采用 `script_video_rhythm_plan/v1`，绑定此前整片提速报告及视频哈希，逐镜记录来源哈希、修改原因、附加倍率与可选的 `keep_end_seconds`；未列出的镜头沿用此前倍率。裁掉静音尾部必须先保存本地音量与 ASR 对照、实际尾部画面检查，至少保留估计发音结束后 150 毫秒；ASR 单字尾点可能延伸至静音，须核对音量而不能只信单次识别。不能裁掉有意义的动作或对白来掩盖生成缺陷。渲染后核对字句、全部切点及起手动作，记录有意删除的停留帧和实际时长，导出独立版本，不覆盖旧片、不修改原逐段审核、不增加付费生成失败次数。画面检查和本地 ASR 不能替代声音与口型的人工确认。

## 火山方舟 Seedance 2.0 Mini 首镜测试

用户新购的 API 使用独立的 `ark_api` 渠道，首选 `doubao-seedance-2-0-mini-260615`、480p、9:16、原生音频。`.env` 设置 `SEEDANCE_PROVIDER=ark_api`、`ARK_API_KEY`，模型和服务地址分别由 `ARK_SEEDANCE_MODEL`、`ARK_BASE_URL` 配置。官方服务地址为 `https://ark.cn-beijing.volces.com/api/v3`，任务路径 `/contents/generations/tasks`。不复用即梦 OAuth 或 BytePlus API Key。

Mini 时长在提交前限定为 4–15 秒整数。依据用户提供的官方提示词指南，Mini 提示词按动作顺序编译，不向模型强压小数秒时间点；内部执行计划仍保留时间表，供看片比较。台词、角色、座位、机位、光线及动作内容均来自锁定剧本和项目模型的修订计划。

```powershell
.venv\Scripts\python.exe scripts/run_script_video.py prepare --run-dir data/video_generation/<Mini测试批次> --script <剧本.json> --direction-plan <执行计划.json> --provider ark_api --test-shot S01 --authorization <已有用户授权>
.venv\Scripts\python.exe scripts/run_script_video.py submit --run-dir data/video_generation/<Mini测试批次> --shot S01
.venv\Scripts\python.exe scripts/run_script_video.py query --run-dir data/video_generation/<Mini测试批次> --shot S01
```

`--test-shot S01` 将本批付费提交范围限制为首镜，不能直接扩展至其他镜头。创建请求前保存回执，结果不明时禁止重提；查询只使用已保存任务 ID。API 不返回即梦积分消耗，账单不能套用 BytePlus 美元单价；页面显示接口返回的 tokens 和真实任务状态。没有接口时间的旧报告显示“未记录”，不使用文件修改时间补齐。

制作入口现已接入方舟原始视频参考：`submit --reference-video <本批已审原片>` 核对文件哈希，再用当前 API Key 查询来源任务，取得原始 URL。只接受当前锁定型号成功生成且在官方 30 天有效期内的原始产物；预览使用保存的回执，不联网。不能直接把旧 CLI 视频或跨平台重绘人像作为方舟原始参考。用户明确认可某个镜头时，可保存带原片哈希、原话和记录时间的 `USER_ACCEPTANCE.json`，与参考审核记录绑定；保留原技术观察，不伪造四项检查全部通过。

若任务已创建后明确失败于 `SetLimitExceeded`，确认用户明确要求重试后，可用 `retry-ark-configuration --authorization <实际用户指令>` 恢复一次。恢复前重新查询服务器确认失败类型，保留旧任务回执，最多恢复一次。不要把“用户要求再试”记成“用户已修改额度”；不自动关闭体验额度，不把未返回用量当作零费用。

更多型号及文生视频、参考、首尾帧、编辑、延长的统一调用方式见 [Seedance 指南索引](reference/seedance/README.md)。

## 首帧与尾帧

Ark 成功下载的视频会保存原始尾帧 `S01.last_frame.png` 及哈希。只读补取已有尾帧：

```powershell
.venv\Scripts\python.exe scripts/run_script_video.py save-last-frame --run-dir data/video_generation/<批次> --shot S01
```

为目标镜头准备对应机位的首帧，将图片放入本批目录，保存实际审核记录：

```json
{
  "shot_id": "S02",
  "camera_id": "south_close",
  "checks": {"composition": true, "identity": true, "opening_state": true},
  "notes": "填写实际检查结论，确认构图、人物和开场动作状态。",
  "evidence": ["S02.opening.png"]
}
```

审核值必须来自实际看片/看图，不复制示例结论。以下命令只绑定和预览：

```powershell
.venv\Scripts\python.exe scripts/run_script_video.py bind-first-frame --run-dir data/video_generation/<批次> --shot S02 --first-frame data/video_generation/<批次>/S02.opening.png --review-file data/video_generation/<批次>/S02.frame_review.json
.venv\Scripts\python.exe scripts/run_script_video.py preview --run-dir data/video_generation/<批次> --shot S02 --first-frame data/video_generation/<批次>/S02.opening.png
```

确认在已有生成授权范围内时，将 `preview` 改成 `submit` 才会创建任务。`--test-shot S01` 批次依然禁止提交 S02；添加首帧不会扩大授权范围。预览不覆盖原付费回执。首帧使用 `image_url`、`role=first_frame`、`ratio=adaptive`；登记的原始方舟尾帧使用当前账号查询到的原始 URL，其他符合服务要求的图片可用 Base64。

连续机位可以绑定上一镜的原始尾帧。换机位可用原始视频参考，或准备符合服务肖像规则的新构图首帧；程序禁止将已登记的双人中景原始尾帧直接绑定到单人特写。首帧和普通参考视频不能在此模式混用。含人脸素材应遵循 [官方肖像参考方案](https://docs.volcengine.com/docs/82379/2608626#trust-model-output)，不将跨平台重绘图片当作方舟原始产物。

首帧模式将图片中的实际姿态作为第一动作的准备状态，编译时替换文字计划的首帧姿态，保留原动作顺序和对白，避免两种开场状态冲突。

首帧模式的座位、构图和机位也以实际审核过的图片为准，编译器不再重复文生视频的抽象南北座位和另一个构图要求，避免让模型重新摆位。首段可以引用用户已认可的同账号原始产物；复制至本批 `original_sources` 时保留原任务回执、来源哈希和用户认可记录，提交时仍由当前账号查询取得原始 URL。第二段以后必须使用本轮紧邻已通过片段的尾帧，不能再次拿旧首镜或失败片段替代。

上游剧本定点修改后，导演入口可用 `--baseline-plan <上一版真实计划> --feedback-file <具体差异>` 只修不匹配的动作与状态，分别记录旧计划哈希、旧剧本哈希和新剧本哈希。`--draft` 仍只接受同一剧本的计划，不能修改旧哈希伪装成同稿续审。导演输入用每镜 `duration_seconds`，所有动作和开口时间从该镜0秒开始，防止将成片全局时间写入单段。

本次用户已明确选择“由我播放原片确认声音”。助手继续本地画面及转写检查，声线与声音和口型的匹配保持待审核，收到绑定原片的用户确认后再补全审核。没有音频外传授权，不调用外部音频理解服务。

## 完整片字幕校正

用户于2026-09-08明确指出黑底字幕条与此前样式不一致。后续沿用白字、细描边、无底条样式，不再默认加整条黑底。当前固定机位单镜可运行 `scripts/render_script_video_captions.py --run-dir <批次> --shot S06 --preview-audit <本批S06.speed_1p08.json> --clean-plate <已实际检查的无字幕原始帧.png> --authorization <用户要求>`。保留变速原片与旧版，输出独立的 `.overlay.mp4`；字幕从锁定剧本按短句生成，原片 ASR 时间按倍率换算，音轨直接复制并校验哈希。旧字区域使用同一视频无字帧的桌面背景作羽化修补，修补区域内不保留原反射运动，不能描述成原像素全部不变。只适用于已检查的固定构图且人物和道具不进入修补区域的镜头，新构图必须重新检查。字幕正确不等于音频无漏字；派生版仍须看片和用户声音确认，审核不自动放行。获准交付的各镜叠字版直接参与合并，不再套用旧版全片黑底渲染。

逐镜 ASR 和画面检查后，`scripts/render_script_video_captions.py --run-dir <批次>` 从锁定剧本取字幕，按本地识别字符时间对齐；保留 `short_45s_candidate.mp4` 原始合并版，输出 `short_45s_review.mp4`。当前字幕区按本片实测位置设在画面下方四分之一，覆盖模型错误文字；新场景必须先检查该区域是否遮挡人物或道具。音频直接复制，不用字幕校正掩盖对白缺失或截断。`caption_render.json` 保存文字来源、时间、遮挡区域及输入输出哈希。
