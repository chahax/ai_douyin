# Seedance 型号、调用方式与指南

本页是本项目后续调整视频提示词、模型与参数的入口。首选保持 **火山方舟 API / Seedance 2.0 Mini / 480p / 9:16 / 原生音频**。注册型号不会替用户购买、开通或自动切换至其他型号。

## 已保存的官方指南

2026-09-07 将用户提供的四份正文原样复制到项目，保留表格、示例代码、图片和视频链接。没有下载远程示例媒体。归档日期是保存时间，不代表文档发布日期；原文未提供发布日期。

| 文档 | 本地完整副本 | 原文地址 |
| --- | --- | --- |
| 2.0 系列能力与 API | [seedance_2_0_api.md](2026-09-07/seedance_2_0_api.md) | [官方能力说明](https://docs.volcengine.com/docs/82379/2291680) |
| 2.0 系列提示词 | [seedance_2_0_prompt.md](2026-09-07/seedance_2_0_prompt.md) | [官方提示词指南](https://docs.volcengine.com/docs/82379/2222480) |
| 2.5 能力与 API | [seedance_2_5_api.md](2026-09-07/seedance_2_5_api.md) | [官方能力说明](https://docs.volcengine.com/docs/82379/2607688) |
| 2.5 提示词 | [seedance_2_5_prompt.md](2026-09-07/seedance_2_5_prompt.md) | [官方提示词指南](https://docs.volcengine.com/docs/82379/2607689) |

[归档清单](2026-09-07/manifest.json) 记录来源附件、真实保存时间、文件字节数和 SHA-256。副本中的官方 Skill 安装说明只是保留原文，本次没有安装或执行外部 Skill。

## 型号配置

可执行配置位于 [config/seedance_models.json](../../../config/seedance_models.json)。以下规格来自上述用户提供的官方文档快照，不等于当前账号已开通这些型号。

| 型号 | Model ID | 时长 | 清晰度 | 输出格式 |
| --- | --- | --- | --- | --- |
| Seedance 2.0 Mini（首选） | `doubao-seedance-2-0-mini-260615` | 4–15 秒或 `-1` | 480p / 720p | MP4 |
| Seedance 2.0 Fast | `doubao-seedance-2-0-fast-260128` | 4–15 秒或 `-1` | 480p / 720p | MP4 |
| Seedance 2.0 | `doubao-seedance-2-0-260128` | 4–15 秒或 `-1` | 480p / 720p / 1080p / 4k | MP4 |
| Seedance 2.5 | `doubao-seedance-2-5-260628` | 4–30 秒或 `-1` | 480p / 720p / 1080p | MP4 / MOV |

`-1` 表示模型在有效区间内选择时长。项目的指定 45 秒剧本仍按锁定分镜逐镜传入整数时长，不自动改成 `-1`。2.0 系列最多 9 图、3 视频、3 音频，共 15 项；2.5 最多 30 图、10 视频、10 音频，共 50 项。2.0 的音频参考须搭配图或视频，2.5 支持单独音频参考。

## 三种渠道

| 渠道 | 接入方式 | 身份与费用 |
| --- | --- | --- |
| `ark_api`（本项目首选） | `https://ark.cn-beijing.volces.com/api/v3` | `.env` 的 `ARK_API_KEY`，火山方舟 API 账单 |
| `byteplus_api` | `https://operator.las.ap-southeast-1.bytepluses.com/api/v1` | `SEEDANCE_API_KEY`，BytePlus LAS 账单；原有默认模型为 `dreamina-seedance-2-5-260628` |
| `dreamina_cli` | 项目 `DreaminaCLIClient` 调用本地 `dreamina.exe` | 本机 OAuth 登录与即梦积分；原有默认 `seedance2.5` |

三个渠道独立鉴权，不共享余额、网页积分或模型开通状态。API Key 不作为命令行参数，不写进提示词、回执或指南。方舟模型资格/充值与开通具体型号是两个步骤；`ModelNotOpen` 必须在方舟控制台解决，不能自动换模型继续扣费。

## 项目命令行

查看型号，无网络请求：

```powershell
.venv\Scripts\python.exe scripts/seedance_generate.py --list-models
```

输入是本项目的 `analysis_video_prompt_pack/v1` 提示词包。以下命令默认仅预览请求；实际生成才追加 `--submit --wait --download`。不同试验使用不同输出目录，存在付费请求回执时禁止覆盖和重提。

```powershell
# 保持当前首选：Mini 480p
.venv\Scripts\python.exe scripts/seedance_generate.py <提示词包.json> --segment S01 --provider ark_api --model doubao-seedance-2-0-mini-260615 --duration 6 --resolution 480p --ratio 9:16 --output-dir data/video_generation/mini_preview

# 单次换用其他型号，不修改项目首选
.venv\Scripts\python.exe scripts/seedance_generate.py <提示词包.json> --segment S01 --provider ark_api --model doubao-seedance-2-0-fast-260128 --duration 6 --resolution 480p --output-dir data/video_generation/fast_preview
.venv\Scripts\python.exe scripts/seedance_generate.py <提示词包.json> --segment S01 --provider ark_api --model doubao-seedance-2-0-260128 --duration 6 --resolution 1080p --output-dir data/video_generation/standard_preview
.venv\Scripts\python.exe scripts/seedance_generate.py <提示词包.json> --segment S01 --provider ark_api --model doubao-seedance-2-5-260628 --duration 20 --resolution 480p --output-dir data/video_generation/v25_preview
```

引用素材时，`--reference-image`、`--reference-video`、`--reference-audio` 可以重复传入；使用公开可读 URL、素材 `asset://` ID，图片/音频还可用支持的 Base64。API 入口不能直接把本地磁盘视频路径当作 URL。

| 任务 | CLI 选择 | 2.5 必要参数 |
| --- | --- | --- |
| 文生视频 | `--task-type text` | 只有文字 |
| 全模态参考 | `--task-type reference` + 引用素材参数 | 提示词明确各素材职责；模型仍会判断意图 |
| 首帧 | `--task-type first_frame --first-frame <图片URL>` | `--ratio adaptive` |
| 首尾帧 | `--task-type first_last_frame --first-frame <URL> --last-frame <URL>` | `--ratio adaptive` |
| 视频编辑 | `--task-type edit --reference-video <URL>` | `--ratio adaptive --duration -1`；程序发送 `omni_reference_task_type=edit` |
| 视频延长 | `--task-type extend --reference-video <URL>` | `--ratio adaptive`；程序发送 `omni_reference_task_type=extend` |

2.5 可传 `--output-format mov`。2.0 系列不发送 2.5 独有字段。首尾帧角色不能与普通参考素材混用。素材数量、音频单独引用、型号时长/清晰度、2.5 任务参数约束在请求创建前检查；URL 可访问性、肖像素材资格、媒体尺寸/时长仍需按原文检查，不能由参数校验推断平台会接受。

制作中的双人短剧使用 [run_script_video.py 流程](../../SCRIPT_VIDEO_RUN.md)，保留剧本、执行计划、参考审核与单镜授权范围。一般 API 调用入口不代替该内容质量检查。

## REST 与 Python 调用

四个方舟型号共用任务协议：

- 创建：`POST /contents/generations/tasks`，`Authorization: Bearer <ARK_API_KEY>`，返回 `id`。
- 查询：`GET /contents/generations/tasks/{id}`，成功时读取 `content.video_url`、`usage`，按返回字段保存实际用量。
- 状态与产物必须以服务端回执为准。没有任务 ID 的错误不能伪装成运行中；网络超时也不能盲目重提。

可复用本项目客户端，无需额外 SDK：

```python
from dataclasses import replace
from src.content_factory.seedance_client import SeedanceClient, SeedanceConfig

config = SeedanceConfig.from_env("ark_api", require_key=False)  # 仅构造预览
config = replace(config, model="doubao-seedance-2-5-260628")
with SeedanceClient(config) as client:
    payload = client.build_task_payload(
        "替换为已审阅的项目提示词", duration=6,
        resolution="480p", ratio="9:16", generate_audio=True,
    )
    print(payload)  # 不包含 API Key，不创建任务
```

官方也提供 Python `volcenginesdkarkruntime.Ark` SDK（安装包 `volcengine-python-sdk[ark]`），调用方法为 `client.content_generation.tasks.create(...)` 和 `.get(task_id=...)`。四份完整指南已保留官方 Python、cURL 等示例，本项目继续复用现有 HTTP 客户端。

## 余额、免费额度与本地用量

2026-09-07 核查：截图中的 **Doubao-Seed-2.0-mini** 是文字模型，其 500,000 tokens 不能用于判断本项目 **Doubao-Seedance-2.0-mini** 视频模型的剩余额度。

- 账户资金余额：官方费用中心提供 [QueryBalanceAcct](https://www.volcengine.com/docs/6269/1223898?lang=zh)，版本 `2022-01-01`，返回可用余额、现金余额、欠费和冻结金额等。它不返回某个视频模型还能生成多少秒。
- 身份验证：官方 [Python SDK](https://github.com/volcengine/volcengine-python-sdk) 的 `BILLINGApi.query_balance_acct` 使用 AK/SK 签名。`ARK_API_KEY` 是推理凭证，不能替代管理接口的 AK/SK。只读余额查询已于 2026-09-08 使用用户配置的管理凭证取得真实结果；页面按查询时间展示，不把历史余额当作实时余额。配置见 [余额查询配置](BALANCE_SETUP.md)。
- 视频模型的免费额度、资源包余量与安心体验限制：本次未找到公开文档支持用现有推理 API Key 直接查询这些剩余量。应在对应 Seedance 视频型号的开通管理、资源包或账单页面确认；不接入未经官方文档证实的 `/quota` 接口。
- 单任务用量：视频任务回执中的 `usage` 是已发生用量，不是剩余额度。接口缺失该字段时显示“未返回”，不能记为零费用。不要拿文字模型额度、即梦积分或其他渠道用量相减推算方舟余额。

`SetLimitExceeded` 表示当前模型的设置限制阻止了推理，不足以判断充值余额为零。只有真实任务成功回执才能说明该次生成已执行；后续可用额度仍应单独查询。

## 剧本工作流中的首帧衔接

`scripts/run_script_video.py` 支持 `save-last-frame`、`bind-first-frame`、`preview --first-frame` 和 `submit --first-frame`。成功视频自动保存 API 原始尾帧；遗漏时可只读补取，不重新生成。登记过的方舟原始尾帧会核对本地哈希、当前账号任务和有效期，并使用任务返回的原始 URL；其他符合接口要求的图片可使用 Base64。实际输入为 `role=first_frame`、`ratio=adaptive`，继续要求返回尾帧。

首帧绑定到目标分镜、机位、剧本和执行计划哈希；绑定时检查构图、人物身份和开场状态，提交时再次核对图片哈希。同一机位的连续动作可以从上一镜尾帧开始；从双人中景切到人物特写时，需另准备目标机位首帧，不能直接把双人尾帧当作特写。首帧只约束画面，不能单独保证声线与口型一致。

2026-09-07 的 S01 试验实际为纯文字输入，已启用 `return_last_frame=true` 并保存原始尾帧。本轮补齐流程和无付费测试，没有把旧的纯文字试验改标为首帧生成，也没有提交后续镜头。完整命令与审核示例见 [剧本制作流程](../../SCRIPT_VIDEO_RUN.md)。

2026-09-08 完整短片已接入 `--reference-video`：验证本账号成功任务与本地原片哈希，使用服务端原始 `video_url` 支持换机位。依据 [官方肖像参考说明](https://docs.volcengine.com/docs/82379/2608626#trust-model-output)，本账号近 30 天的指定模型原始产物可作为肖像参考；不能把跨平台重绘、裁剪压缩或其他账号的素材视为原始产物。官方全文与来源哈希已保存至 [2026-09-08 快照](2026-09-08/portrait_reference_official.md)。素材审核拒绝时保留回执，不修改素材规避审核。

## 后续更新提示词和参数的约定

1. 先确认渠道、Model ID 和任务意图，再阅读对应版本的完整指南。保留每次新指南快照与哈希，不覆盖本次原文。
2. 2.0 系列提交提示词使用动作/镜头顺序；2.5 支持整数秒时间轴或镜头顺序，不将小数秒频次当作精确控制保证。
3. 2.5 先说明素材编号与用途，再写主体、场景、事件、镜头和声音；台词、音效、音乐、字幕按指南分开。编辑/延长必须明确对应意图，避免被误判为普通参考生成。
4. 项目人物座位、机位轴线、道具与左右手连续性、无旁白、对白和明确结局约束继续保留。参数正确不等于动作或空间正确，首镜须实际看片通过才能继续。
5. 修改 [型号配置](../../../config/seedance_models.json) 和 [请求校验](../../../src/content_factory/seedance_models.py) 后，用无付费的请求构造测试验证；实际模型测试保持单镜范围，记录目标时长、真实时长和实际回执，不套用其他渠道价格。

原文存在细节差异时保留原文：例如 2.5 编辑输出时长误差在两篇中分别写作约 0.3 秒和不超过 0.4 秒。本项目不以其中一个阈值假定成片合格，实际测量并报告差异。
