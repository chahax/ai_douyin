# 能力优先流程：实施与主agent审查交接

本轮先保存[完整修改方向](CREATIVE_CAPABILITY_FIRST_IMPLEMENTATION_PLAN_20261012.md)，三个子agent分模块实施，主agent检查代码、实际跨模块接线和原冻结记录，并另派独立审查。完成的是新独立代码的离线接线，尚未产生新的可采用导演计划、实际逐段表演、制作交接或视频。本轮生成、媒体和发布请求均为0。

当前正文保持512《桌面那张纸》及513同稿全文复审：公司要求小林离开，却要求在“个人原因”申请上签名；小林先质问、两次拒签，周姐从公司口径转为私人劝说，最后收走未签纸笔独自离开，小林留坐。没有手工回填剧情或转换517的失败导演稿。真实导演候选仍为4/4、remaining0，原未知70/160及消耗保留。

## 实际新增代码

| 模块 | 文件 | 实际接入与限度 |
| --- | --- | --- |
| A 能力预检 | [creative_provider_preflight_v1.py](../src/content_factory/creative_provider_preflight_v1.py) | 消费精确模型/协议注册表；区分逻辑请求和已序列化wire；检查思考/工具、格式与参考模式/数量/时长。五层证据分开，未检查字段明确列出，不能称完整wire强保障 |
| B 素材编译 | [creative_reference_compiler_v4.py](../src/content_factory/creative_reference_compiler_v4.py) | 原字节、原任务/回执、明确批准与主体映射进入真实content；编号按实际顺序。批准独立图片以image_url回传导演，正式首帧与多参考互斥 |
| C 新合同适配 | [creative_complete_production_pipeline_v4.py](../src/content_factory/creative_complete_production_pipeline_v4.py) | 模型原生选择终点与预算档，程序唯一推导连续起点与范围；局部使用既有表演合同，整片算术编译使用确定性projection，全审仍保留原生导演 |
| C 完整协调器 | [creative_complete_production_coordinator_v4.py](../src/content_factory/creative_complete_production_coordinator_v4.py) | 能力预检先于持久claim与派发；整片→局部→编译→同源全文复审；局部超窗回整片，有界完整返修；未知结果不重派，换图失效相关缓存 |
| 主agent只读集成入口 | [preview_creative_capability_pipeline_v5.py](../scripts/preview_creative_capability_pipeline_v5.py) | 核实真实512/513/517、当前LOOP_STATE、两个冻结与账本；预览新端点请求并验证原4/4零invoke。没有提交或重置操作 |

新协调器显式使用新阶段适配，没有替换或monkeypatch旧模块。原v1/v3/v4派发入口及冻结源码保持原字节，默认v23没有迁移。本轮同时将文档先行与主agent审查要求写入AGENTS.md，导航指向本记录。

## 审查发现与修复

| 实际问题 | 后果 | 本轮修复与负例 |
| --- | --- | --- |
| 音频可绑定actor/scene，主体缺失仍可编译 | 带素材却没有视觉人物对应 | actor/scene只能image/video，voice只能真实audio；必需主体、空subject、遗漏角色/场景均阻断 |
| 新图只进入导演，局部缓存身份未承接选图 | 换人设仍复用旧表演 | 程序派生选图/主体证据摘要进入局部输入；不同原素材或批准身份使局部缓存失效，全片复审重做 |
| 素材回调畸形或B的已知错误不形成停点 | 自动运行退出但缺明确阶段原因 | 缺主体、过期、畸形proof等结构化停止，零导演claim；实际派发异常独立作为结果未知保存 |
| 正式尾帧证据仅与旧合同自洽 | 旧剧情尾帧可能接到新剧情 | 必须独立传入当前冻结expected_continuation，逐项比较script、fixed identity、已完成来源前缀和previous task；缺当前证据即阻断 |
| brief、参考全文或偏好改变，旧正文proof仍自洽 | 当前创作输入与审查来源脱节 | 新proof绑定完整冻结production_context SHA；该绑定证明输入一致，不假称513语义审过视频偏好 |
| 派发回调原地改动请求 | 原预检/claim和返回请求可能错位 | 独立请求快照与回调副本分离；返回证据按原快照核对，错model/改source不得继续或内容返修 |
| 未核实MiniMax strict及非法ratio仍可能通过 | 将未验证服务能力误写成可用参数 | strict在未验证适配下阻断；ratio消费核实的七值，错类型/非法值/缺登记阻断；完整wire字段验收仍明确false |
| 显式新增候选后把完整旧停点再次送入模型 | 旧请求、全文和回执递归重复，输入继续膨胀 | 完整停点保留在状态历史；请求只带停点摘要、哈希与最多一份最新已知完整的原生失败反馈；未知结果不重开 |

比例依据为[创建视频生成任务官方API](https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh)。定点核实与注册表更新前快照保存在[OFFICIAL_RATIO_VERIFICATION.json](../data/qa/creative_capability_first_20261012/OFFICIAL_RATIO_VERIFICATION.json)；不修改先前能力审计回执。MiniMax工具响应保证及DeepSeek直接类型化strict依然需要各自的真实适配验证。

## 可复用分工和失效范围

