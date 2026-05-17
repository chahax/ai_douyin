---
doc_status: reference
doc_category: platform
last_reviewed: 2026-05-10
model_usage: 平台功能参考文档；用于抖音发布、数据持久化、自动回复相关实现。
---

> 文档状态：平台功能参考文档；用于抖音发布、数据持久化、自动回复相关实现。

# AI Douyin 管理后台 — 数据持久化与管理界面

## 1. 目标

为 `ai_douyin` 项目新增本地数据持久化层和 Streamlit 管理界面，实现：

1. **视频数据本地化** — 同步抖音创作者后台视频列表（含播放/点赞/评论数据），存入本地 SQLite
2. **评论管理与自动回复** — 抓取自己视频下的评论，支持浏览器自动化回复
3. **管理界面** — Streamlit 页面展示视频/评论，支持手动触发同步和定时任务

---

## 2. 技术选型

| 组件 | 技术 | 说明 |
|------|------|------|
| 浏览器自动化 | Playwright | 已有 `browser_session.py`，复用 |
| 数据库 | SQLite | 本地文件 `data/douyin.db`，不上云 |
| 管理界面 | Streamlit | 端口 8501 |
| 定时任务 | APScheduler | 定时触发同步脚本 |
| ORM | SQLAlchemy（原生） | 轻量，不引入新依赖 |

> **注意：** 项目已有 SQLAlchemy（用于 `wisdom_ai.db`），本模块复用 `sqlalchemy` 但新建独立的 SQLite 文件和 Base，不混用已有模型。

---

## 3. 数据库设计

文件路径：`data/douyin.db`

### 建表 SQL

```sql
-- 视频主表
CREATE TABLE IF NOT EXISTS videos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自增主键
    local_id       TEXT,                       -- 本地唯一标识（publish 时生成 UUID）
    video_id       TEXT,                       -- 抖音视频 ID（sync 后补上）
    title          TEXT,                       -- 视频标题（sync 匹配 key）
    description    TEXT,                       -- 视频描述
    status         TEXT DEFAULT 'pending_review',  -- pending_review / published / failed
    publish_time   TEXT,                       -- 发布时间字符串
    cover_url      TEXT,                       -- 封面URL
    stats_views    INTEGER DEFAULT 0,          -- 播放量
    stats_likes    INTEGER DEFAULT 0,          -- 点赞数
    stats_comments INTEGER DEFAULT 0,          -- 评论数
    last_synced_at TEXT,                       -- 最后同步时间
    created_at     TEXT                        -- 首次入库时间
);

-- 评论表
CREATE TABLE IF NOT EXISTS comments (
    comment_id     TEXT PRIMARY KEY,           -- 抖音评论ID
    video_id       TEXT,                       -- 关联 videos.video_id
    user_nickname  TEXT,                       -- 评论用户昵称
    user_avatar    TEXT,                       -- 评论用户头像URL
    content        TEXT,                       -- 评论内容
    like_count     INTEGER DEFAULT 0,          -- 点赞数
    is_top         INTEGER DEFAULT 0,          -- 是否置顶 0/1
    reply_count    INTEGER DEFAULT 0,          -- 子回复数
    created_at     TEXT,                       -- 评论时间
    is_replied     INTEGER DEFAULT 0,          -- 是否已回复 0/1
    replied_at     TEXT,                       -- 回复时间
    reply_content  TEXT,                       -- 回复内容
    FOREIGN KEY (video_id) REFERENCES videos(video_id)
);

-- 同步历史
CREATE TABLE IF NOT EXISTS sync_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_type     TEXT,                        -- videos / comments / stats
    total_count   INTEGER DEFAULT 0,           -- 本次处理总数
    new_count     INTEGER DEFAULT 0,           -- 本次新增数
    started_at    TEXT,                        -- 开始时间
    finished_at   TEXT,                        -- 结束时间
    status        TEXT                         -- success / failed / partial
);

-- 自动回复规则（预留）
CREATE TABLE IF NOT EXISTS auto_reply_rules (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword        TEXT,                       -- 触发关键词
    reply_template TEXT,                       -- 回复模板
    enabled        INTEGER DEFAULT 1,          -- 是否启用 0/1
    created_at     TEXT
);
```

