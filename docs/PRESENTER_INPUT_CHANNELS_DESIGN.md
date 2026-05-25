---
doc_status: current
doc_category: implementation_plan
last_reviewed: 2026-05-24
model_usage: Presenter 输入通道改造设计。用于把关键词生成、文章直接生成、文章提炼生成拆成清晰的三条入口。
---

> 文档状态：当前设计修改文档。能力现状仍以 `CURRENT_CAPABILITIES.md` 为准；本文用于指导下一步代码实现。

# Presenter 输入通道改造设计

更新时间：2026-05-24

## 背景

当前动漫数字人主讲流程已经能跑通：

```text
关键词/文本
  -> 口播稿
  -> 分段
  -> 分段音频
  -> ComfyUI 背景图
  -> Sonic 狐狸数字人层
  -> 视频合成
```

但输入入口还不够清晰。现在主要依赖：

- `--keywords`：关键词生成口播稿。
- `--text`：直接传入完整口播文本。

实际使用中还需要支持“已有长文章”。长文章有两种不同需求：

- 文章直接制作：文章本身就是口播稿，只需要清洗、分段、配音、出图。
- 文章提炼制作：文章太长或不是口播风格，需要先提炼成短视频口播稿。

因此建议把 Presenter 输入明确拆成 3 个通道。

## 目标

新增并明确 3 种输入模式：

| 模式 | 输入 | 处理方式 | 适用场景 |
|---|---|---|---|
| `keywords` | 关键词 | RAG 可用时检索知识库；不可用时用关键词直出素材；再生成口播稿 | 临时选题、批量选题 |
| `article_direct` | 文章文本/文章文件 | 不重写观点，只做清洗、断句、长度规范，然后直接进入分段/音频/图片 | 用户已有成稿 |
| `article_extract` | 文章文本/文章文件 | LLM 提炼核心观点、痛点、金句和行动建议，再改写成短视频口播稿 | 长文、公众号、笔记、资料稿 |

## 非目标

- 不在本次改造中重做视频合成器。
- 不改变 Sonic 狐狸默认人物层。
- 不改变 ComfyUI 按需启动/生成后关闭策略。
- 不把文章导入长期知识库；文章输入只作用于本次生成。

## 当前涉及代码

### CLI 入口

`main.py`

当前相关命令：

```text
presenter
presenter-assets
quick
auto-publish
```

当前行为：

- `presenter --keywords`：关键词生成完整视频。
- `presenter --text`：直接使用文本生成完整视频。
- `presenter-assets --keywords`：关键词生成“文本 + 分段音频 + 背景图”，不合成视频。
- `presenter-assets --text`：直接文本生成“文本 + 分段音频 + 背景图”，不合成视频。

需要修改：

- 给 `presenter` 和 `presenter-assets` 增加：

```text
--input-mode keywords|article_direct|article_extract
--text-file <path>
```

- `--keywords` 保持兼容，默认 `input_mode=keywords`。
- `--text` 保持兼容，默认可视为 `article_direct`，但只有在未指定 `--keywords` 时生效。

### Presenter 请求模型

`src/content_factory/presenter/models.py`

当前相关结构：

```python
@dataclass
class PresenterRequest:
    keywords: str = ""
    text: str = ""
    title: str = ""
    ...
    use_comfy_background: bool = True
```

需要新增：

```python
input_mode: str = "keywords"
text_file: str = ""
```

建议常量：

```python
INPUT_MODE_KEYWORDS = "keywords"
INPUT_MODE_ARTICLE_DIRECT = "article_direct"
INPUT_MODE_ARTICLE_EXTRACT = "article_extract"
```

### Presenter 主流程

`src/content_factory/presenter_pipeline.py`

当前关键方法：

```python
PresenterPipeline.run()
PresenterPipeline.run_assets_preview()
PresenterPipeline._resolve_script()
PresenterPipeline._synthesize_segments()
```

当前 `_resolve_script()` 行为：

```text
if request.text:
  return request.text
else:
  GenerationService._resolve_script_content(...keywords...)
```

需要改为：

