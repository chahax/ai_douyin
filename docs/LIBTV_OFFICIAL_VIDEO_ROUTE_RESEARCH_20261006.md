# LibTV官方与视频参考方案核对（2026-10-06）

结论：优先研究LibTV官方Remote MCP接入，而不是认定只有方舟素材库一条路。上一条400只证明当前方舟接口拒绝了现有三张人物参考，不能扩展成所有视频工具都不能处理AI人物。LibTV是否接受这五张图仍须实际验证，本轮没有该验证结果。

## 核实到的官方入口

可核实的当前官方生产仓库是 [liblib-ai/marketplace](https://github.com/liblib-ai/marketplace)，官网[插件页](https://www.liblib.tv/plugin)直接给出该仓库。生产插件为 `libtv@libtv`，版本1.0.0，Remote MCP地址为 `https://mcp.liblib.tv/mcp`，使用LibTV OAuth身份。固定提交为 `4ac581c3cbdaa53d0d42df85c6bf62e45600bc5f`；配置和相关流程资料已按原字节保存。本次没有核实到名为LibTV-official的唯一仓库身份，不将同名第三方项目当成官方。

插件支持画布编排、上传自己的素材、选择模型及查看生成进度，属于另一个账户和服务入口。MCP公开配置没有披露完整生成Schema、人像审核内部处理或原始尾帧返回合同；这些不能凭展示文案推定。[官方插件定义](https://github.com/liblib-ai/marketplace/blob/main/plugins/libtv/.codex-plugin/plugin.json)、[MCP配置](https://github.com/liblib-ai/marketplace/blob/main/plugins/libtv/.mcp.json)。

通用插件目录搜索未返回LibTV，不能据此否定官网的自有marketplace。官方安装路径已核实，但本次仅研究，未执行安装或账户授权。

## 几条候选路线

| 路线 | 已核实的能力 | 与当前任务的差别及未决项 |
|---|---|---|
| LibTV官方MCP，直接参考生视频 | 平台支持参考素材和媒体生成，提供官方Codex接入 | 首选接入候选；需登录后查当前模型、五图输入模式、人像处理、原任务查询及服务原尾帧。当前五图是否可采用未知 |
| LibTV与Blender白模联动 | 官方有场景与人物图、三维环境/走位/机位、白模视频、最终视频的分工 | 对空间控制有参考价值；默认Seedance2.5，与当前2.0Mini不同。当前用户已结束合成首帧流程，不因此重启首帧或重制整套人设 |
| 方舟现有接口 | URL/Base64可直接传；自有AIGC资产及指定同账户原始产物有官方使用路径 | 当前直传已明确400，自有素材库创建曾403；既有图来源不会因改URL或再上传而自动成为可信Seedream文生图原产物 |
| ComfyUI/Wan VACE | 官方支持参考图生视频及视频/掩码控制 | 项目已有下载和实验记录；采用会换媒体模型。旧本地试验仅有技术文件证据，不构成双人表演、声音或本片质量通过 |
| Veo参考生视频 | 官方提供主体参考图输入，最多3张 | 无法原样消费当前五张独立参考；需要不同模型、账户及参考合同，因此不作为当前首选 |

Blender联动依据[官方流程](https://github.com/liblib-ai/marketplace/blob/main/plugins/libtv/skills/libtv-blender-live-action/SKILL.md)；VACE依据[作者仓库](https://github.com/ali-vilab/VACE)；Veo依据[当前官方参考输入文档](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/video/generate-videos-from-references)。这里的能力声明不等于我们已经完成对应生产测试。

较早的 [libtv-labs/libtv-skills](https://github.com/libtv-labs/libtv-skills) 是会话式Agent入口：上传文件、发送自然语言任务、查会话结果。它与当前Remote MCP不等价，公开请求示例没有给出本项目所需的逐镜严格模型/次数合同。第三方libtv-video-agent、libtv-skill-pro及libtV-studio可作经验或源码参考，不能用其宣传或历史成功记录保证当前账户、模型与这五张图通过。LibTV平台可能使用不同的接入权益或素材处理，这是待核实的解释，不是已验证服务端原因。

## 建议的最小下一步

先接入官方插件并只读核对能力，继续使用当前五张图及SH01全文，暂不让平台Agent重写或批量生成整片。逐项确认：当前2.0Mini模型能否解析、五张图支持的模式和编号关系、人像素材流程、4秒/9:16/480p/声音设置、原任务查询、生成估价，以及服务原始尾帧是否可取。若只提供VIP/2.5或不支持原尾帧，应明确差异后另定采用范围。

[接入提案](../data/qa/libtv_official_video_routes_20261006/INTEGRATION_PROPOSAL.json)已绑定五图SHA、表演提示及真实400回执。该文件是设计提案，未授权上传、开通套餐、切换模型或再次生成。已用的首段提交1/1和同稿失败1/10不重置。视频未来成功保存后仍为awaiting_human_review，未经用户批准原始尾帧不续段；助手不抽帧、不听看、不ASR。

本轮实际产物：五份官方配置/流程原文快照、版本核对记录、接入提案及本文。新增媒体调用0、素材上传0、安装0、模型切换0。主线仍为现有完整剧本的可制作交付，人设、剧情和表演窗口保持原绑定。

## 用户明确素材适配优先级（2026-10-06）

用户原话：“图片生成的可以没必要换模型主要视频生成无法放素材进去就不对”。后续保留现有图片生成模型、已选人物与空间以及五张独立参考，优先适配能够接收这些素材的视频入口。不能以现有代码接入方便为由要求重做角色图，也不将自有素材库权益作为唯一推进路线。

可灵3.0 Omni作为直接参考候选：官方列出最多7张图片/元素及Base64/URL传入，当前五图字节、尺寸、大小及原SH01表演提示已核对；[离线候选预览](../data/qa/video_existing_reference_adaptation_20261006/KLING_FIVE_REFERENCE_PREVIEW.json)只机械转换图片引用标记，保留原4秒动作和道具起态。候选std模式为720P，与原480p不同，尚未采用。该预览含不可提交的本地引用占位符，未上传素材或调用模型。

五图实际接受、当前账户入口和服务原始尾帧输出仍未知。可灵文档支持首/尾帧输入不等于服务输出原始尾帧。保留人工审核与批准原尾帧续段规则，不自行抽帧补尾帧、不以整段视频续写静默替代。原400回执、1/1已用提交与同稿1/10失败记录保留；本次新增模型调用0，配置切换0。
