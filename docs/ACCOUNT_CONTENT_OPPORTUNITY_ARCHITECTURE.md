---
doc_status: current
doc_category: architecture
last_reviewed: 2026-09-01
model_usage: 多账号内容机会发现、视频内容分析、时间趋势、反馈归因和剧本生成闭环的升级设计。
---

# 多账号内容机会分析与剧本生成闭环设计

## 当前实施状态（2026-09-01）

已完成 P0、P1、P2 和 P3 代码：

- 新增统一 `AccountProfile` 和稳定账号 UUID；
- 新增 `douyin_accounts`、`account_strategy_versions` 持久化与不可变版本；
- 新增 `DomainStrategy` 契约、配置 Schema 和版本化注册表；
- 接入 `legal_services/v1`、`novel_promotion/v1`；
- `TrendAnalyzer` 已按账号和策略生成隔离的 Cluster、Brief 和领域证据；
- 热门选题页面已增加“账号策略”，采集后分析使用所选账号策略；
- 已使用第三个测试领域验证无需修改核心分析服务即可扩展。
- 领域查询计划可生成基线、发现、动量三类波次，并按单批页面上限自动拆批；
- 采集计划、账号 UUID、账号策略版本、领域策略版本和实际执行批次已形成审计链；
- 计划可根据已完成批次恢复剩余工作，基线/发现默认 24 小时、动量默认 6 小时；
- 来源视频补充页面可见发布时间、展示指标口径，标签族和视频支持 14 天多时间点动量；
- 趋势页展示领域分批计划、视频动量、标签族动量、观察点数和置信度。
- 新增统一 `ContentAnalysisProvider` 契约和网页人工实现切换；
- 接入 `metadata_heuristic/v1` 降级实现与 `local_qwen_paraformer/v1` 本地实现；
- 现有 Qwen3-VL 关键帧和 Paraformer 转写脚本已接入隔离输出的本地工具链；
- 批处理支持账号隔离、输入指纹缓存、最大并发、失败降级和批次审计；
- 每条候选输出内容摘要、主题、用户意图、钩子、展示方式、节奏、时间段、证据、
  不确定项、原创边界，以及相对当前账号关键词/业务范围的相关度与置信度。
- 新增账号级 `ContentOpportunity`，综合流量、时间动量、内容证据、相关度、
  新鲜度、饱和度、风险与制作可行性，并设置 48 小时或 7 天有效期；
- 机会卡锁定推荐展示方式、钩子、节奏、15 秒时长、发布时间窗和工作流方案；
- 新增可扩展脚本策略注册表，首批接入法律与小说 A/B 脚本策略；
- 每个脚本固定输出 0—5、5—10、10—15 秒三段画面、口播/对白和字幕，
  同时保留来源要求、事实核验、原创边界和工作流快照；
- 小说策略使用授权章节与角色占位符，未绑定目标小说时不会伪造目标书剧情。

尚未完成：发布反馈的多维归因、时间窗基线、策略版本胜率和下一轮自动调权。后续阶段继续按本文 P4 实施。

## 1. 核心目标

系统的核心产物不是“热门视频列表”，而是针对某一个运营账号，在某一个时间窗口内给出可追溯的内容机会判断：

1. 这个账号现在应该做什么主题；
2. 为什么现在适合做；
3. 应采用什么视频展示方式；
4. 应使用什么开头、叙事结构、时长和发布窗口；
5. 结论来自哪些关键词、标签族、视频内容、流量快照和用户反馈；
6. 发布后实际表现是否证明这个判断有效；
7. 下一轮应保留、调整还是淘汰哪些策略。

第一阶段首批接入两类账号，但它们只是领域策略插件，不是系统支持范围的硬编码边界：

- 法律/律所宣传账号：目标是建立专业信任、获取合规咨询线索、推广律所服务；
- 小说推广账号：目标是提高小说兴趣、搜索/阅读意愿，并关联番茄推广任务或推广标的。

后续新增其他领域时，必须只增加领域策略实现、领域配置 Schema 和必要的合规规则，不修改采集、时间序列、机会排行、剧本版本、发布归因等核心协议。

## 2. 总体判断

