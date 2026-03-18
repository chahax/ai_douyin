import json
from openai import OpenAI
from src.shared.config import settings
from src.shared.logger import logger

class LLMClient:
    def __init__(self):
        self.api_key = settings.LLM_API_KEY
        self.base_url = settings.LLM_BASE_URL
        self.model = settings.LLM_MODEL
        
        if self.api_key:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            logger.info(f"LLM Client initialized with model: {self.model}")
        else:
            self.client = None
            logger.warning("LLM API Key not provided. Running in Mock Mode.")

    def chat_completion(self, messages, temperature=0.7, json_mode=False):
        """
        Executes a chat completion request.
        :param messages: List of message dicts [{"role": "user", "content": "..."}]
        :param temperature: Creativity parameter
        :param json_mode: Whether to force JSON output (if supported)
        :return: Response content string
        """
        if not self.client:
            return self._mock_response(messages)

        try:
            response_format = {"type": "json_object"} if json_mode else None
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                response_format=response_format
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM API Error: {e}")
            return None

    def _mock_response(self, messages):
        """Returns a dummy response for testing without API cost."""
        last_msg = messages[-1]['content']
        logger.info(f"[Mock LLM] Processing: {last_msg[:50]}...")
        
        # Simple heuristic to return valid JSON if requested
        if "JSON" in last_msg or "json" in last_msg:
            return json.dumps({
                "title": "Mock Wisdom",
                "core_message": "This is a mock response because no API key is set.",
                "actionable": "Set your API key in .env file."
            })
        return "This is a mock response from LLMClient."

# Singleton instance
llm_client = LLMClient()
