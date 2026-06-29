---
doc_status: current
doc_category: mainline
last_reviewed: 2026-06-29
topic: 番茄小说推广端到端工作流（V5 阶段）
---

# 番茄小说推广 — 端到端工作流

> 完整链路：**抓书 → 申请别名 → 出视频 → 上传抖音 → 回填视频 URL**。所有数据存本地文件系统，Agent 可自然语言调起。

## 1. 完整链路

```text
① 抓书 (fanqie_fetch_book)
   │  达人中心搜索书名 → 详情页抓 meta + 章节
   ↓
   books/<book_id>_<书名>/{ meta.json, chapters/001.txt..., material.txt }
   ↓
② 申请别名 (fanqie_apply_promotion)
   │  达人中心点"别名推广" → 弹窗填别名 + 发文类型 → 提交
   ↓
   tasks/<task_id>/task.json { apply_status: pending_review }
   ↓
③ [番茄审核] 秒过
   ↓
   apply_status: pending_review → active / rejected
   ↓
④ 列出已抓书 (fanqie_list_books)
   │  扫 books/ 列出所有 meta.json
   ↓
   按 tags/categories 选要推广的书
   ↓
⑤ 出视频 (fanqie_generate_video / fanqie_promo_video)
   │  读 meta.json + chapters/ → LLM 写推广脚本 → Presenter 流水线出 mp4
   ↓
   data/videos/<file>.mp4
   ↓
⑥ 上传抖音 (douyin_publish)
   │  浏览器自动上传 + 填标题描述话题
   ↓
   抖音视频 URL
   ↓
⑦ 回填视频 URL (fanqie_bind_douyin_video) [未做]
   │  推广列表点"回填发文" → 弹窗填抖音视频 URL → 提交
   ↓
   开始计算推广收益
```

## 2. 数据存储布局

```text
data/fanqie_promotion/
├── books/                              ← 抓书产物
│   └── <book_id>_<书名>/
│       ├── meta.json                  ← 元数据（书名/作者/简介/标签/分类）
│       ├── chapters/                  ← 每章正文
│       │   ├── 001.txt
│       │   ├── 002.txt
│       │   └── ...
│       └── material.txt               ← 兼容旧 promo-video（拼接给 LLM）
│
├── tasks/                              ← 申请别名任务
│   └── <task_id>/
│       ├── task.json                  ← apply_status / promotion_alias / book_id / video_path
│       └── promo_script.txt           ← LLM 推广脚本
│
└── browser/fanqie/                     ← KOL 浏览器会话（login 态 + user_data）
    ├── storage_state.json
    └── user_data/
```

### `meta.json` 字段

| 字段 | 来源 | 用途 |
|---|---|---|
| `book_id` | kol 详情页 URL | 全链路唯一标识 |
| `book_name` | `.book-name-WEvqxi` | 推广展示用 |
| `author` | `.book-author-Ygu_Z1` | 简介 |
| `abstract` | `.book-abstract-content-p6QvfA` | 简介（可能含 `\n展开` 后缀） |
| `tags` | `.book-tag-yYbHV7` | 年代/字数/评分/状态 |
| `categories` | `.book-category-w1IX9j` | 题材分类（现代言情/萌宝/团宠/...） |
| `total_chapters_seen` | 目录项数 | 可见章节数 |
| `chapters_fetched` | 实际抓的 | 抓到章节数 |
| `paywall_hit` | bool | 是否遇到付费墙 |
| `paywall_at_chapter` | int | 在第几章遇到付费墙（如果有） |
| `paywall_reason` | str | 关键词代码（vip_required / preview_ended / ...） |
| `scraped_at` | ISO | 抓书时间 |
| `source_url` | str | kol 详情页 URL |
| `fetch_log` | list[dict] | 每章 {index, title, item_id, char_count, file} |

### `task.json` 关键字段

| 字段 | 说明 |
|---|---|
| `book_id` / `book_name` | 关联 meta.json |
| `promotion_alias` | 申请到的推广别名 |
| `apply_status` | `started` → `pending_review` → `active`/`rejected` / `alias_taken` / `failed` |
| `extra.click` | apply 弹窗 click 结果 |
| `extra.fill` | apply 弹窗 fill + wait 结果（含 `wait.title="别名创建成功"`） |
| `extra.wait` | list 同步结果（如果跑过 list-promotions） |
| `material_path` | 关联 books/ 路径 |
| `script_path` | LLM 推广脚本路径 |
| `video_path` | 出片后路径 |
| `has_fill_link` | list 同步时回填，标记能否在番茄页面"回填发文" |
| `fill_status` | "未填写" / 已回填 URL |

## 3. CLI 命令清单

```bash
# === 抓书 ===
python main.py fanqie-book-fetch --book-name "我的6个超级奶爸" --chapters 10
python main.py fanqie-list-books                                # 列已抓

# === 申请别名（B 环节）===
python main.py fanqie-promo-apply --book-name "我的6个超级奶爸"
                                                  --no-wait-login
                                                  --publish-type "AI数字人"
                                                  --max-alias-attempts 4
                                                  --keep-open

# === 列出已申请别名 + 同步状态 ===
python main.py fanqie-promo-list                              # 默认 sync 到 task.json

# === 出视频（用 books/ 里的素材）===
python main.py fanqie-promo-video --task-file data/fanqie_promotion/tasks/<task_id>/task.json

# === 上传抖音 ===
python main.py douyin-publish --video data/videos/<file>.mp4 --title "..."

# === 回填视频 URL（未做，TODO） ===
# python main.py fanqie-bind-douyin-video --task-file <task.json> --video-url <url>
```

