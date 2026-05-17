from src.shared.config import settings
from src.shared.llm_providers import MockProvider, OllamaProvider, OpenAICompatibleProvider
from src.shared.logger import logger


class LLMClient:
    def __init__(self):
        self.provider_name = self._resolve_provider_name()
        self.provider = self._build_provider()
        logger.info(f"LLM Client initialized with provider: {self.provider_name}")

    def _resolve_provider_name(self) -> str:
        provider = (settings.LLM_PROVIDER or "").strip().lower()
        if provider:
            if provider in {"openai", "deepseek"}:
                return "openai_compatible"
            return provider
        if self._is_legacy_ollama_configuration():
            logger.warning("Detected legacy Ollama configuration via LLM_BASE_URL/LLM_MODEL. Using ollama provider.")
            return "ollama"
        if settings.LLM_API_KEY:
            return "openai_compatible"
        return "mock"

    def _build_provider(self):
        if self.provider_name == "ollama":
            return OllamaProvider(
                base_url=self._resolve_ollama_base_url(),
                model=self._resolve_ollama_model(),
                timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
            )
        if self.provider_name == "openai_compatible":
            return OpenAICompatibleProvider(
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
                model=settings.LLM_MODEL,
                timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
            )
        logger.warning("LLM provider is mock. Real model calls are disabled.")
        return MockProvider()

    def _is_legacy_ollama_configuration(self) -> bool:
        base_url = (settings.LLM_BASE_URL or "").strip().lower()
        api_key = (settings.LLM_API_KEY or "").strip().lower()
        return "11434" in base_url or api_key == "ollama"

    def _resolve_ollama_base_url(self) -> str:
        explicit_base = (settings.OLLAMA_BASE_URL or "").strip()
        legacy_base = (settings.LLM_BASE_URL or "").strip()

        if (settings.LLM_PROVIDER or "").strip():
            return explicit_base.rstrip("/")
        if self._is_legacy_ollama_configuration() and legacy_base:
            return legacy_base.removesuffix("/v1").rstrip("/")
        return explicit_base.rstrip("/")

    def _resolve_ollama_model(self) -> str:
        if (settings.LLM_PROVIDER or "").strip():
            return (settings.OLLAMA_MODEL or "").strip()
        if self._is_legacy_ollama_configuration() and (settings.LLM_MODEL or "").strip():
            return settings.LLM_MODEL.strip()
        return (settings.OLLAMA_MODEL or "").strip()

    def chat_completion(self, messages, temperature=0.7, json_mode=False):
        """
        Executes a chat completion request.
        :param messages: List of message dicts [{"role": "user", "content": "..."}]
        :param temperature: Creativity parameter
        :param json_mode: Whether to force JSON output (if supported)
        :return: Response content string
        """
        return self.provider.chat_completion(messages, temperature=temperature, json_mode=json_mode)


llm_client = LLMClient()