### 索引

```sql
CREATE INDEX IF NOT EXISTS idx_comments_video_id   ON comments(video_id);
CREATE INDEX IF NOT EXISTS idx_comments_is_replied ON comments(is_replied);
CREATE INDEX IF NOT EXISTS idx_videos_status       ON videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_local_id      ON videos(local_id);
CREATE INDEX IF NOT EXISTS idx_videos_title        ON videos(title);
CREATE INDEX IF NOT EXISTS idx_sync_history_type    ON sync_history(sync_type);
```

---

## 4. 目录结构

```
src/
├── platform_adapter/
│   ├── sync_workflow.py       # 改造：结果写入 service，不直接 print
│   ├── comment_workflow.py    # 改造：接入浏览器解析 + 写 service
│   ├── browser_session.py     # 已有：Playwright 封装
│   └── models.py              # 已有：VideoItem, CommentRecord 等
│
├── services/                   # 新增：数据服务层
│   ├── __init__.py
│   ├── database.py            # SQLite 连接 + 建表初始化
│   ├── video_service.py       # 视频 upsert / 查询
│   ├── comment_service.py      # 评论 upsert / 查询 / 标记已回复
│   └── sync_history_service.py # 同步历史记录
│
└── dashboard/                 # 新增：Streamlit 管理界面
    ├── __init__.py
    ├── dashboard.py           # 主界面（Tab 导航）
    ├── tabs/
    │   ├── __init__.py
    │   ├── videos_tab.py      # 视频列表 + 同步按钮
    │   ├── comments_tab.py     # 评论列表 + 回复功能
    │   ├── rules_tab.py       # 自动回复规则（预留）
    │   └── history_tab.py     # 同步历史
    └── scheduler.py           # APScheduler 定时任务

scripts/
├── sync_videos.py             # 视频同步入口（供 dashboard 调用）
└── sync_comments.py           # 评论同步入口

data/
└── douyin.db                  # SQLite 数据库文件
```

---

## 5. 服务层 API 设计

### `video_service.py`

```python
def save_video(video: VideoItem) -> bool
    """Upsert 视频，已存在则更新，不存在则插入"""

def get_videos(status: str | None = None, limit: int = 50, offset: int = 0)
    -> list[dict]
    """分页查询视频列表，支持状态筛选"""

def get_video_by_id(video_id: str) -> dict | None
    """根据 video_id 查询单个视频"""

def update_video_stats(video_id: str, stats: VideoStats) -> bool
    """更新视频统计数据"""

def count_videos(status: str | None = None) -> int
    """统计视频数量"""
```

### `comment_service.py`

```python
def save_comment(comment: CommentRecord, video_id: str) -> bool
    """Upsert 评论"""

def get_comments(video_id: str | None = None, is_replied: int | None = None,
                 limit: int = 50, offset: int = 0) -> list[dict]
    """分页查询评论列表，支持视频ID和回复状态筛选"""

def mark_comment_replied(comment_id: str, reply_content: str) -> bool
    """标记评论已回复，记录回复内容和时间"""

def count_comments(video_id: str | None = None, is_replied: int | None = None) -> int
    """统计评论数量"""

def get_reply_rate() -> float
    """计算评论回复率"""
```

### `sync_history_service.py`

```python
def record_sync(sync_type: str, total: int, new_count: int,
                started_at: str, finished_at: str, status: str) -> int
    """记录同步历史，返回 id"""

def get_sync_history(sync_type: str | None = None,
                     limit: int = 20) -> list[dict]
    """查询同步历史"""
```

---

## 5.5 发布与同步的数据流设计

发布和同步是两个独立阶段，通过 `title` 字段匹配实现数据关联：

```
发布阶段（auto_publish_service）
  1. 生成 UUID 作为 local_id
  2. 视频发布到抖音（此时不知道 video_id）
  3. save_video(local_id=UUID, video_id=None, title="标题", status=PENDING)
     → 数据库记录：status=pending_review, video_id=NULL

独立 Sync 阶段（douyin-sync 命令）
  1. 调用 work_list API 获取抖音视频列表（含真实 video_id）
  2. 对每条记录调用 save_video(video_id="763048800", title="标题")
  3. save_video 匹配逻辑（按优先级）：
     a) local_id 匹配 → 更新（同一条本地记录）
     b) video_id 匹配 → 更新（已知抖音 ID）
     c) title + pending_review 匹配 → 补上 video_id，更新 status=published
     d) 均未命中 → 插入新记录（纯同步场景）
```

