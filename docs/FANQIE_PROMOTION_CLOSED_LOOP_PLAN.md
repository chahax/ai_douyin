---
doc_status: current
doc_category: mainline
last_reviewed: 2026-08-09
topic: 番茄推书任务数据库闭环与可审计交付推进计划
---

# 番茄推书任务闭环推进计划

## 当前实现状态（2026-08-09）

P0-B 实现代码存在于分支 `codex/fanqie-closed-loop-p0`，尚未提交。独立聚焦验证结果如下：

| 项目 | 状态 |
|---|---|
| 分支 | `codex/fanqie-closed-loop-p0`（未提交） |
| Alembic 头 | `0008_fanqie_closed_loop_p0` |
| 迁移验证 | 从 `5cb67ecb2df3` 重建隔离库成功升级；`fanqie_bindings` 及 partial unique indexes 已创建；现有 20 行 `fanqie_batch_books` 保留；新建闭环表干净 |
| 已实现组件 | models、repositories、state machine、import、reconcile、query/event 支持、Douyin 旧库 account-aware 迁移/repository/sync 校验、旧 CLI write-through（兼容路径，同步写 DB） |
| 推广列表解析 | 现网使用 `/page/promotion-list?tab_type=2&top_tab_genre=-1`，按观察到的 11 列中文表头驱动解析 |
| 测试 | **151 通过**，仅 3 条 deprecation warning；CLI `--help`、task list、旧迁移 false/head true 探针、diff 检查均通过 |
| P0-A 结论 | **`partially_verified`**：观察页面 4 行（3 强制失效、1 不通过），均未填写，无可点击回填入口；无授权 active 任务 + 真实抖音 URL 完成的回填提交 |
| P0-B 代码 | **review-ready / accepted as a candidate**；但 P0 整体验收 **未达成** |
| P3 绑定自动化 | **阻塞**于外部 P0-A 门禁 |
| 未完成 | 未执行 P1 视频生成冒烟测试，未执行 P3 真实发布/回填 |

旧命令（`fanqie-book-fetch`、`fanqie-promo-apply`、`fanqie-promo-list`）是兼容路径：执行时通过 DB write-through 同步数据库和事件，并打印弃用提示指向 `fanqie-task-*` 目标命令。P0-A 探针（`fanqie-task-p0a-probe`）是只读探针，不写入任何数据，结论固定为 `partially_verified`。

## 1. 文档目标

本计划把一条番茄小说推广任务推进为可查询、可恢复、可审核的完整业务闭环：

```text
选书 → 抓取素材 → 申请推广 → 生成脚本 → 生成视频
→ 机器质检 → 人工审核 → 抖音发布 → 同步作品 ID
→ 番茄回填 → 效果监控与复盘
```

完成标志不是“视频已经生成”或“抖音已经发布”，而是对应抖音作品 URL 已成功回填到正确的番茄推广任务，并且全过程的数据库状态和审计产物可以追溯。

第一阶段采用人工审核式闭环。验证码、短信、安全验证和平台异常进入人工处理状态，不尝试绕过平台安全机制。

## 2. 当前基线

截至 2026-08-09，已经具备：

- 番茄达人中心登录态保存、推广申请、推广列表扫描和审核状态同步。
- 小说搜索、章节抓取、本地素材包和批量抓取队列。
- `fanqie_batch_books` 数据表及 Alembic 迁移。
- 推广脚本和 Presenter 视频生成入口。
- 抖音视频发布及发布后同步作品 ID 的基础能力。

当前缺口：

- 书籍、推广任务、脚本版本、视频任务、审核、发布和回填尚未形成规范化数据库关系。
- 推广任务仍主要保存在 `task.json`，书籍正文和元数据主要保存在文件目录。
- 尚无 `fanqie-bind-douyin-video` 正式回填入口。
- 没有完整的端到端验收记录，无法从一条数据库任务追溯到最终番茄回填结果。
- 投放效果、转化和收益数据尚未形成每日快照。

### 2.1 开工前风险门禁

以下风险不允许推迟到对应后期阶段才验证：

| 风险 | 提前措施 | 阻塞条件 |
|---|---|---|
| 番茄回填从未验证 | P0-A 在人工监督下手动完成一次“回填发文”可行性试验，记录入口、字段、限制、页面响应和脱敏截图 | 无法确认存在合法可操作的回填入口时，P3 不得按现设计开工 |
| 文件和数据库继续分裂 | P0 不只导入旧文件，还必须让现有写命令同步落库，并提供差异巡检 | 新操作仍只写 JSON 时，P0 不得验收 |
| 人工中断堆积 | P1 开始即提供 attention list/看板、原因分类、下一动作和责任人 | 人工任务只能从日志发现时，P1 不得验收 |
| 批量与单本抓取分叉 | 两个入口统一调用同一书籍解析和素材服务，统一主记录及目录规则 | 同一本书能生成两套活跃素材目录时，P1 不得验收 |

