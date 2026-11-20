# 番茄写实真人动态视频流：Claude Code 修改交接包

更新时间：2026-08-12  
状态：用户已授权；Claude Code 隔离审查与 Codex 独立复核已完成；68.1 秒、9 镜头写实真人审片已生成并通过机器门禁及 Codex 抽帧预审，已登记为 `review_required`；仍待用户播放终审，未发布、未回填。

## 0. 2026-08-11 实施与验收快照

- 审查范围使用脱敏隔离包：P0 相关源码、测试、文档、参考视频和样片证据；未包含数据库、账号、Cookie、浏览器 profile 或密钥。
- Claude 候选修改经 Codex 复核后，修正了单角色场景锚点、受控 LTX 帧数、MuseTalk 模型参数与时长门禁、RIFE/证据哈希、最终音频传递和 `hold_last` 合成策略等问题。
- 实机前又发现并修复 3 个真实缺陷：单角色场景锚点指纹引用未定义变量、PowerShell 大写 SHA-256 被错误拒绝、MuseTalk 未以其根目录为 cwd 导致本地 `models/sd-vae` 无法解析。
- 专项测试：`tests/test_live_action_ltx_provider.py` **93 passed**；包含该专项、视频生成与 P3 状态机的最终组合回归 **244 passed**。仅有 SQLAlchemy 2.0 弃用警告，无失败。
- 非口播镜头 `03_offer_reaction` 实机通过：704×1248、H.264 yuv420p、50fps；LTX 2.6 秒，经单次时长对齐与 RIFE 后输出 6.78 秒，最终合成按 `hold_last` 对齐 7 秒音频；各阶段 SHA-256 已记录。
- 第一次口播镜头技术链通过，但视觉出现额外疑似未成年人和卡通玩偶背包，按视觉门禁拒绝，不得用于样片或发布。
- 收紧为“始终单人、空背景不变”并换 seed 后，口播镜头重生成通过：LTX→7 秒对齐→MuseTalk→RIFE 50fps，未出现额外人物/卡通元素；可播放人审样片为 `data/fanqie_promotion/renders/task1_story_v5_smoke/01_campus_boast_review_v1.mp4`，7.000 秒，SHA-256 `772DE6546A2644B1B4BF196ECA136DB259A91A5FC297C13CCB9967055B83AFDC`。
- 9 镜头整片已完成。镜头 `04`、`07a`、`08` 的首版分别出现额外人物/卡通元素、伪英文覆盖、人物服装或体型漂移，均被拒绝并只重跑失败镜头；连同早期口播首版，共保留 4 次拒绝证据。
- 最终审片：`data/fanqie_promotion/renders/task1_story_v5_full/task1_story_v5_review.mp4`，68.100 秒，1080×1920，H.264 High/yuv420p/50fps，AAC LC 48kHz 双声道，SHA-256 `6cad5c73727ad05cf06cd1683825efb5d28ed25070ba830ca099693323e9a585`。
- 机器门禁通过：原始合成质量报告 `passed=true`、`issues=[]`；9 个接受镜头的文件哈希均与阶段审计一致。最终联系表：`data/qa/task1_story_v5_final_contact_v4.png`。
- 已将最终候选登记到 P0 数据库：`FanqieVideoJob.id=4`、`status=review_required`，任务 1 转为 `review_required`、版本 25；发布记录 0、回填记录 0，`publish_allowed=false`。
- 发布/监控/回填、闭环调度、养号调度和账号同步交叉回归在隔离可写目录中为 **228 passed，2 deselected**；2 项仅因显式 `py_compile` 会写只读 P0 worktree，另以只读 AST 验证 **198 个 Python 文件全部通过**。
- 真实 dry-run 证明：未人工批准时发布被 `review_required` 拦截，闭环调度拒绝提前进入发布阶段；P0 闭环库部署预检为 `ready=true`。在数据库副本中模拟人工批准后，发布仍因 `AI数字人 + story_video` 类型不匹配而拒绝，发布/回填记录保持 0。
- 养号调度可生成每日低频计划；当前活跃养号和闭环调度仍均为 0。无人值守参数固定禁用点赞/评论、`max_retries=0`，真实页面遇到登录页或验证码立即停止。
- 最新验收报告：`data/qa/fanqie_closed_loop_acceptance_20260812.json`；Claude 隔离交接包已更新为 76 个文件、约 53 MB，包含 P0 源码、参考视频、最终审片和审计证据，不含数据库、账号、Cookie、profile、密钥或 `.env`。
- 2026-08-12 只读扫描番茄达人中心共 5 条推广：唯一生效任务是 `AI数字人`（别名“我闭着眼睛玩”，有回填入口）；唯一 `解说混剪` 任务为“审核不通过”，没有回填入口；未发现生效的 `AIGC/解说混剪` 匹配任务。首次 CLI 扫描偶发等待 60 秒仍无表头，随后两次诊断探针约 2 秒读到完整表格，登录有效且无验证码；已作为 Claude 二次审查项记录，要求增加可配置超时和有界诊断/重试。
- 正向门禁演练：在另一份数据库副本中模拟 `publish_type=AIGC` 并模拟人工批准后，当前成片通过全部本地发布预检，返回 `preflight_ok`；没有调用浏览器、没有发布记录或回填记录。由此确认真实发布前剩余的本地业务条件就是用户终审与匹配的生效任务。
- 抖音养号真实冒烟通过：`account01` 推荐页浏览 1 条、固定 8 秒、无评论打开、无视频点赞或评论点赞，状态 `completed`，浏览器正常关闭并保存日志；账号仍为 `logged_in`，`last_warmup_at=2026-08-12T02:16:02`。未创建定时任务。首次使用默认旧 `wisdom_ai.db` 时在浏览器启动前被迁移预检拦截，显式指向 P0 `0009` 库后成功；生产 worker/CLI 的数据库配置必须统一。
- 当前结论：整片生产和机器验收已完成，用户人工播放终审尚未完成；任务 1 的 `publish_type=AI数字人` 与目标 `story_video/AIGC` 不匹配，因此即使人审通过也不能用该任务发布或回填。