**解决的核心问题：** 抖音发布后页面不跳转出 video_id，无法在发布时写入真实 ID。采用本地先记录 + 后续 sync 匹配的设计，避免依赖发布时获取 ID。

---

## 6. 浏览器自动化流程

### 6.1 视频同步

复用现有 `sync_workflow.py`，改造 `_do_sync` 返回 `List[VideoItem]` 后，调用 `video_service.save_video()` 写入数据库。

**新增 `scripts/sync_videos.py`：**

```python
# 入口脚本，供 dashboard 和定时任务调用
from src.services.video_service import save_video, get_video_by_id
from src.services.sync_history_service import record_sync
from src.platform_adapter.sync_workflow import SyncWorkflow
from src.platform_adapter.browser_session import BrowserSession
import time

def main():
    started = iso_now()
    session = BrowserSession()
    workflow = SyncWorkflow(session)
    videos = workflow.sync_videos()
    new_count = 0
    for v in videos:
        if save_video(v):
            new_count += 1
    record_sync("videos", len(videos), new_count, started, iso_now(), "success")
```

### 6.2 评论同步

改造 `comment_workflow.py`，实现真实浏览器自动化抓取。

**目标页面：** `https://creator.douyin.com/creator-micro/content/manage` → 点击视频 → 评论 tab

**流程：**
1. 打开视频管理页，获取视频列表（video_id + title）
2. 逐个视频进入详情页，抓取评论列表
3. 调用 `comment_service.save_comment()` 写入

**关键选择器（需实际验证后调整）：**

```python
VIDEO_CARD_SELECTOR   = ".video-list-item, [class*='video-card']"
COMMENT_ITEM_SELECTOR  = "[class*='comment-item'], [class*='comment']"
NEXT_PAGE_SELECTOR    = "button:has-text('下一页')"
```

### 6.3 评论自动回复（浏览器自动化）

**流程：**
1. 管理界面点「回复」→ 调用 `reply_bot.reply_to_comment(comment_id, content)`
2. `reply_bot` 打开该视频的评论页，定位到目标评论
3. 输入回复内容，点击发送
4. 更新 `comments` 表 `is_replied=1, reply_content=xxx, replied_at=now`

**关键风险：** 抖音有反自动化风控，请求间隔和随机延迟是必要的。

---

## 7. Streamlit 管理界面

入口：`streamlit run src/dashboard/dashboard.py`

### Tab 1：视频管理

- 视频列表（`st.dataframe` 或 `st.table`），分页展示
- 顶部筛选：`status` 下拉（全部 / 已发布 / 失败）
- 列：标题、状态、发布时间、播放数、点赞数、评论数
- 手动触发「同步视频」按钮（`st.button`，触发子进程运行 `scripts/sync_videos.py`）
- 点击视频行展开详情（`st.expander`）

### Tab 2：评论管理

- 筛选：`is_replied` 单选（未回复 / 已回复 / 全部）
- 可按视频筛选（`st.selectbox` 选视频）
- 列：用户、内容、点赞数、回复状态、操作
- 点「回复」按钮 → `st.text_input` 输入回复内容 → 确认后调用 `reply_bot`
- 底部统计：总评论数、已回复数、回复率

### Tab 3：自动回复规则

- 预留 Tab，当前显示「功能开发中」
- 后续实现：关键词匹配 + 回复模板

### Tab 4：同步历史

- `st.dataframe` 展示 sync_history 表
- 列：同步类型、时间、数量、状态

---

## 8. 定时任务

使用 APScheduler，在 `dashboard/scheduler.py` 中配置。

**默认调度：**

| 任务 | 触发方式 | 说明 |
|------|---------|------|
| `sync_videos` | 定时：每 6 小时 | `APScheduler.triggers.IntervalTrigger(hours=6)` |
| `sync_comments` | 定时：每 1 小时 | `APScheduler.triggers.IntervalTrigger(hours=1)` |

