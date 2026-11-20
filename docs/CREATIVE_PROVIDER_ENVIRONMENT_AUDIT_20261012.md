# 模型能力、现有环境与视频制作入口核对

核对日期：2026-10-12。范围是本地代码/文档、官网与开源源码阅读，以及一次当前配置的 DeepSeek `GET /models`。生成调用0、媒体调用0、安装0、模型切换0。没有查看视频、抽帧、听音、ASR或替用户判定画面通过。

## 结论与已验证原因

相关能力不是查不到：Seedance同账号原视频/原尾帧复用说明已经在2026-09-08归档，通用客户端和旧制作入口也已有实现。近期新制作链没有把这些能力完整接入，旧只读能力审计主要测试文字/首帧与时长；因此文档中的能力仍需要用户提醒才被重新考虑。这是已核实的流程缺口。

人物错配、性别变化和脸部异常是用户反馈的实际内容问题。已核实旧请求缺少完整人物形象及素材主体映射，不能证明服务内部改变人物的唯一原因。官方参考能力和程序输入检查可减少漏传、错传、模式混用，却不保证每次生成视觉一致；内容继续由用户审查。

当前正文仍为512《桌面那张纸》，公司要求小林离开却递个人原因申请；小林两次拒签，周姐收纸笔独自离开，小林留坐，争议未结束。此次没有改剧情、台词或表演。

## 需要分开的五层证据

| 层次 | 回答的问题 | 本次证据 |
| --- | --- | --- |
| 官方能力 | 精确型号、协议和模式支持哪些输入/限制 | 带核对日期和直接官网链接的[能力登记](../config/creative_provider_capabilities_20261012.json) |
| 通用客户端 | 本地能否正确构造这些字段 | `seedance_client.py`、`seedance_models.py` |
| 选定制作入口 | 当前入口是否真的把素材送进去 | 新v1媒体只允许纯文字首段；v3多模态只有预览；v4仅文本 |
| 实际接口验收 | 当前账户、原素材、实际请求是否被服务接受 | 本次只查询DeepSeek目录；新共用多模态视频尚未验收 |
| 人工内容批准 | 生成后的人物、动作、声音是否符合预期 | 本次无新视频，无新内容批准 |

“客户端支持”“有技能/节点”“请求预览通过”不能填写成后两层通过。官网示例不是当前账户回执。

## Seedance：保持Mini，补齐素材与模式适配

