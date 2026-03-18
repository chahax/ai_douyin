# RAG 知识库与 ChromaDB 集成方案

## 1. 什么是 RAG 和 ChromaDB？

### 1.1 RAG (Retrieval-Augmented Generation)
RAG 意为“**检索增强生成**”。
简单来说，就是把大模型（LLM）比作一个“超级大脑”，但它不知道你私有的数据（比如你电脑里的几百本人生方向书籍）。
RAG 的作用就是给这个大脑配一个“**外挂图书馆**”：
1.  **检索 (Retrieval)**: 当你要生成文案时，先去图书馆里把相关的书籍片段找出来。
2.  **增强 (Augmented)**: 把找出来的片段喂给大模型。
3.  **生成 (Generation)**: 大模型基于这些片段，写出既有深度又符合你要求的内容。

### 1.2 ChromaDB
ChromaDB 就是这个“**外挂图书馆**”的软件实现，它是一个开源的**向量数据库**。
它的核心魔法是**Embedding（向量化）**：
*   它不只是存字，而是把文字变成一串数字（向量）。
*   比如“人生迷茫”和“找不到方向”，字面上没有重复，但在向量空间里它们离得很近。
*   这样即使你搜“迷茫”，它也能帮你找到书中关于“方向感缺失”的段落。

## 2. 为什么你的项目需要它？
目前我们的 `BookProcessor` 只是**随机**读取一个片段。这就像是你在图书馆里闭着眼睛随便抽了一本书的一页，可能抽到的是目录，也可能是一段无关紧要的景色描写。

引入 ChromaDB 后，我们可以实现：
1.  **精准选题**: 你想做一期关于“坚持”的视频，系统能瞬间从 100 本书中找出所有关于“坚持”的金句段落。
2.  **跨书融合**: 可以同时提取《钢铁是怎样炼成的》和《平凡的世界》里关于奋斗的观点，让 AI 综合生成。
3.  **质量飞跃**: 因为喂给 AI 的是精选过的、高相关性的素材，AI 写出的文案会更言之有物，而不是泛泛而谈。

## 3. 技术架构设计

### 3.1 流程图
```
[你的书籍 PDF/TXT] 
       ⬇️ (1. 数据入库)
[文本切分器] -> [Embedding 模型] -> [ChromaDB 向量库]
                                         ⬇️
[用户输入主题: "如何克服焦虑"] -> [向量检索] -> [Top 5 相关片段]
                                                  ⬇️
                                            [GPT/DeepSeek]
                                                  ⬇️
                                            [高质量爆款文案]
```

### 3.2 核心组件
1.  **LangChain**: 用来串联整个流程的胶水代码。
2.  **Embedding Model**: 推荐 `m3e-base` 或 `bge-large-zh`（中文效果最好的开源模型，可本地运行）。
3.  **ChromaDB**: 存储向量数据。

## 4. 实施步骤 (调整后：优先文案质量)

**核心策略变更**: 鉴于视频和音频模块已有 MVP，现在的首要任务是**大幅提升文案质量**。我们将暂缓视频合成的开发，优先引入 RAG 模块，确保生成的内容“言之有物、引经据典”。

### 第一阶段：环境与知识库构建 (当前重点)
1.  **环境配置**: 安装 `chromadb`, `langchain`, `sentence-transformers`。
2.  **知识库导入器 (KnowledgeImporter)**:
    *   编写脚本遍历 `data/books`。
    *   实现**语义切分**（Semantic Splitter），确保每一段话都是完整的观点。
    *   调用本地 Embedding 模型（如 `m3e-base`），将切分后的段落向量化存入 ChromaDB。

### 第二阶段：检索服务集成
1.  **升级 BookProcessor**:
    *   废弃随机读取逻辑。
    *   新增 `search_wisdom(query, top_k=5)` 接口，根据关键词从 ChromaDB 检索最相关的 5 个片段。
2.  **多书融合 Prompt**:
    *   设计新的 Prompt，让 LLM 能够综合这 5 个片段（可能来自不同书籍），生成一篇逻辑严密的文案。
    *   例如：“请结合《孟子》的‘生于忧患’和《钢铁是怎样炼成的》的‘磨砺’，写一篇关于‘逆境成长’的短视频文案。”

### 第三阶段：回归视频合成
*   文案质量达标后，再将生成的优质文案喂给 `TTS` 和 `VideoComposer`，完成最终视频。

## 5. 代码预览

```python
# 伪代码示例
from langchain.vectorstores import Chroma
from langchain.embeddings import HuggingFaceEmbeddings

# 1. 初始化模型
embeddings = HuggingFaceEmbeddings(model_name="moka-ai/m3e-base")

# 2. 建库
db = Chroma.from_documents(
    documents=split_book_chunks, 
    embedding=embeddings,
    persist_directory="./data/chroma_db"
)

# 3. 检索
docs = db.similarity_search("人生迷茫怎么办", k=3)
print(docs[0].page_content) # 输出最相关的书籍片段
```

## 6. 建议
鉴于我们还在 MVP 阶段，建议：
1.  **当前**: 先把视频合成（VideoComposer）跑通，完成闭环。
2.  **下一步**: 在 Week 3 引入 ChromaDB，把“随机生成”升级为“主题生成”，这将是产品质量的一个巨大飞跃。
