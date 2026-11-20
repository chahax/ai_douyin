---
doc_status: planning
doc_category: implementation_plan
last_reviewed: 2026-08-26
model_usage: 人工导入优先、书面授权后启用网页采集的热点情报与法律原创脚本执行计划。
---

> 文档状态：执行中。自动网页采集不是默认阶段；只有授权门通过后才执行 P6。

# 网页采集版热点情报与法律脚本：执行计划

更新时间：2026-08-26

## 1. 路线总览

```text
先做：人工选样/CSV/自有导出 → 热点分析 → 原创脚本 → 本地样片

并行准备：申请网页自动采集与生成式处理的书面授权

授权后：Playwright 网页采集 → 小流量联调 → 定时快照 → 趋势分析
```

技术栈使用 Python，不新增 Go 服务。

## 2. 阶段划分

| 阶段 | 目标 | 是否自动访问抖音 | 交付 |
|---|---|---:|---|
| P0 | 数据许可和范围决策 | 否 | Source Policy、授权模板、No-Go 门 |
| P1 | 统一数据模型和 Provider 骨架 | 否 | 模型、迁移、策略门 |
| P2 | 人工导入/自有数据 MVP | 否 | CSV/URL/自有导出 Provider |
| P3 | 法律过滤、聚类和评分 | 否 | 话题簇、样本排行 |
| P4 | TrendBrief、脚本和门禁 | 否 | 三类原创脚本 |
| P5 | UI、调度和本地样片 | 否 | 可用离线 MVP |
| P6 | 授权网页采集联调 | **是，必须已授权** | Playwright Provider 和 QA 证据 |
| P7 | 授权后的定时采样优化 | **是，授权需覆盖调度** | 指标快照和稳定性验证 |

### 2.1 apachong 框架复用边界

本项目不安装或直接依赖 `D:\IT\apachong`。只参考其任务恢复、证据和限速思想，在 `src/trend_intelligence/collection/` 内实现平台无关骨架：

```text
采用：SourcePolicy / CollectionJob / Checkpoint / CollectionRateLimiter
后续采用：精简 CaptureBundle（脱敏、hash、保存期限）
保留本项目：BrowserSession / Scheduler / DB / LLM / 工作流契约 / 日志
排除：电商领域模型 / anti-detect / 代理 / 验证码识别 / 内部 API 监听重放
```

`src/shared/rate_limiter.py` 已负责 LLM QPS，不改造成网页限速器。网页采集的访问间隔和页数硬预算由 `CollectionRateLimiter` 与 `PageBudget` 单独承担。

### 2.2 当前实施状态（2026-08-26）

- [x] Source Policy 的 fail-closed 纯逻辑骨架；
- [x] CollectionJob 状态机与策略门协调；
- [x] JSON Checkpoint 原子落盘和恢复；
- [x] 断点恢复强制重新检查授权，Checkpoint 拒绝会话敏感字段；
- [x] 按来源最小间隔与每次/每日页数硬预算；
- [x] 不联网单元测试；
- [ ] 数据库模型、迁移和审计表；
- [ ] 人工 CSV Provider；
- [ ] Capture Bundle；
- [ ] 任何授权网页 Provider（保持关闭）。

## 3. P0：数据许可与 Source Policy

### 工作项

- 保存最新版抖音用户协议和 robots 检查日期；
- 明确当前未获得书面授权时 `WEB_CRAWLER_ENABLED=false`；
- 准备授权申请说明：允许域名/路径/字段/用途/频率/保存期；
- 单独询问是否允许生成式处理和脚本辅助；
- 盘点自有账号可导出数据；
- 确定人工导入数据来源和使用说明；
- 制定数据删除和授权到期处理流程。

### 交付

```text
config/trend_sources/default_policy.yaml
config/trend_domains/legal_cn.yaml
docs/examples/trend_source_authorization.example.json
docs/examples/trend_manual_import.example.csv
docs/examples/trend_provider_capabilities.example.json
```

### 授权记录示例

```json
{
  "provider": "authorized_web",
  "status": "unverified",
  "allowed_hosts": [],
  "allowed_paths": [],
  "allowed_fields": [],
  "allowed_purposes": [],
  "min_interval_seconds": 30,
  "max_pages_per_run": 20,
  "expires_at": null,
  "authorization_file_hash": null
}
```

### 验收

- 默认策略拒绝所有自动网页采集；
- 只有 `approved` 且用途匹配才能运行；
- 授权到期自动拒绝；
- 未记录保存期的数据源不能入库。

## 4. P1：模型、迁移和 Provider 合约

### 新增文件

```text
src/trend_intelligence/__init__.py
src/trend_intelligence/models.py
src/trend_intelligence/schemas.py
src/trend_intelligence/repository.py
src/trend_intelligence/source_policy.py
src/trend_intelligence/collection/job.py
src/trend_intelligence/collection/checkpoint.py
src/trend_intelligence/collection/rate_limiter.py
src/trend_intelligence/providers/base.py
alembic/versions/<revision>_add_trend_intelligence_tables.py
tests/test_trend_models.py
tests/test_trend_provider_contract.py
tests/test_trend_source_policy.py
tests/test_trend_collection_framework.py
```