- Dashboard 启动时初始化调度器
- 页面显示当前定时任务状态（下次触发时间）
- 支持页面按钮「暂停/恢复」定时任务

---

## 9. 依赖安装

```bash
pip install streamlit apscheduler
# Playwright 已安装，确认版本
pip show playwright
```

---

## 10. 实现顺序

```
Phase 1 — 数据库 + 服务层（纯本地，无浏览器）
  Step 1.1  ✅ 新建 src/services/database.py（建表 + 连接）
  Step 1.2  ✅ 实现 video_service.py
  Step 1.3  ✅ 实现 comment_service.py
  Step 1.4  ✅ 实现 sync_history_service.py

Phase 2 — 视频同步（改造现有 workflow）
  Step 2.1  ✅ 改造 sync_workflow.py，对接数据库
  Step 2.2  ⏳ scripts/sync_videos.py（可选，CLI 已通过 main.py douyin-sync 覆盖）
  Step 2.3  ✅ 验证视频同步到 douyin.db

Phase 3 — 评论同步
  Step 3.1  ⏳ 完善 comment_workflow.py（浏览器自动化）
  Step 3.2  ⏳ 新建 scripts/sync_comments.py
  Step 3.3  ⏳ 验证评论抓取到 douyin.db

Phase 4 — Streamlit 管理界面
  Step 4.1  ⏳ 主框架 + Tab 导航
  Step 4.2  ⏳ 视频 Tab
  Step 4.3  ⏳ 评论 Tab
  Step 4.4  ⏳ 回复功能 + reply_bot.py
  Step 4.5  ⏳ 同步历史 Tab
  Step 4.6  ⏳ 定时任务 + 启停控制

Phase 5 — 联调测试
  Step 5.1  ⏳ 全流程联调
  Step 5.2  ⏳ 风控延迟参数调优
```

**图例**：✅ 已完成  ⏳ 待实现

---

## 11. 已知风险与限制

| 风险 | 说明 | 应对 |
|------|------|------|
| 抖音反爬/风控 | 浏览器自动化可能被检测 | 请求间隔 + 随机延迟，发现后停用 |
| 页面选择器不稳定 | 抖音页面随时可能改版 | 选择器需可配置化，支持热更新 |
| 评论回复 API 缺失 | 无法通过接口回复 | 浏览器自动化模拟点击，稳定性较差 |
| 多页翻页限制 | page_limit 防止无限翻页 | 实际使用时按需调整 |

---

## 12. 文件清单（新增/修改）

### 已完成 ✅

**新增文件**
```
src/services/database.py              ✅ 已创建
src/services/__init__.py              ✅ 已更新
src/services/video_service.py         ✅ 已创建
src/services/comment_service.py       ✅ 已创建
src/services/sync_history_service.py  ✅ 已创建
scripts/find_video_id.py              ✅ 已创建（调试工具）
scripts/capture_with_session.py       ✅ 已创建（调试工具）
scripts/test_video_list_api.py        ✅ 已创建（调试工具）
scripts/parse_video_api.py            ✅ 已创建（调试工具）
```

**修改文件**
```
src/platform_adapter/sync_workflow.py      ✅ 重写为 API 方案
src/platform_adapter/douyin_adapter.py    ✅ 新增 sync_videos 对接数据库
src/platform_adapter/models.py             ✅ 新增 VideoItem/VideoStatus/SyncResult
main.py                                  ✅ 新增 douyin-sync 命令
docs/ARCHITECTURE_STATUS.md              ✅ 更新为 2026-04-24 版本
```

### 待实现 ⏳

**新增文件**
```
src/dashboard/__init__.py
src/dashboard/dashboard.py
src/dashboard/tabs/__init__.py
src/dashboard/tabs/videos_tab.py
src/dashboard/tabs/comments_tab.py
src/dashboard/tabs/rules_tab.py
src/dashboard/tabs/history_tab.py
src/dashboard/scheduler.py
src/platform_adapter/reply_bot.py     # 评论自动回复机器人
scripts/sync_comments.py
```

**修改文件**
```
src/platform_adapter/comment_workflow.py   # 完善评论抓取
```
```
