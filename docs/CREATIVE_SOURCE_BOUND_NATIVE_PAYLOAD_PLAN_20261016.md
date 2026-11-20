# 第27轮：原生创作载荷与本地来源信封分工

## 证据与目标

用户授权审查达标直接生成一次测试视频，MiniMax文本不逐次确认，视频人工审查。真实682完整返回15963tokens，唯一Schema错是没有复述本地版本schema；typed端点已符合Schema，仍不能补schema采用。原681/682合同及失败冻结保留。

## 本轮最小方案

原生事件载荷仅steps与temporal_relations；原生比较载荷仅fields与revision_target。schema、context_sha256、origin_native_script_sha256、compiled_ledger_sha256都是本地可确定数据，改由本地已冻结请求/原始回执身份与版本化信封确定性绑定，不要求模型复写，不增加提示词。请求、receipt、source_manifest、SQL、调用意图与实际SDK/wire核对仍必须完整，不能靠删除来源验证放行。

新协议/新请求，绝不将682删键、补键、转为新协议采用。实际新报告domain字段逐值保留；如果复用冻结A2验证器，必须显式生成只用于检查的canonical derived envelope，新增元信息全部来自实际请求，报告为派生而非原生；原生报告SHA与编译报告SHA分别保留，外部ledger/packet/决策绑定真实原生SHA。不得修改verdict、动作、对白或source quote，不伪装旧A2报告服务原生。优先选择简单、可审查的纯适配；不全局monkeypatch，不再复制庞大平台。

官方strict Beta已核实，但当前full Schema有allOf/if与长度等非支持项，需要独立wire子集与本地完整Schema适配；本轮保持现已验证客户端与端点，server_schema_guarantee=false。本轮解决的是不该由模型填写的本地常量职责，不宣称服务强制格式保障完成。不能为一个版本字段再扩大为整套新客户端/重写所有审查。

## 分工

A：新source-bound payload纯协议/薄WF；新原生载荷直接验证新Schema，来源信封和canonical checking identity显式、可反查；原生不变、来源篡改、越界/unknown/wholefield/未来open/词form检查；原682只作拒绝负控，原生两报告writer引用闭包完整。
B：known682桥，沿已确认681证书完整同字节freeze保祖先，只682本身SDK/wire/SQL/intent/固定v10replay实核一次；fixedregistry v11（先确认未被实际制作freeze绑定）；新config root round_07 / active27key / 原余额2body6review。
C：薄v11调用同一既有flow、mechanics、默认full7准入；不要把每次合同小改都复制187行协调器。显式固定policy/父证明/工作流回调，端点和媒体客户端不变。预算0/0/2/6=8，校准2审后剩4能完成1份新正文及聚焦/全文双审；writer前仍reserve4。已有C10完整SDK深验证复用为历史证据，不重跑400秒同路径；本次精选SDK两阶段→正确writer feedback/request生成以及新原生原样保存、原始请求身份/Replay验证即可，变化若确实涉及深证明则补唯一必要控并解释。
Root：独立审核与actualpreview/prepare/唯一RUN；定期内容进度核对，合格完整文本+导演表演制作通过即一次视频。

## 用量与边界

累计682/14835413reported tokens/680known；历史70/160和93117预留不变；原2body15–16/6review只承接余额，非新增/重置。旧RUN全部终止不重启。默认v23/旧冻结/模型分工不迁移。未知结果/用量、截断、缺工具仍按原边界停；不会删原生字段使旧失败变通过。若本轮原余额不足，不生成无复审容量的新稿。