## 4. Agent Skill 清单

```python
# 自然语言调起 → 上面 CLI 同等效果

fanqie_fetch_book          # 抓书：book_name, chapters(默认10)
fanqie_list_books           # 列已抓
fanqie_apply_promotion      # 申请别名：book_name, alias, publish_type, max_alias_attempts
fanqie_list_promotions      # 列推广别名 + 同步状态
fanqie_generate_video       # 出视频：book_name, alias, chapters
fanqie_promo_apply          # 申请别名
fanqie_promo_list           # 同步状态
```

## 5. 业务约束（番茄侧控制）

| 约束 | 影响 |
|---|---|
| B 环节（apply）只能对达人中心 list 推荐池里的书生效 | 番茄 KOL 推荐池控制可推广范围 |
| 申请别名要 1 天审核（实际秒过） | 推 promotion-list 立即看到 active |
| 别名有效期约 6 个月（2026-06-29 ~ 2026-12-26） | 长期不推就过期 |
| 已生效别名必须回填抖音视频 URL 才计算收益 | G 环节必须做 |
| 番茄对未回填的别名显示"未填写" + "回填发文" link | 可批量回填 |

## 6. 状态机

### 抓书
```
fetch_book started
  ├─ kol 搜索框输入书名
  ├─ DOM 过滤找书卡 → click → pushState
  ├─ 详情页拿 book_id + meta
  ├─ 抓目录项（max_count=10000）
  ├─ 逐章 click + 抓 #content + 付费墙检测
  ├─ 写 meta.json + chapters/NN.txt + material.txt
  └─ return FanqieBookFetchResult

fetch_book failed
  └─ 抛 RuntimeError（"达人中心搜索未匹配" / "详情页 URL 未含 book_id" / 等等）
```

### 申请别名
```
apply started
  ├─ 达人中心 list 找书卡 → click 别名推广
  ├─ 弹窗：等 modal、填别名（默认推荐）、选发文类型（默认 AI数字人）
  ├─ 点击提交
  ├─ 等服务端响应
  └─ status: pending_review | alias_taken (→ 重试) | closed | timeout → needs_manual_check | active (服务端通过)
```

### list 同步
```
list started
  ├─ 扫推广列表页
  ├─ 每行 { alias / book_id / publish_type / alias_status / ... }
  └─ 按 promotion_alias 匹配 task.json，把 active/under_review/rejected/expired 同步回 task.apply_status
```

## 7. 失败/异常处理

| 失败类型 | 触发条件 | 处理 |
|---|---|---|
| 搜索未匹配 | 达人中心 list 没这本书 | 报错"达人中心搜索未匹配" |
| 详情页未含 book_id | URL 没 pushState 到 book-detail | 报错 |
| 目录项未找到 | 详情页无 .catalogue__item-ImEeJx | 报错 |
| 付费墙（试读结束/开通会员/付费章节/请先登录） | 抓到的文本含关键词 | 自动 break + 记 `paywall_at_chapter` |
| 提交按钮 disabled | 弹窗下拉没选/没填 | 报错"提交按钮未启用或未找到" |
| 别名被他人申请 | err-list 显示 | 自动换下一个候选别名（默认 5 次） |
| 弹窗内 alias_error 客户端校验撞名 | err-list 出现 | 自动换下一个 |

## 8. 端到端示例（已经跑通过）

```bash
# 1. 抓书（搜 "我的6个超级奶爸" → 抓 5 章）
python main.py fanqie-book-fetch --book-name "我的6个超级奶爸" --chapters 5
# → books/7577735918904151065_我的6个超级奶爸/{meta.json + 5 chapters/001-005.txt + material.txt}
# → meta.total_chapters_seen=439, chapters_fetched=5, paywall_hit=false

# 2. 列已抓书
python main.py fanqie-list-books
# → 1 本："我的6个超级奶爸" (id=7577735918904151065, 5/439 章)

# 3. 申请别名（搜达人中心 list）
python main.py fanqie-promo-apply --book-name "我的6个超级奶爸" --no-wait-login
# → tasks/20260629_152616/task.json { apply_status: "pending_review", promotion_alias: "林辰被带走" }

# 4. 同步状态（秒过后状态会变 active）
python main.py fanqie-promo-list
# → task.apply_status 从 pending_review → active

# 5. 出视频（TODO: 还没端到端跑过）
python main.py fanqie-promo-video --task-file tasks/20260629_152616/task.json
# → data/videos/presenter_<date>.mp4

# 6. 上传抖音
python main.py douyin-publish --video data/videos/<file>.mp4 --title "..."
# → 抖音视频 URL

# 7. 回填视频 URL（TODO: 还没做）
# python main.py fanqie-bind-douyin-video --task-file <task.json> --video-url <url>
```

## 9. 下一步

1. **G 环节** `fanqie_bind_douyin_video`：在推广列表点"回填发文" link，弹窗填抖音视频 URL
2. **D 端到端**：用 apply 成功的 task + meta.json 跑 `fanqie-promo-video` 出片
3. **fetch_book 容错**：搜索未匹配时 fallback 到 fanqienovel 搜索 API（用 book_id 直接拼 kol 详情页 URL）
4. **fetch_book 增量更新**：已经抓过的书只抓新增章节
