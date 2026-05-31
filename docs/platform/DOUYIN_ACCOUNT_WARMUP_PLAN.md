---
doc_status: current
doc_category: implementation_plan
last_reviewed: 2026-05-30
model_usage: 抖音账号养号/活跃维护计划。用于记录上传视频账号的低频活跃维护、内容偏好训练、评论区浏览和可控点赞能力；CLI 测试版已完成。
---

> 文档状态：当前平台支线文档。CLI 测试版已完成：支持多账号网页登录、随机观看、按视频时长倍率停留、自动下滑、评论区打开/滚动、可控视频点赞和评论点赞；不做批量作弊或绕过平台风控。

# 抖音账号养号/活跃维护计划

更新时间：2026-05-30

## 一句话定位

为负责上传推广视频的抖音账号增加一个“低频活跃维护”支线：用户在网页端自行登录账号后，系统自动不定期下滑同领域视频，并为每条视频设置随机观看时长，帮助账号保持基础活跃和内容兴趣垂直度。

## 目标

- 让上传视频的账号保持基础活跃，不长期只发视频不浏览。
- 让账号兴趣更接近小说推广、剧情解说、短剧、网文、听书等相关领域。
- 给后续视频发布前后提供轻量运营动作，例如发布前自动浏览同类内容、发布后查看评论。
- 把账号维护动作做成可记录、可暂停、可人工确认的任务。

## 非目标

- 不做刷播放、刷粉、批量评论或无上限点赞。
- 不做批量账号矩阵作弊。
- 不做绕过验证码、滑块、设备校验或平台风控。
- 不做高频、长时间、机械化刷视频；只做低频随机浏览。
- 不发布无意义评论或诱导性垃圾评论。

## 合规边界

必须遵守：

- 只操作用户自己授权登录的抖音账号。
- 只做低频、可解释的正常浏览和运营动作。
- 关注、评论、私信、收藏类动作默认不执行；视频点赞和评论点赞必须显式传参开启，并受单次最大数量限制。
- 遇到验证码、异常登录、风控提示时立即停止，提示用户手动处理。
- 不伪造设备、IP、地理位置或用户身份。
- 不用该功能制造虚假互动数据。

## 运营策略

### 账号兴趣方向

小说推广账号建议围绕以下内容维护兴趣：

| 方向 | 关键词示例 | 目的 |
|---|---|---|
| 小说推文 | 小说推荐、番茄小说、网文推荐 | 贴近推广内容领域 |
| 剧情解说 | 剧情反转、爽文、悬疑故事 | 学习视频钩子和节奏 |
| 短剧切片 | 短剧推荐、逆袭、重生 | 学习强冲突标题和评论区话术 |
| 听书/书单 | 听书、书荒推荐、书单 | 建立阅读类兴趣标签 |
| 同类达人 | 小说解说号、推文号 | 参考标题、封面、评论引导 |

### 日常动作建议

| 动作 | 频率 | 自动化程度 | 说明 |
|---|---|---|---|
| 打开抖音网页端 | 每日 1 次 | 自动 | 用户需先网页登录；系统只复用当前登录态 |
| 浏览同类视频 | 每日 5-20 条 | 自动 | 优先读取视频时长，按 0.1-2.0 倍随机停留；可用 `--max-watch` 封顶 |
| 不定期下滑 | 单次任务内自动 | 自动 | 下滑间隔随机，偶尔暂停，不连续高速滑动 |
| 搜索关键词 | 每日 1-3 个 | 自动 | 围绕小说、短剧、剧情解说 |
| 查看评论区 | 每日 1-5 条视频 | 自动/可关闭 | 默认至少打开 1 次评论区并下滑 3 次，不自动发评论 |
| 视频点赞 | 单次 0-N 个 | 显式开启 | 默认关闭；用 `--like-probability` 和 `--max-likes` 控制 |
| 评论点赞 | 单次 0-N 个 | 显式开启 | 默认关闭；用 `--comment-like-probability` 和 `--max-comment-likes` 控制 |
| 收藏候选视频 | 每日 0-3 个 | 人工确认 | 只收藏对脚本/封面有参考价值的视频 |
| 关注同类账号 | 每周 0-5 个 | 人工确认 | 避免短时间大量关注 |
| 评论互动 | 每周 0-3 条 | 人工确认 | 只发真实、有内容的评论 |
| 查看自己视频数据 | 发布后当天/次日 | 自动 | 同步播放、评论、点赞等数据 |

## 任务流程

### 账号登录入口

账号登录由用户手动完成，系统提供账号入口、独立浏览器会话目录和登录态检测。账号密码可以保存在自动化浏览器自身的密码管理/登录会话中，但项目代码、配置文件和业务数据库不保存明文账号密码。