```text
_resolve_script(request)
  -> 读取 text_file 或 text
  -> input_mode=article_direct：清洗文章并返回
  -> input_mode=article_extract：调用文章提炼提示词生成口播稿
  -> input_mode=keywords：走现有关键词生成
```

建议新增私有方法：

```python
_load_input_text(request) -> str
_clean_direct_article(text) -> str
_extract_article_script(text, request) -> str
```

### 文案生成服务

`src/services/generation_service.py`

当前相关能力：

- `GenerationService._resolve_script_content()`：关键词/RAG/随机书籍 -> wisdom -> 口播稿。
- `GenerationService.resolve_script()`：公开的关键词生成脚本文本接口。
- `_build_keyword_wisdom()`：RAG embedding 不可用时，用关键词直出素材，避免跑偏到随机书摘。

需要新增或复用：

- 可以新增 `resolve_article_script(text, hints)`，但最小实现可放在 `PresenterPipeline` 内部，避免扩大服务层范围。
- 如果后续 `quick`、`auto-publish` 也要支持文章提炼，再把文章提炼能力上移到 `GenerationService`。

### 脚本提示词

当前已有：

`docs/prompts/script-generation.txt`

用途：根据 wisdom 数据生成短视频口播稿。

需要新增：

`docs/prompts/article-to-presenter-script.txt`

用途：把长文章提炼成短视频口播稿。

建议输出 JSON：

```json
{
  "title": "短视频标题",
  "script_content": "60-90秒口播逐字稿",
  "visual_cues": ["画面建议1", "画面建议2"],
  "bgm_suggestion": "背景音乐建议"
}
```

### 背景图生成

`src/content_factory/presenter/background_resolver.py`

当前相关能力：

- `resolve_segment_backgrounds()`：按分段/时长分组生成背景图。
- `build_background_prompt_with_plan()`：优先 LLM 构图方案，失败回退规则。
- `_visual_plan()`：关键词规则兜底，包含 `legal_rules`。
- `_create_comfy_background()`：按需启动 ComfyUI，生成后关闭。

本次输入通道改造不需要大改背景生成。文章直接和文章提炼最终都会进入相同的分段文本，因此继续复用现有背景逻辑。

### 分段和音频

`src/content_factory/presenter/script_segmenter.py`

当前能力：把口播稿切成 `PresenterSegment`。

`src/content_factory/tts_engine.py`

当前能力：Edge-TTS/GPT-SoVITS 生成音频。

本次改造不需要修改分段和 TTS，只需要保证三种输入最终都返回干净的 `script`。

## 当前涉及文档

需要更新或引用：

| 文档 | 处理建议 |
|---|---|
| `docs/CURRENT_CAPABILITIES.md` | 实现后增加三输入通道说明 |
| `docs/USER_GUIDE.md` | 实现后增加 `--input-mode` 和 `--text-file` 示例 |
| `docs/DEVELOPMENT_PROGRESS.md` | 实现后记录 Presenter 输入通道完成情况 |
| `docs/prompts/script-generation.txt` | 保持关键词生成提示词 |
| `docs/prompts/background-plan-generation.txt` | 保持背景构图提示词 |
| `docs/PRESENTER_INPUT_CHANNELS_DESIGN.md` | 本设计文档 |

## 交互设计

### CLI 示例

关键词生成完整视频：

```bash
python main.py presenter --keywords "法律，规则" --title "法律，规则"
```

关键词生成预览资产，不合成视频：

```bash
python main.py presenter-assets --keywords "法律，规则" --title "法律，规则" --max-segments 16
```

文章直接生成完整视频：

```bash
python main.py presenter --input-mode article_direct --text-file data/articles/rule_law.txt --title "法律，规则"
```

文章直接生成预览资产：

```bash
python main.py presenter-assets --input-mode article_direct --text-file data/articles/rule_law.txt --title "法律，规则"
```

文章提炼生成完整视频：

```bash
python main.py presenter --input-mode article_extract --text-file data/articles/rule_law.txt --title "法律，规则"
```

文章提炼生成预览资产：

```bash
python main.py presenter-assets --input-mode article_extract --text-file data/articles/rule_law.txt --title "法律，规则"
```

