# 小说首段视频试片

2026-10-18，用户先要求“试试视频生成分段”，随后明确“先生成一段我先审核”。本轮仅《渡口的单程票》首个视频服务片段一次提交，保存后停止等待用户；不适用其他故事的整批生成例外，不自动重试、续段或发布。

来源：`data/novel_agent_production/20261018_original_trial_v7/run` 的完整机器合格剧本、导演及全文审核。旧文本5次/88362 tokens及全部冻结不改。本轮独立媒体账本记录来源、编译配方、真实提示词、原生请求/响应、任务ID、用量（服务有返回时）、文件SHA和失败；新故事初次视频从0登记，不能换目录重领本次一次提交。

实际环境：项目Ark凭据已配置，模型doubao-seedance-2-0-mini-260615，本地注册与官方文档均支持4–15秒、720p、有声视频和服务尾帧；本地H3未启动，Comfy CLI不在PATH。本次沿项目现有SeedanceClient及ProviderCallLedger，不安装或启动其他模型、不变更旧任务。

原导演S1预计28秒，本轮首片标记S1-A、15秒，只表演第一项周禾抢先说明决定的完整对白及其动作/反应；周明保持坐姿倾听，原第二项放笔和回应留待S1-B。不得把28秒剧情强塞入15秒，不提前广播、船票、后续对白或离场。世界框架、两人身份、起态与所选表演从冻结导演机械绑定；竖屏9:16、720p、普通话原生对白、写实生活短剧、无字幕，首片固定同框建立空间。

已先查自有资产目录：缺少适配五旬父亲和渡口候船室，不把其他故事人物/办公室当成本片已选素材。首次text-only建立本片形象；本轮没有固定人像/声线获批，不对连续性或口型作通过声明。后续只有用户批准当前原片后，才能使用服务直接返回的原始尾图。

prepare只冻结，submit前永久登记唯一claim及实际请求，仅POST一次；提交未知只保留原证据，已知ID仅查询原ID。query成功后下载服务原片和原始尾图，只用ffprobe/文件大小/SHA/流包核对技术完整性，不抽帧、播放听看、ASR或音画审核。结果标为awaiting_human_review，助手不代替用户判断内容。

子agent实施独立适配器与少量故障测试，主agent核对实际提示词/参数/来源及唯一提交门后生产。新增适配器不修改旧小说v7或旧媒体冻结入口。

能力来源：[官方模型列表](https://docs.volcengine.com/docs/ark/model-list?lang=zh&redirect=1)、[官方Seedance系列说明](https://docs.volcengine.com/docs/ark/seedance-2-0?lang=en)。本地注册见`config/seedance_models.json`。

## 实际结果

独立适配器与CLI已实现，14项核心测试通过；主agent核实际27字符原句、首段动作/起态、15秒720p9:16、仅一次提交及未来人工审核回执兼容。旧文本根21个文件SHA均未变，文本仍5次/88362tokens。

实际只提交一次，任务`cgt-20261018024437-nlsvb`。服务先返回running，后明确failed，错误`OutputVideoSensitiveContentDetected.PolicyViolation`，原文为“The request failed because the output video may be related to copyright restrictions.”平台未指出具体作品或片段；这不是输入小说侵权的证据。本次未返回视频或尾图，不能交付待审片或声称视频生成成功。失败回执没有usage，实际收费未知。

所有原生请求、提交响应及3次原ID查询已保存在`data/video_generation/novel_ferry_first_trial_20261018/S1A`，新故事失败1/10、累计视频提交1。没有自动重试/续段或发布。汇总见父目录RESULT.json；同一来源/提示词的新增一次候选提案保存为RETRY_PROPOSAL.json，仍awaiting_explicit_user_authorization，未派发。
