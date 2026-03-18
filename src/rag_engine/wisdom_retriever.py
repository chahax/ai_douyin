import os
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from src.shared.logger import logger

class WisdomRetriever:
    def __init__(self, persist_dir="./data/chroma_db", embedding_model=None):
        self.persist_dir = persist_dir
        
        # Determine model path (same logic as Importer)
        local_model_path = os.path.abspath("./data/models/text2vec-base-chinese")
        if os.path.exists(local_model_path) and os.path.exists(os.path.join(local_model_path, "config.json")):
            self.embedding_model_name = local_model_path
            logger.info(f"Using local embedding model: {self.embedding_model_name}")
        else:
            self.embedding_model_name = embedding_model or "shibing624/text2vec-base-chinese"
            logger.info(f"Using remote embedding model: {self.embedding_model_name}")
        
        logger.info("Initializing Wisdom Retriever...")
        try:
            self.embeddings = HuggingFaceEmbeddings(model_name=self.embedding_model_name)
            self.db = Chroma(
                persist_directory=self.persist_dir, 
                embedding_function=self.embeddings
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
            return []

if __name__ == "__main__":
    # Test Retriever
    retriever = WisdomRetriever()
    docs = retriever.search_wisdom("人生迷茫怎么办")
    for i, doc in enumerate(docs):
        print(f"\n--- Result {i+1} (Source: {doc.metadata.get('source_book')}) ---")
        print(doc.page_content)