P0-A 回填试验是可行性验证，不要求先完成正式自动化。必须由操作人使用一条明确授权的测试/真实任务手动执行；在未获得合适任务和作品 URL 前，只完成页面入口与字段调研，不制造虚假回填结果。

## 3. 核心业务规则

1. 一本小说可以关联多个推广任务或推广别名。
2. 一个推广任务可以生成多个脚本版本和视频候选。
3. 每次生成、审核、发布和回填都是独立操作记录，禁止覆盖历史。
4. 一个视频候选必须明确关联脚本版本、小说、推广任务和生成参数。
5. 只有机器门禁完成且人工审核通过的视频才能发布。
6. 一条抖音作品原则上只能绑定一个番茄推广任务。
7. 抖音发布成功不等于推广任务完成；番茄回填成功才进入 `bound`。
8. 小说正文、音频、图片、视频和截图放文件系统；数据库保存元数据、路径、哈希和关系。
9. 外部页面操作必须保存时间、结果摘要；关键操作保存截图或响应快照。
10. 自动重试必须有上限，平台验证和数据歧义进入 `manual_intervention`。

## 4. 业务流程与状态

### 4.1 选书入池

从番茄达人中心按榜单、频道、连载状态、字数和更新时间获取候选小说。确认选择后建立小说主记录和推广任务。

```text
candidate → selected
```

必须记录来源榜单、筛选条件、选择原因、操作人和入池时间。同一 `fanqie_book_id` 不重复建书籍主记录。

### 4.2 素材抓取

```text
selected → fetching → material_ready
                    ├→ fetch_failed
                    └→ manual_intervention
```

产物包括 `meta.json`、章节正文、`material.txt` 和 `fetch_report.json`。报告记录计划/实际章节数、付费墙、耗时、错误、内容哈希和抓取版本。

### 4.3 推广申请和审核同步

```text
material_ready → applying → under_review → active
                          ├→ rejected
                          └→ expired
```

保存推广别名、发布类型、申请时间、有效期、审核状态、拒绝原因和平台结果快照。只有 `active` 任务允许最终发布和回填。

旧 `task.json.apply_status` 只作为兼容输入，P0 统一映射到新状态机：

| 旧状态 | 新状态/处理 |
|---|---|
| `started` | `applying` |
| `submitted`、`pending_review`、`under_review` | `under_review` |
| `active` | `active` |
| `rejected` | `rejected` |
| `expired` | `expired` |
| `alias_taken` | 保持 `applying`，追加可重试的别名冲突事件 |
| `failed` | `application_failed` |
| `needs_manual_check` | `manual_intervention` |
| `manual_or_skipped`、未知值 | 不自动推进，进入 `manual_intervention` |

旧文件中的 `valid_range` 必须解析为每条任务自己的 `valid_from`/`valid_until`。`2026-06-29 ~ 2026-12-26` 只是历史任务的观测样例，不得编码成全局硬截止日期；解析失败时进入人工确认。

### 4.4 脚本生产

```text
material_ready/active → scripting → script_review → script_approved
                                               ├→ script_rejected
                                               └→ revision_required
```

每个脚本版本保存章节范围、钩子、正文、标题、简介、话题、CTA、目标受众、剧透级别、模型、提示词版本和参数。人工审核重点检查事实、剧透、虚假宣传和合规表达。

### 4.5 视频生成与质检

```text
queued → generating → quality_check → review_required
                   ├→ generation_failed
                   └→ quality_failed
```

每次生成建立独立 `video_job`。通过视频质量、风格、灯光、平滑度、音画、字幕安全区等门禁后才进入人工审核。

### 4.6 人工审核

审核结果只能是：

- `approved`
- `rejected`
- `revision_required`
- `approved_with_override`

审核记录必须包含审核人、时间、意见、问题分类、机器报告路径，以及覆盖机器门禁时的理由。批准记录保存被批准文件的 SHA-256，防止审核后文件被替换。

### 4.7 抖音发布与作品同步

```text
approved → publish_queued → publishing → publish_pending_sync → published
                                   └→ publish_failed
```

发布前冻结视频、标题、描述、话题、推广别名和审核结果。发布瞬间无法取得作品 ID 时先保存本地发布 UUID，随后通过 `douyin-sync` 补齐 `video_id` 和作品 URL。

匹配至少综合本地发布 UUID、账号、标题、发布时间窗口和视频哈希；出现多个候选时禁止自动绑定，进入人工处理。

### 4.8 番茄回填

```text
published → binding → bound
                    ├→ binding_failed
                    └→ manual_intervention
```

回填前校验推广任务仍为 `active`、别名未过期、抖音作品属于指定账号、小说和任务一致、URL 未被其他任务使用。保存回填时间、页面结果、截图、尝试次数和操作人。

### 4.9 数据监控

```text
bound → monitoring → completed
                   ├→ stopped
                   └→ expired
```