```text
用户填写账号标识
  -> 系统打开独立浏览器用户目录
  -> 用户手动输入账号密码、扫码或验证码登录抖音网页端
  -> 浏览器保存该账号的登录会话/密码
  -> 系统检测登录成功
  -> 保存该账号的浏览器会话目录
  -> 后续养号任务复用该会话
```

账号入口需要记录：

| 字段 | 说明 |
|---|---|
| `account_id` | 本地账号标识，例如 `douyin_novel_01` |
| `display_name` | 备注名，例如 `小说推广号 A` |
| `douyin_uid` | 抖音公开 ID 或 UID，能看到就填 |
| `login_name` | 脱敏登录名，例如 `138****1234` 或备注邮箱 |
| `phone_hint` | 脱敏手机号提示，不保存完整手机号 |
| `purpose` | 账号用途，例如 `novel_promotion` |
| `status` | `active` / `paused` / `disabled` |
| `notes` | 账号备注，例如绑定平台、内容方向、注意事项 |
| `keywords` | 该账号养号关键词列表 |
| `browser_profile_dir` | 该账号独立浏览器用户目录 |
| `browser_channel` | 浏览器类型，例如 `chromium` / `chrome` / `msedge` |
| `login_status` | `unknown` / `logged_in` / `expired` / `blocked` |
| `last_login_at` | 最近一次用户手动登录时间 |
| `last_warmup_at` | 最近一次养号任务时间 |

MVP 不在项目侧保存明文账号密码，只保存浏览器会话目录和登录状态。浏览器 profile 内部可以由浏览器保存账号密码、cookie、localStorage、sessionStorage。登录过期、验证码、扫码确认、短信验证都由用户在浏览器里手动处理。

### 多账号隔离

后续可能维护多个抖音账号，因此必须使用账号级隔离：

```text
account_id=douyin_novel_01 -> data/douyin_warmup/accounts/douyin_novel_01/profile/
account_id=douyin_novel_02 -> data/douyin_warmup/accounts/douyin_novel_02/profile/
```

隔离规则：

- 每个 `account_id` 使用独立浏览器 profile 目录。
- 不同账号之间不共用 cookie、localStorage、缓存和密码库。
- 养号任务必须显式指定 `--account-id`，不默认混用账号。
- 同一时间默认只运行一个账号的浏览任务，避免多账号并发触发异常。
- 每个账号单独记录登录状态、浏览日志、关键词偏好和异常截图。
- 删除账号时只删除该账号对应 profile 和日志，不影响其他账号。

### 自动浏览策略

用户先在网页端完成登录，系统只负责在已登录会话中自动浏览：

```text
检查网页端登录态
  -> 默认打开精选页 `https://www.douyin.com/jingxuan`
  -> 点击“推荐”入口，必要时关闭“我知道了”引导
  -> 读取 `.time-current` / `.time-duration` / `.time-live-tag`
  -> 按视频时长乘以 0.1-2.0 的随机倍率停留
  -> 默认至少打开 1 次评论区，评论区下滑 3 次
  -> 可选随机视频点赞/评论点赞
  -> 随机等待 1-8 秒
  -> 下滑到下一条视频
  -> 达到本次视频数或时长上限后停止
```

随机参数建议：

| 参数 | 建议范围 |
|---|---|
| 每条视频观看时长 | 读取到时长时按视频时长的 0.1-2.0 倍随机；`--max-watch 0` 表示不封顶 |
| 下滑前额外等待 | 1-8 秒 |
| 单次浏览视频数 | 5-20 条 |
| 单次任务总时长 | 3-12 分钟 |
| 每日任务次数 | 1-3 次 |
| 两次任务间隔 | 2-8 小时随机 |
| 打开评论区概率 | 默认至少 1 次，可叠加 `--comment-probability` |
| 评论区下滑次数 | 默认 3 次 |
| 单次视频点赞数 | 默认 0，显式开启后由 `--max-likes` 限制 |
| 单次评论点赞数 | 默认 0，显式开启后由 `--max-comment-likes` 限制 |

行为限制：

- 默认不点赞；显式开启时按概率和上限执行。
- 不关注。
- 不收藏。
- 不评论。
- 不私信。
- 不连续高速下滑。
- 检测到验证码、异常登录、风控提示后停止自动浏览，并默认保持浏览器打开等待用户手动处理。

### MVP 流程

```text
检查抖音登录态
  -> 默认打开精选页 `https://www.douyin.com/jingxuan`
  -> 输入小说/短剧相关关键词
  -> 自动随机停留浏览少量视频
  -> 自动不定期下滑下一条视频
  -> 记录视频标题、作者、链接、停留时间
  -> 同步自己账号近期视频数据
  -> 输出养号日志
