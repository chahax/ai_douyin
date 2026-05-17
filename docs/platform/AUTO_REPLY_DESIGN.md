---
doc_status: reference
doc_category: platform
last_reviewed: 2026-05-10
model_usage: 平台功能参考文档；用于抖音发布、数据持久化、自动回复相关实现。
---

> 文档状态：平台功能参考文档；用于抖音发布、数据持久化、自动回复相关实现。

# 自动回复机器人设计文档

## 1. 背景与目标

为 `ai_douyin` 项目实现评论自动回复机器人，提供：

1. **评论过滤** — 自动跳过不需要回复的评论（作者评论、纯数字/符号、违禁词等）
2. **用户管理** — 每个用户独立设置回复次数上限，防止刷回复
3. **回复记录** — 每个用户的回复历史管理
4. **多轮上下文** — 支持同一用户的多轮对话上下文
5. **规则引擎** — 关键词触发 + LLM 生成回复

---

## 2. 核心概念

### 2.1 用户身份

用户以 `user_nickname`（抖音昵称）为标识，同一昵称的评论共享同一个用户的配置和上下文。

### 2.2 评论过滤策略（按优先级）

| 策略 | 条件 | 动作 |
|------|------|------|
| 作者评论 | `is_author = True` | 跳过 |
| 空评论 | `content.strip() == ""` | 跳过 |
| 纯数字/符号 | 无中文内容 | 跳过 |
| 违禁词 | 包含违禁词表 | 跳过 |
| 已回复 | `is_replied = 1` | 跳过 |
| 用户超限 | 该用户今日回复数 >= 限制 | 跳过 |
| 机器人回复 | 用户昵称是机器人自己的 | 跳过 |

### 2.3 回复上限机制

- 每个用户独立设置 `daily_limit`（每日回复上限）和 `total_limit`（累计回复上限）
- 超限后该用户所有评论都跳过，直到计数器重置
- 支持白名单用户绕过限制

### 2.4 多轮上下文

- 以 `user_nickname` + `video_id` 为一组对话上下文
- 保留最近 N 条历史评论和回复内容
- 上下文用于 LLM 生成更自然的连续对话回复

---

## 3. 数据库设计

### 3.1 新增表

```sql
-- 用户回复配置表
CREATE TABLE IF NOT EXISTS user_reply_configs (
    user_nickname  TEXT PRIMARY KEY,   -- 抖音昵称（唯一标识）
    daily_limit    INTEGER DEFAULT 5,  -- 每日回复上限
    total_limit    INTEGER DEFAULT 50, -- 累计回复上限
    daily_count    INTEGER DEFAULT 0,  -- 今日已回复数
    total_count    INTEGER DEFAULT 0,  -- 累计已回复数
    last_reply_date TEXT,              -- 上次重置日期（YYYY-MM-DD）
    is_whitelist  INTEGER DEFAULT 0,  -- 白名单（绕过限制）
    created_at     TEXT,
    updated_at     TEXT
);

-- 用户回复历史表
CREATE TABLE IF NOT EXISTS reply_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_nickname   TEXT,                       -- 用户昵称
    video_id        TEXT,                       -- 视频ID
    comment_id      TEXT,                       -- 被回复的评论ID
    reply_content   TEXT,                       -- 回复内容
    auto_generated  INTEGER DEFAULT 1,           -- 是否自动生成（1=自动，0=手动）
    model_used      TEXT,                       -- 使用的模型（如 ollama/qwen）
    created_at      TEXT
);

-- 回复上下文记录（每组对话保留最近N条）
CREATE TABLE IF NOT EXISTS reply_context (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_nickname   TEXT,
    video_id        TEXT,
    role            TEXT,                        -- 'user' 或 'assistant'
    content         TEXT,                        -- 评论或回复内容
    created_at      TEXT
);

-- 违禁词表
CREATE TABLE IF NOT EXISTS blocked_words (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    word            TEXT UNIQUE,                 -- 违禁词
    created_at      TEXT
);
```

### 3.2 已有表变更

