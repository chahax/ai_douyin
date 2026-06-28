import asyncio
import time
from typing import List, Optional

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

    @property
    def model_name(self) -> str:
        """供 I-4 用的当前 model 名。"""
        if hasattr(self.provider, "model"):
            return self.provider.model
        if self.provider_name == "ollama":
            return self._resolve_ollama_model()
        return settings.LLM_MODEL or ""

    def chat_completion(self, messages, temperature=0.7, json_mode=False):
        """
        [已废弃] 同步入口 — 不走 I-4 治理（无 token 计量 / 无缓存 / 无限流）。
        新代码请用 chat_completion_tracked() 或 chat_completion_async()。
        """
        return self.provider.chat_completion(messages, temperature=temperature, json_mode=json_mode)

    def chat_completion_tracked(
        self,
        messages,
        caller: str = "unknown",
        temperature: float = 0.7,
        json_mode: bool = False,
        use_cache: bool = True,
    ) -> Optional[str]:
        """
        I-4 同步入口：从 sync 上下文调用，走 async 治理路径（限流 + 缓存 + 计量 + 记录）。

        实现：用 asyncio.run() 启动临时 event loop 调用 chat_completion_async。
        若已在 async 上下文中调用（已有 event loop），降级到直接 provider 调用并 logger.warning。

        Args:
            messages: OpenAI 风格 messages
            caller: 调用方标识（用于限流豁免判断 + 计量统计）
                推荐值: "agent_chat", "script_gen", "scene_plan", "tag",
                        "wisdom_extractor", "dialogue_gen", "background_plan",
                        "background_prompt", "error_reviewer", "skill_registry",
                        "memory_classifier", "fanqie_promo", "auto_reply"
            temperature / json_mode / use_cache: 透传给 async 路径
        """
        try:
            asyncio.run(
                self.chat_completion_async(
                    messages,
                    caller=caller,
                    temperature=temperature,
                    json_mode=json_mode,
                    use_cache=use_cache,
                )
            )
        except RuntimeError as exc:
            # 已在 event loop 中（async 上下文嵌套）— 降级路径
            if "asyncio.run()" in str(exc) or "loop" in str(exc).lower():
                logger.warning(
                    f"[LLM tracked fallback] caller={caller} 在已有 event loop 中调用，"
                    f"降级为直接 provider 调用（不走限流/缓存/记录）"
                )
                return self.provider.chat_completion(
                    messages, temperature=temperature, json_mode=json_mode
                )
            raise
        except Exception as exc:
            logger.error(f"[LLM tracked] caller={caller} 调用异常: {exc}")
            return None

    async def chat_completion_async(
        self,
        messages: List[dict],
        caller: str = "unknown",
        temperature: float = 0.7,
        json_mode: bool = False,
        use_cache: bool = True,
    ) -> Optional[str]:
        """
        I-4 异步入口：限流 + 缓存 + 计量 + 记录一站式。

        Args:
            messages: OpenAI 风格 [{"role": ..., "content": ...}]
            caller: 调用方标识（用于计量统计 + 限流豁免判断）
            temperature / json_mode: 透传给 provider
            use_cache: 是否读 / 写缓存（CLI 调试时可关闭）

        Returns:
            LLM 响应字符串，或 None（失败 / 缓存命中也会返回）
        """
        # 懒导入避免循环依赖
        from src.shared.token_counter import count_tokens, estimate_cost
        from src.shared.llm_usage_log_model import record_usage
        from src.shared.rate_limiter import acquire as rate_acquire, is_exempt
        from src.shared.llm_cache import make_key, get_cached, set_cached, is_enabled as cache_enabled

        model = self.model_name

        # 1. 缓存查询
        if use_cache and cache_enabled():
            key = make_key(model, messages, temperature, json_mode)
            cached = get_cached(key)
            if cached is not None:
                # 缓存命中：只记 1 条 usage（cost=0, latency=0, cache_hit=True）
                record_usage(
                    model=model,
                    prompt_tokens=0,
                    completion_tokens=0,
                    cost_usd=0.0,
                    latency_ms=0,
                    caller=caller,
                    cache_hit=True,
                )
                logger.debug(f"[LLM cache hit] caller={caller} key={key[:12]}...")
                return cached

        # 2. 限流（exempt 跳过）
        await rate_acquire(caller)

        # 3. 实际调用 + 计时
        t0 = time.time()
        result = self.provider.chat_completion(messages, temperature=temperature, json_mode=json_mode)
        latency_ms = int((time.time() - t0) * 1000)

        # 4. 计量 + 记录
        if result is not None and isinstance(result, str):
            prompt_text = "".join(
                str(m.get("content", "")) for m in messages if isinstance(m, dict)
            )
            prompt_tokens = count_tokens(model, prompt_text)
            completion_tokens = count_tokens(model, result)
            cost = estimate_cost(model, prompt_tokens, completion_tokens)
        else:
            prompt_tokens = completion_tokens = 0
            cost = 0.0

        record_usage(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            caller=caller,
        )

        # 5. 缓存结果
        if use_cache and cache_enabled() and result is not None and isinstance(result, str):
            key = make_key(model, messages, temperature, json_mode)
            set_cached(key, result)

        return result


llm_client = LLMClient()