## 1. 目标

把已经由律师参考项目验证过的动态视频工艺接入番茄推广闭环：

```text
批准脚本
→ 写实成年角色设定与固定母版人工审核
→ 可审计分镜
→ LTX-Video 2.3 逐镜头 I2V
→ 单次时长对齐
→ 仅对白近景使用 MuseTalk 1.5
→ RIFE 4.26：25fps → 50fps
→ FFmpeg 配音、BGM、字幕、拼接
→ 技术门禁 + 视觉门禁 + 人工审核
→ 抖音只上传一次
→ 轮询抖音平台审核
→ 审核通过后将作品 URL 回填番茄达人中心
```

番茄视频必须是全屏写实真人剧情短剧。禁止动漫人物、卡通、Q 版、软萌 3D 人物、玩偶、吉祥物、数字人主持人层和静态幻灯片回退。

## 2. 权威输入

- P0 工作区：`D:\IT\ai_douyin_p0`
- 参考成片：`D:\IT\ai_douyin\data\qa\wenshu_lawyer_brand_v1\wenshu_lawyer_brand_v1_50fps.mp4`
- 参考成片 SHA-256：`99D0F9F61BFA3E7A57290CE3093E6B0A8D8F472C53A0B3C92F23B61B668B801E`
- 参考说明：`D:\IT\ai_douyin\data\qa\wenshu_lawyer_brand_v1\DELIVERY.md`
- 参考项目：`D:\IT\ai_douyin\data\qa\wenshu_lawyer_brand_v1\project.json`
- 写实番茄流清单：`D:\IT\ai_douyin\data\fanqie_promotion\scene_plans\task1_story_v5_live_action_flow_ready.json`
- 番茄主目标文档：`D:\IT\ai_douyin_p0\docs\AUTOMATED_NOVEL_PROMOTION_OPERATIONS_PLAN.md`

## 3. 已验证证据

1. 参考项目存在 10 个 LTX 原始片段、10 个 MuseTalk 结果和 10 个 RIFE 结果。
2. LTX 2.3 22B FP8、LTX VAE、Gemma 文本编码器、MuseTalk V1.5 和 RIFE 4.26 模型均存在。
3. 参考成片为 704×1248、H.264、AAC、50fps、79.275 秒。
4. 参考链相关 5 个 Python 文件通过只读 AST 解析。
5. `fanqie-task-generate-video` 已增加生产 Provider `comfyui_ltx_i2v`，并保留旧 Provider 兼容。
6. `fanqie_live_action_video_flow/v1` 已支持固定成年角色母版、场景锚点、对白、动作、镜别、脚本段落映射和逐阶段审计。
7. 9 镜头整片已按固定角色母版逐镜头生成；失败镜头可按内容指纹单独重跑，不复用已拒绝产物。
8. 最终视频机器门禁通过并登记为 `review_required`，没有自动批准。
9. P0 数据库当前有 4 个视频任务；最新 id 4 为本次写实真人候选。抖音发布记录仍为 0，番茄回填记录仍为 0。
10. 默认 `wisdom_ai.db` 仍停留在旧 Alembic 版本；本次登记明确使用 `fanqie_closed_loop_p0.db`，未修改默认库。

