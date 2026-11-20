# S7角色/场景设定图板返修记录（2026-10-06）

用户否决首轮人物单幅肖像，并指出办公室与门外走廊不是同一空间。原六张图均来自Seedream 5.0 pro（doubao-seedream-5-0-pro-260628），没有使用不同背景模型。六张原图、请求、响应、用量和用户失败回执完整保留，不进入正式资产库。

## 已确认的问题与修改

| 分类 | 证据与判断 | 本轮修改 |
| --- | --- | --- |
| 生成合同 | 首轮人物提示词明确要求单幅照片、不做拼图或三视图；与本次用户要求的角色设定用途不匹配。 | 改为每名角色一张A/B两行候选图板，每行正面、完整侧面、背面，统一全身比例、发型和服装。 |
| 空间设计 | 办公室和走廊独立生成，没有同一布局或实际图片参考关联；用户明确反馈两处不是同一区域。 | 在同张图板一次生成平面关系和五个机位；以旧办公室失败图作为材质/门窗修复输入，按静态合同统一两桌两椅、窗、门和柜位置。 |
| 接口输入 | 角色A/B身份尚未选定。已有参考若只写文件名或提示词，不能证明图片已进入请求。 | 两张人物图板请求各带两张真实参考，场景带一张参考；实际request.image的base64解码SHA与原图一致。服务已成功返回的方澄/场景回执分别报告input_images=2/1。 |
| 状态契约 | 失败样板不能当已通过资产复用，也不能把技术文件保存当内容通过。 | 实际失败原话、文件SHA与人工回执绑定；参考仅允许repair_failed_visual_asset。身份、空间与正式首帧审核仍未批准。 |
| 接口异常 | 林屿POST等待响应时ReadTimeout，未收到HTTP响应或服务任务ID。 | 原请求状态submit_outcome_unknown，结果与计费未知，未重发。隔离后仅完成原定第三项、此前0次调用的独立场景请求；调用上限仍为3。 |

“同张图板内多角度”是本次采用的生成策略，不能强制保证几何或身份完全一致。是否达到人物设定图、同一空间多角度图的要求仍由用户实际审核；不能由接口成功推断通过。

## 产物与实际验证

[直接查看已保存的两张原始图板](../data/video_generation/this_time_i_leave_s7_setting_boards_repair_20261006/REPAIR_REVIEW.md)。方澄已保存A/B正侧背候选图板，场景已保存平面与五视角图板；林屿尚无可交付返修原图。本轮是部分完成，不是整批设定图通过。

两张2560×1440原始JPEG已完整解码，文件SHA、请求SHA、响应SHA与回执一致。12项离线来源/有限范围/失败参考/未知结果不重派检查通过；共享媒体账本核对原六条和本轮三条，每个来源只有一条。原S7剧本、静态定义、全文审查265、制作交接、源代码冻结绑定均未改变。

新图片请求3次，保存2张；累计S7图片请求9次，已保存8张。图片reported tokens：原六次86400，本轮已知28800，累计已知115200；林屿用量未知，不能记为0或宣称得到完整总数。文本仍为265次/4559929 reported tokens，旧93117未知预留完整保留；本轮未新增MiniMax、DeepSeek、视频、音频或发布调用。

[技术核验](../data/video_generation/this_time_i_leave_s7_setting_boards_repair_20261006/TECHNICAL_COMPLETION.json) · [最终执行状态](../data/video_generation/this_time_i_leave_s7_setting_boards_repair_20261006/EXECUTION_STATUS_FINAL.json) · [实际用户原话](../data/video_generation/this_time_i_leave_s7_setting_boards_repair_20261006/USER_FEEDBACK_ORIGINAL.md) · [人工审核待填写](../data/video_generation/this_time_i_leave_s7_setting_boards_repair_20261006/HUMAN_REVIEW_PENDING.json)。

## 执行代码与后续边界

既有scripts/generate_ark_asset_pack.py未修改。独立返修入口.codex_staging/s7_setting_boards_v2.py绑定原S7与本次3张有限范围；独立多参考执行器.codex_staging/generate_ark_asset_pack_s7_refs_v2.py扩展真实参考数组，严格要求当前失败人工回执与SHA。场景故障隔离入口.codex_staging/s7_setting_boards_v2_isolated_space.py只选择尚未派发的SPACE_BOARD，核验林屿未知原回执不变；不绕过未知结果重派门。

[代码快照与哈希](../data/video_generation/this_time_i_leave_s7_setting_boards_repair_20261006/SOURCE_SNAPSHOTS.json)已本地保存，未声明此次图片及新代码已经上传Git。旧六张、旧账本与旧源记录保留，未迁移任务或重置调用预算。

用户选定人物与场景后再列正式镜头首帧的用途和数量，并与分镜一起人工审核。图板中门打开仅用于空间展示，不自动定义剧情门起态或增加推/关门动作；不自动扩展资产、修订表演或启动视频。S7门开合适配、短于本地4秒下限镜头的组合、正式首帧和真实声音仍待验证。

图像选定不等于完整文本质量确认，也不等于视频授权；视频成功保存只记awaiting_human_review，助手不抽帧、听看、ASR或调用音画审核模型。用户明确通过后才用服务原始尾帧续段。

官方接口来源：[火山方舟图片生成API](https://docs.volcengine.com/docs/ark/image-generation-api?lang=en)。实际输入参考数组、模型、参数和用量以本轮原请求与回执为准。


## 用户再次否决场景：进入固定三维布局工具调研

场景图板尚未通过，用户要求查找更具物理约束的Skill/MCP/工具，并增加角色面部细节。二次失败原话与SHA另存user_reviews/SPACE_BOARD_20261006_followup.json；不改原技术保存回执。最新[研究与候选路线](SCENE_GEOMETRY_AND_FACE_WORKFLOW_RESEARCH_20261006.md)优先固定三维布局、多机位渲染再接生成器。本轮没有新调用或安装；角色A/B未明确选定，林屿原请求仍结果未知。
