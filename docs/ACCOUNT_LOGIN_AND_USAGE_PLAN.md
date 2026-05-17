---
doc_status: current
doc_category: mainline
last_reviewed: 2026-05-13
model_usage: 管理后台账号登录、邮箱验证码、用户用量控制的实施方案。
---

> 文档状态：当前主线方案。用于后续实现“账号登录 + 163 邮箱验证码 + 每用户用量控制”。

# 账号登录与用量控制方案

更新时间：2026-05-13

## 目标

管理后台需要从当前的简单用户名/密码登录，升级为可运营的账号体系：

1. 用户通过邮箱验证码登录，验证码由 163 SMTP 服务发送。
2. 每个登录用户有角色权限：超级管理员、运营管理员、运营编辑、查看者。
3. 超级管理员可以设置每个用户的每日、每月、累计用量。
4. 视频生成、视频发布、自动回复等消耗型动作都要先检查额度，再记录用量。
5. 保留现有 Streamlit 管理后台和 SQLite 本地数据库，先做轻量可靠版。

## 当前项目基础

项目已有这些基础能力：

- 登录入口：`src/web/components/auth.py`
- 用户管理页：`src/web/app.py` 的 `page_users()`
- 用户配置表：`user_reply_configs`
- 回复限流：`src/services/user_profile_service.py`

当前 `user_reply_configs` 更偏“抖音评论回复对象”的限流配置，不适合作为长期账号主表。建议保留它给自动回复使用，新增独立账号表。

## 推荐登录方式

第一版建议使用“邮箱 + 验证码”：

```text
用户输入邮箱
  -> 系统检查邮箱是否是已启用账号
  -> 生成 6 位验证码
  -> 通过 163 SMTP 发送验证码
  -> 用户输入验证码
  -> 校验成功后写入 Streamlit session
  -> 进入管理后台
```

不建议第一版开放任意邮箱自注册。账号由超级管理员先创建，避免后台被陌生人占用额度。

## 163 SMTP 配置

`.env` 建议增加：

```env
SMTP_HOST=smtp.163.com
SMTP_PORT=25
SMTP_USERNAME=your_163_email@163.com
SMTP_PASSWORD=your_163_smtp_authorization_code
SMTP_FROM=your_163_email@163.com
SMTP_USE_SSL=false
LOGIN_CODE_TTL_MINUTES=10
LOGIN_CODE_COOLDOWN_SECONDS=60
```

注意：`SMTP_PASSWORD` 用 163 邮箱的 SMTP 授权码，不是网页登录密码。

如果使用 163 的 465 端口，则把 `SMTP_PORT` 改成 `465`，并把 `SMTP_USE_SSL` 改成 `true`。当前提供的配置使用 25 端口，所以本地 `.env` 应保持 `SMTP_USE_SSL=false`。

旧版 Python 字典配置可以这样映射：

| 旧字段 | 新 `.env` 字段 | 说明 |
|---|---|---|
| `sender_email` | `SMTP_USERNAME` / `SMTP_FROM` | 发件邮箱 |
| `sender_password` | `SMTP_PASSWORD` | 163 SMTP 授权码 |
| `smtp_server` | `SMTP_HOST` | SMTP 服务器 |
| `smtp_port` | `SMTP_PORT` | 当前为 25 |
| `receiver_email` | 不固定入库 | 登录验证码应发送到用户输入的邮箱；该字段只适合做测试收件人 |

## 数据表设计

### accounts

后台登录账号主表：

```sql
CREATE TABLE IF NOT EXISTS accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT UNIQUE NOT NULL,
    display_name    TEXT,
    role            TEXT DEFAULT 'viewer',
    status          TEXT DEFAULT 'active',
    created_at      TEXT,
    updated_at      TEXT,
    last_login_at   TEXT
);
```

### login_verification_codes

验证码表，只保存验证码哈希，不保存明文：

```sql
CREATE TABLE IF NOT EXISTS login_verification_codes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT NOT NULL,
    code_hash       TEXT NOT NULL,
    purpose         TEXT DEFAULT 'login',
    expires_at      TEXT NOT NULL,
    used_at         TEXT,
    attempt_count   INTEGER DEFAULT 0,
    created_at      TEXT
);
```