## 4. 不能直接运行律师脚本的原因

`scripts/generate_lawyer_ltx_clips.py` 不能原样作为番茄 Provider：

- 正向提示词硬编码了 `High-end semi-realistic Chinese 3D animated legal suspense drama`，违反写实真人要求。
- `MOTIONS` 硬编码为 6 个律师镜头，与番茄任务分镜无关。
- 输入目录、输出前缀、分辨率、模型、seed 和报告路径部分硬编码。
- 没有读取番茄任务、脚本版本、角色母版或分镜契约。
- 没有把逐镜头工作流、角色哈希、模型哈希和阶段产物写进 `FanqieVideoJob` 审计包。
- 不是可恢复的阶段式任务；中途失败后缺少规范化续跑和幂等判定。

应复用工艺和已经验证的 ComfyUI 节点组合，不应复制律师内容或动画风格。

## 5. 必须实现的代码范围

建议的最小完整改动：

### 5.1 新增 `src/novel_promotion/live_action_flow.py`

- 定义并加载 `fanqie_live_action_video_flow/v1`。
- 验证任务、脚本、角色、母版、分镜、动作、对白、帧率和内容策略。
- 支持 `script_segment_refs` 或等价字段，使一个脚本段落可以拆成多个镜头。
- 每个出镜人物必须声明 `adult=true` 且年龄不低于 18。
- 母版路径必须存在，计算 SHA-256，并禁止同一角色在任务内静默换母版。
- 正向提示词必须为 ASCII 英文，且不得包含 anime、cartoon、chibi、3D animated、presenter、mascot、plush、child、minor、readable text、logo、watermark。
- 明确区分旁白和对白；只有 `spoken_closeup=true` 的对白镜头允许进入 MuseTalk。

### 5.2 扩展 `src/novel_promotion/scene_provider.py`

保持旧 Provider 兼容，可给 `ScenePlan` 增加一个默认空字典的 `metadata`，或增加兼容的专用计划类型。动态 Provider 至少需要取得：

- `character_ids`
- `master_image_paths` 与 SHA-256
- `framing`
- `motion_prompt`
- `duration_seconds`
- `dialogue`
- `spoken_closeup`
- `seed`
- `source_segment_refs`

### 5.3 新增 `src/novel_promotion/comfy_ltx_video_provider.py`

Provider 名称固定为 `comfyui_ltx_i2v`，`test_only=False`，`requires_structured_scene_plan=True`。

职责：

1. 只读 preflight：检查 ComfyUI loopback URL、必需节点、模型文件、FFmpeg、FFprobe、MuseTalk 和 RIFE；不得启动服务或写文件。
2. 每镜头从固定母版生成 LTX 2.3 I2V 工作流。
3. 使用内容指纹实现幂等和断点续跑；指纹至少包含母版哈希、动作 prompt、negative prompt、模型、seed、宽高、帧数、采样参数和 Provider 版本。
4. 每镜头保存 workflow JSON、请求摘要、prompt_id、ComfyUI history 摘要、原始片段和 SHA-256。
5. 单次时长对齐，不允许首尾循环、倒放或来回拼接。
6. 对白近景按清单使用 MuseTalk；要求使用时缺失或失败必须 fail-closed，不得悄悄换 Presenter、SadTalker 或静态图。
7. RIFE 输出必须经 ffprobe 验证为 50fps。
8. 输出完整 `SceneAsset.metadata`，包括各阶段输入输出、哈希、模型和审计路径。
9. 任一镜头失败时返回精确 `MissingCapability`，不生成半成品可发布任务。

### 5.4 修改 `src/novel_promotion/video_generation_service.py`

- 支持新 live-action schema，不再把镜头数强制绑定到双换行段落数。
- 写入 flow manifest SHA-256、角色母版哈希、逐镜头阶段产物和 Provider 版本。
- 最终仍调用现有 story-video 合成能力或一个严格兼容的合成适配层。
- 最终视频任务只能进入 `review_required`，绝不自动批准。
- 任何内容/技术门禁失败进入 `revision_required` 或生成失败，不得进入发布候选。

