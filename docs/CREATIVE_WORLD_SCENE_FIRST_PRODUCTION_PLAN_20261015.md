# 世界场次原生正文到首段制作证明

本轮只接本会话 v28 实际 TEXT_HANDOFF 之后的完整导演、首段局部表演与首段制作审查。MiniMax 创作，DeepSeek 必要审查；root 审查后唯一派发。本模块开发、预览和测试不派发模型或视频，不改另一会话媒体文件，不把旧导演7/7重置。

## 同源与额度

固定调用 scripts.creative_world_scene_text_handoff_verifier_v1.verify_text_handoff；它按原STATE.schema在已知v1/v2实际验证器白名单中准确选择，不fallback、不只认ready。必须完整真实验收，继承其实际 inherited、parent_identity、source_files，不硬编码640或未来ordinal。644旧v1已知停点未ready，不得以它启动制作；新v2真实验收后才可进入。新 grant 明确导演最多3、首段表演最多3、制作审查最多3，Runtime7 对应 goal_plan/complete_script/full_review=3/3/3，goal_audit=0，总计9。每次明确完整内容拒绝保留原生全文及诊断；未知、截断、用量未知、缺/错工具立即停止，不自动运输重试。

新 root 使用 canonical parent identity 与真实 parent-root 双唯一后继；精确配置、授权、源码/输入、实际图片和原始用户素材委托全部冻结。TaskStore 在 SDK 前领取；Runtime 锁内再查配置绑定的当前轮门、冻结和精确重建请求。交接时实际修复轮为第15轮，代码不硬编码14或15，不能凭旧QA轮身份派发。原 RUN 不重启，所有实际请求、SDK raw、TaskStore、用量与终态保存。生产证明只给 first_segment_only，不代表其他段表演或整片制作已合格。

## 原生制作接线

1. 使用 pipeline_v4.build_director_input / whole_direction_schema / compile_direction；完整新正文、原生世界和场次、canonical 人物 profile、brief 已确认初态、R01全文各按真实来源携入。shared.build_pending_manifest 仅声明未知素材资格，profile 从原生 goal 精确引用；初态 scene_id 明确派生自第一拍，不能猜左右。三张独立静态参考实际接到 M3.1 multimodal user message，顺序环境/女/男，新的角色映射和原始图像生成请求来源冻结，当前委托选择不伪称用户审美批准。
2. 只给首段连续 source prefix 建立 local_performance 原生 schema；保留每人的 stimulus/reception、continuous_performance、逐项时长、对白听者、反应窗口和状态变化证据，调用 pipeline_v4.compile_performance。若超窗不得删句加速；可在剩余完整导演额度内携完整失败演法回整片导演改切点，并重新做首段演法。只支持首拍内首段，超出则明确停止，不能裁正文。
3. 生成横屏1280×704 H3 提示词采用新确定性 renderer，原对白仅当前来源各一次，正常普通话、无字幕；不调用旧9:16 renderer，不把未来剧情注入本clip。演员/场次/起态和表演均取原生/编译对象，非助手代写动作。H3帧网格从已编译实际表演总时长向上求17k+5帧，24fps，最多362帧；若有网格尾余量，提示词与制作审查显式给出保持既有终态的编码余量，不隐瞒/变速，语义可行仍由审查决定。
4. DeepSeek 在同一次首段制作审查中看到完整原稿、整片导演、当前原生表演/编译排时、原生世界/当前场次/全人物、实际三图映射、R01及最终实际 prompt。原生固定11项 checks：identity_asset_mapping、source_dialogue_fidelity、opening_causal_action、ensemble_emotional_action、stimulus_reaction、normal_speech_and_overlap、props_state_continuity、world_scene_continuity、current_prompt_isolation、spoken_language_and_unspoken_metadata、encoding_hold_not_new_action。每条 pass/fail/unknown 必须 quote 真实字段路径的逐字片段，wire与本地共同约束对应源字段组；不能仅引标题替代人物profile/映射/原asset请求三者对照。本地只核引用/身份/完整性/数值，不能用关键词判断语义。unknown停止，明确fail只能剩余额度内完整新表演并复审。

## 权威交付接口

scripts.creative_world_scene_production_probe_v1.verify_first_segment_handoff(root,text_verified=...) 返回已写媒体桥规范的 verified_first_segment：三原生身份、first beat/prefix、实际编码duration、prompt及UTF8 SHA、三图 ordered reference_map、原生 proof_files、handoff file SHA、same-story story_id。重新核验原 SDK 请求/响应、TaskStore、状态/成本/冻结和每个同源原生编译及审查；只信完整实际结果，不信手填 accepted。

父文本缺失/未验收、原生模型失败或任何证据不完整均不给媒体准备资格。生成、文件完整与人工内容通过仍分开。本模块无视频 POST、播放、抽帧、ASR、发布或后续段授权。
