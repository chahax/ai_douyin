# 世界、场次与全体人物：最小独立合同设计

2026-10-15，第12轮子任务C。主agent已确认本最小方向。本文件另存，不修改已计轮冻结的CREATIVE_WORLD_SCENE_CONTEXT_PLAN。纯开发与离线验证，0付费/生产claim/计轮。

## 规范来源与字段

- 新完整规划在同一次MiniMax输出的whole_plan.world_frame补时代/现实基调、社会场域、前史、关系补充与既有scene_id之间的空间联系。旧人物profile/initial_state/want、scene description/appearance、audience_path与claims直接引用；不复制整套人物/事实/法律表。具体设定是原生作者内容，不能因位于框架而获法律豁免。
- 新完整正文保留title/premise/beats/steps。顶层scene_contexts每个剧情情境出现只存一次id、scene_id、story_time(label与相对前场关系)、environment_delta、previous_context_id。物理同地点可有多个情境出现。无固定秒数、段数或角色名。
- beat增加scene_context_id、ensemble及parallel_with。ensemble按实际参与的角色ID定位，动作只引用本拍已有action步骤索引；原生神情写一次并锚到动作，允许保持/安静聆听。parallel_with只声明action步骤与dialogue步骤可并行，不分配秒数。第一版以情境present_character_ids与每拍ensemble一致作覆盖约定；人员集合改变需原生新情境或明确进出，不由编译器补。
- present_character_ids表示本情境参与演员，不证明第一时点已经站在室内；入场仍由原生步骤和初态共同说明。不能只数speaker判断听者是否在场。真正场内身份/遗漏由全文审查对照初态、前后事件及动作。
- 前因沿原trigger，启后定位下一原生beat，不新增自由预测动作。故事时间不等于视频秒。世界作为剧本前置介绍与共享请求来源，输出结构要求归coordinator，不强制写成角色口播UC。

## 纯模块与API

独立creative_world_scene_context_v1.py，旧v23/v26/v27和未知creative_screenplay_world_v1不改。

1. build_goal_schema / validate_goal：新显式native版本；可在私有内存投影核旧字段，但不能把投影报成原生或拿旧审查批准新字段。原634无新增字段应明确不合格，不补默认世界/神情。
2. build_script_schema / validate_script：新场次与ensemble覆盖、ID/索引/引用/并行关系核对；原生完整新稿保持。旧step E编号不因标题/框架文字而挪动。
3. build_evidence_catalog：规划G/C递归目录能覆盖world新增字句；正文原E只管steps。另给H场次与P神情目录并标来源职责，背景/元信息不作已经演出的事件证据，神情不替代物件动作与法律成立条件。
4. 请求适配：完整世界只在native_goal_document保留一次；正文实际writer、source/scope及完整semantic构造必须含新文字和覆盖目录。适配器保持模型/参数与原请求来源，不派发。新schema/真实审查范围不齐时标不具生产资格，不伪造旧版本报告。
5. render_script：先框架与人物关系，再场次头/环境/参与人/承接和对白+并行表演；直接解析原生字段与引用，不生成新动作。
6. build_segment_context：同源世界一次、当前情境/beat/ensemble、验证当前snapshot、前一拍剧本事件及下一锁定事件。previous_script_event_is_verified_executed=False明确前一拍文本并不证明已演出；实际已发生状态只取合格snapshot/proof。proof必须精确绑定goal/script/beat/快照种类与SHA，资格仍由外部原始证据验证器核验。当前函数只构造可核对payload，实际director/media接线另验。

## 依赖影响表

| 改动 | 必须接入/重新核对 | 可复用与限制 |
|---|---|---|
| 新world_frame原生内容 | 新goal schema/源scope及source全文/commitment作用域/drama/全文semantic/正文/导演共享来源 | 旧G/C目录可递归取新字段；旧native SHA或旧报告不可当新批准；背景不一律变成对白义务 |
| 场次时间、环境、参与人、承接 | 新正文schema、H目录、全文语义与物理相关检查、渲染、当前段context | 角色和环境静态档案引用已有ID；不拷贝另一套人物/背景；时间语义需模型审查 |
| ensemble神情/动作引用 | P目录、每在场角色覆盖/听者反应检查、导演/局部表演输入 | 动作事实仍steps唯一来源；保持允许，无逐词或逐肌肉清单 |
| action-dialogue并行 | 部分顺序表示、全文semantic/physical前提与顺序schema、导演实际窗口 | 旧physical按更早E编号枚举前提不能直接证明新并行正确；不能将文档序当秒序 |
| 新正文完整返修 | 新完整原生稿及同稿全文复审，相关导演/表演/compile缓存身份 | 不手改局部或混旧新稿；可继续复用资格成立的静态资产 |
| 仅渲染格式修改 | 渲染版本与交付读回 | 原生字节/审查身份未变时不制造模型调用；不能靠渲染补正文缺失 |
| 实际director/local/media payload接线 | 新source binding/world/context/snapshot/角色映射与原始续段资格 | 现条线还无有效导演/表演/交接，旧7/7与账本不变；本模块不授媒体 |

## 本轮接线边界与验收

纯适配器必须用实际构造证明world/scene/ensemble文字进入source和semantic payload与目录，而非只render标题。适配旧请求时需保留完整source/原文身份；不能用删除新字段的检查投影声称完成新字段审查。既有full-review物理前提/顺序表按E文档先后建立，真实生产须接并行感知的审查合同；若本轮纯适配尚不能替换此约束，明确列为未接入/不生产，不放宽为自动pass。现有四审与完整全文审查不被小样例替代，不增加审查层或world付费阶段。

离线最小控制：原627/634缺字段拒绝；一个及多个角色/场景的合成正例；在场听者遗漏/未知ID/动作索引错误/错scene/world SHA/伪snapshot拒绝；保持与边说边做允许；同地点连续或跳时可显式表达；世界、场次和神情新字句有逐字目录并进入实际请求；渲染和payload不添原文未有内容。离线语义示例只是合同样例，不是模型批准。

## 已有原型只读结论

creative_screenplay_world_v1当前untracked，作者来源未知，本agent未创建。src/scripts/tests/docs精确引用扫描只见模块自身；对原635/636实际freeze另存字节证据，不能仅用时间戳推所有历史。其SHA绑定/ensemble/渲染机制可参考，角色名、C01/C02、150–180秒、10–18段、15秒档、4.2语速和0秒开口是专项限定，未核授权不采用。
