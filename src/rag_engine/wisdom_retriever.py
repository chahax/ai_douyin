import os
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from src.shared.logger import logger
from src.shared.config import settings


class WisdomRetriever:
    def __init__(self, persist_dir="./data/chroma_db", embedding_model=None):
        self.persist_dir = persist_dir
        self.embedding_model = embedding_model

        # 优先使用 Ollama 本地 embedding（需提前安装：ollama pull nomic-embed-text）
        # 其次用本地 HuggingFace 模型，最后才请求 HuggingFace Hub
        ollama_model = getattr(settings, "OLLAMA_EMBEDDING_MODEL", "")
        local_model_path = os.path.abspath("./data/models/text2vec-base-chinese")

        embedding = None

        # 1. 尝试 Ollama embedding
        if ollama_model:
            try:
                from langchain_ollama import OllamaEmbeddings
                candidate_embedding = OllamaEmbeddings(
                    model=ollama_model,
                    base_url=settings.OLLAMA_BASE_URL,
                )
                candidate_embedding.embed_query("测试")
                embedding = candidate_embedding
                logger.info(f"Using Ollama embedding model: {ollama_model}")
            except Exception as exc:
                logger.warning(f"Ollama embedding 初始化失败: {exc}")

        # 2. 尝试本地 HuggingFace 模型
        if embedding is None and os.path.exists(local_model_path):
            try:
                embedding = HuggingFaceEmbeddings(model_name=local_model_path)
                logger.info(f"Using local HuggingFace embedding model: {local_model_path}")
            except Exception as exc:
                logger.warning(f"本地 embedding 模型加载失败: {exc}")

        # 3. Fallback: HuggingFace Hub（需要网络，默认关闭，避免生成流程卡在模型下载）
        if embedding is None:
            if settings.ENABLE_HF_EMBEDDING_FALLBACK:
                embedding = self._build_huggingface_embedding()
            else:
                raise RuntimeError(
                    "No local embedding model available. Run `ollama pull nomic-embed-text` "
                    "or set ENABLE_HF_EMBEDDING_FALLBACK=true."
                )

        logger.info("Initializing Wisdom Retriever...")
        try:
            self.embeddings = embedding
            self.db = Chroma(
                persist_directory=self.persist_dir,
                embedding_function=self.embeddings,
            )
        except Exception as e:
            logger.error(f"Failed to initialize Retriever: {e}")
            raise

    def search_wisdom(self, query: str, top_k: int = 3) -> list:
        """
        Retrieves top_k relevant wisdom chunks for the given query.
        """
        logger.info(f"Searching wisdom for: '{query}'")
        try:
            results = self.db.similarity_search(query, k=top_k)
            logger.info(f"Found {len(results)} relevant chunks.")
            return results
        except Exception as e:
            logger.error(f"Search failed: {e}")
            if self._retry_with_huggingface():
                try:
                    results = self.db.similarity_search(query, k=top_k)
                    logger.info(f"Found {len(results)} relevant chunks after embedding fallback.")
                    return results
                except Exception as retry_exc:
                    logger.error(f"Search retry failed: {retry_exc}")
            return []

    def _build_huggingface_embedding(self):
        hf_model = self.embedding_model or "shibing624/text2vec-base-chinese"
        logger.info(f"Using HuggingFace Hub embedding model: {hf_model}（无本地模型，将请求 HuggingFace）")
        return HuggingFaceEmbeddings(model_name=hf_model)

    def _retry_with_huggingface(self) -> bool:
        try:
            self.embeddings = self._build_huggingface_embedding()
            self.db = Chroma(
                persist_directory=self.persist_dir,
                embedding_function=self.embeddings,
            )
            return True
        except Exception as exc:
            logger.error(f"Embedding fallback failed: {exc}")
            return False

if __name__ == "__main__":
    # Test Retriever
    retriever = WisdomRetriever()
    docs = retriever.search_wisdom("人生迷茫怎么办")
    for i, doc in enumerate(docs):
        print(f"\n--- Result {i+1} (Source: {doc.metadata.get('source_book')}) ---")
        print(doc.page_content)
