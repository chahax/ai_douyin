# Seedance 2.5 代码接入

## 已接入范围

项目现在支持两条可切换渠道：

- `dreamina_cli`：即梦官方 CLI，复用即梦网页账户与套餐积分；当前默认渠道。
- `byteplus_api`：BytePlus LAS 异步任务接口，需要独立 API Key 和 API 余额。

两条渠道共用同一套分段提示词、任务报告和看板：

- 创建视频任务。
- 使用任务 ID 查询 `queued`、`running`、`succeeded`、`failed` 等状态。
- 成功后立即下载临时视频链接。
- 从 `analysis_video_prompt_pack/v1` 中选择 `S01` 等单个分段提交。
- 即梦 CLI 支持文生视频，以及图片、视频、音频混合的“全能参考”。
- BytePlus API 支持 URL 或平台资产形式的图片、视频和音频参考素材。
- 默认生成 480p、9:16、带原生音频的视频；可在配置文件中覆盖。
- 默认只做 dry-run；只有明确传入 `--submit` 才会产生云端任务和费用。

BytePlus 官方配置：

```text
Base URL: https://operator.las.ap-southeast-1.bytepluses.com/api/v1
Model: dreamina-seedance-2-5-260628
Create: POST /contents/generations/tasks
Query:  GET  /contents/generations/tasks/{task_id}
```

Seedance 2.5 当前 API 支持4–30秒、480p/720p、24fps和原生音频。任务成功后返回的视频预签名链接只有有限有效期，因此等待成功后应立即下载。

## 相关代码

- `src/content_factory/seedance_client.py`：API 客户端、参数校验、轮询和下载。
- `scripts/seedance_generate.py`：从分段提示词包提交单个镜头。
- `tests/test_seedance_client.py`：完全离线的请求、轮询、失败和下载测试。

## 第一步：选择渠道

配置文件默认使用已购买网页套餐的即梦 CLI：

```dotenv
SEEDANCE_PROVIDER=dreamina_cli
DREAMINA_CLI_PATH=data/tools/dreamina/dreamina.exe
DREAMINA_MODEL_VERSION=seedance2.5
SEEDANCE_DEFAULT_RATIO=9:16
SEEDANCE_DEFAULT_RESOLUTION=480p
```

官方安装入口为：

```bash
curl -fsSL https://jimeng.jianying.com/cli | bash
```

本项目在 Windows 上把官方可执行文件放在 `data/tools/dreamina/dreamina.exe`，不要求修改系统 PATH。第一次使用执行：

```powershell
& "data\tools\dreamina\dreamina.exe" login
& "data\tools\dreamina\dreamina.exe" user_credit
```

CLI 使用 OAuth Device Flow；登录状态保存在当前 Windows 用户的 `.dreamina_cli` 目录并自动复用。`user_credit` 返回即梦账户的真实剩余积分，查询本身不产生生成费用。

CLI 1.4.17 当前暴露的主要能力：

- `text2video`：文生视频。
- `image2video`：单图生视频。
- `frames2video`：首尾帧视频。
- `multiframe2video`：2–20 张图片的连贯故事视频。
- `multimodal2video`：图片、视频和音频全能参考；本项目有参考素材时使用此命令。
- `query_result`、`list_task`、`session`：查询、下载、历史和会话管理。

Seedance 2.5 在 CLI 中属于 VIP 模型，支持 4–30 秒、480p/720p/1080p，以及 1:1、3:4、4:3、16:9、9:16、21:9。实际可用性仍由账号套餐和服务端队列决定。

### 可选：BytePlus API

需要在 BytePlus ModelArk/LAS 的 `ap-southeast-1` 区域开通 Seedance 2.5，并创建同区域 API Key。即梦 CLI 的 OAuth 登录不能作为 BytePlus API Key 使用，两条渠道的余额也不混用。

将密钥写入项目根目录 `.env`，不要把真实密钥提交到 Git：

```dotenv
SEEDANCE_API_KEY=你的_API_Key
SEEDANCE_PROVIDER=byteplus_api
SEEDANCE_BASE_URL=https://operator.las.ap-southeast-1.bytepluses.com/api/v1
SEEDANCE_MODEL=dreamina-seedance-2-5-260628
SEEDANCE_TIMEOUT_SECONDS=120
SEEDANCE_POLL_INTERVAL_SECONDS=5
```

如果使用其他官方区域或火山方舟后续提供的兼容接口，只需使用控制台展示的 Base URL 和 Model ID 覆盖对应变量，客户端代码不需要改。

## 第二步：先预览请求

下面的命令不会访问云端，也不会产生费用：

```powershell
.\.venv\Scripts\python.exe scripts\seedance_generate.py `
  data\video_analysis\40426344181-1-192\video_prompt_pack.seedance_2_5.json `
  --segment S01 `
  --provider dreamina_cli `
  --output-dir data\video_generation\seedance
```