现有 `trend_intelligence` 已经具备关键词采样、标签族扩展、页面样本流量、标题聚类、选题卡和发布后指标快照的骨架；本地也已经有 Qwen3-VL、Paraformer、镜头切分和剧本整理能力。

当前缺少的不是单一算法，而是以下四条主线之间的统一业务主键和稳定契约：

```text
账号策略
  ├─ 搜索与标签族研究
  ├─ 来源视频内容理解
  ├─ 当前内容机会判断
  └─ 生成、发布与反馈学习
```

升级后必须以 `account_uuid + strategy_version` 为分析起点。相同的热点，对不同账号可能得出完全不同的发布建议。

## 3. 目标架构

```text
运营账号画像 AccountProfile
        │
        ▼
领域策略 DomainStrategy
        │ 生成关键词、用户问题、意图、排除词、合规规则
        ▼
查询计划 QueryPlan
        │
        ├── 根关键词、多排序采集
        ├── 标签族扩展和共现图
        ├── 相关问题/场景词扩展
        └── 多时间点复采
        ▼
来源视频事实层 SourceVideoFact
        │
        ├── 页面指标与排名时间序列
        ├── 授权媒体获取
        └── 元数据去重/内容去重
        ▼
内容理解 ContentAnalysis
        │
        ├── ASR / OCR / 关键帧 / 镜头
        ├── 主题、人物、冲突、钩子、回报
        ├── 展示形式、节奏、时长、字幕、CTA
        └── 风险、版权和不确定性
        ▼
账号相关度 + 时间趋势 + 用户反馈 + 生产可行性
        ▼
ContentOpportunity（当前内容机会卡）
        │
        ▼
人工批准 / 选择实验方案
        │
        ▼
ScriptBrief → ScriptVersion → 视频工作流方案
        │
        ▼
发布 → 1h/6h/24h/72h/7d 指标与评论反馈
        │
        └─────────────── 回写账号策略和机会模型
```

## 4. 统一账号画像

### 4.1 账号主数据

新增统一的 `AccountProfile`，复用现有 `WarmupAccount.account_id`、`videos.account_key` 和番茄支线规划的 `douyin_accounts`，不再让趋势分析、养号、发布和番茄推广各自维护一套账号身份。

建议字段：

| 字段 | 说明 |
|---|---|
| `account_uuid` | 跨数据库稳定 UUID |
| `account_key` | 当前 CLI、目录和发布数据使用的账号键 |
| `platform` | `douyin` 等平台 |
| `display_name` | 内部展示名 |
| `business_mode` | `law_firm_lead`、`novel_promotion` 等 |
| `domain_strategy_id` | 领域策略实现 |
| `strategy_version` | 不可变策略版本 |
| `domain_config_json` | 由领域策略 Schema 校验的扩展配置 |
| `business_goal` | 咨询线索、品牌信任、阅读转化等 |
| `target_audiences` | 目标人群列表 |
| `service_scope` | 律所业务范围或小说推广范围 |
| `geo_scope` | 律所服务地域；无地域限制可空 |
| `seed_keywords` | 初始关键词 |
| `negative_keywords` | 排除的误召回词 |
| `allowed_formats` | 允许的视频表现形式 |
| `forbidden_formats` | 不允许的表现形式 |
| `cta_policy` | 允许的行动引导 |
| `compliance_profile` | 合规规则版本 |
| `workflow_profile` | 默认视频生产方案 |
| `publishing_windows` | 偏好的发布时间窗 |
| `experiment_policy` | 稳定/相邻/实验内容比例 |
| `status` | `active`、`paused`、`disabled` |

账号表不得保存 Cookie、token、密码、验证码或浏览器 storage state 内容。浏览器 Profile 继续按 `account_key` 隔离。

### 4.2 法律律所号示例

```json
{
  "account_key": "douyin_legal_01",
  "business_mode": "law_firm_lead",
  "business_goal": ["专业信任", "合规咨询线索"],
  "target_audiences": ["婚姻家事当事人", "劳动争议职工"],
  "service_scope": ["婚姻家事", "劳动争议"],
  "geo_scope": ["本市", "本省"],
  "seed_keywords": ["夫妻共同债务", "彩礼返还", "劳动仲裁"],
  "negative_keywords": ["法律职业资格考试", "法学考研"],
  "allowed_formats": ["场景普法", "律师口播", "证据清单", "对话短剧"],
  "cta_policy": ["提示结合个案咨询", "允许私信咨询，不承诺结果"],
  "workflow_profile": "legal_presenter"
}
```