**`comments` 表改动：**
- `author_name` → 改为 `user_nickname`（保持现有 user_nickname 列）
- 新增 `user_nickname TEXT` — 存储评论者昵称（已在库中）

**`auto_reply_rules` 表改动：**
- 已有 `keyword`, `reply_template`, `enabled` 列
- 新增 `match_type TEXT DEFAULT 'contains'` — 'exact' | 'contains' | 'regex'
- 新增 `reply_type TEXT DEFAULT 'fixed'` — 'fixed' | 'llm' | 'default'
- 新增 `llm_model TEXT` — LLM 模型名称（如 'ollama/qwen2.5:7b'）

---

## 4. 模块设计

### 4.1 目录结构

```
src/
├── services/
│   ├── auto_reply_service.py      # 主服务：协调所有组件
│   ├── comment_filter.py          # 评论过滤器
│   ├── user_profile_service.py    # 用户配置与计数管理
│   └── reply_context_service.py   # 多轮上下文管理
├── platform_adapter/
│   ├── reply_bot_workflow.py      # 浏览器自动化执行回复
│   └── comment_workflow.py        # 已有（复用 fetch_comments）
└── services/
    └── reply_rules_service.py     # 规则 CRUD（扩展现有的 auto_reply_rules）
```

### 4.2 AutoReplyService 主流程

```python
class AutoReplyService:
    def process_video_comments(self, video_id: str) -> AutoReplyResult:
        """
        1. fetch_comments(video_id)         # 拉取评论
        2. for each comment:
               if not filter.should_reply(comment): continue
               if not user_profile.can_reply(user): continue
               reply_content = self._generate_reply(comment, context)
               reply_bot.send_reply(video_id, comment, reply_content)
               user_profile.record_reply(user)
               context.add(comment, reply_content)
        3. 返回处理结果
        """

    def _generate_reply(self, comment, context) -> str:
        # 优先用关键词规则
        rule = reply_rules_service.match_keyword(comment.content)
        if rule:
            return rule.reply_template

        # 否则用 LLM 生成（带上下文）
        return llm.generate(
            prompt=build_prompt(comment, context),
            model=self.config.llm_model
        )
```

### 4.3 CommentFilter

```python
class CommentFilter:
    def should_reply(self, comment: CommentRecord, user_profile) -> tuple[bool, str]:
        """返回 (是否回复, 跳过原因)"""
        if comment.is_author:
            return False, "作者评论"
        if not comment.content.strip():
            return False, "空评论"
        if self._is_noise(comment.content):
            return False, "纯数字/符号评论"
        if self._has_blocked_word(comment.content):
            return False, "违禁词"
        if comment.is_replied:
            return False, "已回复"
        if not user_profile.can_reply(comment.user_nickname):
            return False, "用户超限"
        return True, ""
```

### 4.4 ReplyContextService

```python
class ReplyContextService:
    def get_context(self, user_nickname: str, video_id: str, limit: int = 10) -> list[dict]:
        """获取最近 N 条上下文"""

    def add_user_comment(self, user_nickname: str, video_id: str, content: str):
        """追加用户评论到上下文"""

    def add_bot_reply(self, user_nickname: str, video_id: str, content: str):
        """追加机器人回复到上下文"""
```

---

## 5. 回复生成策略

### 5.1 回复生成策略（优先级从高到低）

| 优先级 | 策略 | 说明 |
|--------|------|------|
| 1 | 违禁词过滤 | 评论含违禁词 → 跳过（不回复） |
| 2 | 用户超限 | 用户超限 → 跳过 |
| 3 | 固定回复规则 | 精确/模糊匹配关键词 → 返回预设模板 |
| 4 | LLM 生成 | 无规则匹配 → 调用 LLM 生成回复 |
| 5 | 默认回复 | LLM 失败或生成内容含违禁词 → 返回默认回复 |

### 5.2 固定回复规则（ReplyRule）