按日保存播放、点赞、评论、分享及实际可获得的番茄点击、转化、收益数据。每日写新快照，不覆盖历史累计值。

状态触发条件：

- `bound → monitoring`：第一次绑定成功后自动进入。
- `monitoring → completed`：推广有效期结束并经过默认 7 天数据归集窗口，或操作人确认结项；不以收益达标为必要条件。
- `monitoring → stopped`：操作人主动停止、账号/作品被禁用，或合规要求停止；必须填写原因。
- `active/... → expired`：任务在成功绑定前推广有效期已经结束。
- 已绑定任务到期不改成 `expired`，而是在归集窗口后进入 `completed`，保留曾成功绑定的事实。

P4 数据来源分级：

1. 优先使用项目已有的抖音创作者后台同步能力或平台明确提供的接口。
2. 番茄侧没有正式 API 时，通过已登录达人中心页面读取，保存原始响应/页面快照并标注 `source=browser`。
3. 页面无法稳定获取时允许人工 CSV/JSON 导入，标注 `source=manual_import` 和操作人。
4. 缺失字段保存为 `NULL`，禁止用估算值冒充平台指标。
5. P4 开发前先做字段可得性调研；不可得指标不阻塞 P3 闭环验收。

## 5. 数据库设计

沿用 SQLAlchemy + Alembic。**当前目标数据库明确为 SQLite**（`DATABASE_URL=sqlite:///./data/wisdom_ai.db`），P0 不同时兼容 PostgreSQL/MySQL。建议所有业务表使用自增内部主键，同时为业务对象增加稳定 UUID。时间统一以 UTC 入库，展示时转换为本地时区。

SQLite 实施约束：

- 启用 `PRAGMA foreign_keys=ON`。
- Alembic 使用 batch mode 处理 SQLite 改表限制。
- 条件唯一规则使用 SQLite partial unique index，同时在服务层做相同校验。
- 不依赖 `SELECT FOR UPDATE SKIP LOCKED` 保证并发正确性；使用原子条件更新和乐观锁。
- 将来迁移 PostgreSQL 时单独开展兼容阶段，不在 P0 隐含承诺跨库行为。

当前项目还存在两套持久化：SQLAlchemy 主库 `data/wisdom_ai.db` 和抖音旧服务使用的 `data/douyin.db`。SQLite 不能建立跨数据库外键，因此 P0 决策如下：

- 本文新增的番茄闭环表和 `douyin_accounts` 全部进入 `wisdom_ai.db`。
- `fanqie_publish_records` 保存抖音 `video_id`、URL 和发布快照，不对 `douyin.db` 的 `videos` 表声明外键。
- `douyin.db.videos` 增加 `account_key`；账号感知的 `douyin-sync --account-id` 按 `(account_key, video_id)` 保存和查询作品。没有账号上下文的旧记录不能自动关联番茄任务。
- `DouyinLegacyVideoRepository` 只读查询 `douyin.db`；`NovelPromotionPublishSyncService`（位于 `src/novel_promotion/publish_service.py`）是唯一可以补齐 `fanqie_publish_records.douyin_video_id` 的业务服务。
- `fanqie-task-sync-douyin` 先调用账号感知的底层同步，再调用 `NovelPromotionPublishSyncService` 校验账号、作品ID、发布时间窗口和本地发布记录；通用 `douyin-sync` 不直接修改番茄闭环表。
- 校验成功和失败都追加同步事件。作品存在但账号不匹配、旧记录缺少账号、或出现多个候选时进入 `manual_intervention`。
- 合并两套数据库属于后续独立迁移项目，不阻塞 P0–P3；在合并完成前必须有跨库一致性测试。

### 5.1 `fanqie_books`

小说主数据，一本番茄小说一条记录。

| 字段 | 说明 |
|---|---|
| `id` | 内部主键 |
| `book_uuid` | 本地稳定 UUID，唯一 |
| `fanqie_book_id` | 番茄书籍 ID，唯一 |
| `book_name`、`author` | 基本信息 |
| `abstract`、`categories_json`、`tags_json` | 内容信息 |
| `serial_status`、`word_count` | 连载和字数信息 |
| `source_ranking`、`selection_filters_json` | 选书来源 |
| `selection_reason`、`selected_by` | 选择依据 |
| `material_status` | 素材状态 |
| `material_root`、`material_hash` | 素材目录及版本哈希 |
| `created_at`、`updated_at` | 时间 |

约束：`fanqie_book_id` 唯一；未知书 ID 时允许暂存，但在进入推广申请前必须补齐。

`fanqie_book_id` 的规范格式为纯数字字符串，P0 暂定校验表达式 `^[0-9]{10,24}$`。输入为 URL 时只解析明确的 `book_id` 查询参数或番茄书籍路径；存在多个候选、非数字内容或无法确认来源时不得自动转换。