### 4.3 小说推广号示例

```json
{
  "account_key": "douyin_novel_01",
  "business_mode": "novel_promotion",
  "business_goal": ["阅读兴趣", "搜索转化", "推广任务转化"],
  "target_audiences": ["女频爽文用户", "重生复仇用户"],
  "service_scope": ["番茄小说推广任务"],
  "seed_keywords": ["小说推文", "重生复仇", "大女主", "一口气看完"],
  "negative_keywords": ["盗版全文", "免费全集下载"],
  "allowed_formats": ["剧情解说", "悬念钩子", "人设爽点", "情绪共鸣"],
  "cta_policy": ["引导搜索书名", "引导平台内阅读"],
  "workflow_profile": "novel_story"
}
```

## 5. 可扩展领域策略接口

法律和小说不能共用同一套硬编码选题卡，核心服务也不能直接依赖 `LegalStrategy` 或 `NovelStrategy`。新增稳定接口和策略注册表：

```python
class DomainStrategy(Protocol):
    strategy_id: str
    version: str

    def config_schema(self) -> dict: ...
    def build_query_plan(self, profile: AccountProfile) -> QueryPlan: ...
    def classify_intent(self, analysis: ContentAnalysis) -> IntentResult: ...
    def score_account_fit(self, profile, analysis) -> ScoreEvidence: ...
    def build_opportunity_brief(self, opportunity) -> OpportunityBrief: ...
    def build_script_brief(self, opportunity) -> ScriptBrief: ...
    def validate_script(self, script, evidence) -> ValidationResult: ...
```

```python
class DomainStrategyRegistry:
    def register(self, strategy: DomainStrategy) -> None: ...
    def get(self, strategy_id: str, version: str) -> DomainStrategy: ...
    def list_available(self) -> list[DomainStrategySpec]: ...
```

注册表必须执行以下约束：

- `strategy_id + version` 唯一；
- 所有策略返回相同版本的 `QueryPlan`、`ContentOpportunity` 和 `ScriptBrief`；
- `domain_config_json` 必须先通过该策略提供的 JSON Schema；
- 策略版本发布后不可原地修改，修改规则必须增加版本；
- 历史机会卡、剧本和发布记录继续引用原策略版本；
- 网页根据策略提供的配置 Schema 渲染领域特有字段，不在页面里写死法律或小说表单；
- 未注册或健康检查失败的策略不能用于新任务，但不能影响历史记录读取。

首批内置实现：

| `strategy_id` | 首版实现 | 用途 |
|---|---|---|
| `legal_services` | `LegalServicesStrategy/v1` | 律所品牌、普法和咨询线索 |
| `novel_promotion` | `NovelPromotionStrategy/v1` | 小说推文和推广任务转化 |

未来可以按相同契约增加教育、职场、财税、本地生活等领域，而不扩展核心服务的条件分支。

### 5.1 法律策略

需要额外提取和校验：

- 法律问题、当事人角色、事实条件和地域；
- 用户所处阶段：预防、协商、取证、诉讼、执行；
- 高频误区、证据需求、行动步骤；
- 法规时效和事实不确定性；
- 咨询意图强度，但不得输出胜诉承诺或确定性结论；
- 热门视频用于发现关注点，法律依据必须使用独立权威事实源核验。

### 5.2 小说推广策略

需要额外提取：

- 题材、性别向、时代、世界观；
- 主角身份、核心困境、反派、关系线；
- 爽点、虐点、反转、悬念和情绪回报；
- 是否适合 15 秒、30 秒或连续剧结构；
- 推广标的、书名、任务和授权章节；
- 不得把热门样本文案当作小说原文，不得编造推广小说不存在的桥段。

## 6. 大规模采集与分层分析

“大量采集”不应等于“所有视频都运行重型视觉模型”。应采用三层漏斗：

### 6.1 第一层：全量元数据发现

采集范围由授权和页面预算控制，保存：