```python
@dataclass
class ReplyRule:
    id: int
    keyword: str          # 触发关键词
    reply_template: str   # 回复模板
    match_type: str       # 'exact' | 'contains' | 'regex'
    reply_type: str       # 'fixed' | 'llm' | 'default'
    llm_model: str        # 使用的模型（如 ollama/qwen2.5:7b）
    enabled: bool
```

**匹配逻辑：**
- `exact`: 评论内容 == keyword（忽略空格）
- `contains`: keyword in comment_content（子串包含）
- `regex`: 正则匹配（灵活但需用户提供正则）

**多规则优先级：** 最长 keyword 优先匹配（避免"买"和"怎么买"冲突）

### 5.3 LLM 生成

当没有匹配到任何关键词规则时，使用 LLM 生成回复：

**Prompt 模板：**
```
你是抖音主播的AI助手，正在回复粉丝评论。
视频主题：{video_title}
评论历史（最近{limit}条）：
{context_history}

当前评论：
评论者：{nickname}
内容：{comment_content}

请生成一条简短、自然的回复（20字以内）：
```

**模型可配置：** 通过 `reply_type='llm'` 的规则可指定使用的模型，默认使用配置中的 `default_llm_model`

### 5.4 违禁词过滤

- **评论过滤**：评论含违禁词 → 跳过该评论
- **生成后过滤**：LLM 生成的回复内容含违禁词 → 降级为默认回复（如"感谢支持！"）
- **预置违禁词**（初始数据）：
  - 微商类：微信、QQ、加我、私信、看主页
  - 广告类：联系我、购买、链接
  - 违禁内容：政治敏感词（预置空，后续手动添加）

### 5.5 默认回复

当 LLM 不可用或生成内容违禁时，使用默认回复模板：
`"感谢支持！"`

---

## 6. CLI 命令设计

```bash
# 对指定视频运行自动回复
python main.py auto-reply --video-id 7632946497323076904

# 对所有已发布视频运行（定时任务用）
python main.py auto-reply --all --headless

# 管理用户配置
python main.py auto-reply --set-limit --user 张三 --daily 3 --total 20
python main.py auto-reply --add-blocked-word "微信"
python main.py auto-reply --list-blocked-words

# 管理回复规则
python main.py auto-reply --add-rule --keyword "怎么买" --template "点击主页链接查看"
```

---

## 7. 实现顺序

```
Phase 1 — 数据库层
  Step 1.1:  创建新表（user_reply_configs, reply_history, reply_context, blocked_words）
  Step 1.2:  更新 comments 表新增 user_nickname 列（如不存在）
  Step 1.3:  更新 auto_reply_rules 表新增字段

Phase 2 — 核心服务
  Step 2.1:  CommentFilter（评论过滤）
  Step 2.2:  UserProfileService（用户配置与计数）
  Step 2.3:  ReplyContextService（上下文管理）
  Step 2.4:  ReplyRulesService（规则 CRUD）

Phase 3 — 回复生成
  Step 3.1:  LLM 回复生成（复用现有 llm_client）
  Step 3.2:  ReplyBotWorkflow（浏览器自动化执行回复）

Phase 4 — 主服务 + CLI
  Step 4.1:  AutoReplyService 主流程编排
  Step 4.2:  main.py 新增 auto-reply 子命令

Phase 5 — 验证
  Step 5.1:  对一个视频运行自动回复，验证完整流程
```

---

## 8. 关键文件

| 文件 | 改动 |
|------|------|
| `src/services/database.py` | 新增建表 SQL |
| `src/services/comment_service.py` | 复用 `get_comments`，新增按昵称查询 |
| `src/services/auto_reply_service.py` | 新增 |
| `src/services/comment_filter.py` | 新增 |
| `src/services/user_profile_service.py` | 新增 |
| `src/services/reply_context_service.py` | 新增 |
| `src/services/reply_rules_service.py` | 新增 |
| `src/platform_adapter/reply_bot_workflow.py` | 新增（复用 comment_workflow.reply_to_comment） |
| `src/platform_adapter/douyin_adapter.py` | 新增 `auto_reply` 方法 |
| `main.py` | 新增 `auto-reply` CLI 命令 |
