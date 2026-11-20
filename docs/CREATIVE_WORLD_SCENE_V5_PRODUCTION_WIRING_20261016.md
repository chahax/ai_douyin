# 第21轮：v5文本到既有一次视频提交的固定接线

## 只读发现

`creative_world_scene_text_handoff_verifier_v1`只识别文本Session v1–v4，故真实v5即使合格也会被拒绝。`production_probe_v1.Session`有文本verifier注入点，但其公开交接验证函数重新构造默认Session，仍回到旧selector。媒体v1的live入口以函数身份锁旧text/production验证器；媒体v2重验又调用该入口。仅新增selector无法接通。

提交器v1已有`Submitter(..., verifier=...)`，可由固定新CLI注入新的媒体深核函数。沿用原`AUTHORIZATION_ID=world_scene_live_20261015_one_video_user_authorization_v1`、按授权和制作交接的双唯一claim、单POST、原ID查询及人工视频审核，不增加视频额度。

只读核对SETTLED664合并的986份`source_files`：上述selector、production v1、media v1/v2和video_submit v1均未列入该消费链；这不是哈希漂移。它们有既有QA和已验证历史，仍保留原文件，不借此改旧入口。被冻结的文本、world、workflow、全文审查及SDK模块也不修改。本文记录的是新接线范围，不代表已有文本或媒体合格。

## 最小独立文件

1. `creative_world_scene_text_handoff_verifier_v2.py`：固定版本registry。v1–v4仍由原固定selector深核；v5只能调用C提供的固定`creative_world_scene_live_session_v5.verify_text_handoff(root)`。未知版本拒绝，无配置模块路径、readyflag替代、旧报告转换或任意验证器import。核根路径、完整native身份、原SDK/SQL及新源状态门的责任属于对应原生verifier。
2. `creative_world_scene_production_probe_v2.py`：显式薄Session绑定registry2；复用原导演/表演/制作审查、SDK、任务、预算和原生编译函数。原存储及native交接协议继续明确共享production/v1，新增entry-binding固定registry2和本模块身份，并进入授权、preview及freeze。公开交接深核使用新的固定Session；仅移植旧函数缺少注入缝的验证段，不复制整个调度器、不替换旧globals。
3. `creative_world_scene_media_probe_v3.py`：固定registry2和production2深核；复用旧graph、参考顺序、timing、显式encoding和保存约定。旧live函数拒绝新verifier，所以新增必要live glue，不使用`offline_test=True`后翻旗。生成真实的共享PREPARED/v1与PREPARED_V2/v2协议，并额外绑定v3入口身份；新verify按实际新固定验证器重建全部来源、参考、图和encoding，兼容提交器v1的既有精确格式。
4. 新固定CLI：生产仅显式`run`派发模型；媒体准备不提交视频；提交CLI固定注入media3，显式`run`才调用原Submitter.submit，沿用同一授权ID和claim位置。旧CLI默认不迁移。原native_validate仍只显式GET节点描述和本地图检查，不向`/prompt`发validate-only请求。

## 准入与验证边界

当前没有真实v5 text_ready，不能prepare真实production/media、创建媒体claim或调用H3/API。本轮只落独立代码和有区分度的Mock：未知文本版本/伪ready拒绝；v5固定verifier被实际选择；制作深核不掉回selector1；媒体新live链重建且不能接受synthetic；提交器固定注入仍保同一全局单次授权。

新模块路径、版本和实际verifier代码SHA必须在prepare来源清单冻结，并在verify重新比对。配置不能选择任意callable/module。文字深核失败、新源审查unknown或未完整全文审查都不能被后段flag兜底。实际文本准备、模型派发、媒体提交和验收由主agent审查后执行；本说明不增加授权、预算或重试。

## 固定调用方接口

- 文本：`creative_world_scene_text_handoff_verifier_v2.verify_text_handoff(text_root)`，v5始终调用其自己的原生深核函数。返回既有标准`paths/identity/inherited/parent_identity/source_files`及新`verifier_entry`，不是机器状态旗标的转换。
- 制作：`creative_world_scene_production_probe_v2.Session(Config)`的`preview/authorization_template/prepare/run`及同模块`verify_first_segment_handoff(root)`。复用共享production/v1原生协议；新`entry_binding`必须同时等于当前源码、原preview、原授权，并进入实际freeze。仅显式`run`可派发模型，scope仍最多3导演、3首段表演、3制作审查。
- 媒体：`creative_world_scene_media_probe_v3.prepare(Config)`及`verify_prepared(root)`。prepare前须真实文本与制作双深核；仅prepare显式读取本地服务GET状态，不能POST。验证重建图、三参考顺序和原字节、同源prompt及encoding、保存命名空间、原账本与固定模块。共享`PREPARED/v1`与`PREPARED_V2/v2`是本次新生成的真实保存协议，另有`MEDIA_ENTRY_V3`固定绑定；不修改旧协议文件或翻旧synthetic旗标。
- 提交：`run_creative_world_scene_video_submit_v2.submitter(config)`固定注入上述media3；原`Submitter`与授权/制作交接双唯一claim位置完整沿用。新CLI本身也进入提交来源freeze。`preview/authorization/native-validate`不提交视频；只有显式`run`调用原单次POST，`poll/finalize`只处理原ID与容器/文件技术信息。