- 查询计划、根关键词、查询类型和标签族；
- 排序、名次、标题、作者、标签、URL、视频 ID；
- 来源发布时间（能够可靠取得时）；
- 页面展示字段原文、标准化值、`metric_kind` 和质量；
- 采集时间、解析器版本和证据哈希；
- 页面阻断、字段缺失和排序未确认状态。

采集任务必须使用现有 `CollectionJob`、Checkpoint 和 PageBudget 能力，不再由 Streamlit 请求同步跑完整批次。

### 6.2 第二层：候选筛选和轻量分析

按以下条件筛选进入内容获取队列：

- 与账号关键词/人群问题具有初步文本相关度；
- 在标签族或排序中进入相对高位；
- 指标增长、排名增长或跨排序覆盖出现信号；
- 每个标签族保留内容多样性，避免只分析同一作者和近重复视频；
- 新视频、持续热视频和异常增长视频分别保留样本。

轻量分析可只使用标题、标签、封面/OCR、时长和有限文本，优先淘汰误召回。

### 6.3 第三层：高流量候选完整内容分析

只对自有、许可、书面授权或人工合法提供的媒体执行自动下载和完整分析。媒体访问模式固定为：

- `metadata_only`；
- `authorized_download`；
- `manual_local_media`；
- `owned_account_export`；
- `licensed_feed`。

对所有进入高流量候选集合的视频执行 ASR、OCR、关键帧、镜头和叙事分析。分析结果按媒体 SHA-256、分析器版本和提示词版本缓存，重复批次不得重复消耗 GPU。

### 6.4 去重

至少使用四层去重：

1. `platform + video_id`；
2. 来源 URL 规范化；
3. 媒体 SHA-256 / 感知哈希；
4. 标题、转写和视觉摘要 embedding 近重复。

同一视频在不同关键词、标签和排序中出现时，保留一个视频事实实体和多条查询观察记录。

## 7. 视频内容分析契约

新增 `video_content_analysis/v1`，至少包含：

```text
source_identity
  video_id / media_sha256 / source_url / rights_mode

media
  duration / width / height / fps / audio / file_size

text_evidence
  title / caption / hashtags / transcript_segments / ocr_segments

semantic_content
  topics / user_questions / intents / entities / claims / uncertainties

narrative
  hook / setup / conflict / escalation / proof / payoff / reversal / cta

presentation
  format / speaker_mode / scene_type / shot_count / avg_shot_seconds
  subtitle_density / visible_evidence / camera_style / color_style
  music_and_voice / editing_rhythm

retention
  first_3_seconds / first_5_seconds / suspense_devices / payoff_timing

generation_fit
  recommended_workflow / required_assets / difficulty / estimated_cost

risk
  copyright / privacy / legal_claim / sensitive_expression / uncertainty

provenance
  analyzer_id / analyzer_version / prompt_version / evidence_paths / created_at
```

现有 `analyze_video_frames_qwen.py`、`transcribe_video_local.py`、镜头/字幕对齐脚本作为第一版实现，由一个新的 `ContentAnalysisOrchestrator` 统一调用。

## 8. 关键词与内容相关度

相关度必须针对账号画像计算，而不是全局计算一次。

建议初始分解：

```text
keyword_relevance =
  40% transcript_semantic
  + 25% title_hashtag_semantic
  + 20% visual_ocr_semantic
  + 15% audience_intent_match
```

每一项必须保存：

- 分数；
- 命中的证据片段；
- 未命中或冲突的证据；
- 模型和 embedding 版本；
- 账号策略版本。

增加硬过滤规则：

- 命中账号排除词；
- 地域、业务范围或推广标的不匹配；
- 只有标签相同但实际内容无关；
- 不能验证来源或无法合法处理媒体；
- 内容风险超过账号策略阈值。

## 9. 时间维度

### 9.1 两种时间线

必须分开处理：

1. 来源样本时间线：判断领域当前正在增长、持续还是衰退；
2. 自有发布视频时间线：判断账号采用某个主题和展示方式后的真实表现。

### 9.2 来源视频和标签族复采

建议默认计划：

| 对象 | 建议复采 |
|---|---|
| 新发现高位视频 | T0、+2h、+6h、+24h、+72h |
| 稳定高位视频 | 每24h，连续7天 |
| 标签族排行 | 热点期每6h；普通期每天 |
| 关键词领域基线 | 每天固定时段，连续至少28天 |

