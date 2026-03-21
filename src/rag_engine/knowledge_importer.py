import os
import zipfile
from typing import List

from langchain_core.documents import Document
from langchain_community.document_loaders import TextLoader
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.shared.logger import logger
from src.shared.config import settings


class KnowledgeImporter:
    def __init__(self, persist_dir="./data/chroma_db", embedding_model=None):
        self.persist_dir = persist_dir

        # Determine model path
        local_model_path = os.path.abspath("./data/models/text2vec-base-chinese")
        if os.path.exists(local_model_path) and os.path.exists(os.path.join(local_model_path, "config.json")):
            self.embedding_model_name = local_model_path
            logger.info(f"Using local embedding model: {self.embedding_model_name}")
        else:
            self.embedding_model_name = embedding_model or "shibing624/text2vec-base-chinese"
            logger.info(f"Using remote embedding model: {self.embedding_model_name}")

        logger.info("Initializing Embedding Model...")
        try:
            self.embeddings = HuggingFaceEmbeddings(model_name=self.embedding_model_name)
            self.db = Chroma(
                persist_directory=self.persist_dir,
                embedding_function=self.embeddings
            )
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB or Embeddings: {e}")
            raise

    @staticmethod
    def _extract_text_from_txt(file_path: str) -> str:
        loader = TextLoader(file_path, encoding="utf-8")
        docs = loader.load()
        return "\n".join(d.page_content for d in docs)

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

    def _load_book_as_documents(self, file_path: str) -> List[Document]:
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

    def import_books(self, books_dir: str):
        """
        Imports supported files from the directory into ChromaDB.
        Supported: .txt .epub .pdf
        """
        if not os.path.exists(books_dir):
            logger.error(f"Books directory not found: {books_dir}")
            return

        supported_ext = {".txt", ".epub", ".pdf"}
        files = [
            f for f in os.listdir(books_dir)
            if os.path.splitext(f)[1].lower() in supported_ext
        ]

        if not files:
            logger.warning("No supported files found to import (.txt/.epub/.pdf).")
            return

        total_docs = []
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            separators=["\n\n", "\n", "。", "！", "？", " ", ""]
        )

        for file in files:
            file_path = os.path.join(books_dir, file)
            logger.info(f"Processing book: {file}")

            try:
                documents = self._load_book_as_documents(file_path)
                if not documents:
                    logger.warning(f"  - No extractable text: {file}")
                    continue

                chunks = text_splitter.split_documents(documents)

                for chunk in chunks:
                    chunk.metadata["source_book"] = file

                total_docs.extend(chunks)
                logger.info(f"  - Split into {len(chunks)} chunks")

            except Exception as e:
                logger.error(f"Failed to process {file}: {e}")

        if total_docs:
            logger.info(f"Importing {len(total_docs)} chunks into ChromaDB...")
            batch_size = 100
            for i in range(0, len(total_docs), batch_size):
                batch = total_docs[i:i + batch_size]
                try:
                    self.db.add_documents(batch)
                    logger.info(f"  - Imported batch {i // batch_size + 1}/{(len(total_docs) - 1) // batch_size + 1}")
                except Exception as e:
                    logger.error(f"Failed to import batch: {e}")

            logger.info("Knowledge Import Completed Successfully!")
        else:
            logger.warning("No valid content found to import.")


if __name__ == "__main__":
    importer = KnowledgeImporter()
    importer.import_books(settings.BOOKS_DIR)
