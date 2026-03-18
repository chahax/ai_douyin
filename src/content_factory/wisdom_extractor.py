import json
from src.shared.llm_client import llm_client
from src.shared.logger import logger

class WisdomExtractor:
    def __init__(self):
        # Load the prompt template
        try:
            with open("docs/prompts/book-extraction.txt", "r", encoding="utf-8") as f:
                self.prompt_template = f.read()
        except FileNotFoundError:
            logger.warning("Prompt file not found. Using default prompt.")
            self.prompt_template = """
            角色：资深编辑+人生教练
            任务：从书籍内容中提取适合短视频传播的人生智慧
            输入文本：{book_chunk}
            输出JSON格式：
            {
              "title": "短视频标题",
              "hook": "前3秒抓人话术",
              "core_message": "核心道理",
              "elaboration": "详细阐述",
              "actionable": "具体行动建议",
              "quote": "书中金句",
              "emotion": "情感标签",
              "scene": "适用场景"
            }
            """

    def extract_wisdom(self, book_chunk: str) -> dict:
        """
        Extracts wisdom from a book chunk using LLM.
        :param book_chunk: Text content from the book.
        :return: JSON object with extracted wisdom metadata.
        """
        prompt = self.prompt_template.replace("{book_chunk}", book_chunk)
        
        messages = [
            {"role": "system", "content": "你是一位善于提炼人生智慧的资深编辑。"},
            {"role": "user", "content": prompt}
        ]
        
        logger.info("Sending chunk to LLM for extraction...")
        response_text = llm_client.chat_completion(messages, temperature=0.7, json_mode=True)
        
        if not response_text:
            return None
            
        try:
            # Clean up potential markdown code blocks if present
            cleaned_text = response_text.replace("```json", "").replace("```", "").strip()
            wisdom_data = json.loads(cleaned_text)
            logger.info(f"Extracted wisdom: {wisdom_data.get('title', 'Untitled')}")
            return wisdom_data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return None

if __name__ == "__main__":
    # Test with a dummy chunk
    extractor = WisdomExtractor()
    test_chunk = "人最宝贵的是生命。生命属于人只有一次。人的一生应当这样度过：当他回首往事的时候，不会因为虚度年华而悔恨，也不会因为碌碌无为而羞愧..."
    result = extractor.extract_wisdom(test_chunk)
    print(json.dumps(result, indent=2, ensure_ascii=False))
