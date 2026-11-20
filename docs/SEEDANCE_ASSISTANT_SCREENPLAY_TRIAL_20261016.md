# 本次亲自修订稿的Seedance单段对照

用户明确要求：“这个剧本用seedances生成个视频看看”。沿用主助手亲自编写的完整180秒剧本及S01，不调用其他文本模型修稿或审稿。范围是一个约15秒开场试片，不是批量续段，也不以此宣布全稿人工采用。

源：`data/video_generation/h3_project_script_20261015/revision_02/assistant_authored/FULL_SCREENPLAY.md`及同目录`FIRST_SEGMENT.json`。新独立运行目录`data/video_generation/seedance_assistant_screenplay_20261016`，旧H3和旧Seedance冻结、账本与失败记录保留。

目标：沿用当前配置的方舟Seedance 2.0 Mini，`doubao-seedance-2-0-mini-260615`，15秒、720p、16:9、原生音频、返回服务原始尾帧。图片顺序为空间/C01桂芳/C02经理，均为reference_image，不混入正式首帧。H3尾帧未获用户通过，不作输入。首段明确桂芳已在屋内工作，经理跨门立即说话；台词、动作、视线与回应全部取本次S01。

先核对本地客户端、当前官网及实际素材来源。原人物图必须核实是同账号近30天Seedream受信模型原始产物；静态无人背景沿用户选定素材。元数据、文件身份及来源资格与用户对新视频的内容批准分开。

实施由子agent补齐最小独立prepare/submit/query入口，主agent核对实际源/参考顺序/实际请求与失败分支后才提交。预览不计调用；唯一不可覆盖claim在POST之前持久保存，明确结果/原ID全保留，未知不重派，无自动重试、换模、降档或续段。通过既有SeedanceClient记录真实媒体服务调用，不改文本token账本。旧同故事失败1/10不重置，追加新媒体真实提交/失败事件。

下载保存全在D盘。成功后仅核对接口、非空原文件/SHA及容器/包元数据，尾帧只核对PNG编码完整性，不看图、不抽帧、不听音、不ASR。每个输出仍`awaiting_human_review`。交付实际视频预览/链接和绝对路径，等待用户审核。

官方核对（2026-10-16）：创建任务API https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh&redirect=1 ，原生人像产物规则 https://docs.volcengine.com/docs/ark/seedance-portrait-asset-guide?lang=zh 。官网列明Mini支持720p；16:9对应1280×720；近30天同账号Seedream5.0文生图原始人像产物受信，不能把本地完整性误写成接口受理。

## 本次参考选择的实际核对

H3所用的C01/C02多视图board是Codex内置图像工具产物，没有Ark原生资格，不能作为受信Seedream图提交。已从两份board原回执的identity父引用找到同角色上游原始照片：`S7_SAMPLE_C01_A/original.jpeg`与`S7_SAMPLE_C02_A/original.jpeg`，均为2026-10-06 Seedream5pro260628文生图，input_images=0，本地原字节与回执SHA相符。主助手只查看这两张静态素材并选择为本次角色参考；未打开新旧生成视频或其首尾帧。

两张父图旧审核是wrong_asset_format，原用户要求三视图，identity_selected=null；旧failed与旧形式修复范围保持。此次不把单人照片宣布为通过的三视图，不重开旧生产run；依据当前单段试片及既有人物素材自主选取授权，在新任务中另记助手委托选取，保留board→父图关系与原失败证据。实际人物外观是否符合当前片仍由用户看视频。

原同步Seedream回执没有账号指纹，不能声称已独立证明当前凭据与历史账号相同。新admission明确same_account=null、service_input_acceptance=pending，只允许此一次有原生来源依据的候选素材服务验证；服务受理/拒绝单独留回执，不把本地核对写成接口通过。当前凭据只读GET/models为HTTP200，不代表媒体权限或素材已验收。

## 实际生成与交付

唯一任务`cgt-20261016093324-czthg`已成功，三份实际参考输入被本次服务接受，具体证据见新运行目录`SERVICE_INPUT_ACCEPTANCE.json`；这不回写原候选记录、不证明未来素材资格或人物画面符合预期。

视频`S01.original.mp4`，1280×720、H.264视频＋AAC音轨，容器15.104秒，7466770字节，SHA256 `9ef1fae17e87ae524c5a2e1e6ecbf4c2c582977e86be58d4936d4916778e7af3`。只核容器/包和文件SHA，未听看、抽帧或ASR。服务原尾帧实际是JPEG，旧本地PNG假定导致一次收尾失败；现已以JPEG编码marker/SOF/SOS/EOI核对收尾，保留误扩展原文件和相同SHA，无转码、无像素解码、无新媒体调用。只有这一个任务，未自动续段。

本次结果及视频内容状态为`awaiting_human_review`。4项原门检查和1项原JPEG／截断拒绝检查通过；旧同故事失败1/10与原账本保持，单独媒体事件记录本次真实提交与保存。两份人物原图已以稳定ID和original版本新增自有检索库，33→35项，旧wrong_asset_format失败未改。