### 数据表

```text
trend_source_policies
trend_collection_runs
trend_page_evidence
trend_domains
trend_queries
trend_items
trend_metric_snapshots
trend_clusters / trend_cluster_items
trend_briefs
trend_scripts
```

### 验收

- `alembic upgrade head` 可从干净 SQLite 数据库完成；
- `(provider, external_id)` 幂等；
- 授权状态和采集数据建立外键/逻辑关联；
- token、Cookie、localStorage 不进入数据库；
- 保存期限可以查询和执行清理。

## 5. P2：人工导入和自有数据 MVP

### 新增文件

```text
src/trend_intelligence/providers/mock.py
src/trend_intelligence/providers/manual_import.py
src/trend_intelligence/providers/owned_account_export.py
src/trend_intelligence/providers/licensed_feed.py
src/trend_intelligence/normalizer.py
src/trend_intelligence/ingest_service.py
src/trend_intelligence/metric_service.py
tests/test_manual_import_provider.py
tests/test_owned_export_provider.py
tests/test_trend_ingest.py
tests/test_trend_metric_snapshots.py
```

### CSV 最小字段

```text
source_url,title,caption_excerpt,author_display_name,published_at,
like_count,comment_count,share_count,collected_at,permission_note
```

### 实现要求

- 导入文件只允许来自配置目录；
- 验证大小、编码、列名和 URL host；
- 指标同时保存原始展示值和归一化值；
- 内容去重但保留多个指标快照；
- 缺少许可说明时进入 `quarantined`，不能用于脚本生成；
- 处理失败只影响当前行，不丢弃整批。

## 6. P3：法律过滤、聚类和评分

### 新增文件

```text
src/trend_intelligence/domain_classifier.py
src/trend_intelligence/clusterer.py
src/trend_intelligence/ranker.py
tests/test_legal_domain_classifier.py
tests/test_trend_clusterer.py
tests/test_trend_ranker.py
```

### 实现顺序

1. 法律关键词和排除词；
2. 内容 hash/长句近重复；
3. embedding 语义分类；
4. 话题簇；
5. 新鲜度、互动百分位和页面/导入顺序；
6. 多作者重复出现度；
7. 按数据完整度输出评分类型。

### 评分类型

| 数据 | 输出 |
|---|---|
| 文本和人工顺序 | `sample_relevance_score` |
| 单次互动指标 | `sample_score` |
| 两个以上可比快照 | `trend_score` |

### 验收

- 排除“律师穿搭”“律师电视剧”等误召回；
- 每个簇可以追溯到来源；
- 每个分数显示查询/导入范围和指标质量；
- 网页样本不显示为“官方热榜”。

## 7. P4：TrendBrief、原创脚本与法律门禁

### 新增文件

```text
src/trend_intelligence/brief_builder.py
src/trend_intelligence/script_generator.py
src/trend_intelligence/originality_guard.py
src/trend_intelligence/fact_guard.py
docs/prompts/trend-brief-generation.txt
docs/prompts/legal-trend-script-generation.txt
tests/test_trend_brief_builder.py
tests/test_trend_script_generator.py
tests/test_trend_originality_guard.py
tests/test_trend_fact_guard.py
```

### 生成要求

- 输入话题簇摘要，不输入单条爆款完整文案；
- 每簇生成普法解释、生活场景、行动清单三种角度；
- 保留 source IDs、法规来源、不确定说法和模型版本；
- 长句/连续字串/语义相似度超阈值时退回重写；
- L2/L3 法律风险不能批准，也不能创建生产视频项目；
- 模型返回的法规和案件事实不自动视为已核验。

## 8. P5：UI、调度和离线样片

### 页面

```text
人工录入/CSV 导入
→ 来源许可和样本范围
→ 法律过滤与话题簇
→ 评分分项和来源证据
→ TrendBrief
→ 三版脚本
→ 法律/原创性审核
→ 锁定脚本（Video Pipeline V2 通过验收后再生成样片）
```

### 调度任务

```text
process_imported_samples
recompute_trend_clusters
build_daily_legal_digest
expire_raw_evidence
```

此阶段不包含自动访问抖音的任务。

### 离线 MVP 验收

```text
100 条人工/自有样本
→ 至少 10 个法律话题簇
→ 每簇 3 个原创脚本
→ 人工批准 1 个脚本
→ 人工批准 1 个锁定脚本；视频样片不属于当前阶段验收
```

## 9. P6：授权网页采集联调

### 强制前置门

- 书面授权状态为 `approved`；
- 授权明确覆盖自动采集和热点分析；
- 若调用 LLM，授权覆盖生成式处理；
- 域名、路径、字段、频率、保存期完整；
- 采集会话与发布账号会话隔离；
- UI 和配置默认仍为关闭，需显式启用。

### 新增文件

