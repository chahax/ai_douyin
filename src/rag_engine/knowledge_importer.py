import os
from typing import List
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
        # 1. Try local path first
        local_model_path = os.path.abspath("./data/models/text2vec-base-chinese")
        if os.path.exists(local_model_path) and os.path.exists(os.path.join(local_model_path, "config.json")):
            self.embedding_model_name = local_model_path
            logger.info(f"Using local embedding model: {self.embedding_model_name}")
        else:
            # 2. Fallback to HuggingFace (or whatever user passed)
            self.embedding_model_name = embedding_model or "shibing624/text2vec-base-chinese"
            logger.info(f"Using remote embedding model: {self.embedding_model_name}")
        
        logger.info(f"Initializing Embedding Model...")
        try:
            self.embeddings = HuggingFaceEmbeddings(model_name=self.embedding_model_name)
            
            self.db = Chroma(
                persist_directory=self.persist_dir, 
                embedding_function=self.embeddings
            )
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB or Embeddings: {e}")
            raise

    def import_books(self, books_dir: str):
        """
        Imports all txt files from the directory into ChromaDB.
        """
        if not os.path.exists(books_dir):
            logger.error(f"Books directory not found: {books_dir}")
            return

        files = [f for f in os.listdir(books_dir) if f.endswith('.txt')]
        if not files:
            logger.warning("No .txt files found to import.")
            return

        total_docs = []
        # Semantic splitting: Try to keep paragraphs together
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            separators=["\n\n", "\n", "。", "！", "？", " ", ""]
        )

        for file in files:
            file_path = os.path.join(books_dir, file)
            logger.info(f"Processing book: {file}")
            
            try:
                # Use TextLoader with explicit encoding or auto-detect
                loader = TextLoader(file_path, encoding='utf-8')
                documents = loader.load()
                
                # Split text into chunks
                chunks = text_splitter.split_documents(documents)
                
                # Add metadata (book source)
                for chunk in chunks:
                    chunk.metadata['source_book'] = file
                
                total_docs.extend(chunks)
                logger.info(f"  - Split into {len(chunks)} chunks")
                
            except Exception as e:
                logger.error(f"Failed to process {file}: {e}")

        if total_docs:
            logger.info(f"Importing {len(total_docs)} chunks into ChromaDB...")
            # Batch add to avoid memory issues if too large
            batch_size = 100
            for i in range(0, len(total_docs), batch_size):
                batch = total_docs[i:i+batch_size]
                try:
                    self.db.add_documents(batch)
                    logger.info(f"  - Imported batch {i//batch_size + 1}/{(len(total_docs)-1)//batch_size + 1}")
                except Exception as e:
                    logger.error(f"Failed to import batch: {e}")
            
            logger.info("Knowledge Import Completed Successfully!")
        else:
            logger.warning("No valid content found to import.")

if __name__ == "__main__":
    # Test Importer
    importer = KnowledgeImporter()
    importer.import_books(settings.BOOKS_DIR)