### 5.2 `fanqie_chapters`

章节元数据。正文继续保存在文件系统。

| 字段 | 说明 |
|---|---|
| `id`、`book_id` | 主键及书籍外键 |
| `chapter_index`、`chapter_title` | 章节序号和标题 |
| `source_url`、`content_path` | 来源与正文路径 |
| `content_hash`、`char_count` | 内容校验 |
| `is_paywalled`、`fetched_at` | 抓取结果 |

唯一约束：`(book_id, chapter_index)`。

### 5.3 `fanqie_promotion_tasks`

闭环主表。页面展示和 API 查询以此为入口。

| 字段 | 说明 |
|---|---|
| `id`、`task_uuid` | 主键及稳定业务 UUID |
| `book_id` | 小说外键 |
| `platform_task_id` | 番茄侧任务标识，可空 |
| `promotion_alias` | 推广别名 |
| `publish_type` | 发布类型 |
| `status`、`failure_stage` | 主状态和失败阶段 |
| `version` | 乐观锁版本号，默认 1 |
| `valid_from`、`valid_until` | 有效期 |
| `application_snapshot_path` | 申请结果快照 |
| `last_error`、`manual_reason` | 错误及人工处理原因 |
| `created_by`、`created_at`、`updated_at` | 审计字段 |

同一本书、同一推广别名在非终态任务中不得重复。SQLite 使用 partial unique index：

```sql
CREATE UNIQUE INDEX uq_fanqie_task_active_alias
ON fanqie_promotion_tasks(book_id, promotion_alias)
WHERE promotion_alias IS NOT NULL
  AND status NOT IN ('rejected', 'expired', 'completed', 'stopped', 'cancelled');
```

所有状态变化同时写事件表。

### 5.4 `fanqie_script_versions`

| 字段 | 说明 |
|---|---|
| `id`、`script_uuid`、`task_id` | 标识和推广任务外键 |
| `version`、`parent_script_id` | 版本和修订来源 |
| `chapter_range` | 使用的章节 |
| `hook`、`script_text`、`title`、`description` | 内容 |
| `hashtags_json`、`cta`、`spoiler_level` | 发布策略 |
| `model_name`、`prompt_version`、`generation_params_json` | 生成来源 |
| `status`、`content_hash` | 审核状态和哈希 |
| `created_at` | 时间 |

唯一约束：`(task_id, version)`。

### 5.5 `fanqie_video_jobs`

| 字段 | 说明 |
|---|---|
| `id`、`job_uuid` | 主键和稳定业务 UUID |
| `task_id` | `fanqie_promotion_tasks.id` 外键 |
| `script_id` | `fanqie_script_versions.id` 外键，非空 |
| `video_mode`、`quality_profile` | 生成模式和档位 |
| `status`、`failure_stage`、`error_message` | 状态 |
| `request_path`、`manifest_path`、`output_path` | 审计文件路径 |
| `quality_report_path`、`review_packet_path` | 验收产物 |
| `output_sha256` | 成片哈希 |
| `runtime_json`、`duration_ms`、`cost_json` | 环境、耗时和成本 |
| `started_at`、`finished_at` | 时间 |

### 5.6 `fanqie_reviews`

| 字段 | 说明 |
|---|---|
| `id`、`review_uuid`、`video_job_id` | 标识 |
| `decision` | 审核决定 |
| `reviewer`、`reviewed_at` | 审核人和时间 |
| `issues_json`、`comment` | 问题和意见 |
| `machine_gate_passed`、`override_reason` | 门禁和覆盖理由 |
| `approved_sha256` | 被批准文件哈希 |

### 5.7 `fanqie_publish_records`

| 字段 | 说明 |
|---|---|
| `id`、`publish_uuid`、`task_id`、`video_job_id` | 标识和关联 |
| `douyin_account_id` | `douyin_accounts.id` 外键 |
| `status` | 发布状态 |
| `title_snapshot`、`description_snapshot`、`hashtags_json` | 发布快照 |
| `douyin_video_id`、`douyin_video_url` | 同步后的作品信息 |
| `published_at`、`synced_at` | 时间 |
| `platform_response_path`、`last_error` | 审计和错误 |

约束：`douyin_video_id` 和 `douyin_video_url` 在非空时唯一。

### 5.7.1 `douyin_accounts`

多账号运营主数据表。现有 `data/douyin_warmup/accounts/<account_id>/` 继续保存浏览器 profile 和本地登录配置，P0 只导入其中的非敏感元数据。

| 字段 | 说明 |
|---|---|
| `id`、`account_uuid` | 主键和稳定 UUID |
| `account_key` | 当前 CLI 使用的 `account_id`，唯一 |
| `display_name`、`masked_login_name` | 展示信息，不保存完整手机号 |
| `status` | `active`、`paused`、`disabled` |
| `profile_dir` | 浏览器 profile 路径 |
| `platform_uid` | 可安全取得时保存的抖音账号 ID |
| `created_at`、`updated_at` | 时间 |