### usage_quotas

每个用户的额度配置：

```sql
CREATE TABLE IF NOT EXISTS usage_quotas (
    account_id          INTEGER PRIMARY KEY,
    daily_generate_limit INTEGER DEFAULT 5,
    monthly_generate_limit INTEGER DEFAULT 100,
    total_generate_limit INTEGER DEFAULT 1000,
    daily_publish_limit INTEGER DEFAULT 3,
    monthly_publish_limit INTEGER DEFAULT 60,
    daily_reply_limit INTEGER DEFAULT 50,
    monthly_reply_limit INTEGER DEFAULT 1000,
    is_unlimited       INTEGER DEFAULT 0,
    updated_at         TEXT,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);
```

### usage_events

所有消耗动作都写流水，统计时从流水聚合：

```sql
CREATE TABLE IF NOT EXISTS usage_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL,
    event_type      TEXT NOT NULL,
    amount          INTEGER DEFAULT 1,
    resource_id     TEXT,
    status          TEXT DEFAULT 'success',
    created_at      TEXT,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);
```

`event_type` 第一版建议固定为：

- `video_generate`
- `video_publish`
- `comment_reply`
- `framepack_import`

## 用量扣减规则

建议按“成功后扣量”为主：

| 动作 | 检查时机 | 扣量时机 |
|---|---|---|
| 生成视频 | 点击生成前 | 视频文件成功输出后 |
| 发布视频 | 调用发布前 | 抖音上传进入待审核或发布成功后 |
| 自动回复 | 每条回复前 | 回复成功后 |
| FramePack 导入 | 导入前 | 文件导入并完成检查后 |

如果后续生成任务变长，可以升级成“先预占、失败释放”的模式。

## 管理后台页面调整

`用户管理` 页面建议增加：

- 新建账号：邮箱、显示名、角色、初始额度。
- 启用/禁用账号。
- 设置额度：每日生成、每月生成、累计生成、每日发布、每月发布、每日回复、每月回复。
- 查看用量：今日、本月、累计。
- 重置用量：只对特殊情况开放给超级管理员。

视频页和自动回复页在执行动作前统一调用：

```text
usage_service.ensure_quota(account_id, event_type)
```

动作成功后调用：

```text
usage_service.record_usage(account_id, event_type, resource_id)
```

## 代码落点

建议新增文件：

```text
src/services/account_service.py
src/services/email_verification_service.py
src/services/usage_quota_service.py
```

建议调整文件：

```text
src/services/database.py
src/web/components/auth.py
src/web/app.py
src/shared/config.py
.env.example
```

## 分阶段实施

### 第一阶段：可登录、可设额度

- 增加账号表、验证码表、额度表、用量流水表。
- 接入 163 SMTP 发验证码。
- 后台登录改成邮箱验证码。
- 用户管理页可以创建账号和设置额度。

### 第二阶段：接入核心动作

- 视频生成前检查 `video_generate` 额度。
- 视频发布前检查 `video_publish` 额度。
- 自动回复前检查 `comment_reply` 额度。
- 看板展示当前用户今日/月度用量。

### 第三阶段：运营增强

- 增加登录失败锁定。
- 增加验证码发送频率限制。
- 增加账号操作审计日志。
- 支持管理员导出用量流水。

## 安全建议

- 验证码有效期默认 10 分钟。
- 同邮箱验证码发送冷却默认 60 秒。
- 验证码错误 5 次后作废。
- SMTP 授权码只放 `.env`，不要提交到仓库。
- 登录 session 只保存 account_id、email、role，不保存验证码或 SMTP 信息。
- 超级管理员账号必须手动初始化，不允许公开注册成超级管理员。

## 当前结论

先用 163 SMTP 邮箱验证码作为登录入口，后台由超级管理员创建账号和设置额度。额度不要散落在各个页面里判断，而是统一通过 `usage_quota_service` 检查和记录，这样后续无论是单人口播、双角色视频、FramePack 半自动导入，还是自动回复，都能统一计量。
