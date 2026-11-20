import os
import zipfile
from typing import List

from src.shared.logger import logger
from src.shared.config import settings


def _resolve_local_embedding_path() -> str | None:
    """
    按优先级查找本地 embedding 模型路径：
      1. ./data/models/text2vec-base-chinese   (项目内置约定路径)
      2. ~/.cache/huggingface/hub/models--shibing624--text2vec-base-chinese/snapshots/*/   (HF 缓存)
    返回第一个含 config.json 的路径；都找不到返回 None。
    """
    import glob
    candidates = [
        os.path.abspath("./data/models/text2vec-base-chinese"),
        *glob.glob(os.path.expanduser(
            "~/.cache/huggingface/hub/models--shibing624--text2vec-base-chinese/snapshots/*/"
        )),
    ]
    for path in candidates:
        if os.path.isdir(path) and os.path.exists(os.path.join(path, "config.json")):
            return path
    return None


class KnowledgeImporter:
    def __init__(self, persist_dir="./data/chroma_db", embedding_model=None):
        self.persist_dir = persist_dir

        from langchain_community.vectorstores import Chroma
        from langchain_huggingface import HuggingFaceEmbeddings

        # Determine model path: prefer local (项目路径 or HF cache), else HF Hub
        local_model_path = _resolve_local_embedding_path()
        if local_model_path:
            self.embedding_model_name = local_model_path
            logger.info(f"Using local embedding model: {self.embedding_model_name}")
        elif embedding_model or settings.ENABLE_HF_EMBEDDING_FALLBACK:
            self.embedding_model_name = embedding_model or "shibing624/text2vec-base-chinese"
            logger.info(f"Using remote embedding model: {self.embedding_model_name}")
        else:
            raise RuntimeError('No local embedding model available; network model fallback is disabled.')

        logger.info("Initializing Embedding Model...")
        try:
            self.embeddings = HuggingFaceEmbeddings(model_name=self.embedding_model_name,
                model_kwargs={'device': 'cpu', 'local_files_only': bool(local_model_path)})
            self.db = Chroma(
                persist_directory=self.persist_dir,
                embedding_function=self.embeddings
            )
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB or Embeddings: {e}")
            raise

    @staticmethod
    def _extract_text_from_txt(file_path: str) -> str:
        from pathlib import Path
        return Path(file_path).read_text(encoding='utf-8-sig')

    @staticmethod
    def _extract_text_from_epub(file_path: str) -> str:
        """
        轻量 EPUB 提取（无额外依赖）：读取 epub(zip) 中 xhtml/html 内容并去标签。
        """
        import re

        chunks: List[str] = []
        with zipfile.ZipFile(file_path, "r") as zf:
            for name in zf.namelist():
                low = name.lower()
                if not (low.endswith(".xhtml") or low.endswith(".html") or low.endswith(".htm")):
                    continue
                try:
                    data = zf.read(name).decode("utf-8", errors="ignore")
                except Exception:
                    continue
                # 去掉 script/style
                data = re.sub(r"<script[\s\S]*?</script>", "", data, flags=re.IGNORECASE)
                data = re.sub(r"<style[\s\S]*?</style>", "", data, flags=re.IGNORECASE)
                # 去 html 标签
                text = re.sub(r"<[^>]+>", " ", data)
                text = re.sub(r"\s+", " ", text).strip()
                if text:
                    chunks.append(text)
        return "\n\n".join(chunks)

    @staticmethod
    def _extract_text_from_pdf(file_path: str) -> str:
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception as e:
            raise RuntimeError(
                "PDF import requires `pypdf`. Install with: pip install pypdf"
            ) from e

        reader = PdfReader(file_path)
        texts = []
        for page in reader.pages:
            txt = page.extract_text() or ""
            if txt.strip():
                texts.append(txt)
        return "\n\n".join(texts)

    def _load_book_as_documents(self, file_path: str) -> list:
        from langchain_core.documents import Document
        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".txt":
            raw_text = self._extract_text_from_txt(file_path)
        elif ext == ".epub":
            raw_text = self._extract_text_from_epub(file_path)
        elif ext == ".pdf":
            raw_text = self._extract_text_from_pdf(file_path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")

        if not raw_text.strip():
            return []

        return [Document(page_content=raw_text, metadata={})]

    def import_books(self, books_dir: str, *, selected_files=None):
        """Import selected local files and return verified write accounting."""
        from src.rag_engine.knowledge_import_result import import_directory, write_stable_chunks
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500, chunk_overlap=50,
            separators=["\n\n", "\n", "。", "！", "？", " ", ""])
        result = import_directory(books_dir, load=self._load_book_as_documents,
            split=splitter.split_documents, write=lambda batch: write_stable_chunks(self.db, batch),
            selected_files=selected_files)
        logger.info(f"Knowledge import result: {result}")
        return result


if __name__ == "__main__":
    importer = KnowledgeImporter()
    importer.import_books(settings.BOOKS_DIR)