页面字段含义不明确时，只能在相同 `metric_kind + 页面类型 + 排序` 内比较，不能把 `displayed_unknown` 直接当成播放量。

### 9.3 时间特征

新增：

- `age_hours`：距来源发布时间的小时数；
- `metric_velocity`：相同口径指标的单位时间增量；
- `rank_velocity`：排名变化速度；
- `acceleration`：增长速度是否继续提高；
- `persistence`：跨时间窗口保持高位的能力；
- `half_life`：热度衰减速度；
- `freshness`：对账号发布窗口的剩余价值；
- `seasonality`：星期、小时、节假日和事件周期；
- `family_momentum`：标签族整体增长，而不是单条视频增长；
- `novelty_pressure`：同主题高相似视频增长带来的拥挤度。

每张机会卡必须有 `valid_from`、`expires_at` 和推荐发布时间窗，避免把过期热点继续推荐。

## 10. 用户反馈模型

“用户反馈”分两类，权限和用途不同：

### 10.1 公开样本反馈

优先使用页面公开聚合指标：点赞、评论数、分享数、收藏数或无法确定语义的展示字段。公开评论文本只有在授权范围允许时才采集，并且只保存去标识化的主题、问题和情绪聚合，不保存用户画像。

### 10.2 自有账号反馈

复用现有创作者视频同步和评论能力，关联 `account_uuid + opportunity_id + script_id + workflow_profile`。需要分析：

- 播放增速、完播率（可取得时）、互动率；
- 评论问题、咨询意图、反对意见和重复疑问；
- 法律号的咨询主题和地域/服务需求，不做自动法律结论；
- 小说号的书名询问、求后续、情绪反馈和阅读意图；
- 钩子、展示形式、时长、发布时间和工作流方案的相对表现。

反馈学习只比较相同账号、相近生命周期和相近曝光窗口，不能直接用累计播放量比较新旧视频。

## 11. 当前内容机会评分

先执行硬门禁，再执行软排序。

### 11.1 硬门禁

- 账号业务范围和受众匹配；
- 媒体处理权限有效；
- 法律事实或小说推广标的具备可验证来源；
- 风险未超过阈值；
- 证据覆盖达到最低要求；
- 不是高相似复制方案。

### 11.2 初始软评分

```text
opportunity_score =
  20% temporal_momentum
  + 20% account_keyword_relevance
  + 15% audience_feedback_signal
  + 10% tag_family_evidence
  + 10% presentation_pattern_performance
  + 10% account_historical_fit
  + 10% production_feasibility
  + 5% novelty
  - compliance_penalty
  - saturation_penalty
  - staleness_penalty
```

权重属于 `strategy_version`，法律号和小说号可以不同。任何总分必须同时展示分项、样本量、时间窗和证据链接。

## 12. 内容机会卡与剧本契约

### 12.1 `ContentOpportunity`

至少包含：

- `opportunity_id`、`account_uuid`、`strategy_version`；
- 主题、目标人群和用户问题；
- 当前机会分及分项；
- `valid_from`、`expires_at`、推荐发布时间；
- 标签族、代表视频和时间序列证据；
- 高表现内容结构和展示形式；
- 饱和内容、常见套路和差异化空间；
- 推荐时长、开头、回报点、CTA；
- 推荐工作流及制作难度；
- 风险、事实核验和版权边界；
- 状态：`draft / approved / rejected / expired / used`。

### 12.2 `ScriptBrief`

剧本模型不直接读取一条热门视频完整文案，而读取机会卡中的聚合结构和授权事实：

```text
账号人设与业务目标
+ 当前用户问题
+ 多视频共性结构
+ 高表现展示方式
+ 应避免的饱和表达
+ 授权事实/章节材料
+ 时长与工作流约束
+ 合规规则
→ 生成原创 ScriptBrief
```

法律剧本必须把“热点关注点”和“权威法律事实”分开引用；小说剧本必须使用目标推广小说的授权章节或任务材料，不能使用热门样本剧情替代目标小说内容。

### 12.3 剧本版本与实验

同一机会可以生成多个可归因版本：