预览保存在：

```text
data/video_generation/seedance/segment-S01.seedance.json
```

重点检查请求中的：

- `provider` 是否为计划使用的渠道。
- `model` 是否为 `seedance2.5`（即梦）或控制台已开通的模型 ID（BytePlus）。
- `duration` 是否为4–30之间的整数。
- `ratio` 是否为 `9:16`。
- `generate_audio` 是否为 `true`。
- `content[0].text` 是否包含准确对白、口型和字幕要求。

## 第三步：提交并下载

确认请求和预估费用后，显式添加 `--submit --wait --download`：

```powershell
.\.venv\Scripts\python.exe scripts\seedance_generate.py `
  data\video_analysis\40426344181-1-192\video_prompt_pack.seedance_2_5.json `
  --segment S01 `
  --provider dreamina_cli `
  --output-dir data\video_generation\seedance `
  --submit `
  --wait `
  --download
```

产物：

```text
data/video_generation/seedance/segment-S01.seedance.json
data/video_generation/seedance/segment-S01.mp4
```

只提交、不等待：

```powershell
.\.venv\Scripts\python.exe scripts\seedance_generate.py `
  data\video_analysis\40426344181-1-192\video_prompt_pack.seedance_2_5.json `
  --segment S01 `
  --submit
```

任务 ID 会写入报告。即梦任务可用 `dreamina query_result --submit_id=<id>` 查询；BytePlus 任务可通过 `SeedanceClient.get_task(task_id)` 查询。

## Python 直接调用

```python
from src.content_factory.seedance_client import SeedanceClient, SeedanceConfig

prompt = """现实主义竖屏剧情短片。粉衣女子在霓虹街头边走边说：
“这大哥三天就给我转了一万二。”同步生成普通话人声、准确口型和中文字幕。"""

config = SeedanceConfig.from_env()
with SeedanceClient(config) as client:
    request = client.build_task_payload(
        prompt,
        duration=4,
        ratio="9:16",
        resolution="480p",
        generate_audio=True,
        watermark=False,
    )
    created = client.create_task(request)
    final = client.wait_for_task(created["id"], timeout_seconds=1800)
    client.download_video(final, "data/video_generation/seedance/S01.mp4")
```

## 默认画幅与清晰度

统一默认值位于 `.env`：

```dotenv
SEEDANCE_DEFAULT_RATIO=9:16
SEEDANCE_DEFAULT_RESOLUTION=480p
```

CLI 会自动读取这两个值；临时覆盖仍可传入 `--ratio` 和 `--resolution`。

## 用量与本地额度看板

Streamlit 侧边栏“Seedance 用量”页面可选择“即梦 CLI（网页套餐）”或“BytePlus API”，读取 `data/video_generation/seedance/*.seedance.json` 并按渠道过滤，展示：

- 成功、运行中、失败和请求预览数量。
- 成功生成总秒数。
- 按清晰度估算的消费金额。
- 当前自然月的本地预算余额和时长额度余额；进入新月份后自动重新计算。
- 每个任务的模型、时长、画幅、清晰度、音频状态和任务 ID。
- 即梦 CLI 登录后可直接查询账户真实剩余积分；BytePlus 仍显示本地预算估算。

可选配置：

```dotenv
SEEDANCE_MONTHLY_BUDGET_USD=50
SEEDANCE_MONTHLY_QUOTA_SECONDS=300
SEEDANCE_ESTIMATED_USD_PER_SECOND_480P=0.2056
SEEDANCE_ESTIMATED_USD_PER_SECOND_720P=0.4621
SEEDANCE_USAGE_REPORT_DIR=data/video_generation/seedance
```

这些余额是本地预算台账，不是 BytePlus 账号权威余额。视频生成 API返回单任务用量，但不返回账号剩余免费额度；平台免费额度、代金券和最终账单仍需在 Activation Management / Billing 控制台核对。

## 参考素材

命令行可重复传入以下参数：

```text
--reference-image https://example.com/character.png
--reference-video https://example.com/camera-motion.mp4
--reference-audio https://example.com/voice.wav
```

即梦 CLI 渠道传入本地文件路径，并自动上传；只要存在任意参考素材，项目就会使用 `multimodal2video`。BytePlus 渠道使用公开 URL、`asset://<ASSET_ID>` 或受支持的图片/音频 Base64；视频不要使用 Base64。临时 URL必须在任务执行期间持续有效。

官方接口对真实人物参考素材有额外授权和素材库要求。调用前应确认人物授权，并按照控制台要求开通素材库能力。

## 当前边界

- CLI 一次提交一个分段，避免误操作一次创建62个付费任务。
- 目前不自动重试失败任务，防止重复计费；失败原因会保留在任务报告。
- API Key和即梦 OAuth 状态不会写入请求预览、任务报告或控制台输出。
- 预签名下载链接不持久保存为正式资产，脚本会在成功后立即下载到本地。