### 管理后台建议

`src/web/app.py`

后续可在“在线制作/发布”表单增加：

```text
输入方式：
- 关键词生成
- 文章直接生成
- 文章提炼生成
```

对应输入控件：

- 关键词生成：关键词输入框。
- 文章直接生成：长文本框或上传 `.txt`。
- 文章提炼生成：长文本框或上传 `.txt`。

## 处理规则

### keywords

```text
keywords
  -> GenerationService.resolve_script()
  -> RAG 可用则检索知识库
  -> RAG 不可用则 _build_keyword_wisdom()
  -> script-generation prompt
  -> script_content
```

要求：

- 关键词必须作为主线。
- 不允许随机书摘覆盖关键词主题。
- RAG 不可用时直接用关键词生成，不阻塞。

### article_direct

```text
article text/file
  -> 清洗空白、标题、连续换行
  -> 可选长度裁剪或提示过长
  -> 直接作为 script_content
```

要求：

- 不改变文章核心表达。
- 不额外插入随机书摘。
- 不调用文章提炼 LLM。
- 如果文章太长，先限制最大字符数并在日志提示。

建议清洗：

```text
去掉 Markdown 标题符号
合并连续空行
去掉明显 URL
去掉多余空格
保留中文标点
```

### article_extract

```text
article text/file
  -> article-to-presenter-script prompt
  -> JSON script_content
  -> 分段音频和背景图
```

要求：

- 提炼而不是照搬。
- 生成 60-90 秒口播。
- 开头必须具体场景化。
- 保留文章核心观点，不引入无关书籍内容。
- 输出适合 TTS 的自然中文。

## 测试方案

### 编译检查

```bash
python -m py_compile main.py src/content_factory/presenter_pipeline.py src/content_factory/presenter/models.py src/services/generation_service.py
```

### 功能测试

关键词预览：

```bash
python main.py presenter-assets --keywords "法律，规则" --title "法律，规则" --max-segments 16
```

文章直接预览：

```bash
python main.py presenter-assets --input-mode article_direct --text-file data/articles/rule_law.txt --title "法律，规则" --max-segments 16
```

文章提炼预览：

```bash
python main.py presenter-assets --input-mode article_extract --text-file data/articles/rule_law.txt --title "法律，规则" --max-segments 16
```

完整视频：

```bash
python main.py presenter --input-mode article_extract --text-file data/articles/rule_law.txt --title "法律，规则" --max-segments 16
```

### 验收标准

- 3 种通道都能输出 `script.txt`、`segments.json`、分段音频和背景图。
- `presenter` 能进一步输出 mp4。
- `article_direct` 不大改原文。
- `article_extract` 能把长文章压缩成口播稿。
- `keywords` 在 RAG embedding 缺失时不再卡 HuggingFace 下载，也不跑偏到随机书摘。
- ComfyUI 按需启动，生成后关闭，无 `8190` 残留监听。

## 风险和后续优化

| 风险 | 处理 |
|---|---|
| 文章过长导致 LLM 超上下文 | 第一版限制字符数，后续做分块提炼 |
| 文章直接模式文本太长导致视频过长 | 给出字符数/时长提示，必要时让用户改用 article_extract |
| article_extract 改写偏离原文 | 提示词要求保留核心观点，并输出摘要理由用于审查 |
| 背景图仍出现伪文字 | 继续优化 `background_resolver.py` 场景词和负向 prompt |
| RAG embedding 缺失 | 建议安装 `nomic-embed-text`，当前已有关键词兜底 |

## 推荐实施顺序

1. 增加 `PresenterRequest.input_mode` 和 `text_file`。
2. 给 `main.py` 的 `presenter`、`presenter-assets` 增加 CLI 参数。
3. 在 `PresenterPipeline._resolve_script()` 里完成三通道分流。
4. 新增 `docs/prompts/article-to-presenter-script.txt`。
5. 跑三条 `presenter-assets` 测试。
6. 测试通过后更新 `USER_GUIDE.md` 和 `CURRENT_CAPABILITIES.md`。
