---
doc_status: deferred
doc_category: archived_design
last_reviewed: 2026-05-25
model_usage: 背景图生成后图片理解质检与重抽设计。用于接入 MiniMax-M2.7-highspeed 检查伪文字、牌匾、墙面字画、主题偏离等问题。
---

> 文档状态：已暂缓。用户决定先废弃图片理解质检方案，本文仅保留为历史设计参考；当前生产能力仍以 `CURRENT_CAPABILITIES.md` 为准。

# 背景图图片质检与重抽设计

更新时间：2026-05-25

## 背景

Presenter 动漫数字人主讲流程已经支持：

```text
关键词/文章
  -> 口播稿
  -> 分段音频
  -> ComfyUI 背景图
  -> 字幕/角色合成
  -> 视频
```

但社会、法律、劳动、法院、工伤、平台用工等主题在背景图生成时容易出现以下问题：

- 画面中出现伪中文、伪英文、数字。
- 出现牌匾、公告栏、证书、文件正文、墙上字画。
- 出现法院门口、机构门头、办公室墙面等高风险文字载体。
- 主题动作不明确，只是泛化的门口、墙面、桌面。
- 人物过大或近景背影抢占数字人主讲角色空间。
- 下方字幕区和右下角色区被复杂物体占用。

单纯继续增加 prompt 负向词不能彻底解决，因为图片模型会在“法律/法院/劳动”语义下自动补全门头、牌匾和文字。需要在图片生成后增加图片理解质检能力，发现问题后自动重抽或回退安全背景。

用户已有可用的图片理解模型：

```text
MiniMax-M2.7-highspeed
```

## 目标

新增背景图生成后的自动质检流程：

```text
ComfyUI 生成背景图
  -> 图片理解模型质检
  -> 合格：保留
  -> 不合格：换 seed / 换安全场景重抽
  -> 多次失败：回退本地安全背景
```

质检重点：

- 是否有可读文字。
- 是否有伪文字、类文字、乱码字符。
- 是否有牌匾、证书、公告栏、海报、墙上字画。
- 是否有法院/机构门头/办公室墙面等高风险载体。
- 是否有人物过大、近景背影、大脸。
- 下方 35% 字幕区是否干净。
- 右下数字人角色区是否干净。
- 画面是否和当前文案主题、动作、主体相关。

## 非目标

- 不在本次设计中替换整个 ComfyUI 工作流。
- 不强制依赖 MiniMax；MiniMax 不可用时流程应降级为不质检或本地规则检查。
- 不做长期图片资产管理系统。
- 不把图片上传到公开存储；只把本地图片作为模型输入。

## 当前涉及代码

### 背景生成主逻辑

`src/content_factory/presenter/background_resolver.py`

当前相关方法：

```python
resolve_segment_backgrounds()
build_background_prompt_with_plan()
_create_comfy_background()
_create_anime_background()
_visual_plan()
_social_legal_plan()
```

当前问题：

- `_create_comfy_background()` 只负责生成图片，不判断图片内容是否合格。
- `build_background_prompt_with_plan()` 虽然已经对社会/法律/劳动类增加安全规则，但仍无法保证模型不生成文字和牌匾。
- `segments.json` 已记录 `background_prompt` 和 `background_plan`，但没有记录图片质检结果。

需要修改：

- 在 ComfyUI 图片生成成功后调用图片质检。
- 不合格时支持重抽。
- 把质检结果写入分段元数据或单独文件。

建议新增方法：

```python
_create_reviewed_comfy_background(prompt, output_path, seed, segment_text, plan) -> tuple[bool, dict]
_review_background_image(image_path, segment_text, prompt, plan) -> dict
_fallback_safe_background(output_path, cue, scene_text) -> None
```

### Presenter Segment 模型

`src/content_factory/presenter/models.py`

当前已有：

```python
background_path: str
background_prompt: str
background_plan: dict
```

建议新增：

```python
background_review: dict = field(default_factory=dict)
background_retry_count: int = 0
```

用于写入 `segments.json`，方便排查每张图为什么被接受或重抽。

### 配置项

`src/shared/config.py`

当前已有：

```python
COMFYUI_HOST
COMFYUI_PORT
COMFYUI_MAIN_PATH
COMFYUI_CHECKPOINT
COMFYUI_STEPS
COMFYUI_CFG
```

建议新增：

```python
ENABLE_BACKGROUND_IMAGE_REVIEW: bool = False
BACKGROUND_REVIEW_PROVIDER: str = "minimax"
BACKGROUND_REVIEW_MODEL: str = "MiniMax-M2.7-highspeed"
BACKGROUND_REVIEW_MAX_RETRIES: int = 2
BACKGROUND_REVIEW_MIN_SCORE: int = 75
MINIMAX_API_KEY: str = ""
MINIMAX_BASE_URL: str = ""
```

`.env` 示例：

```env
ENABLE_BACKGROUND_IMAGE_REVIEW=true
BACKGROUND_REVIEW_PROVIDER=minimax
BACKGROUND_REVIEW_MODEL=MiniMax-M2.7-highspeed
BACKGROUND_REVIEW_MAX_RETRIES=2
BACKGROUND_REVIEW_MIN_SCORE=75
MINIMAX_API_KEY=你的key
MINIMAX_BASE_URL=你的MiniMax接口地址
```

### 新增图片理解客户端

建议新增文件：

```text
src/shared/vision_review_client.py
```

职责：

- 读取本地图片。
- 转 base64 或 multipart，调用 MiniMax 图片理解接口。
- 要求模型只输出 JSON。
- 解析 JSON，失败时返回保守结果。

建议接口：

```python
class VisionReviewClient:
    def review_background(self, image_path: Path, segment_text: str, prompt: str, plan: dict) -> dict:
        ...
```