### 5.5 修改 `src/novel_promotion/cli.py`

- Provider choices 增加 `comfyui_ltx_i2v`。
- 增加必要参数，但优先从 flow manifest 读取，避免十几个平行 CLI 参数成为第二事实源。
- `--dry-run` 必须零目录、零 POST、零 ComfyUI 启动、零数据库和事件写入。
- `--confirm` 才允许生成本地视频；生成不等于授权发布。

### 5.6 复用并保持发布闭环门禁

不得放松以下文件中的现有门禁：

- `src/novel_promotion/review_service.py`
- `src/novel_promotion/full_publish_service.py`
- `src/novel_promotion/monitor_service.py`
- `src/novel_promotion/binding_service.py`
- `src/novel_promotion/orchestration.py`
- `src/novel_promotion/closed_loop_schedule_service.py`

顺序必须保持：

```text
人工批准视频 SHA-256
→ 仅上传一次
→ 等待并轮询抖音审核
→ 只有平台审核通过且得到唯一 canonical URL
→ 回填番茄
```

验证码、安全验证、零候选、多候选、错账号、标题歧义、任务过期或类型不匹配全部 fail-closed。

## 6. 测试矩阵

至少新增：

1. live-action manifest 正常加载。
2. 非成年角色、缺少年龄、动漫/卡通/3D animated 正向 prompt 被拒绝。
3. 母版缺失、母版哈希变化、镜头引用未知角色被拒绝。
4. 8 镜头映射 6 个脚本段落成功，非法段落引用失败。
5. `spoken_closeup=false` 不调用 MuseTalk。
6. `spoken_closeup=true` 且 MuseTalk 不可用时 fail-closed。
7. LTX 工作流使用指定母版、模型、seed、25fps 和固定纵屏分辨率。
8. RIFE 结果必须为 50fps；错误帧率被拒绝。
9. 相同指纹重跑复用逐镜头产物；修改母版或 prompt 后只重跑受影响镜头。
10. ComfyUI 离线 preflight 返回 `service_unavailable`，无写入。
11. dry-run 不创建目录、不 POST、不启动 ComfyUI、不写 DB/事件。
12. 单镜头失败不创建可发布 `FanqieVideoJob`。
13. 成功生成后状态为 `review_required`，`auto_approved=false`。
14. 审核后文件哈希变化时发布预检拒绝。
15. `publish_type=AI数字人` + `video_mode=story_video` 仍被拒绝。
16. fake 端到端：人工批准 → 上传一次 → awaiting_review → approved → bind；重复执行不重复上传或回填。
17. 真实浏览器上传、审核和番茄回填测试必须另行人工授权，不能由单元测试触发。

## 7. 文档修正

更新 `docs/AUTOMATED_NOVEL_PROMOTION_OPERATIONS_PLAN.md` 和 `docs/CURRENT_CAPABILITIES.md`：

- 开发前准确描述为：“本机 LTX/MuseTalk/RIFE 动态视频参考链已跑通，但尚未接入番茄 Provider”。
- 接入并测试后才能改成：“番茄写实动态 Provider 已实现”。
- 不得再把番茄推书描述为动漫数字人主线。
- 当前养号和闭环活跃调度任务均为 0，不得写成已经无人值守运行。
- 当前默认 `wisdom_ai.db` 尚未升级为闭环运行库。
- 当前任务 1 的 `publish_type=AI数字人`，与目标 `story_video/AIGC` 不匹配，禁止发布。
- P0-A 回填仍只有 `partially_verified`，没有真实成功回填证据。

## 8. 当前账号与调度证据

- `account01`：数据库状态 `active`；本地 `account.json` 为 `login_status=logged_in`，但最后登录时间是 2026-08-04、平台 UID 为空，真实上传或启用定时任务前仍须重新做 profile 登录预检。
- `douyin_novel_01`：数据库为 `login_required`，本地 `account.json` 为 `login_status=expired`，不可用于自动发布或养号。
- 当前 85 个 enabled 调度任务均为旧抓书/调查任务。
- 安全养号定时任务：0。
- 番茄闭环推进定时任务：0。

在用户播放并批准该写实视频、获得匹配的生效 AIGC 番茄任务、账号登录状态复核完成之前，不启用自动发布或回填调度。即使用户批准当前成片，现有 `AI数字人` 任务仍因类型不匹配而禁止发布。
