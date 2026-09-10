"""Project text-model synthesis of source-bound observations; never uploads media."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import time

from .artifacts import write_json
from .source_synthesis_json import ALGORITHM_VERSION, parse_source_synthesis_json

SYSTEM_PROMPT = (
    "你负责视频来源表达的证据归纳。只读文字观察和本地ASR；你没有看到图像或听到音频，不能声称已看片或听音。"
    "保留条件、动作对象和未知，严格按请求JSON格式回答。只输出合法JSON，不输出解释或代码围栏。"
    "JSON字符串内引用台词用中文「」引号，不能嵌入未转义的英文双引号。逐条遵守请求规定的字数、条数和引用数上限，"
    "每条只写一个证据支持的要点，避免把全部内容塞进一条长句。插入配图不等于屏幕操作或真人案件复演。"
)


class ConfiguredTextSynthesis:
    def __init__(self, output_dir: str | Path, *, client=None):
        if client is None:
            from src.shared.config import settings
            from src.shared.llm_client import LLMClient
            model = (getattr(settings, "SOURCE_EXPRESSION_LLM_MODEL", "") or settings.SCRIPT_LLM_MODEL
                     or settings.SCRIPT_REVIEW_LLM_MODEL or settings.LLM_MODEL)
            extra_body = None
            if model.lower() == "minimax-m3" and settings.SCRIPT_LLM_THINKING in {"disabled", "adaptive"}:
                extra_body = {"thinking": {"type": settings.SCRIPT_LLM_THINKING}, "reasoning_split": True}
            client = LLMClient(model=model,
                               timeout_seconds=settings.SCRIPT_LLM_TIMEOUT_SECONDS,
                               max_tokens=6000, max_retries=0, preserve_invalid_json=True, extra_body=extra_body)
        if client.provider_name == "mock":
            raise ValueError("source text synthesis requires a real configured model")
        self.client = client
        self.output_dir = Path(output_dir)
        self.index = max((int(path.stem.rsplit("_", 1)[-1])
                          for path in self.output_dir.glob("text_synthesis_response_*.json")
                          if path.stem.rsplit("_", 1)[-1].isdigit()), default=0)

    @property
    def identity(self) -> dict:
        return {"provider": self.client.provider_name, "model": self.client.model_name,
                "input_mode": "text_observations_and_local_asr_only", "media_uploaded": False,
                "max_output_tokens": 6000, "temperature": 0.1,
                "syntax_policy": ALGORITHM_VERSION,
                "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()}

    def __call__(self, content: list[dict]) -> dict:
        if not content or any(set(row) != {"type", "text"} or row["type"] != "text"
                              or not isinstance(row["text"], str) for row in content):
            raise ValueError("configured source synthesis only accepts text; media inputs are forbidden")
        text = "\n".join(row["text"] for row in content)
        if len(text) > 64000:
            raise ValueError("source synthesis text exceeds its bounded stage budget")
        self.index += 1
        started_at = datetime.now(timezone.utc).isoformat()
        started = time.perf_counter()
        raw = self.client.chat_completion_tracked(
            [{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user", "content": text}], caller="source_expression_synthesis",
            temperature=0.1, json_mode=True, use_cache=True)
        response_path = self.output_dir / f"text_synthesis_response_{self.index:03d}.json"
        response = {"schema": "source_text_synthesis_response/v1", **self.identity,
                    "started_at": started_at, "completed_at": datetime.now(timezone.utc).isoformat(),
                    "elapsed_seconds": round(time.perf_counter()-started, 3), "input": text, "answer": raw}
        write_json(response_path, response)
        if not isinstance(raw, str) or not raw.strip():
            raise RuntimeError("configured source synthesis returned no text; local evidence was preserved")
        result, repair = parse_source_synthesis_json(raw)
        if repair is not None:
            write_json(response_path, {**response, "syntax_repair": repair})
        return result