- 钩子 A/B；
- 展示形式 A/B；
- 15秒/30秒时长；
- 律师口播/场景短剧；
- 小说剧情解说/悬念钩子。

发布记录必须保存 `opportunity_id`、`script_id`、`script_version`、`format_id`、`hook_id` 和工作流方案。

## 13. 工作流节点升级

现有工作流注册表需要把“运营研究”加入视频生产前半段：

| 阶段 | 统一输入 → 输出 | 首批实现 |
|---|---|---|
| `account_profile` | account key → `account_profile/v1` | SQLite/JSON兼容读取 |
| `query_planning` | profile → `query_plan/v1` | 法律策略、小说策略 |
| `trend_collection` | query plan → `trend_observations/v2` | 原生页面、人工导入、许可数据源 |
| `media_acquisition` | candidates → `media_artifacts/v1` | metadata-only、授权下载、本地导入 |
| `content_analysis` | media → `video_content_analysis/v1` | Qwen+Paraformer、轻量文本 |
| `semantic_relevance` | profile+analysis → `relevance_evidence/v1` | 本地 embedding、规则兜底 |
| `temporal_model` | snapshots → `temporal_signal/v1` | 速度/排名/半衰期模型 |
| `feedback_analysis` | own metrics/comments → `feedback_signal/v1` | 账号反馈聚合 |
| `opportunity_ranking` | all signals → `content_opportunity/v1` | 可解释规则模型 |
| `script_planning` | opportunity → `script_brief/v1` | 法律、小说策略 |
| `script_generation` | brief → `script_artifact/v1` | 现有 LLM Provider |
| `compliance_gate` | script+evidence → decision | 法律/小说领域门禁 |

所有实现继续使用现有 `NodeExecutionRequest/NodeExecutionResult` 信封，提供健康检查、版本、错误码、重试语义和来源元数据。网页允许按账号方案人工切换实现，新任务读取快照，运行中的任务不受切换影响。

如果后续确认 `apachong` 或外部自动化里存在稳定的 `collectDouyinKeywords`，应作为 `trend_collection` 或 `media_acquisition` 的适配器接入，而不是把 PHP/JS 参数直接写入业务服务。

## 14. 数据模型升级

### 14.1 账号与策略

- `douyin_accounts`：稳定账号主数据；
- `account_strategy_versions`：不可变策略快照；
- `account_query_plans`：每批研究使用的查询计划；
- `account_workflow_profiles`：账号默认和实验工作流方案。

### 14.2 来源视频与内容分析

- 扩展 `trend_items`：`published_at`、`duration_seconds`、`author_id_hash`、`content_hash`；
- 扩展 `trend_observations`：`metric_kind`、`metric_quality`、`page_type`、`parser_version`；
- `source_media_assets`：权限模式、文件哈希、保留期限、分析状态；
- `source_video_analyses`：结构化内容分析和版本；
- `source_video_embeddings`：标题、转写、视觉摘要 embedding；
- `source_video_metric_snapshots`：来源视频多时点页面指标；
- `topic_families`、`topic_family_versions`、`topic_family_members`；
- `topic_family_snapshots`：标签族时间序列。

### 14.3 机会、剧本与反馈

- `content_opportunities`；
- `opportunity_evidence`；
- `script_briefs`；
- `script_versions`；
- 扩展 `published_content_context`：`account_uuid`、`opportunity_id`、`format_id`、`hook_id`、`publish_window_id`；
- `audience_feedback_aggregates`；
- `strategy_evaluation_runs`：保存一次策略评估的输入版本和结果。

趋势库和现有 `douyin.db` 可以继续物理隔离，但跨库只使用稳定 UUID，不建立跨库外键。`douyin.db.videos.account_key` 迁移到稳定 `account_uuid` 时保留兼容映射。

## 15. 代码目录升级方向

```text
src/
  operations_accounts/
    models.py
    repository.py
    service.py

  trend_intelligence/
    query_planning.py
    candidate_selection.py
    content_pipeline.py
    relevance.py
    temporal.py
    opportunity.py
    feedback.py
    domain/
      base.py
      registry.py
      legal.py
      novel.py
    providers/
      douyin_web.py
      manual_import.py
      licensed_feed.py
      apachong_adapter.py       # 仅在接口确认后加入

  content_analysis/
    contracts.py
    orchestrator.py
    qwen_paraformer.py
    lightweight_text.py

  workflow/
    contracts.py
    catalog.py                  # 注册新增运营研究节点
```