禁止在该表保存 Cookie、token、密码、短信验证码或 storage state 内容。

### 5.8 `fanqie_bindings`

| 字段 | 说明 |
|---|---|
| `id`、`binding_uuid`、`task_id`、`publish_id` | 标识和关联 |
| `status`、`attempt_count` | 回填状态和次数 |
| `submitted_url` | 实际提交的作品 URL |
| `response_snapshot_path`、`screenshot_path` | 平台证据 |
| `bound_at`、`last_attempt_at` | 时间 |
| `operator`、`last_error` | 操作人和错误 |

约束：一个 `publish_id` 只允许一个成功绑定；一个任务第一阶段只允许一个当前有效绑定。

### 5.9 `fanqie_operation_events`

追加写事件表，记录所有关键状态变化：

物理表名固定为 `fanqie_operation_events`；模型、迁移、测试和文档统一使用该拼写，不允许使用 `fanqie_operaion_events`。

| 字段 | 说明 |
|---|---|
| `id`、`event_uuid`、`task_id` | 标识 |
| `event_type`、`from_status`、`to_status` | 事件和状态变化 |
| `actor_type`、`actor_id` | 用户、Agent、调度器或系统 |
| `payload_json`、`artifact_path` | 事件数据和证据 |
| `created_at` | 时间 |

事件表只追加，不更新和删除业务历史。

### 5.10 `fanqie_performance_daily`

| 字段 | 说明 |
|---|---|
| `id`、`publish_id`、`snapshot_date` | 关联与日期 |
| `views`、`likes`、`comments`、`shares` | 抖音指标 |
| `completion_rate` | 可获得时保存 |
| `fanqie_clicks`、`conversions`、`revenue` | 番茄侧可获得指标 |
| `raw_snapshot_path`、`collected_at` | 原始数据和时间 |

唯一约束：`(publish_id, snapshot_date)`。

### 5.11 现有表处理

`fanqie_batch_books` 继续作为受控抓取队列，不承担书籍主数据、推广状态或发布关系。**P0 确定新增可空外键 `fanqie_book_pk` → `fanqie_books.id`**，不采用只把关系藏在事件 JSON 中的方案。

迁移顺序：

1. 创建 `fanqie_books`。
2. 给 `fanqie_batch_books` 增加可空 `fanqie_book_pk` 和普通索引。
3. 根据现有 `book_id` 回填主表和外键；无法确认书 ID 的记录保留空外键并生成导入问题报告。
4. 新抓取成功时，在同一服务事务中 upsert `fanqie_books` 并更新 `fanqie_book_pk`。
5. 该外键暂不设为非空，因为失败和未抓取队列天然还没有书籍主记录。

导入前必须先生成 `book_id` 格式报告，按 `valid_numeric`、`empty`、`parsed_from_url`、`invalid_format`、`ambiguous` 分类。当前数据库审计基线为 20 条记录，其中 16 条是有效纯数字 ID、4 条为空、0 条非空异常格式；该数字仅是 2026-08-09 快照，实施时必须重新扫描。

### 5.12 并发控制

`fanqie_promotion_tasks.version` 使用乐观锁。状态变更执行原子条件更新：

```sql
UPDATE fanqie_promotion_tasks
SET status = :new_status, version = version + 1, updated_at = :now
WHERE id = :task_id
  AND version = :expected_version
  AND status = :expected_status;
```

受影响行数为 0 说明任务已被其他操作人或 Worker 修改，当前操作必须重新加载，禁止静默覆盖。

同时采用三层保护：数据库唯一索引防重复、状态机防非法跳转、发布/回填命令使用幂等键。SQLite 本阶段只支持单机有限并发；任务领取使用原子 `UPDATE ... WHERE status='queued'`，不把现有 `SKIP LOCKED` 写法当作多进程安全保证。

### 5.13 发布后回填失败的补偿路径

抖音已经发布但番茄回填失败时，不自动删除作品，也不回滚已经发生的外部事实。发布记录进入 `published_unbound`，推广任务进入 `binding_failed` 或 `manual_intervention`，并产生高优先级告警。

允许的人工处置：

- `retry_binding`：修复登录态、URL 或页面问题后重试原任务。
- `rebind_task`：业务确认后改绑到正确且有效的推广任务，保留原失败记录。
- `keep_unbound`：保留作品，但明确标记“不计入番茄推广闭环”。
- `hide_or_delete_requested`：登记人工隐藏/删除请求及最终结果；系统第一阶段不自动删除抖音作品。

任何补偿操作都追加事件，不能把失败发布记录改写成“从未发生”。

## 6. 审计产物规范

推荐目录：

