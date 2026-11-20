# 世界框架与完整分段剧本独立修订入口

本轮来源为`revision_02/USER_REVISION_BRIEF.json`，用户改变旧634初态并要求完整重写。旧634正文/635全文审查/636诊断及旧freeze不修改；不把局部试拍当全链通过，不改他人计数round11。

实现为纯合同模块`src/content_factory/creative_screenplay_world_v1.py`与显式CLI`scripts/run_h3_screenplay_world_revision_v1.py`。复用原`creative_goal_context_dispatch_v7`的单发、先落pending回执、原始HTTP证据与严格结果/用量门，以及`creative_m31_flash_role_clients_v1`实际客户端。MiniMax-M3.1-Flash-Preview创作，DeepSeek-flash必要全文审查，SDK重试0；没有媒体调用。

本次消费父锚为`data/qa/creative_paired_live_diagnostic_20261015/PROBE636_SPEND_ANCHOR_v1.json`，只读重放真实原始receipt/SQL/冻结证据确认636次、13,408,816 reported tokens、634已知用量，历史未知70/160与93,117预留仍保留。旧director7/7不变。只读preview显示双successor是否已占用；prepare在主agent批准该预览身份后原子占用双successor，已有另一个后继则拒绝，不分支重领。

world单独1次来自本次用户明确新增世界框架要求，并不是重新领whole_plan5或导演候选。正文沿原complete_script剩余2次，仅初稿+1份完整内容返修；全文审查最多2次，从原剩余5中占用。最多5个真实请求；world合同失败即停，不自动追加。已完整返回且用量已知的正文合同失败、完整同源审查明确失败可以在2份正文内重写，带原生全文和精确诊断。未知/截断/缺工具/用量未知/审查不完整合同立即停，保留原身份；RUN不可自动重启。

## 原生合同与输出

world包含明确时代环境、固定人物图ID/SHA/外貌、动机与让步代价、可落实的空间区位/连接、道具唯一身份与初始持有/计划去向、冲突因果与法律表达边界。world先保存`WORLD_NATIVE.json`，中文自然分项投影为`WORLD_FRAMEWORK.md`。

正文保留`brief_sha256`与`world_sha256`，总计150–180秒、10–18段。首段15.0秒，后续单段≤15.083333334秒；H3实际帧数由媒体编译器另行处理，不把帧网格差值写成新对白。每段含整片起秒/持续秒、剧中时间、地点、环境光声、前因/后果/情绪重心、段首/段尾完整人物与道具状态以及逐event表演。每个event都描述C01/C02的动作、神情、视线和带本段相对秒的对白。events时间并集需覆盖全段，允许同步动作重叠但禁止未描述空档与重叠说话。必要检查限制普通语速上限4.2中文字/秒；语气与情绪自然性由同源全文审查及主agent文本审查判断，程序不假装语义识别。

正文状态逐值接上段原生end_state，首段道具逐值对world初态；经理0秒开口、桂芳当段实际回复为新用户明确要求。具体跨门、工作被打断、让步动因、纸张用途与来源/去向的真实性仍由全文模型语义审查，不用关键词代替内容判断。

DeepSeek一份全文审查同时覆盖9个世界/故事项及所有段；同源哈希锁定，引用只能是该完整正文或对应段的原始字符串。判定逐项pass/fail/unknown，一致聚合，fail须具体完整返修要求，unknown停止。机器文本成功仅记`text_review_accepted_for_local_trial`，旧text_ready_for_director、用户采用、创作质量批准与视频批准均不伪写。双原生文档及审查实际路径/文件SHA/规范JSON SHA在`TEXT_HANDOFF.json`独立保留；媒体不能把它们机械合并冒充一次模型原生结果。

## 主审与运行

```powershell
.venv/Scripts/python.exe scripts/run_h3_screenplay_world_revision_v1.py preview --output data/video_generation/h3_project_script_20261015/revision_02/text/PREVIEW_FOR_PRIMARY.json
.venv/Scripts/python.exe scripts/run_h3_screenplay_world_revision_v1.py prepare --approve-preview-sha <主审通过的primary_review_identity>
.venv/Scripts/python.exe scripts/run_h3_screenplay_world_revision_v1.py run
```

preview不建claim、不构造实际provider客户端、不发请求。prepare核对同一源码/brief/父锚/请求/预算完整身份再冻结。每次真正dispatch在runtime锁内重核完整继承及当前源；未知结果不盲重派。所有文件在D盘。

11项新增离线验证覆盖固定演员SHA、native来源哈希、跨段状态/道具、事件覆盖/尾空档/同步动作、经理即说与桂芳回应、语速/时长、同源逐段引用/结论一致、中文纯投影、主审身份门、未知后停发与单次RUN。运行方式：`.venv/Scripts/python.exe -m unittest discover -s tests -p test_creative_screenplay_world_v1.py -v`。默认系统Python缺jsonschema，实际使用项目既有.venv，不安装新依赖。

## 本轮输出容量复核

主agent审查后，新独立profile为`config/creative_screenplay_world_profile_v1.json`：world上限16000、完整正文65536、DeepSeek全文审查32000。MiniMax官方[Chat Completions参数文档](https://platform.minimax.cn/docs/api-reference/text-chat-openai)于2026-10-15读取，M3.1推荐输出额度131072、最大524288，且思考常开；本次为完整分段正文和思考留65536的有界上限，并非预付或新增候选。实际消耗只按真实usage累加。

旧adapter将writer输出固定16000，故新增`creative_m31_screenplay_role_clients_v1.py`子类，仅允许`complete_script`的精确65536，原world与review映射保持。旧模块/冻结profile原字节不改，未猴子补丁修改任何旧全局。新子类复用原序列化守卫、原始HTTP证据与单发代码；实际安装SDK的MockTransport已证实发送65536且先保存请求、不联网，其他值或阶段拒绝。此为离线接线证据，真实服务是否接受新正文容量仍待本次原始回执，不能先写已实测通过。