```text
src/trend_intelligence/providers/authorized_web/provider.py
src/trend_intelligence/providers/authorized_web/browser.py
src/trend_intelligence/providers/authorized_web/navigator.py
src/trend_intelligence/providers/authorized_web/risk_detector.py
src/trend_intelligence/providers/authorized_web/evidence.py
src/trend_intelligence/providers/authorized_web/extractors/base.py
src/trend_intelligence/providers/authorized_web/extractors/search_results.py
src/trend_intelligence/providers/authorized_web/extractors/topic_or_hot.py
src/trend_intelligence/providers/authorized_web/extractors/video_detail.py
tests/test_authorized_web_policy_gate.py
tests/test_authorized_web_extractors.py
tests/test_authorized_web_risk_detector.py
```

### BrowserSession 扩展

优先在热点模块做包装，减少修改共享会话：

- 单次 DOM 结构化读取；
- 页面标题、URL、文本 hash；
- 截图证据；
- 风险页识别；
- 页面预算和访问间隔；
- 安全停止/续跑游标。

不增加：响应拦截、内部 API 重放、stealth、代理池、验证码处理。

### 联调顺序

1. 单个已授权 URL；
2. 单个关键词、第一页；
3. DOM 字段和数字归一化；
4. 页面为空和缺字段；
5. 登录/验证码/403/429 安全停止；
6. 有限滚动或翻页；
7. 中断续跑；
8. 第二次指标快照；
9. 法律相关性和话题簇复核；
10. 生成不发布的脚本。

### QA 包

```text
data/qa/trend_web/<date>/source_policy.redacted.json
data/qa/trend_web/<date>/selector_profile.json
data/qa/trend_web/<date>/extraction_report.json
data/qa/trend_web/<date>/risk_stop_report.json
data/qa/trend_web/<date>/legal_relevance_review.json
data/qa/trend_web/<date>/score_review.json
```

不得包含 Cookie、localStorage、token、验证码截图或完整个人资料。

## 10. P7：授权后的定时采样

只有授权明确允许无人值守定时采集，且 P6 连续稳定后实施。

### 任务

```text
collect_authorized_legal_search_samples
refresh_authorized_visible_metrics
recompute_trend_clusters
expire_authorized_raw_evidence
```

### 上线门

- 连续 7 天无验证码/风控；
- 页面解析成功率达到项目阈值；
- 403/429 为零或按授权预期处理；
- 每次运行不超授权频率和页面预算；
- 授权到期自动停止测试通过；
- DOM 变化能失败关闭；
- 人工抽样确认指标和内容映射正确。

## 11. 环境变量

```env
WEB_CRAWLER_ENABLED=false
TREND_WEB_PROVIDER_MODE=disabled
TREND_WEB_USER_DATA_DIR=./data/browser/trend_web/user_data
TREND_WEB_STORAGE_STATE_PATH=./data/browser/trend_web/storage_state.json
TREND_WEB_MIN_INTERVAL_SECONDS=30
TREND_WEB_MAX_PAGES_PER_RUN=20
TREND_WEB_RAW_RETENTION_DAYS=0
TREND_DATA_RETENTION_DAYS=90
```

Source Policy 可以收紧这些值，不能用环境变量突破书面授权上限。

## 12. 测试策略

### 不联网单元测试

- 保存脱敏、许可使用的 HTML fixture；
- Selector profile 版本测试；
- 数字“2.8万/3623”等归一化；
- 空页、登录页、验证码页、429 页识别；
- 授权到期和用途不匹配；
- 幂等、快照和删除策略。

### 授权后的联网测试

- 只对授权 host/path；
- 串行、小页数、人工触发；
- 不在普通 CI 中运行；
- 使用 `pytest -m authorized_web_live` 单独标记；
- 日志只记录 URL hash、状态、数量和停止原因。

## 13. 工作量估计

| 阶段 | 估计 |
|---|---:|
| P0 | 1～2 天，授权等待另计 |
| P1 | 2～3 天 |
| P2 | 2～3 天 |
| P3 | 3～5 天 |
| P4 | 3～5 天 |
| P5 | 2～4 天 |
| P6 授权网页采集 | 4～7 天 |
| P7 定时稳定性 | 3～5 天 + 7 天观察窗口 |

不含授权等待的离线 MVP：约 2～3 周。获得授权后的网页采集版：约 4～6 周。

## 14. Definition of Done

### 离线 MVP

- 至少一个人工/自有/许可数据源运行；
- 样本范围和许可状态在 UI 可见；
- 法律过滤、聚类、评分和脚本门禁通过验收；
- 未批准脚本不能生成视频；
- 未确认发布不能上传。

### 授权网页采集版

- 书面授权证据登记且未过期；
- Source Policy Gate 有测试覆盖；
- 无授权时不会访问抖音；
- 采集与发布会话隔离；
- 风控/验证码/限流安全停止；
- 不包含反检测、代理池、内部 API 重放；
- 数据可追溯、可按期删除；
- 网页样本不会被表述为官方全量热榜；
- 测试、迁移和脱敏 QA 证据齐全。