```text
data/fanqie_promotion/audit/<task_uuid>/
├── task_snapshot.json
├── selection/
│   └── source_snapshot.json
├── material/
│   ├── fetch_report.json
│   └── material_manifest.json
├── application/
│   ├── request.json
│   ├── response.json
│   └── screenshot.png
├── scripts/<script_uuid>/
│   ├── script.json
│   └── prompt_snapshot.json
├── videos/<job_uuid>/
│   ├── request.json
│   ├── manifest.json
│   ├── output.mp4
│   ├── quality_report.json
│   ├── review_packet/
│   └── generation.log
├── publish/<publish_uuid>/
│   ├── publish_snapshot.json
│   └── platform_response.json
└── binding/<binding_uuid>/
    ├── request.json
    ├── response.json
    └── screenshot.png
```

JSON 至少包含 `schema_version`、业务 UUID、生成时间和关联文件 SHA-256。审计产物不存 Cookie、token、短信验证码或其他认证秘密。

## 7. 服务和命令边界

建议新增正式服务包 `src/novel_promotion/`，逐步把浏览器细节从业务编排中拆出：

```text
src/novel_promotion/
├── models.py
├── repositories.py
├── state_machine.py
├── task_service.py
├── artifact_store.py
├── script_service.py
├── video_service.py
├── publish_service.py
└── binding_service.py
```

第一阶段应具备的命令：

```text
fanqie-task-create
fanqie-task-show
fanqie-task-list
fanqie-task-fetch-material
fanqie-task-apply
fanqie-task-sync-status
fanqie-task-generate-script
fanqie-task-generate-video
fanqie-task-review
fanqie-task-publish
fanqie-task-sync-douyin
fanqie-task-bind
fanqie-task-audit
```

`fanqie-task-*` 是目标公开入口，旧 `fanqie-*` 是过渡兼容层；两者必须调用同一组 Service，禁止维护两套业务实现。

迁移和弃用规则：

| 旧命令 | 目标命令 | 过渡策略 |
|---|---|---|
| `fanqie-book-fetch` | `fanqie-task-fetch-material` | P0 接入同一 Service 并输出弃用提示 |
| `fanqie-promo-apply` | `fanqie-task-apply` | P0 接入数据库和事件；P1 文档改用新命令 |
| `fanqie-promo-list` | `fanqie-task-sync-status` | P0 兼容旧状态映射 |
| `fanqie-promo-video` | `fanqie-task-generate-video` | P1 冒烟通过后由新命令接管 |
| `douyin-publish` | `fanqie-task-publish` | 底层能力保留，番茄任务必须走新入口 |
| 规划中的 `fanqie-bind-douyin-video` | `fanqie-task-bind` | 不再新增旧命令实现，直接实现新入口 |

P0：旧命令仍可运行，但必须同步数据库并打印目标命令。P1：文档、Agent Skill 和人工操作统一使用新命令。P3 验收后：旧写命令默认拒绝作为独立番茄闭环入口，仅保留显式 `--legacy-compat` 的维护窗口；移除时间在P3验收记录中确定。

## 8. 开发与审核机制

### 8.1 开发方式

按 P0–P4 纵向切片开发，每个切片必须同时包含数据库、服务、命令、审计和测试，不先堆完所有表再补业务逻辑。

代码职责：

- `models.py` 只定义持久化模型和约束。
- `repositories.py` 封装查询、幂等写入和乐观锁更新。
- `state_machine.py` 是状态转换的唯一规则来源。
- `task_service.py` 负责事务边界和事件追加。
- 平台适配器只负责页面/API 交互，不直接决定业务状态，不直接跨多表提交。
- `artifact_store.py` 负责路径、manifest、哈希和敏感字段过滤。

每个开发单元按以下顺序推进：

1. 写状态转换、数据库约束和失败语义。
2. 写迁移及升级/降级测试。
3. 写 repository/service 单元测试，再实现代码。
4. 接入现有番茄或抖音适配器。
5. 用脱敏夹具跑集成测试。
6. 人工复核审计包后才允许进入下一阶段。

### 8.2 数据库变更审核

每个 Alembic revision 必须单独审核：

- `upgrade`、`downgrade` 均可执行。
- 迁移前自动备份 SQLite 文件，并记录备份路径和 SHA-256。
- 旧 JSON 导入先运行 `dry-run`，输出新增、更新、冲突、跳过和失败数量。
- 禁止在无法唯一匹配时自动合并书籍、推广任务或抖音作品。
- 外键、唯一索引、partial index 和查询索引必须有测试。
- 导入工具重复执行结果一致，证明幂等。

### 8.3 代码审核门槛

代码审核至少检查：

- 状态是否只能通过状态机变化。
- 乐观锁冲突是否显式返回，而不是最后写入者覆盖。
- 外部操作是否有幂等键、超时、有限重试和人工接管。
- 数据库提交和事件写入是否处于同一事务。
- 文件是否先写临时路径、校验哈希后原子替换。
- 日志、事件和审计 JSON 是否过滤 Cookie、token、手机号和验证码。
- 失败是否保留原始事实，是否存在错误“回滚”外部平台动作的假象。