整片导演决定情绪、因果、观察对象、新增信息和叙事切点；选择来源终点与预算档。程序计算连续范围和排时边界。当前512的数学图给出最少9段、总预算下界100秒，这只约束正常对白和动作下界，既不是固定审美段数，也不证明表演可行。

局部表演负责当前刺激与反应、对白与动作的实际重叠和反应窗口。共享人物、场景和道具规格作为固定输入，当前持物/位置/情绪作为动态状态传递。单段超窗时返回完整原生表演诊断，重建整片安排；不删句、手动压时或拼接新旧稿。

仅原输入、原规则、原模型、原Schema及选图身份完全一致时复用原生表演。新导演改变某段或其上游终态会改变受影响下游输入；换选图会改变局部素材绑定摘要。新整片安排总要重新全文制作复审，不复用旧整片审查。

MiniMax导演真实图片消息保留原正文/reference全文，再追加批准独立图片的原字节image_url。DeepSeek全文审查获得原生导演、实际请求/回执身份、素材映射证明与完整文字；避免把整块base64图再次塞入文本审查。仍锁定MiniMax-M3创作与deepseek-flash文本审查，无未经验证的模型替换。

## 素材合同与人审边界

新外层合同不会改旧SHARED_MANIFEST。它要求assets原文件/哈希、原服务task与回执、明确用户批准、subjects及entity_bindings，并显式列出当前需要的required_entities。声音没有独立真实audio输入时标unbound；图像或提示词里的声线描述不能替代音频绑定。

正式首帧需要已批准的服务原始尾帧及独立当前续接绑定；多参考模式仅作为参考，不声称正式首帧硬约束。原生素材的同账号/30天资格、签名URL期限与内容质量独立检查；30天采用原服务和原GET body一致的task创建时间作保守起点，本地completed_at不能延长期限。

素材编译器只消费已有原GET证据，不自己查询账号或判断像素中的人物。当前只接已登记精确Seedance 2.0/2.5原视频与对应服务尾帧的资格核对；Seedream原生图资格、旧回执规范化、当前账号实时GET和实际多模态提交适配仍未接入。测试中的PNG和批准文件是明确合成夹具，不是正式角色资产或真实用户批准。

视频仅由用户人工审核。助手不抽帧、听看、ASR或调用音画审核模型；成功保存应记awaiting_human_review。纯模块、模拟服务、接口成功均不能写成用户采用或视频passed。

## 离线证据与当前停点

主agent的跨模块测试实际调用B构造素材消息，再经过A预检和C完整模拟服务链；验证原生端点、两个局部、整片编译与同源复审，且改变原素材身份会使局部重新生成。合成两段样例只用于合同测试，没有替代512整片导演。

真实只读预览使用512正文、513审查、517完整拒绝回执和当前4/4停点，未派发新请求，未改原LOOP_STATE或账本。最新预览、最终测试XML、独立审查与冻结哈希见本记录末尾最终交接。原文、参考全文与初态仍由原冻结绑定核实；有效剧本文本与制作计划待完成分开记录。

后续须建立新冻结生产适配并承接原消耗；当前4/4不因开发完成而增加。还有实际SDK wire预检挂接、素材回执规范化/实时资格查询与原ID媒体提交保存需要完成。当前请求预览和模拟完整链不构成生产质量通过，也不证明脱离人工监管的运营质量普遍可靠。

## 最终交接（2026-10-12）

主agent最终相关回归为**263 passed，0 failed，0 skipped，12.49秒**，覆盖新三模块、实际跨模块模拟链、真实停点预览及依赖的旧制作/返修/媒体合同。独立审查此前复验179项；最后针对恢复请求的3项新增用例再次通过。没有把离线测试解释成模型生产质量通过。

| 实际产物 | 内容与证据 |
| --- | --- |
| [最新可读预览](../data/qa/creative_capability_first_20261012/integrated_preview_r2/WORKFLOW_REVIEW.html) | 当前512完整原生正文、新导演请求全文、来源绑定和待补素材；全部未派发 |
| [最终测试XML](../data/qa/creative_capability_first_20261012/ROOT_FINAL_VALIDATION_r2.xml) | 263项实际结果；早先XML及预览仍保留 |
| [最终离线验证记录](../data/qa/creative_capability_first_20261012/FINAL_OFFLINE_VALIDATION.json) | 新源码/注册表/产物哈希、两个冻结核对、真实4/4门禁与零调用记录 |
| [独立审查记录](../data/qa/creative_capability_first_20261012/INDEPENDENT_CODE_REVIEW.md) | 请求变更、来源绑定、素材映射、严格模式及恢复输入的发现与复验范围 |

两个旧冻结分别核对1026和1036个绑定文件，均无变化；原账本、授权、原回执与LOOP_STATE保持原字节。当前实际导演仍为4/4、remaining0，新增生成0、媒体0、发布0，预算重置false。本文是代码交接，不是新的整片制作交接。

本轮开发与审查已完成。主线下一步是补独立生产适配：实际SDK出站预检、现有原生素材回执与当前账号GET证据、精确Seedream资格和原ID视频提交/保存。完成这些适配不自动恢复导演次数；当前有效完整导演、实际表演窗口、新制作交接及成片质量仍待生产验证。
