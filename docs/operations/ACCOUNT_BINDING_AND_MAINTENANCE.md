# 抖音账号绑定与运营维护

## 目标

系统以 `AccountRuntimeContext` 作为运营账号的唯一运行入口，将以下三者保存为一对一关系：

- 运营账号（稳定 `account_uuid` / `account_key`）
- 独立浏览器环境（用户目录和 storage state）
- 经过确认的真实抖音公开身份（昵称、头像、公开 UID/OpenID/sec_uid）

系统不保存抖音账号密码。存在绑定缺失、登录过期、浏览器环境变化或身份不匹配时，采集、同步、维护和发布均拒绝执行。

## 管理员绑定流程

1. 管理员进入“热门选题 → 账号策略”，选择运营账号。
2. 优先使用开放平台 OAuth；配置项为 `DOUYIN_CLIENT_KEY`、`DOUYIN_CLIENT_SECRET`、`DOUYIN_OAUTH_REDIRECT_URI`。
3. 没有开放平台应用凭据时，点击“登录并绑定抖音账号”，在独立浏览器环境中扫码。
4. 关闭登录窗口后，系统从真实个人主页读取昵称、头像、公开 UID/sec_uid。
5. 管理员核对预览并点击“确认身份并保存唯一绑定”。换绑必须再次明确勾选确认。
6. “检测登录健康”会重新访问真实页面。登录过期、验证码拦截或身份不一致都会更新绑定状态。

官方 OAuth 身份仍需和当前浏览器页面身份组合确认，确保开放平台身份与浏览器环境确实属于同一运营账号。

## 发布门禁

视频管理页必须先选择登录健康的运营账号，并显示“即将使用 XX 抖音账号发布”。管理员需勾选本次身份确认。选题卡账号与当前账号 UUID 不一致、绑定不健康或页面验真不一致时，系统拒绝发布。

同步后的作品记录带有 `account_uuid/account_key`，不同账号之间不会再互相覆盖或误判删除。

## 账号健康与运营维护

旧的随机“自动养号”入口已升级为受控维护：

- `daily`：登录健康检查，以及有限的账号相关内容调研。
- `pre-publish`：采集近期同领域样本、标签族和可见用户反馈，进入内容分析与机会排序。
- `playback`：从本次分析结果选择达到相关度阈值的视频，按相关度和点赞表现分配不同观看时长，使用绑定浏览器实际播放，并在结束后读取 `video.currentTime` 验证真实播放进度。
- `post-publish`：同步本账号作品指标和评论，不访问随机推荐页。

采集先做账号相关度预检，命中排除词或相关度不足的内容不会落库。长时播放维护会扩大排序和相关标签族采样，并排除最近 7 天已经验证播放的视频。日志记录不同视频的真实视频 ID、标题、作者、标签、页面可见时长、关联关键词、相关度、可见指标、发布时间和 URL。

播放模式默认不互动。管理员可在单次任务中显式启用自动点赞或安全自动评论。互动预算不再使用固定的每日次数，而是以“当天累计通过真实播放校验的视频数 × 动态比例”计算；基础比例由管理员设置，系统再依据本批候选的领域相关度和点赞表现上调或下调。单条视频也会独立计算互动概率，因此点赞率或同批次点赞表现更高、且与账号领域更相关的视频，获得点赞的概率更高。

能同时取得点赞数和播放量时，系统使用真实点赞率；搜索卡片只有一个页面展示指标时，仅计算同批次相对表现，并在日志中标记为代理指标，绝不伪装成真实点赞率。评论仍限制同一作者每天最多 1 条、间隔至少 30 分钟。评论只从批准的领域模板生成，评论区内容仅用于识别表达族，不逐字复制；手机号、微信/QQ、链接、私信引流、免费咨询等广告表达，以及与评论区或账号历史高度相似的文本会被拦截。关注仍不自动执行。

维护任务之间不再设置账号级固定冷却，避免一次只读健康检查阻塞随后播放；每个账号仍应用互斥锁、每日运行额度和连续三次异常后的熔断。成功标准为：

- 登录身份健康；
- `daily/pre-publish` 采集到不同且相关的视频；
- `playback` 至少有一个候选通过真实 `currentTime` 增量校验，且互动未超过策略额度；
- `post-publish` 完成作品数据同步；
- 非播放模式外部互动数始终为零。

维护日志位于 `data/account_maintenance/<account_key>/`，完整研究日志位于 `data/trend_research_runs/`。

兼容 CLI：

```powershell
python main.py douyin-maintenance --account-id account01 --mode daily --authorization-reference "内部工单-001" --headless
python main.py douyin-maintenance --account-id account01 --mode pre-publish --authorization-reference "内部工单-001" --headless
python main.py douyin-maintenance --account-id account01 --mode playback --authorization-reference "内部工单-001" --max-videos 20 --per-video-seconds 90 --total-minutes 20 --min-relevance-score 60
python main.py douyin-maintenance --account-id account01 --mode playback --authorization-reference "内部工单-002" --max-videos 10 --auto-like --like-ratio 0.25 --auto-comment --comment-ratio 0.05
python main.py douyin-maintenance --account-id account01 --mode post-publish --headless
```

`--like-ratio` / `--comment-ratio` 是动态计算的基础比例，不是固定执行比例。兼容参数 `--max-likes` / `--max-comments` 只作为可选的单次紧急安全上限；默认 `0` 表示只使用比例预算。