### 8.4 业务审核门槛

| 阶段 | 自动检查 | 人工审核 | P0/P1临时入口 | 目标界面 | 放行条件 |
|---|---|---|---|---|---|
| 选书 | 去重、书 ID、推广状态 | 选择原因、题材与合规 | CLI确认 | Streamlit任务详情 | `selected` |
| 素材 | 章节数、哈希、付费墙 | 素材完整性 | CLI摘要+只读文件预览 | Streamlit素材页 | `material_ready` |
| 推广申请 | 别名唯一、有效期 | 平台审核结果歧义 | `--attention`列表 | Streamlit人工处理队列 | `active` |
| 脚本 | 必填字段、敏感词、章节引用 | 事实、剧透、宣传表述 | `fanqie-task-review --type script` | Streamlit脚本版本对比 | `script_approved` |
| 视频 | 技术规格和质量门禁 | 画面、音频、字幕、品牌风险 | 审核包+CLI decision | Streamlit播放器和问题勾选 | `approved` |
| 发布 | 哈希、账号、任务有效性 | 最终标题和账号确认 | CLI二次确认 | Streamlit发布快照确认 | `publish_queued` |
| 回填 | URL 唯一、任务/账号一致 | 页面歧义和补偿决策 | `--attention`列表 | Streamlit回填/补偿面板 | `bound` |

机器检查不能代替脚本、视频和最终发布的人工批准。第一阶段禁止从 `quality_check` 直接跳到 `publishing`。

文件管理器只用于只读查看大文件，不能作为审核结果的事实来源。所有审核决定必须通过 CLI 或 Streamlit 调用同一 Review Service，写入数据库和事件表。

### 8.5 测试层级

- 单元测试：状态机、partial unique index、乐观锁、哈希、路径和敏感字段过滤。
- 迁移测试：空库升级、现有库升级、降级、旧 JSON dry-run 和重复导入。
- 集成测试：SQLite + 文件审计目录 + mock 平台适配器。
- 合约测试：固定番茄/抖音页面响应夹具，检测解析字段变化。
- 端到端测试：脱敏测试任务跑到 `bound`；真实平台操作必须人工批准。
- 故障测试：超时、重复执行、Worker 竞争、发布成功但同步失败、回填失败和页面字段缺失。

### 8.6 阶段审核结论

每个 P 阶段结束输出一份验收记录，包含：迁移版本、测试结果、已知限制、样例任务 UUID、审计目录、失败用例和回滚办法。结论只能是：

- `accepted`：进入下一阶段。
- `accepted_with_limits`：明确限制后进入下一阶段。
- `rework_required`：不得进入下一阶段。

## 9. 实施阶段

### P0：回填可行性、数据库骨架和兼容写入

- 先执行 P0-A 回填可行性试验，确认平台入口、URL要求、任务有效期、页面响应和人工验证点，并形成证据记录。
- 新增模型、Alembic 迁移、状态枚举、约束和索引。
- 为旧 `douyin.db.videos` 增加 `account_key` 兼容迁移，并使 `douyin-sync` 明确接收/记录账号上下文；无法确认账号的历史作品标记为待认领，不自动关联。
- 为现有 `books/*/meta.json`、`tasks/*/task.json` 编写只读扫描和导入报告。
- 导入前不修改旧文件；检测重复、缺失 `book_id` 和别名冲突。
- 给 `fanqie-book-fetch`、`fanqie-promo-apply`、`fanqie-promo-list` 等现有写命令接入兼容同步层，确保命令完成时同步更新数据库和事件。
- 提供 `fanqie-task-reconcile`，对比文件与数据库并报告 `file_only`、`db_only`、`hash_mismatch`、`status_mismatch`；不自动覆盖冲突。
- 建立任务详情查询和事件追加能力。

P0 上线后，数据库是业务元数据和状态的唯一事实源，文件系统是正文、视频、截图及平台快照的产物库。现有命令可以继续“先生成文件”，但只有数据库同步和事件提交成功才返回业务成功；同步失败必须返回 `partial_failure`、记录 `manual_intervention` 并由 reconcile 处理，不能静默留下仅文件成功的记录。

验收：回填路径已得到人工可行性证据；可以从数据库查询现有及新产生的书籍和推广任务；迁移可升级/降级；重复导入幂等；现有命令执行后不产生新的 file-only 业务记录。

### P1：选书、素材和推广申请闭环

