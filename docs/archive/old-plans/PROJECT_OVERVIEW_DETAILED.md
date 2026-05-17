---
doc_status: archived_do_not_use_as_current
doc_category: archive
last_reviewed: 2026-05-10
model_usage: 历史归档文档，仅用于追溯问题和避免重复踩坑；不要作为当前实现方案。
---

> 文档状态：历史归档文档，仅用于追溯问题和避免重复踩坑；不要作为当前实现方案。

# AI Douyin 项目详细说明（当前实现版）

> 文档目的：为后续你/我快速理解项目而写，尽量基于当前代码现状，而不是理想设计。
> 更新时间：2026-03-22

---

## 1. 项目定位

这是一个「人生方向/智慧内容」自动化生产项目，核心是：

1. 从书籍中提取可传播的人生智慧（随机或 RAG 检索）
2. 生成短视频口播文案
3. 用 TTS 合成音频（Edge 或 GPT-SoVITS）
4. 可选叠加 BGM，并归档输出

当前主产物是**音频**，视频合成模块在代码中有占位但主流程尚未完整打通。

---

## 2. 当前可运行主入口

入口文件：`main.py`

提供两个 CLI 子命令：

- `generate`：标准流程（可随机书摘 / 可 RAG）
- `quick`：一条命令快速生成（支持直接输入文本）

### 2.1 `generate` 流程（main.py）

1. 获取智慧内容
   - 有 `--topic`：走 RAG（`WisdomRetriever` + `WisdomExtractorRAG`）
   - 无 topic 或 RAG 失败：走随机书摘（`BookProcessor` + `WisdomExtractor`）
2. 生成文案（`ScriptGenerator`）
3. 合成语音（`TTSEngine`）
4. 可选 BGM 混音（`AudioMixer`）

### 2.2 `quick` 流程（main.py）

- 支持 `--text` 直接口播（跳过提取与文案生成）
- 支持 `--prompt/--keywords` 触发主题生成
- 支持输出归档（`finalize_output`）
- 支持 `--no-merge` 分段输出（尤其对 GPT-SoVITS 长文本有用）

---

## 3. 关键模块说明（按当前代码）

## 3.1 内容生成链路

### A) `src/content_factory/book_processor.py`

- 从 `data/books` 读取书籍
- 当前 `list_books()` 支持 `.txt/.pdf` 文件名识别
- `read_random_chunk()` 从文本中抽取相对完整段落
- 注意：`_read_pdf()` 目前是占位，返回空（即随机模式实质依赖 txt）

### B) `src/content_factory/wisdom_extractor.py`

- 用 `docs/prompts/book-extraction.txt` 提取人生智慧 JSON
- 若提示词文件不存在，会用内置 fallback prompt
- 调用 `llm_client.chat_completion(..., json_mode=True)`

### C) `src/content_factory/wisdom_extractor_rag.py`

- 输入：topic + 检索到的 chunks
- 拼接多段 context 后，生成融合型 wisdom JSON
- 用于替代“单段随机摘录”的提炼方式

### D) `src/content_factory/script_generator.py`

- 用 `docs/prompts/script-generation.txt` 生成口播文案 JSON
- 支持附加生成约束（keywords、emotion_type、target_audience 等）
- 自动清理“关注/点赞/评论/转发”类号召语

---

## 3.2 RAG 与向量库链路

### A) `src/rag_engine/wisdom_retriever.py`

- 启动 Chroma 向量库
- embedding 模型优先本地：`./data/models/text2vec-base-chinese`
- 本地不存在时 fallback 到 HF：`shibing624/text2vec-base-chinese`
- 提供 `search_wisdom(query, top_k=3)`

### B) `src/rag_engine/knowledge_importer.py`（已增强）

- 负责把书籍导入 Chroma
- 当前支持格式：
  - `.txt`
  - `.epub`（通过 zip 读取 html/xhtml 后去标签）
  - `.pdf`（依赖 `pypdf`）
- 对文本做分块（RecursiveCharacterTextSplitter）
- metadata 写入 `source_book`