三个CLI均可直接从项目根以项目Python调用`--help`；模块导入和帮助命令不创建客户端、claim或服务调用。生产CLI的`run`参数为已prepare的制作root，其他动作参数为Config JSON；media CLI的`run`参数为Config JSON、`verify`参数为prepare root；提交CLI延用原Config JSON，`native-validate`参数为prepare root。旧默认CLI不迁移。

## 本轮离线证据口径

测试只替换固定函数符号提供明确合成文本证明，不提供生产配置注入后门；其合成报告不证明真实v5创作质量。新制作链使用安装SDK的MockTransport实际走3阶段、原raw/SQL/请求重建及原生制作交接深核；媒体链重建实际图/参考/encoding；提交Mock仅在临时项目发送1次合成POST并证明换root/grant不能重领同授权。没有本地GPU/API真实执行、真实prepare、媒体claim或视频内容审查。

编辑期首次直接CLI帮助检查发现导入路径缺失（`ModuleNotFoundError: scripts`）；已只给新三个入口补项目启动路径，随后三帮助命令均成功。原5项功能套首轮成功；最后启动头版本另存最终XML，不能把编辑前结果单独当最终源码证明。

## 第22轮兼容增量

第21轮的原始registry2、测试及本文字节已另存`data/qa/creative_world_scene_v5_wiring_20261016/round22_before_v6_binding`，原交接与XML保留。主agent明确授权在尚无真实制作/媒体冻结的新固定接线上追加v6；已实际核v5原freeze不含这4个后段新模块。

registry2现显式支持`creative_world_scene_live_session/v6/state`，只能调用固定`creative_world_scene_live_session_v6.verify_text_handoff(root)`，保留v5及原v1–v4路由。production2/media3/唯一submitCLI代码与授权ID不变，现有entry-binding和来源freeze机制自动绑定registry新SHA；旧QA摘要不能当更新后的生产冻结。新v6仍需以本身原SDK/SQL、当前665/四审/670、新source4和正文/双审深核证明完整交接；原671审查不能转换为通过。没有真实text_ready时仍不做后段prepare或API调用。

## 第23轮：原生与派生正文的实际后段兼容

真实v6在672源审查通过后，三份原生正文仍合同拒绝，已独立结算为675；没有合格正文或媒体。新v7合同让模型省略冗余`previous_context_id`，只由确定性编译生成链接。原生正文仍由服务生成，不能拿675改字段后采用。

仅补registry路由不足以兼容：旧制作入口把raw直接交旧合同，会拒新原生版本。主agent据实授权本轮补齐；已核v6真实freeze/祖先清单不含registry2、production2、media3和submitCLI，变更前字节/SHA在`round23_before_v7_binding`，原5文件不改。

新增`creative_world_scene_production_source_v1.verify_documents(proof)`固定调用`creative_world_scene_derived_context_script_v1.compile_document`，逐值核对真实raw、derived、compiled及`source_descriptor`，对应三种SHA。`load_material`只在私有临时checking proof中把canonical路径交旧纯编译校验；该对象不落盘、不对外导出，返回前恢复真实raw与原始proof，canonical及descriptor独立命名。服务原生身份不因兼容而改写。

production2显式覆盖必要`preview/_rebuild/run`胶水，继续共享原SDK、预算、TaskStore、claim、导演/表演编译及交接保存。导演、表演、制作审查实际请求附来源绑定；`full_current_script`和其引用目录明确是canonical compiled，真实provider native用独立SHA追溯。制作审查按实际送达context重建SHA、Schema常量和引文目录，不把旧原生审查报告投影为新通过。

media3同样重算来源转换，保`native_script_sha256`指真实raw、`derived_script_sha256`指canonical、`compiled_script_sha256`指编译稿；参考/源步骤目录明确取canonical，图和prompt继续原样确定性编译。registry2新增固定v7原生深核函数，保v5/v6；submitCLI、全局单次授权ID与原双唯一claim机制均未改。以后prepare冻结的是本次实际新SHA，不是旧QA快照。

必要离线验证只含新native→来源验证/三类实际请求、三制作SDK Mock与原raw/SQL深核、固定v5/v6/v7路由、媒体图重建及来源篡改拒绝。不重跑整片十阶段或H3执行。真实v7文本、制作及媒体仍须各自深核，当前开发证据不代表真实创作通过。