## MiniMax 质检提示词

建议新增：

```text
docs/prompts/background-image-review.txt
```

提示词目标：

```text
你是短视频背景图质检员。请检查这张图是否适合作为动漫数字人主讲背景。

输入：
- 当前口播段落
- 背景生成 prompt
- 背景计划
- 图片

判断标准：
1. 画面不能有可读文字、伪文字、乱码字符、数字、标语、Logo。
2. 不能有牌匾、证书、公告栏、墙上字画、海报、文件正文。
3. 法律/劳动/社会主题不能出现法院门头、机构牌子、办公室证书墙。
4. 人物不能过大，不能是近景背影，不能抢占右下数字人区域。
5. 下方 35% 字幕区必须干净。
6. 右下数字人区域必须干净。
7. 画面主体和动作要与段落主题相关。

只输出 JSON。
```

建议输出 JSON：

```json
{
  "ok": false,
  "score": 42,
  "has_text_or_pseudo_text": true,
  "has_signboard_or_plaque": true,
  "has_wall_art_or_certificate": true,
  "has_large_person": false,
  "safe_area_clean": true,
  "theme_relevance": "weak",
  "problems": [
    "画面中央有机构门头和伪中文",
    "墙上有牌匾/公告类文字载体"
  ],
  "suggested_fix": "改成城市路边、外卖头盔、配送包、手机倒扣、关闭文件夹，不要机构门头和墙面"
}
```

## 重抽策略

### 第一版最小策略

```text
for attempt in 0..max_retries:
  generate image with seed + attempt * 101
  review image
  if ok and score >= min_score:
    keep image
    break
  else:
    continue

if all failed:
  use local fallback safe background
```

第一版不做复杂 prompt 改写，只换 seed。

### 第二版增强策略

如果图片不合格，且 `suggested_fix` 可用：

```text
原 prompt
  + Review feedback: avoid detected problems
  + Suggested safer scene: ...
```

或直接切换安全场景池：

```text
platform_worker_rights -> evidence_phone -> boundary_line -> labor_safety
```

### 第三版 OCR/规则混合

后续可加入：

- OCR 检测可读文字。
- CLIP/视觉模型判断图像风险。
- 自动裁切检测下方字幕区和右下角角色区是否干净。

## 数据记录

建议在 `segments.json` 中新增：

```json
{
  "background_review": {
    "ok": false,
    "score": 42,
    "problems": ["..."],
    "suggested_fix": "...",
    "attempt": 1,
    "review_model": "MiniMax-M2.7-highspeed"
  },
  "background_retry_count": 1
}
```

同时可选写入：

```text
data/presenter*/<stamp>/background_reviews.json
data/presenter_assets/<stamp>/background_reviews.json
```

用于快速汇总所有背景图的质量。

## 当前涉及文档

需要新增或更新：

| 文档 | 处理建议 |
|---|---|
| `docs/BACKGROUND_IMAGE_REVIEW_DESIGN.md` | 本设计文档 |
| `docs/CURRENT_CAPABILITIES.md` | 实现后增加“背景图图片理解质检”能力说明 |
| `docs/USER_GUIDE.md` | 实现后增加 `.env` 配置和测试命令 |
| `docs/DEVELOPMENT_PROGRESS.md` | 实现后记录阶段进度 |
| `docs/README.md` | 增加本文档索引 |
| `docs/prompts/background-image-review.txt` | 新增图片质检提示词 |
| `docs/prompts/background-plan-generation.txt` | 保持构图提示词；后续可根据质检反馈继续优化 |

## 测试方案

### 单图质检测试

先用已有问题图片测试 MiniMax：

```bash
python -m src.shared.vision_review_client --image data/presenter_assets/xxx/backgrounds/bg_001.png --text "这曾是无数外卖骑手、网约车司机、网络主播心中的困惑。"
```

期望：

- 能识别伪文字/牌匾/墙面证书。
- 能输出 JSON。
- 能给出 `ok=false` 和明确问题。

### 生产预览测试

```bash
python main.py presenter-assets --input-mode article_direct --text-file data/articles/你的文章.txt --title "ceshi" --max-segments 6
```

检查：

- `segments.json` 中有 `background_review`。
- 不合格图片会重抽。
- 最终保留图片问题少于当前版本。
- ComfyUI 仍然只在本次流程中启动一次，完成后关闭。

### 完整视频测试

```bash
python main.py presenter --input-mode article_direct --text-file data/articles/你的文章.txt --title "ceshi" --max-segments 12
```

## 风险

| 风险 | 处理 |
|---|---|
| MiniMax 图片理解接口格式不确定 | 先封装独立 client，便于适配 |
| 质检模型误判 | 保留 `score` 阈值和人工复核文件 |
| 重抽次数多导致耗时明显增加 | 默认关闭，按需启用；限制最大重抽次数 |
| 图片上传涉及隐私 | 只传本地生成背景，不传用户原文全文；必要时脱敏段落 |
| 仍然生成伪文字 | 后续加入 OCR 或更换 SDXL 模型/安全场景池 |

## 推荐实施顺序

1. 新增配置项。
2. 新增 `docs/prompts/background-image-review.txt`。
3. 新增 `VisionReviewClient`，先支持 MiniMax 单图 JSON 质检。
4. 在 `BackgroundResolver` 中接入生成后质检。
5. 把质检结果写入 `PresenterSegment.background_review`。
6. 实现最多 1-2 次重抽。
7. 更新 `CURRENT_CAPABILITIES.md`、`USER_GUIDE.md`、`DEVELOPMENT_PROGRESS.md`。
8. 用前 6 段文章测试法律/劳动类背景。
