import os
import random
from typing import List, Optional, Dict
from src.shared.logger import logger

class BookProcessor:
    def __init__(self, books_dir="data/books"):
        self.books_dir = books_dir
        if not os.path.exists(books_dir):
            os.makedirs(books_dir, exist_ok=True)

    def list_books(self) -> List[str]:
        """Lists available book files."""
        return [f for f in os.listdir(self.books_dir) if f.endswith('.txt') or f.endswith('.pdf')]

    def read_random_chunk(self, book_name: Optional[str] = None, min_size=300, max_size=1000) -> Optional[Dict]:
        """
        Reads a random chunk from a book with smart paragraph boundaries.
        :param book_name: Specific book filename, or None for random.
        :param min_size: Minimum characters to read.
        :param max_size: Maximum characters to read.
        :return: Dict with 'book_name', 'content', 'start_pos'
        """
        books = self.list_books()
        if not books:
            logger.warning("No books found in data/books")
            return None

        if not book_name:
            book_name = random.choice(books)
        
        file_path = os.path.join(self.books_dir, book_name)
        
        try:
            if book_name.endswith('.pdf'):
                content = self._read_pdf(file_path)
            else:
                content = self._read_txt(file_path)
            
            if not content or len(content) < min_size:
                logger.warning(f"Book {book_name} is too short or empty.")
                return None

            return self._extract_chunk(content, min_size, max_size, book_name)

        except Exception as e:
            logger.error(f"Error reading book {book_name}: {e}")
            return None

    def _read_txt(self, file_path: str) -> str:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()

    def _read_pdf(self, file_path: str) -> str:
        # Placeholder for PDF reading logic
        # In a real scenario, use PyPDF2 or pdfminer
        logger.warning("PDF support not fully implemented yet. Returning empty content.")
        return ""

    def _extract_chunk(self, content: str, min_size: int, max_size: int, book_name: str) -> Dict:
        """Extracts a coherent text chunk respecting paragraph boundaries."""
        total_len = len(content)
        
        # Try up to 10 times to find a good chunk
        for _ in range(10):
            start_idx = random.randint(0, max(0, total_len - max_size))
            
            # Find the nearest previous paragraph break (double newline) or start of file
            # Search backwards from start_idx up to 200 chars
            real_start = start_idx
            found_start = False
            for i in range(start_idx, max(0, start_idx - 500), -1):
                if content[i:i+2] == '\n\n' or content[i:i+2] == '\r\n':
                    real_start = i + 2
                    found_start = True
                    break
                # Also check for sentence endings as a fallback
                if not found_start and content[i] in ['。', '！', '？', '!', '?', '.'] and i < start_idx - 1:
                     real_start = i + 1
            
            if real_start == 0:
                found_start = True # Start of file is valid

            # Now look for the end
            end_search_start = real_start + min_size
            if end_search_start >= total_len:
                end_idx = total_len
            else:
                end_idx = min(real_start + max_size, total_len)
                # Search for the best ending punctuation or paragraph break
                best_end = end_idx
                for i in range(end_search_start, end_idx):
                    if content[i:i+2] == '\n\n':
                        best_end = i
                        break
                    if content[i] in ['。', '！', '？', '!', '?', '.']:
                        best_end = i + 1
                end_idx = best_end

            chunk_text = content[real_start:end_idx].strip()
            
            if len(chunk_text) >= min_size:
                 return {
                    "book_name": book_name,
                    "content": chunk_text,
                    "start_pos": real_start
                }

        # Fallback: strict slicing
        start = random.randint(0, max(0, total_len - max_size))
        return {
            "book_name": book_name,
            "content": content[start:start+max_size],
            "start_pos": start
        }

if __name__ == "__main__":
    processor = BookProcessor()
    chunk = processor.read_random_chunk()
    if chunk:
        print(f"Book: {chunk['book_name']}")
        print(f"--- Content Start ---")
        print(chunk['content'])
        print(f"--- Content End ---")