现有模块复用关系：

- `DouyinWebTrendProvider`：继续负责授权页面可见样本；
- `tag_graph.py`：升级为稳定标签族版本和时间快照；
- `CollectionJob`/Checkpoint/PageBudget：接管长批次采集；
- 本地 Qwen/Paraformer 脚本：封装为内容分析 Provider；
- `TrendAnalyzer`：拆成相关度、时间、机会三个可独立测试的评分器；
- `OperationsFeedbackService`：从只按 cluster 聚合升级为多维归因；
- `AutoPublishService`：继续记录发布关联，但补齐账号、机会和实验维度；
- `fanqie_promotion.py`：提供小说推广任务和授权章节，不负责趋势评分。

## 16. 管理页面升级

### 16.1 账号策略

- 选择账号；
- 查看业务目标、受众、领域、地域、关键词、排除词和 CTA；
- 创建策略新版本；
- 选择默认工作流方案；
- 法律和小说展示不同配置项。

### 16.2 领域研究

- 显示查询计划、采集进度、标签族图和分析覆盖率；
- 区分元数据样本、可分析媒体、已完成内容分析样本；
- 显示时间趋势和证据质量；
- 支持人工调整标签族和候选视频。

### 16.3 当前机会

- 按账号展示“现在建议做什么”；
- 显示为什么现在做、有效期和发布窗口；
- 展示推荐形式、时长、钩子、结构和工作流；
- 展示反例、饱和度、风险和证据；
- 支持批准、拒绝、延后和创建 A/B 剧本。

### 16.4 发布复盘

- 账号基线；
- 话题、钩子、形式、时长、发布时间和工作流归因；
- 评论问题和咨询/阅读意图；
- 机会判断与实际结果偏差；
- 下一轮策略修改建议。

## 17. 实施阶段

### P0：账号主键与契约

1. 建立 `douyin_accounts`、`account_strategy_versions` 和领域策略注册表；
2. 导入 `WarmupAccount` 非敏感元数据；
3. 给趋势、发布和番茄任务补稳定 `account_uuid`；
4. 定义内容分析、相关度、时间信号和机会卡协议；
5. 在工作流注册表加入新阶段，但首批可先标记 `PROFILE_ONLY`。

验收：法律号和小说号使用同一套框架、不同策略版本，数据不会串账号；增加一个测试用第三领域策略时，不需要修改核心服务、数据库核心表或工作流端口。

### P1：可恢复的大规模元数据与时间快照

1. 将页面采集接入 `CollectionJob` 和 Checkpoint；
2. 增加来源发布时间、指标口径和解析证据；
3. 建立来源视频和标签族的复采计划；
4. 增加候选筛选、内容多样性和跨批去重；
5. 页面展示批次进度、覆盖率和停止原因。

验收：同一查询计划能够分批恢复，能够区分一次样本与真实时间趋势。

实现说明：P1 使用领域策略生成受限批次，数据库记录计划与批次执行上下文；
跨批 `item_id` 去重后，视频和标签族按最近 14 天计算指标速度、排名改善、
发布新鲜度、观察覆盖率和置信度。页面展示指标无法确认是播放还是点赞时，
继续保留 `displayed_unknown`，不会伪装成官方播放量。

### P2：内容分析与账号相关度

1. 封装 Qwen+Paraformer 内容分析 Provider；
2. 增加媒体权限模式和分析缓存；
3. 建立法律/小说内容结构分类；
4. 实现账号级语义相关度和证据片段；
5. 增加展示方式、钩子、节奏和生成可行性分析。

验收：高流量候选都有结构化内容证据，系统能解释其与某个账号为何相关或无关。

实现说明：本地媒体只有在请求显式声明 `local_media_authorized` 时才能进入
Qwen + Paraformer 工具链；否则使用元数据降级实现。两种实现返回完全相同的
`VideoContentAnalysis` 契约，网页可以人工切换。模型失败或媒体缺失时可按配置
降级，但结果会标记 `degraded` 并列出不确定项，不能伪装成已观看完整视频。

