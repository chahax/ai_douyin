# 番茄真人剧情 V6.1：Claude Code（DeepSeek）审查请求

更新时间：2026-08-14  
状态：源码修改、创意静态关闭复审、生产数据流关闭复审和运行时源码绑定复审均已完成。Claude Code 2.1.226 实际使用 `deepseek-v4-pro / firstParty`；最新结论依次为 `V61_CREATIVE_STATIC_CLOSURE_APPROVED`、`V61_PRODUCTION_DATA_FLOW_APPROVED`、`V61_RUNTIME_SOURCE_BINDING_APPROVED`。本状态只批准在时间窗和真人审核人就绪后生成 7 镜头冒烟片，不批准整片、上传或回填。

## 1. 用户目标与授权边界

目标是生成无解释性旁白、动作和表情驱动、节奏紧凑、情绪语音自然的真人写实整片。成片须经人工审核，并确认存在匹配的生效 AIGC/解说混剪番茄任务后，才可上传抖音；平台审核通过并取得 canonical URL 后才能回填番茄。

用户已明确授权将 P0 源码、参考视频和样片证据发送给 Claude Code 审查修改。允许内容必须是脱敏隔离包；禁止包含数据库、账号、Cookie、浏览器 profile、密钥、`.env` 或登录态。用户指定 Claude Code 工具使用 DeepSeek 模型。

## 2. 当前事实

- 旧 V6 仅生成 8/19 镜头，视觉检查仅 `b02` 暂通过；旧片全部禁止上传。
- V6.1 计划：`data/fanqie_promotion/scene_plans/task1_story_v61_reviewed_anchors.json`。
- V6.1 计划 SHA-256：`D2C15C86B0AC57BE8CD26EF687C65C049D64B2069568707C8B699AE6D5828CB4`。
- 19 个真人写实锚点已经完成 Codex 视觉预检；没有动漫人物、玩偶、吉祥物或主持人叠层。
- P0 真实加载器验证：19 个 beat、19 个 ScenePlan、40.8 秒、无错误、所有动作提示为 ASCII。
- 锚点审计：`data/qa/task1_story_v61_anchor_review.json`；它仅允许进入视频冒烟，不代表成片人工批准。
- 权威数据库任务仍是 `revision_required`；抖音发布记录 0、番茄回填记录 0。
- 当前番茄任务类型为 `AI数字人`，不匹配无主持人 `story_video/AIGC`；禁止发布。
- 2026-08-14 后续变更已删除固定 TTS/GPU 时间锁，静态与运行时预检通过后可立即生成。
- 人工审核改为 Streamlit“视频审核”页的待审核/通过/驳回状态，不再配置 `allowed_signers` 或审核签名。

## 3. 本轮主要源码问题

审查 `src/novel_promotion/comfy_ltx_video_provider.py` 的缓存边界。目前 `_compute_fingerprint()` 把 `dialogue_audio_sha256` 和 `spoken_closeup` 纳入整个逐镜头证据目录指纹。CosyVoice 音频只影响时长对齐之后的 MuseTalk/RIFE 表演阶段，却会使相同锚点、动作、seed、模型和采样参数的昂贵 LTX 原片失去缓存。

目标设计必须满足：

1. LTX 运动阶段指纹只由锚点/人物、motion prompt、negative prompt、模型、seed、尺寸、帧数、采样参数及 Provider 版本决定。
2. 表演/交付阶段指纹由 LTX 阶段指纹、目标时长、`spoken_closeup`、对话音频 SHA、MuseTalk 版本/配置和 RIFE 配置决定。
3. 音频改变时可复用经过 SHA 校验的 LTX 原片，但必须重新执行时长对齐、MuseTalk（如需要）和 RIFE；绝不能复用旧口型或旧音频对应的最终片。
4. 锚点、动作、seed、模型或 LTX 参数改变时必须重新生成 LTX。
5. 旧的单指纹证据目录不能被不安全地当成新阶段缓存；迁移必须失败关闭，或只有在完整哈希验证后显式兼容。
6. 审计元数据同时保存 `ltx_fingerprint`、`delivery_fingerprint`、各阶段 SHA 和对话音频 SHA。
7. 任一阶段缓存文件缺失、哈希不匹配或元数据矛盾时，只能失效相应及其下游阶段，不得静默通过。
8. 不得放松真人写实、无动漫/玩偶/主持人、50fps、人工审核、类型匹配、一次上传和 canonical URL 回填门禁。

## 4. 测试要求

至少覆盖：

- 相同 LTX 输入但对话音频 SHA 改变：`ltx_fingerprint` 相同，`delivery_fingerprint` 不同。
- 音频改变的集成测试：不 POST ComfyUI/LTX，重新执行 MuseTalk 和 RIFE。
- `spoken_closeup` 从 false 变 true：不得复用无口型最终片，但允许复用相同 LTX 原片。
- 锚点 SHA、motion prompt、seed、frame_count 或模型变化：LTX 指纹变化。
- LTX 缓存哈希损坏：必须重新生成 LTX；delivery 缓存哈希损坏：只重跑交付阶段。
- 旧 `_compute_fingerprint` 测试改为分别断言 LTX 和 delivery 边界，不能继续要求音频使 LTX 指纹改变。
- 现有发布、审核、类型匹配和回填测试必须保持通过。

## 5. 输出要求

在实际 P0 工作区修改，而不是只修改隔离包副本。返回：

1. findings（按严重级别）；
2. 修改文件和关键设计；
3. 测试命令、通过数量和失败详情；
4. 仍有的风险或依赖；
5. 明确确认没有执行抖音上传、番茄回填、数据库写入或浏览器操作。

Claude Code 审查完成后，Codex 已独立复核修改并运行回归：主执行/窗口相关测试 `64 passed`，P0 Provider 测试 `212 passed`。运行时还会重新校验受审源码 SHA；只有执行窗口、可信真人审核人、静态门、只读运行时预检、磁盘和不可变路径全部就绪，窗口包才会给出 7 镜头冒烟命令。