当前首选仍为方舟 `doubao-seedance-2-0-mini-260615`、480p、9:16、原生音频。官网列出Mini可接图片、视频及配合图/视频的音频参考；单段4–15秒。无需为使用参考素材先换视频模型。[型号能力](https://docs.volcengine.com/docs/ark/seedance-2-5?lang=zh)

| 能力 | 正确解释 | 当前缺口 |
| --- | --- | --- |
| 同账号原产物复用 | 受信范围包括合格的原生人像视频和服务对应尾帧，须同方舟账号、原始产物且在30天内 | 旧入口有原任务查询；新首帧纯合同仍未接当前凭据下的GET验证 |
| `return_last_frame` | 服务返回原尾帧供连续生成，视频/尾帧下载URL有效期24小时 | 文件、task ID、来源哈希和用户批准需共同保留；URL到期不等于30天素材资格到期 |
| 正式首帧/首尾帧 | `first_frame`或`first_frame + last_frame`；与多模态参考互斥 | 不能在现在的正式首帧请求里直接塞人物图、参考视频和音频 |
| 多模态参考 | `reference_image/reference_video/reference_audio`，由提示词明确每个素材的用途 | 通用客户端已有；新共用生产提交未接通，冻结清单也未采用该模式 |
| 视频参考 | Mini最多3个、单个2–15秒、总时长不超过15秒；传URL或素材ID | 不可把整片、本地磁盘路径或重剪的人像片段当作合格原生参考直接传 |
| 声线参考 | 音频素材与具体角色关联；文字“普通话/同一声线”不是实际声音绑定 | 当前两人voice仍unbound；合同目前也没有完整音频资产输入 |

上述素材信任条件见[肖像产物指南](https://docs.volcengine.com/docs/ark/seedance-portrait-asset-guide?lang=zh)；角色与输入参数边界见[创建任务API](https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh&redirect=1)，返回URL见[查询任务API](https://docs.volcengine.com/docs/ark/get-video-generation-task-api?lang=zh)。素材“受信”是输入审核资格，不能写成人物一致性保证。

官方提示词指南还区分主体复用、编辑与延长，提示多次视频续写可累积画质劣化，尤其是人脸区域。应在导演阶段区分连续动作与换机位/重新入画，不能所有段都无条件续写；多模态中用提示词指定某张图作首帧，也不等于正式首帧参数的硬约束。[2.0提示词指南](https://docs.volcengine.com/docs/ark/seedance-2-0-prompt-guide?lang=zh&redirect=1)

### 本地接线位置

- [通用客户端](../src/content_factory/seedance_client.py:89)和[型号校验](../src/content_factory/seedance_models.py:22)：已有图片/视频/音频引用、模式互斥与数量限制。
- [旧制作入口](../scripts/run_script_video.py:351)：已有原产物哈希、当前账号原任务查询、30天判断、服务原视频/尾帧URL使用。复用其机制，不用它静默恢复旧任务。
- [新共用媒体入口](../scripts/run_creative_shared_full_production_v1.py:435)：首段纯文字建立新选角，拒绝额外references；[verified v2](../scripts/run_creative_shared_verified_media_v2.py:237)仍沿此入口。
- [新纯媒体合同](../src/content_factory/creative_shared_media_contract_v3.py:155)：参考视频的来源/资格检查及预览已有，实际提交尚未接；首帧分支使用原字节Base64，当前账号服务资格仍未核实。
- 冻结清单`run_01/SHARED_MANIFEST.json`仅允许bootstrap/first_frame，人物及场景素材映射unknown、声线unbound。此次登记不修改该清单，不将文档发现写成服务已通过。

## MiniMax与DeepSeek：收紧接口分工

| 项目 | 官网与实际核对 | 本项目行动 |
| --- | --- | --- |
| MiniMax-M3思考/输出 | M3可关闭思考；思考会占输出上限。新集成推荐`max_completion_tokens`，旧`max_tokens`仍有说明 | 保留M3，不按M3.1预览型号的参数换模型；未来独立适配器验证新字段 |
| MiniMax工具 | 官网有tools示例；本次未核实Chat Completions强制工具或严格内层Schema保证 | 本地继续验收；缺工具只按已授权的一次有界格式恢复处理 |
| 选定图片回传导演 | M3官方支持`image_url`等多模态输入 | 美术选定后的图片应进入实际导演请求并保存覆盖证据，不能只传文件名/文字摘要；视频理解仍按用户禁止自动审片规则关闭 |
| DeepSeek强制工具 | 指定函数/required需要非思考模式；默认思考开启 | 当前生产明确disabled合规；新适配器禁止thinking缺省与named tool组合 |
| DeepSeek strict | beta接口支持严格函数Schema及有限Schema子集；JSON mode主要解决语法 | 当前工具只有`payload_json:string`，strict即使约束外层也不能管住字符串内的完整合同；优先对审查结果用直接类型化对象做独立适配验证 |
| 结束原因 | 官方区分length、资源中断、aborted等 | 新故障分类保留具体原因；完整HTTP返回不意味着内容完整可采用，无未知结果重派 |

出处：[MiniMax OpenAI兼容接口](https://platform.minimax.io/docs/api-reference/text-openai-api)、[MiniMax工具指南](https://platform.minimax.io/docs/guides/text-m3-function-call)、[DeepSeek Chat API](https://api-docs.deepseek.com/api/create-chat-completion/)、[DeepSeek strict说明](https://api-docs.deepseek.com/guides/tool_calls/)、[DeepSeek JSON说明](https://api-docs.deepseek.com/guides/json_mode/)。

本次实查当前配置的`GET https://api.deepseek.com/v1/models`，HTTP200；选定`deepseek-flash`实际返回名称为`DeepSeek-V4.1-Flash`，支持的模型元数据已脱敏保存。这是目录查询成功，不是strict/生成质量测试，也没有修改审查模型或输出额度。[官方模型目录API](https://api-docs.deepseek.com/api/list-models/)

517实际为MiniMax-M3、thinking disabled、10000输出上限，完整tool_calls、已知用量。拒绝原因是漏来源/重复来源，不能把它改写成分析耗尽或服务未知。旧长分析耗尽的服务端原因仍缺独立证据。

## 开源平台与官方工具：只吸收适用机制

| 项目 | 本次核实的可参考机制 | 采用范围与限制 |
| --- | --- | --- |
| [ComfyUI](https://docs.comfy.org/development/comfyui-server/comms_routes) | 节点能力发现、工作流、任务ID与history；[Seedance节点](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_api_nodes/nodes_bytedance.py)按真实输入顺序编号素材 | 优先借鉴素材编号与输入连线；合作节点使用Comfy/BytePlus，不能与Ark账号及asset ID混用。GPL-3.0 |
| [LibTV官方插件目录](https://github.com/liblib-ai/marketplace) | Remote MCP和制作skills；[Blender制作skill](https://raw.githubusercontent.com/liblib-ai/marketplace/main/plugins/libtv/skills/libtv-blender-live-action/SKILL.md)用同场景多视角、人物色标和白模固定空间 | 公开的是插件/skills，不是完整生成后端；其2.5/设定板/播放审核默认不替代本项目Mini及人工审片规则 |
| [火宝短剧](https://github.com/chatfire-AI/huobao-drama) | 角色/场景/道具/分镜分表、sys_task保存参数与厂商任务ID；[火山适配器](https://raw.githubusercontent.com/chatfire-AI/huobao-drama/master/backend/src/services/adapters/volcengine-video.ts)使用相同Mini型号的参考图/视频/音频 | 借鉴资产关系和provider adapter；源码存在模型回退、异常统一failed、抽海报帧及未保留服务尾帧，不原样采用。CC BY-NC-SA 4.0，不能直接按商业运营平台整套搬 |
| [LangGraph](https://docs.langchain.com/oss/python/langgraph/interrupts) | checkpoint、固定thread_id、interrupt人工审核等待 | 可借鉴独立审核节点；恢复会重跑节点起点，付费提交必须去重，不把框架恢复当未知请求重派。MIT |
| [Temporal](https://docs.temporal.io/encyclopedia/retry-policies) | 持久工作流、外部批准与任务阶段拆分 | 暂不引入服务器；Activity默认重试不适合现有未知结果边界。MIT |
| [方舟官方Ark CLI](https://github.com/volcengine/ark-cli) | 模型、生成、资源与诊断能力发现，官方skills导航 | 适合作以后发现入口，当前未安装；不会为研究启动生成/理解媒体/购买任务 |

Comfy官方已有Mini主体+场景参考工作流，可验证多参考是一条现成设计路线；不能由该样例推断当前Ark账户的素材审核已通过。[官方Mini工作流](https://docs.comfy.org/tutorials/partner-nodes/bytedance/seedance-2-0)

火山自身的[短剧制作文档](https://docs.volcengine.com/docs/drama-creation/short-play-creation?lang=zh)也展示共用角色、服装、场景、道具和角色音色，再匹配分镜的流程。这是产品流程参考，不是开源系统；网页产品输入限制不能替代Ark API限制。

## 实际环境与本次落地

项目venv已有OpenAI SDK、httpx、jsonschema、火山SDK与LangChain Core；没有LangGraph/Temporal。`comfy/kling/arkcli`当前不在PATH；但项目`tools/scene_lab_20261006/envs/comfy_mcp/Scripts/comfy.exe`及隔离Blender/Comfy MCP环境存在，历史有同几何多视角与VACE试验。服务当前在线、节点与模型完整性尚未核实，不能把历史试验写成当前可生产。

已新增[只读环境审计命令](../scripts/audit_creative_provider_environment_v1.py)和[能力注册表](../config/creative_provider_capabilities_20261012.json)，核查精确型号、实际冻结清单、旧/新源码哈希、依赖与公开模型元数据。默认离线；`--query-models`仅发一次DeepSeek GET，不含生成/余额查询，禁止未知域名、重定向与自动重试，错误正文和凭据不落盘。输出采用新文件，不能覆盖原回执。

```powershell
# 只读离线盘点；每次输出使用新文件名
.venv\Scripts\python.exe scripts/audit_creative_provider_environment_v1.py --output data/qa/creative_provider_environment_20261012/new_offline_audit.json
# 可选：查询已配置DeepSeek的公开模型目录，不生成内容
.venv\Scripts\python.exe scripts/audit_creative_provider_environment_v1.py --query-models --output data/qa/creative_provider_environment_20261012/new_model_directory_audit.json
```

离线验证6项通过，覆盖只GET一次、限制认证目的地、去除凭据及错误正文、畸形200不假成功、不重试、模型缺失不假支持。两份冻结源码核对均无变更，旧/新账本保持原哈希。测试只验证此审计命令，不代表角色一致性或制作质量通过。

本次审计初版只用于保留DeepSeek目录查询证据；最终活动候选容量取[v2审计](../data/qa/creative_provider_environment_20261012/ENVIRONMENT_AUDIT_v2.json)中的实际终止记录，不使用初版误读的claims_count字段。已修活动进度索引残留的516/旧通过状态，保留更正前字段来源，不更改任何制作回执。

## 接下来的最小接入顺序

1. **先核对能力再规划**：精确型号/协议、时长、参考模式和素材来源进入新任务能力记录；新入口强制消费，不能只增加提示词。该注册表本次是操作者入口，尚未接成生产必经门。
2. **补完整导演与表演链**：当前仍停在517导演合同、候选4/4。终点选择新合同解决来源路径的编译分工；素材能力发现不修复这个文本失败，也不重领候选。
3. **建立一个可复用资产绑定**：新首段建立选定人物后，经用户批准登记角色ID→具体画中人→原生task/文件哈希/外貌服装→声线。稳定属性全片共用，持物/座位/情绪等动态状态每段更新。选定图片回到导演实际多模态请求；素材数量按当前出镜人与场景需求生成，不固定扩展三视图。
4. **程序选择模式和编号**：连续可辨人物动作使用正式批准尾帧；换机位、角色重新入画或主体/声线参考需求走独立验证的多模态分支。程序依实际content顺序生成图片/视频/音频编号及角色映射，并核对最终HTTP覆盖。多模态中尾帧只是参考时须明确其约束强度，不能冒充正式first_frame。
5. **生产调度分阶段保存**：提交前持久化身份/claim→保存服务task ID→只查原ID→保存视频与原尾帧→awaiting_human_review→明确批准后续段。结果未知不重派，缺工具/截断/类型错误按具体合同分流。视频审查与发布边界保持现行要求。

需要新版本适配的代码不会写回已冻结的v1/v3/v4或旧账本。本次完成的是资料与环境对照、可复用查询入口和导航修正；尚未完成多模态生产适配、真实导演验收或新视频，不能将此报告作为完整制作交接。

## 文件与证据

- [能力注册表](../config/creative_provider_capabilities_20261012.json)
- [最终只读环境审计](../data/qa/creative_provider_environment_20261012/ENVIRONMENT_AUDIT_v2.json)
- [DeepSeek目录查询脱敏证据](../data/qa/creative_provider_environment_20261012/MODEL_DIRECTORY_READ_ONLY.json)（保留初版来源哈希，不是原始HTTP响应全文）
- [离线测试回执](../data/qa/creative_provider_environment_20261012/OFFLINE_TESTS.xml)
- [本轮517实际生产停点](CREATIVE_COMPLETE_WORKFLOW_PRODUCTION_TEST_20261012.md)