### C) 向量库落盘位置

- `data/chroma_db/`
- 典型文件：`chroma.sqlite3` + hnsw 二进制索引

---

## 3.3 音频生成链路

### A) `src/content_factory/tts_engine.py`

- provider 可选：
  - `edge`（默认）
  - `gpt_sovits`
- 输出目录默认 `settings.VIDEOS_DIR`

### B) Edge TTS

- 文件：`src/content_factory/tts_providers/edge_tts_provider.py`
- 依赖 `edge-tts`
- 默认音色：`zh-CN-YunyangNeural`

### C) GPT-SoVITS

- 文件：`src/content_factory/tts_providers/gpt_sovits_provider.py`
- 支持 SDK 模式 + HTTP 模式回退
- 内含 CPU float32 patch、长文本自动切分、`no_merge` 分段生成
- 参考音频优先级：显式参数 > `data/ref_audio/{voice}.wav` > 默认 ref

### D) 输出归档

- `src/shared/output_manager.py`
- 归档命名：`时间戳_主题_slug_provider.扩展`
- 避免重名冲突

---

## 4. 配置与环境

配置文件：`src/shared/config.py`（通过 `.env` 覆盖）

关键配置：

- `LLM_API_KEY`
- `LLM_BASE_URL`（默认 DeepSeek）
- `LLM_MODEL`（默认 `deepseek-chat`）
- `BOOKS_DIR`（默认 `./data/books`）
- `VIDEOS_DIR`（默认 `./data/videos`）

注意：
- 如果没有 API Key，`LLMClient` 会进入 Mock 模式，流程可跑但质量不是真实产出。

---

## 5. 数据目录现状（概念）

- `data/books`：书籍文本/电子书源
- `data/chroma_db`：向量库
- `data/ref_audio`：GPT-SoVITS 参考音频
- `data/videos`：TTS与混音产物（当前主要输出）
- `data/quick_outputs`：quick 命令归档输出

---

## 6. 当前“已实现”和“未闭环”

## 6.1 已实现（可用）

1. 随机书摘 → 提炼 → 文案 → TTS 的主链路
2. topic 驱动的 RAG 检索与融合提炼
3. Chroma 本地持久化
4. `txt/epub/pdf` 导入能力（Importer 侧）
5. quick 一键生成、归档输出、BGM 混音

## 6.2 未闭环/需注意

1. `BookProcessor` 的 PDF 读取还是占位（随机模式不适合 pdf）
2. 视频渲染不是当前主闭环（更偏音频生产）
3. 导入去重策略还较粗（可继续做哈希级增量）
4. 互动机器人（评论/私信）目前主要是规划层，未见完整上线链路

---

## 7. 典型使用命令（建议）

## 7.1 导入书籍到向量库

```bash
python -m src.rag_engine.knowledge_importer
```

## 7.2 按主题生成（RAG）

```bash
python main.py generate --topic "人生迷茫" --tts-provider gpt_sovits
```

## 7.3 快速直出（直接文本）

```bash
python main.py quick --text "你不是没有方向，只是还没开始持续行动。" --tts-provider edge
```

## 7.4 快速主题生成并归档

```bash
python main.py quick --prompt "如何走出低谷" --output-dir ./data/quick_outputs --tts-provider gpt_sovits
```

---

## 8. 推荐下一步（务实版）

1. 统一“书籍来源目录”策略（你已倾向单目录，这是正确方向）
2. 给知识导入加文件哈希索引，做真正增量去重
3. 为 RAG 输出增加可追踪字段（命中片段、来源书名、相似度）
4. 增加一个 `docs/RUNBOOK.md`：常见故障 + 一键排查命令
5. 若要接网页自动化，按 A/B 线拆分（Data Automation vs Action Automation）

---

## 9. 一句话总结

这是一个以“人生智慧内容生产”为目标的 AI 自动化项目：
当前已经具备 **书籍知识库（Chroma）+ RAG 检索 + LLM 文案 + TTS 出音频** 的核心能力，接下来重点是稳定性、可追踪性和增量入库治理。