```

### 发布前流程

```text
准备发布推广视频
  -> 自动浏览 5-10 条同领域视频
  -> 收集 3-5 个标题/评论关键词
  -> 生成本条视频标题和评论区关键词候选
  -> 发布视频
```

### 发布后流程

```text
视频发布后 1-3 小时
  -> 查看视频是否发布成功
  -> 抓取首批评论
  -> 生成回复建议
  -> 用户确认后回复
```

## 模块规划

当前实现位置：

```text
src/platform_adapter/douyin_warmup.py
```

当前模块：

| 模块/对象 | 职责 |
|---|---|
| `DouyinWarmupService` | 养号任务编排 |
| `WarmupAccount` | 多账号 profile 和账号元数据 |
| `WarmupResult` | 单次养号任务结果和日志结构 |
| `BrowserSession` | 复用现有 Playwright 持久化浏览器会话 |

## 数据记录

当前本地目录：

```text
data/douyin_warmup/
  accounts/
    douyin_novel_01/
      profile/
      account.json
      logs/
    douyin_novel_02/
      profile/
      account.json
      logs/
  sessions/
  keywords/
  candidates/
  logs/
```

建议 `.gitignore` 忽略：

```text
data/douyin_warmup/
```

每次任务记录：

```json
{
  "session_id": "20260528_120000",
  "account": "douyin_xxx",
  "mode": "daily",
  "keywords": ["小说推荐", "短剧反转"],
  "videos_seen": 8,
  "items": [
    {
      "index": 1,
      "watch_seconds": 120,
      "video_timing": {"duration_text": "02:32", "duration_seconds": 152},
      "watch_plan": {"duration_ratio": 0.789, "reason": "duration_ratio"},
      "opened_comments": true,
      "comment_scrolls": 3,
      "comment_likes": 2,
      "liked": false
    }
  ],
  "status": "completed"
}
```

## CLI 规划

当前命令：

```bash
python main.py douyin-warmup-login --account-id "douyin_novel_01"
python main.py douyin-warmup --account-id "douyin_novel_01" --mode daily
python main.py douyin-warmup-report --account-id "douyin_novel_01" --days 7
python main.py douyin-warmup-account list
python main.py douyin-warmup-account show --account-id "douyin_novel_01"
python main.py douyin-warmup-account set --account-id "douyin_novel_01" --display-name "小说推广号A" --login-name "138****1234" --keywords "小说推荐,短剧反转,番茄小说"
```

如果养号过程中遇到登录页、验证码或安全验证，默认浏览器不会立刻关闭。用户在浏览器里处理完成后，回到终端按回车，系统会保存会话并退出。若明确希望检测到异常时直接关闭，可以加：

```bash
python main.py douyin-warmup --account-id "douyin_novel_01" --mode daily --close-on-blocked
```

自动浏览参数：

```bash
python main.py douyin-warmup --mode daily --min-watch 8 --max-watch 45 --max-videos 20
python main.py douyin-warmup --account-id "douyin_novel_01" --mode daily --duration-minutes 8 --keyword "小说推荐"
```

按视频时长倍率停留，长视频可看完整甚至两遍：

```bash
python main.py douyin-warmup --account-id "douyin_novel_01" --mode daily --url "https://www.douyin.com/jingxuan" --min-watch 8 --max-watch 0 --duration-ratio-min 0.1 --duration-ratio-max 2.0 --max-videos 5
```

强制打开评论区并下滑 3 次，不点赞：

```bash
python main.py douyin-warmup --account-id "douyin_novel_01" --mode daily --url "https://www.douyin.com/jingxuan" --max-videos 1 --min-comment-opens 1 --comment-scrolls 3 --keep-open
```

打开评论区并随机点赞可见评论：

```bash
python main.py douyin-warmup --account-id "douyin_novel_01" --mode daily --url "https://www.douyin.com/jingxuan" --max-videos 1 --min-comment-opens 1 --comment-scrolls 3 --comment-like-probability 1 --max-comment-likes 2 --keep-open
```

10 个视频内最多 5 个视频赞、最多 5 个评论赞：

```bash
python main.py douyin-warmup --account-id "douyin_novel_01" --mode daily --url "https://www.douyin.com/jingxuan" --max-videos 10 --like-probability 0.5 --max-likes 5 --min-comment-opens 1 --comment-scrolls 3 --comment-like-probability 0.5 --max-comment-likes 5
```

`douyin-warmup` 默认不进搜索页，默认入口是：

```text
https://www.douyin.com/jingxuan
```

如果要强制指定入口：

```bash
python main.py douyin-warmup --account-id "douyin_novel_01" --mode daily --url "https://www.douyin.com/jingxuan"
```

如果需要观察页面，任务完成后保持浏览器打开：

```bash
python main.py douyin-warmup --account-id "douyin_novel_01" --mode daily --url "https://www.douyin.com/jingxuan" --max-videos 1 --keep-open
```

如果明确要走搜索页，再加 `--use-search`：

```bash
python main.py douyin-warmup --account-id "douyin_novel_01" --mode daily --keyword "小说推荐" --use-search
```

## 管理后台规划

Streamlit 后续新增“账号养号”页面：

| 页面区域 | 功能 |
|---|---|
| 账号状态 | 显示登录态、最近执行时间、异常提示 |
| 账号登录入口 | 选择账号标识，打开独立浏览器窗口，由用户手动登录，浏览器可保存密码 |
| 多账号管理 | 新增、切换、禁用、删除账号 profile，查看各账号登录状态 |
| 兴趣配置 | 配置关键词、领域、屏蔽词 |
| 执行计划 | 设置每日/发布前/发布后自动浏览任务 |
| 自动浏览参数 | 设置观看时长范围、视频数量、任务间隔、评论区查看概率 |
| 人工确认 | 后续如开启收藏、关注、评论，动作进入待确认列表 |
| 执行日志 | 展示浏览记录、失败截图、风控提示 |

## 风控策略

必须内置硬限制：

| 限制项 | 建议值 |
|---|---|
| 每日自动浏览视频数 | 5-20 条 |
| 单次任务时长 | 3-12 分钟 |
| 单条视频观看时长 | 优先按视频时长倍率随机；无时长时按 `--min-watch/--max-watch` |
| 下滑前额外等待 | 1-8 秒随机 |
| 每日任务次数 | 1-3 次 |
| 多账号并发 | 默认关闭，同一时间只跑一个账号 |
| 每日搜索关键词 | 1-3 个 |
| 每日自动评论 | 0 条，不自动发布评论 |
| 每日自动关注 | 0 条，必须人工确认 |
| 每日自动点赞 | 默认关闭，显式开启并受单次上限限制 |
| 遇到验证码/异常 | 立即停止 |

## 开发阶段

### 第 1 阶段：网页登录 + 自动浏览版

目标：用户手动登录抖音网页端后，系统自动搜索关键词、随机停留看视频、不定期下滑，但不做任何互动。

交付：

- `douyin-warmup-login --account-id ...` 打开该账号独立浏览器窗口。
- 用户手动登录后，浏览器保存账号密码/登录会话，系统检测并保存登录状态。
- 多账号使用不同 `account_id` 和 profile 目录隔离。
- 关键词配置。
- 浏览器默认打开推荐页；只有显式传 `--use-search` 时才进入搜索页。
- 自动随机停留观看视频。
- 自动不定期下滑下一条。
- 默认至少打开一次评论区并下滑评论 3 次。
- 可读取视频时长并按倍率随机停留。
- 可显式开启视频点赞和评论点赞，默认关闭并受上限控制。
- 记录候选视频链接、标题、停留时间和执行日志。
- 输出养号日志。

状态：2026-05-30 已完成 CLI 测试版。

### 第 2 阶段：计划任务和随机调度

目标：支持每日 1-3 次随机时间执行自动浏览任务。

交付：

- `douyin-warmup --mode daily`。
- 随机但受控的停留时间和任务间隔。
- 异常/验证码检测后停止。
- 本地日志和截图。

### 第 3 阶段：发布前后运营联动

目标：和小说推广视频发布链路联动。

交付：

- 发布前搜索同类内容，生成标题/评论关键词参考。
- 发布后同步评论，生成回复建议。
- 用户确认后执行回复。

## 与小说推广支线关系

小说推广视频支线负责：

```text
小说内容 -> 推广脚本 -> 推广视频 -> 发布/绑定
```

账号养号支线负责：

```text
账号活跃维护 -> 兴趣方向维护 -> 发布前后轻运营
```

两者通过以下数据关联：

- 小说推广关键词。
- 发布视频 ID。
- 评论区关键词/搜索引导。
- 同类视频标题和评论区高频词。

## 当前不做

- 不做自动评论。
- 不做自动关注。
- 不做自动收藏。
- 不做无上限、批量化刷互动；视频点赞和评论点赞必须显式开启并限制数量。
- 不做多账号并发养号；多账号只做隔离保存和按账号单独执行。
- 不做绕过验证码、滑块和风控。
- 不做无上限点赞；视频点赞和评论点赞只能通过显式参数开启并限制数量。

## 下一步

1. 确认养号账号是否就是发布推广视频的抖音号。
2. 确认日常兴趣关键词，例如小说推荐、短剧反转、番茄小说、书荒推荐。
3. 用 `douyin-warmup-login --account-id ...` 为每个账号完成一次网页登录。
4. 后续如需要再做每日随机调度和发布前后联动。
