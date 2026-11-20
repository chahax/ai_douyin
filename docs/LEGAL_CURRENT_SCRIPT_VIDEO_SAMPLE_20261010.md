# 当前362版剧本：导演、实际表演与首段视频

用户最新请求：“生成视频看看”。范围为当前完整新稿的一段首样，视频由用户人工审查；后续沿用默认的批准原始尾帧再续段规则。旧316批次例外不移用，旧媒体账本、逻辑故事身份与失败历史承接，无自动重试、无发布。

正文：[完整当前稿362](../data/production_revisions/legal_dialogue_refinement_20261009/round_20/DELIVERABLE/FULL_SCRIPT.md)。原文保持不动，完整正文经DeepSeek364复审；不代表视频质量通过。

已建整片导演：[直接阅读](../data/production_revisions/legal_current_production_20261010/round_04/WHOLE_DIRECTION_READABLE.md)。公司当面让小林离开；读到个人原因后从不信转为委屈急切；先拒绝公司要求，再拒绝帮周姐交差；周姐收未签纸笔独自离开，小林留坐，争议未解决。当前仅准备开场样片，后三拍实际表演仍未建。

| 原回执 | 实际情况 | 处理与证据范围 |
| --- | --- | --- |
| 365 | 有完整导演返回；B1两句分配到B2，开场背侧脸及末镜暗藏切镜 | 原合同拒绝，原文和消耗保留；整片导演完整返修，机械逐源归属改为按拍确定性编译 |
| 366 | 完整导演修复跨拍与开场脸部观察，实际共11反应窗；B4有4窗 | 任意每拍上限3造成假阻断，改为每拍6/整片12；原创意文本与11窗口完整保留，旧拒绝记录不改，无重复导演调用；另有来源资格记录 |
| 367 | 完整第一拍返回；催签句2.5秒低于本句至少3秒；开场before0不满足导演1秒 | 完整表演返修，不手补时间、不拼稿；还要求去掉无叙事工牌晃动、过多手部准备、话后反应重复 |
| 368 | HTTP200，完整服务body，finish_reason=tool_calls，却无工具字段；正文只有两步不完整JSON；用量已知17535 | REQUIRED_TOOL_MISSING接口故障，禁止正文兼容兜底；属于已知错误响应，服务端具体成因未知，不能解释为结果未返回或长分析耗尽 |
| 369 | HTTP200有工具结果，但payload_json内实际为五个独立对象的JSONL，不是一个完整对象；用量11331已知 | JSON_DOCUMENT_INNER_INVALID_JSON，禁止拼接/正文兜底，原响应保留 |
| 370 | 新合同要求MiniMax只写15个表演cue字符串；本地按4.7发音字/秒与导演反应下限排时；8797 tokens | 五源完整通过离线/接口编译，但cue引用原台词片段、起态细节多，完整返修不手改 |
| 371 | DeepSeek全文/导演/第一拍审查返回；36991 tokens；30个来源引用超过合同任意6上限，原审查含3条issues | 原文保留。S05 3.2秒实际满足15/4.7；0秒前窗不执行，局部手位不需要粗状态预定义。这些不是已验证服务/物理故障；实际需要消除台词引文与无叙事细节 |
| 372 | 完整返修返回仍引用台词片段；9739 tokens | 本地验收拒绝；完整原稿保留，未手动删引文；下一请求移除旧失败演法正文 |
| 373 | 清理后的上下文返回完整15串表演；9586 tokens | 不含对白引文，五步完整编译20.2秒；前三源13.8秒投影14秒 |
| 374 | DeepSeek完整正文、整片方向与B1全文复审；24621 tokens | 原两项issues均要求B2–B4未建；原assessment明确B1与整片方向零问题，首样范围资格单独记录，原needs_revision=true及两待办不回改 |

首段技术配置沿用Ark Seedance Mini（doubao-seedance-2-0-mini-260615），480p、9:16、原生普通话音轨、无字幕，return_last_frame=true。使用原用户批准的SH01服务原图作为reference_image重建新起态，不作为不兼容旧起态first_frame。旧工牌在桌上/纸面朝下不能沿用；新起态已戴工牌，纸笔在周姐手边，之后只一次推到小林近桌沿一掌宽处。

保存验收只读服务结果、文件大小/哈希与ffprobe元数据：视频/音轨、时长、编码对齐尺寸。缺尾帧时若完整视频已保存仍可交付人审，明确不能续段；下载或技术验收失败记录artifact_save_pending及阶段，始终查询原task_id。重复提交与换目录预算绕过已通过离线模拟验证。

离线：跨拍/时序/来源合同17项，媒体保护12项通过。离线通过和接口成功均不算创作质量通过。本版14秒首段已保存并待人工审核；实际情绪、语速、说话人和声音口型仍待用户看样片。助手不抽帧、听看、ASR或调用音画审核。

表演与编译的新分工：模型写完整当前拍的表情、语气、刺激与反应；本地声明动作时长、按原对白发音字数排活跃时间，保留导演前/中/后反应窗口，机械状态也由源动作推导。没有回填367/370的数字，没有拼接369的JSONL。首次规划覆盖B1.S01–S03共13.8秒，拟生成14秒，包含初态、公司通知和一次推纸；S04追问与S05催签属于随后段。所有时长是规划，实际视频待人工审核。

## 实际首段制作交接与派发

当前交接：[完整导演与B1排时](../data/production_revisions/legal_current_production_20261010/round_10/DELIVERABLE_opening/DIRECTOR_AND_B1.md)；[实际提示词](../data/production_revisions/legal_current_production_20261010/round_10/DELIVERABLE_opening/ACTUAL_OPENING_PROMPT.md)；[首样范围资格](../data/production_revisions/legal_current_production_20261010/round_10/OPENING_SCOPE_QUALIFICATION.json)。原审查374完全保留，其B2–B4待办及两处自由文本笔误另见ORIGINAL_REVIEW_FACTUAL_NOTES.json；首样无待修项不等于整片完成。

本次新增10次文本调用（365–374），163361 reported tokens；历史累计374次、6315744 reported tokens，未知93117预留及70/160记录不变。视频新增1次，task_id=cgt-20261010140842-lzc58，现已succeeded并完整保存；内容状态awaiting_human_review，无再次提交。原人物/会议室参考图真实进入请求，身份/环境用reference_image，按新稿起态重构。最终音画待用户人工审核。

## 首段实际保存结果

[播放视频](../data/video_generation/legal_current_362_20261010/opening_v1/CURRENT362_OPEN01.mp4) · [实际提示词](../data/video_generation/legal_current_362_20261010/opening_v1/PROMPT.txt) · [技术回执](../data/video_generation/legal_current_362_20261010/opening_v1/receipt.json)。本段时长14.08秒，编码尺寸[496, 864]，原生音轨存在，文件3006787字节；模式480p、9:16。服务原始尾帧完整保存但未批准。这里只证明文件技术完整，情绪、动作、语言、字幕与说话人待用户审核。当前样片任务已完成保存，整片制作未完成，不自动派发下一段。
