---
doc_status: reference
doc_category: reference
last_reviewed: 2026-05-10
model_usage: 参考文档，只能作为背景材料；不要覆盖当前主线方案。
---

> 文档状态：参考文档，只能作为背景材料；不要覆盖当前主线方案。

# pending_review 记录问题分析报告

> 生成时间：2026-04-28
> 状态：待修复

---

## 1. 问题描述

抖音发布流程在"话题输入超时"bug 修复前，一次发布失败后，数据库留下了一条 `status=pending_review` 的孤儿记录：

| 字段 | 值 |
|------|-----|
| id | 9 |
| local_id | 639b64caa26849f9bab68b8d15149998 |
| video_id | NULL |
| title | （空） |
| description | #励志 |
| status | pending_review |
| publish_time | 2026年04月28日 12:43 |
| last_synced_at | 2026-04-28T12:43:02 |

---

## 2. 时间线重建

```
12:42  ✅ 第一次发布成功 → videos.id=10 (status=published, video_id=7633665952655215906)

12:43  ❌ 第二次发布尝试（Streamlit UI 触发）
        ├─ 12:43:02  _save_to_database() 执行 → videos.id=9 (status=pending_review)
        │              title 为空（发布失败后未更新）
        │              description="#励志"（来自请求的 hashtags）
        │
        ├─ 发布流程在 _add_hashtags() 阶段抛出 AttributeError
        │  （.first() 漏括号 bug）
        │
        └─ publish() 捕获异常 → 返回 PublishResult(success=False)

12:50  同步运行 (sync_history.id=24)
        ├─ API 返回 1 个视频（12:42 成功发布的）
        ├─ mark_videos_deleted(NOT IN [...]) → published 记录无删除
        └─ pending_review 记录 (id=9) video_id=NULL → 跳过 NOT IN 检查
            → 未被标记为 failed，永远遗留
```

---

## 3. 根因分析

### 3.1 直接原因

**`pending_review` 记录永远不会被 `mark_videos_deleted` 处理。**

`mark_videos_deleted` 的逻辑：

```python
UPDATE videos SET status='failed', last_synced_at=?
WHERE status='published' AND video_id NOT IN (existing_video_ids)
```

- 只处理 `status='published'` 的记录
- 不处理 `status='pending_review'` 的记录
- `pending_review` 记录 `video_id=NULL`，不在 API 返回列表中，但永远不会被标记为 failed

### 3.2 次要原因

**发布流程的数据库写入时机问题。**

```python
# auto_publish_service.publish()
# Step 5: RAG + 写入数据库（此时 publish 尚未执行）
db_video_id = self._save_to_database(request=request, video_path=video_path)

# Step 4: 发布视频（此时 publish 可能失败）
post_id, publish_url = self._publish_video(request, video_path)
```

`publish()` 方法内没有在失败时将对应 `local_id` 的记录回滚或更新为 `failed`。

### 3.3 历史代码缺陷（已修复）

**`.first()` 漏括号 bug** — 导致发布流程在 `_add_hashtags()` 阶段抛出 `AttributeError` 而非正常返回 `success=False`。

---

## 4. 影响范围

- **当前**：1 条 `pending_review` 孤儿记录，video_id=NULL，永远不会被 sync 清理
- **未来隐患**：如果发布流程在"数据库写入后、publish 返回前"失败（任何异常），都会留下 `pending_review` 孤儿记录

---

## 5. 修复方案

### 方案 A：扩展 `mark_videos_deleted` 逻辑（推荐）

将所有非 `published` 状态的孤儿记录都标记为 `failed`：

```python
# 只要 video_id 不为空，且不在 API 返回列表中，就标记为 failed
# 不再限制只处理 'published' 状态
cursor.execute("""
    UPDATE videos
    SET status='failed', last_synced_at=?
    WHERE video_id IS NOT NULL
      AND video_id NOT IN (?)
      AND status != 'failed'
""", (now_iso(), existing_ids_str))
```

但需注意：`pending_review` 可能是抖音正常状态（审核中），不应一律标记为 failed。

### 方案 B：在 `publish()` 失败时更新数据库记录

```python
# publish() 返回后，检查结果
result = self.adapter.publish_video(publish_req, ...)
if not result.success:
    # 找到刚才写入的 pending 记录，更新为 failed
    update_video_status(db_video_id, 'failed')
    return ...
```

### 方案 C：区分"发布中"和"同步来的 pending_review"

在 `auto_publish_service` 中，用单独的 `status='publishing'` 表示"发布进行中"，publish 完成后更新为 `published` 或 `failed`。Sync 时只处理来自 Douyin 的 `pending_review`（video_id 非空）。

---

## 6. 建议修复步骤

1. **立即清理**：将 `pending_review` 且 `video_id=NULL` 的记录标记为 `failed`
2. **修复 `mark_videos_deleted`**：对 `video_id` 不为空但不在 API 结果中的 `pending_review` 记录，也标记为 `failed`
3. **修复 `publish()` 回滚**：publish 失败时更新对应 local_id 记录状态为 `failed`
4. **新增 `publishing` 状态**（可选）：区分"本地上传中"和"Douyin 审核中"

---

## 7. 验证用例

| 场景 | 操作 | 期望结果 |
|------|------|---------|
| 发布成功 | publish 返回 success=True | status=published, video_id 非空 |
| 发布失败（网络） | publish 抛出异常 | status=failed |
| 发布失败（业务逻辑） | publish 返回 success=False | status=failed |
| 发布中（刚写入 DB） | _save_to_database() 后 | status=publishing 或 pending_review |
| 抖音审核中（真实 pending_review） | Sync 时 API 返回 status=pending_review | status=pending_review, video_id 非空 |
| 孤儿 pending_review | video_id=NULL 且不在 API 结果中 | status=failed |

---

## 8. 附录：相关代码位置

| 文件 | 行号 | 问题 |
|------|------|------|
| `auto_publish_service.py` | 121-128 | DB 写在 publish 之前，无回滚 |
| `auto_publish_service.py` | 103 | `_publish_video` 异常被捕获但 DB 记录未更新 |
| `video_service.py` | `mark_videos_deleted()` | 只处理 `published` 状态 |
| `publish_workflow.py` | 192 | `.first()` 漏括号（已修复） |
