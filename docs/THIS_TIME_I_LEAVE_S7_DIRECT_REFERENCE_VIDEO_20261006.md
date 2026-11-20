# S7 人物与场景直接参考视频路线


本次按用户首帧反馈调研并离线准备，未生成图片、视频，也未上传素材。SH01第二轮首帧已记录为用户拒绝；原生成回执和已确认的人设、办公室、走廊批准记录保留。

## 已核实的两种工作流

| 工作流 | 官方依据 | 本片取舍 |
|---|---|---|
| 人物与场景分别作为参考，直接生成视频 | [Seedance 创建任务 API](https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh)：参考图使用 reference_image，参考模式与首帧模式互斥 | 优先准备第一个独立段的此种请求 |
| 人物分支与场景分支先生成合成图，再进入视频 | [Runway Gen-4 Image References](https://help.runwayml.com/hc/en-us/articles/40042718905875-Creating-with-Gen-4-Image-References) | 属于可选构图控制方法；不作为本片每镜必经步骤，也不把此文说成 Runway 视频直接吃多图的证明 |

项目现有底层 SeedanceClient 支持多图；creative_seedance_segments.py 当前制作适配器却固定构造单张 first_frame。这是本地流程的限制，不是官方视频接口必须先合成首帧。离线预览不修改该适配器，也未迁移冻结任务。

## 人设图与实际视频输入分开

依据 [Seedance 2.0 提示词指南](https://docs.volcengine.com/docs/ark/seedance-2-0-prompt-guide?lang=zh)，整张人物多视图容易造成重复人物和脸部参考混淆。三视图仍用于人工确认身份与服装；推荐视频输入为每人独立正面脸部图、全身服装图，加当前场景，共5张。每张标明用途，镜头只携带本段需要的场景；SH01不带走廊。

少量复用方案已列为3张候选：方澄、林屿的已有Seedream独立原图＋确认的办公室图。两张旧原图确实是当前已确认人设图的生成参考源，字节与原回执相符；这不等于用户单独批准旧原图直接作为本次视频身份输入。候选清单保留该未确认项。

## 写实人像的接口来源条件

[官方肖像指南](https://docs.volcengine.com/docs/ark/seedance-portrait-asset-guide?lang=zh)限定受信模型原始产物为同账号、30天内及原始字节；跨平台图和裁剪图不能继承这项信任。旧人物原图的模型与生成方式符合文档列出的候选来源，但当前账号关联、URL可用性尚未核验，不记为服务已接受。

如要使用已确认的新设定图身份及细节，可走[私域虚拟人像库](https://docs.volcengine.com/docs/ark/private-virtual-avatar-library-guide-preview?lang=zh)：自有AIGC素材按角色入库，状态Active后传asset://ID。该路径需要AK/SK、IAM和同项目配置；当前项目尚无此上传接线，本次也未检查账号权益或创建素材。人设图需先准备独立面部和全身素材，不直接把整张多视图当成5个主体输入。

## 本片第一个段的请求方案

输入角色身份与服装、办公室参考和SH01现有表演。仍从方澄站立、林屿坐着、包在椅背、票与便利贴在方澄桌角的起态开始。先静止，再由林屿把自己的明细单推向自己桌沿靠方澄的一侧；不提前把单据放进她桌上，无对白。该动作来自冻结表演全文，不手工新增剧情。

候选请求使用4秒，因为当前接口不接受原SH01的2.9秒。采用另行保存的等比例时间扩展候选，原表演文字、动作顺序、道具起止态不变；全片62.26秒原稿不改，68秒仅为未采用的媒体排时方案。实际模型能否做到、节奏是否合适仍需试片和用户审核，参考图不会提供物理锁定保证。

续段保留原批准规则：用户明确通过后，使用生成服务返回的原始尾帧作下一段首帧。不能同时附加reference_image，也不能把原尾帧降为普通参考后声称满足首帧规则。本次仅设计第一独立段的参考模式，不自行批准整片改为独立多图段。

## 本次实际产物与验证边界

- 原图来源与SHA核对完成；已保存候选参考清单、SH01提示词和带占位URL的请求结构。
- 使用现有请求构造器、禁止网络的HTTP传输验证：3图与5素材槽结构接受；混用首帧、超图数、3秒段长、本地路径均被本地拒绝。
- 原冻结编译和首帧生成回执SHA未改变；新模型、素材上传和视频请求均为0。
- 这只证明请求形状和本地分流；未得到服务回执、正式视频、声画通过或创作质量通过。
- 原未知林屿请求、旧文本未知用量及账本保留。研究阶段没有重派、自动重试或预算重置。

阅读入口：[候选参考清单](../data/qa/s7_direct_reference_video_workflow_20261006/REFERENCE_INPUT_MANIFEST_CANDIDATE.json)、[首段提示词](../data/qa/s7_direct_reference_video_workflow_20261006/SH01_DIRECT_REFERENCE_PROMPT_CANDIDATE.txt)、[离线验证](../data/qa/s7_direct_reference_video_workflow_20261006/OFFLINE_PREFLIGHT.json)、[请求结构（占位，不可提交）](../data/qa/s7_direct_reference_video_workflow_20261006/SH01_REQUEST_SHAPE_PLACEHOLDERS_NOT_FOR_SUBMISSION.json)。


实际候选与验证位于 data/qa/s7_direct_reference_video_workflow_20261006，本文为本次路线设计；无生产治理注册或付费派发。


## 最新用户执行指令：结束合成首帧，采用五图参考

用户已明确采用五图直接生成首段。四张独立人物参考已实际保存，办公室复用，共5张。素材库创建接口真实返回403 SubscriptionRequired，未创建组或上传素材，视频0；等待免费Entry开通后续行。原首帧审核门仅在首段参考模式中取消，原尾帧续段人工批准门保留。详见[五图与实际首段执行记录](THIS_TIME_I_LEAVE_S7_FIVE_REFERENCES_PRODUCTION_20261006.md)。此前“仅研究、尚未授权视频”的状态属于旧时点，本次用户新指令已经授权唯一当前首段；原回执不改写。