### P3：机会排行与原创剧本

1. 实现时间、反馈、饱和度和生产可行性评分；
2. 生成带有效期的 ContentOpportunity；
3. 法律、小说分别生成 ScriptBrief；
4. 接入人工审批和 A/B 剧本；
5. 推荐并锁定工作流方案快照。

验收：系统输出的是“当前账号现在最适合做的视频方案”，而不是通用热门标题。

实现说明：机会分保留完整分项，不把 `displayed_unknown` 当成官方播放量；
多时间点不足时使用 7 天样本有效期，有可靠动量时使用 48 小时有效期。
法律脚本强制权威来源与逐句事实核验，小说脚本强制绑定授权章节，二者均输出
A/B 两版和三段 5 秒节拍，可由页面人工批准后进入制作。

### P4：发布反馈学习

1. 补齐 1h/6h/24h/72h/7d 同步计划；
2. 分析自有评论主题和意图；
3. 按账号、话题、钩子、形式、时长、时间和工作流归因；
4. 形成策略版本评估；
5. 人工确认后发布下一版策略，不自动覆盖生产策略。

验收：至少三个完整发布周期后，下一轮机会排行能够引用账号自身表现证据。

## 18. 测试与验收基线

### 18.1 单元与契约测试

- 同一工作流阶段的不同实现端口完全一致；
- 法律和小说策略对同一输入给出不同、可解释的账号匹配结果；
- 测试用第三领域策略可以只通过注册表接入并完成端到端契约测试；
- 领域配置不符合对应 JSON Schema 时不能激活策略版本；
- 时间分数不会把单次快照解释为趋势；
- 不同 `metric_kind` 不混算；
- 未授权媒体不会进入下载和 ASR；
- 同一媒体哈希不会重复分析；
- 机会卡分数能重算并得到相同结果；
- 过期机会不能直接进入新发布任务。

### 18.2 集成测试

- 账号策略 → 查询计划 → 模拟采集 → 标签族 → 内容分析 → 机会卡；
- 机会批准 → 剧本 → 生成 → 发布关联 → 指标快照 → 反馈；
- 任务中断后从 checkpoint 恢复并重新校验授权；
- 账号 A 的样本、机会和反馈不会进入账号 B 的策略评估；
- 法律事实源缺失时阻断法律剧本，小说授权章节缺失时阻断小说推广剧本。

### 18.3 数据质量指标

- 视频 ID 去重率；
- 直达视频证据覆盖率；
- 发布时间覆盖率；
- 指标口径已知率；
- 高流量候选媒体可分析率；
- ASR/OCR/视觉分析成功率；
- 机会卡证据覆盖率；
- 发布关联和快照覆盖率；
- 推荐过期率和人工拒绝原因。

### 18.4 负载测试

真实网页访问量始终受授权策略和页面预算控制。工程负载测试使用离线回放数据验证：

- 10,000 条观察记录的去重、标签族和候选筛选；
- 1,000 个视频的时间序列特征计算；
- 多账号并行分析但严格隔离；
- GPU 内容分析队列的缓存、失败恢复和显存串行约束。

## 19. 明确不做的事

- 不把抖音页面样本描述为官方全量热榜；
- 不把不明确的页面数字直接称为播放量；
- 不绕过登录、验证码、频率限制或权限；
- 不默认批量下载和复刻第三方视频；
- 不保存评论用户画像作为运营资产；
- 不因为热门视频流量高就复制其完整文案、镜头和独特表达；
- 不让未经人工批准的新策略直接覆盖生产账号；
- 不让热门样本代替法律事实源或小说授权内容。

## 20. 第一轮开发建议

第一轮不要从新的推荐算法或页面样式开始，应先完成以下可验证主链：

```text
统一 AccountProfile
→ 法律/小说两个 DomainStrategy
→ ContentAnalysis 契约和本地实现
→ account_uuid 贯穿趋势、机会、剧本、发布和反馈
→ 两批以上时间快照
→ 第一版可解释 ContentOpportunity
```

这条主链完成后，大规模采集、更多模型实现和页面切换才能围绕稳定数据协议扩展，而不会再次形成相互独立的脚本和数据库。