- 连接 `fanqie_batch_books`、`fanqie_books` 和推广任务。
- 新增统一 `BookMaterialService`：批量抓取与单本 `fanqie-book-fetch` 都先按 `fanqie_book_id` 解析/upsert `fanqie_books`，再调用同一抓取实现。
- 统一素材目录为 `books/<fanqie_book_id>_<safe_name>/`；发现历史重复目录时生成合并报告，不自动删除或覆盖。
- 抓取、申请、审核同步均更新数据库并写事件。
- 建立审计目录和素材 manifest。
- 验证失败、重试和人工处理状态。
- 提供 `fanqie-task-list --attention`（或等价 Streamlit 看板），展示 `manual_intervention`、最终失败、即将过期和发布未回填任务，并给出原因、下一动作、责任人和滞留时长。
- 在P1结束前执行推广视频冒烟：使用固定脱敏 `task.json + meta.json/material.txt`，先跑 `--assets-only`，再用无ComfyUI/兜底背景模式生成短MP4；用 `ffprobe` 验证可解码、音视频轨、时长和非空输出，并保存manifest与日志。

验收：一条任务可从 `candidate` 推进到 `active`，中间结果均可追溯；批量和单本入口对同一书只产生一个主记录和一个当前素材根目录；所有人工任务能从统一入口发现和处理；`fanqie-promo-video` 基础能力已有可重复的短视频冒烟证据。冒烟失败时P2不得开工。

### P2：脚本、视频和审核闭环

- 实现脚本版本、视频任务和审核表。
- 接入现有 Presenter/故事视频/三联画及质量门禁。
- 生成标准审核包，审核后冻结文件哈希。

验收：一个任务可以生成多个候选，只有被批准且哈希一致的候选可发布。

### P3：抖音发布和番茄回填

- 发布前快照、发布记录、`douyin-sync` 关联。
- 实现 `DouyinLegacyVideoRepository` 和 `NovelPromotionPublishSyncService`；只有后者能更新番茄发布记录。
- `fanqie-task-sync-douyin` 按指定账号同步并校验 `(account_key, video_id)`，覆盖作品不存在、账号不匹配、旧记录无账号及多候选场景。
- 实现 `fanqie-task-bind` 和回填证据保存。
- 增加幂等、URL 唯一性、任务有效期和账号检查。

验收：一条真实或测试任务从 `approved` 到 `bound`，数据库能反查完整链路。

### P4：监控和复盘

- 每日数据快照、任务看板和失败队列。
- 按书籍、脚本、视频模式、账号统计表现。
- 明确无法取得的数据，不使用估算值冒充平台指标。

验收：可查看单任务时间线、每日指标及不同内容版本的表现对比。

## 10. 端到端验收用例

一条闭环任务必须满足：

1. 选中的小说有唯一 `fanqie_book_id` 和素材 manifest。
2. 推广任务有有效别名、审核状态和平台申请证据。
3. 至少一个脚本版本通过人工审核。
4. 至少一个视频候选有生成 manifest、质量报告和审核包。
5. 发布视频的 SHA-256 与审核批准的 SHA-256 一致。
6. 抖音发布记录补齐唯一 `video_id` 和 URL。
7. 番茄回填前的小说、任务、账号、URL 校验全部通过。
8. 回填成功有页面响应摘要和截图。
9. 任务状态最终为 `bound` 或 `monitoring`。
10. 从任务详情可以依次跳转到书籍、章节、脚本、视频、审核、发布、回填和事件记录。

失败场景还必须覆盖：重复书籍、推广被拒、别名过期、生成失败、质量门禁失败、审核驳回、发布后无法唯一匹配、重复 URL、回填页面变化和验证码人工接管。

## 11. 第一阶段交付物

- P0-A 番茄回填可行性报告和脱敏证据。
- 数据模型和 Alembic 迁移。
- 旧 JSON/目录扫描与幂等导入工具。
- 现有写命令的数据库兼容同步层，以及文件/数据库差异巡检命令。
- 推广任务状态机及非法跳转检查。
- 审计产物存储器和 manifest schema。
- 任务查询、attention list、事件时间线和失败重试入口。
- 至少一条脱敏的端到端测试夹具。
- 数据库单元测试、迁移测试、状态机测试和审计完整性测试。
- 更新 `FANQIE_PROMOTION_WORKFLOW.md`，从旧文件流程切换到任务 UUID 驱动流程。

## 12. 非目标

当前阶段不做：

- 绕过验证码、短信或安全验证。
- 未经人工审核的全自动批量发布。
- 把 Cookie、token 等认证信息写入业务数据库或审计目录。
- 未经授权抓取付费正文。
- 在平台没有提供数据时推算并伪装成真实转化或收益。
- 第一阶段同时重构所有既有视频生成模块。

## 13. 完成定义

本项目的番茄推书闭环完成，需要同时满足：

- **业务完整**：选书到番茄回填能够完成。
- **数据完整**：每个业务对象有稳定 ID、外键关系和合法状态。
- **审计完整**：关键输入、输出、审核、平台结果和哈希可追溯。
- **失败可恢复**：步骤幂等，失败可定位、可重试、不会串单。
- **权限合规**：人工验证有明确接管点，不保存认证秘密。
- **验收可重复**：测试夹具和至少一条真实/测试闭环记录能够复查。
