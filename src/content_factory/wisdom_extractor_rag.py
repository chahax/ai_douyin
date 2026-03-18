import json
from src.shared.llm_client import llm_client
from src.shared.logger import logger

class WisdomExtractorRAG:
    """
    RAG-Enhanced Wisdom Extractor
    Can process multiple chunks from different books to synthesize a comprehensive insight.
    """
    def __init__(self):
        self.prompt_template = """
        角色：博览群书的人生导师 + 爆款内容主编
        任务：根据提供的多段书籍内容（Context），针对用户主题（Topic），提炼出深刻的“人生解药”。

        用户主题：{topic}

        参考书籍片段（Context）：
        {context}

        请综合上述片段，创作一条直击人心的短视频文案大纲。
        不要只是罗列书摘，要进行**知识融合**，用现代人的视角去解读古老智慧。

        输出JSON格式：
        {{
          "title": "爆款标题（15字内，有悬念/痛点）",
          "core_message": "核心观点（一句话）",
          "quote": "最有力的一句金句（注明出处，如果片段里有）",
          "elaboration": "详细阐述（结合主题和书摘，100字左右）",
          "actionable": "具体行动建议（3点）",
          "scene": "适用场景",
          "emotion": "情感基调"
        }}
        """

    def extract_wisdom(self, topic: str, chunks: list) -> dict:
        """
        Extracts wisdom from multiple RAG chunks.
        :param topic: The user's query topic.
        :param chunks: List of LangChain Document objects.
        :return: JSON object with wisdom metadata.
        """
        if not chunks:
            logger.warning("No chunks provided for RAG extraction.")
            return None

        # Format context from chunks
        context_str = ""
        for i, chunk in enumerate(chunks):
            source = chunk.metadata.get('source_book', '未知来源')
            content = chunk.page_content.strip()
            context_str += f"--- 片段 {i+1} (来源: {source}) ---\n{content}\n\n"

        try:
            prompt = self.prompt_template.format(
                topic=topic,
                context=context_str
            )
        except KeyError as e:
            logger.warning(f"RAG prompt formatting key error: {e}. Falling back to plain context mode.")
            prompt = f"主题：{topic}\n\n上下文：\n{context_str}\n\n请输出JSON：title/core_message/quote/elaboration/actionable/scene/emotion"
        
        messages = [
            {"role": "system", "content": "你是一位善于融会贯通的智者，能从多本书中提炼出解决现代人困惑的智慧。"},
            {"role": "user", "content": prompt}
        ]
        
        logger.info(f"Sending RAG context ({len(chunks)} chunks) to LLM...")
        response_text = llm_client.chat_completion(messages, temperature=0.7, json_mode=True)
        
        if not response_text:
            return None
            
        try:
            cleaned_text = response_text.replace("```json", "").replace("```", "").strip()
            wisdom_data = json.loads(cleaned_text)
            logger.info(f"RAG Wisdom Extracted: {wisdom_data.get('title', 'Untitled')}")
            return wisdom_data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return None
