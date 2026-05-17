import importlib.util
import os
import sys
from urllib import error, request


DEFAULTS = {
    "LLM_PROVIDER": "",
    "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
    "OLLAMA_MODEL": "qwen2.5:7b",
    "BOOKS_DIR": "./data/books",
    "VIDEOS_DIR": "./data/videos",
    "REF_AUDIO_DIR": "./data/ref_audio",
    "CHROMA_PERSIST_DIR": "./data/chroma_db",
    "DEFAULT_BGM_PATH": "./data/ref_audio/Morning-Routine-Lofi-Study-Music(chosic.com).mp3",
    "TTS_PROVIDER": "gpt_sovits",
    "GPT_SOVITS_API_URL": "http://127.0.0.1:9880",
    "GPT_SOVITS_SDK_ROOT": "./GPT_SoVITS",
    "GPT_SOVITS_USE_SDK": "true",
    "GPT_SOVITS_ENABLE_HTTP_FALLBACK": "false",
    "GPT_SOVITS_DEFAULT_REF_AUDIO": "./data/ref_audio/mature_male_ref.wav",
}

REQUIRED_PACKAGES = [
    "loguru",
    "openai",
    "requests",
    "langchain_core",
    "langchain_community",
    "langchain_huggingface",
    "langchain_text_splitters",
    "chromadb",
    "pydantic_settings",
]


def load_env_file(env_path=".env"):
    values = {}
    if not os.path.exists(env_path):
        return values

    with open(env_path, "r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = normalize_env_value(value)
    return values


def normalize_env_value(value: str):
    normalized = value.strip()
    if " #" in normalized:
        normalized = normalized.split(" #", 1)[0].rstrip()
    return normalized


def resolve_setting(key: str, env_values: dict):
    return os.environ.get(key) or env_values.get(key) or DEFAULTS.get(key, "")


def infer_llm_provider(env_values: dict):
    explicit_provider = resolve_setting("LLM_PROVIDER", env_values).strip().lower()
    if explicit_provider:
        if explicit_provider in {"openai", "deepseek"}:
            return "openai_compatible"
        return explicit_provider

    base_url = resolve_setting("LLM_BASE_URL", env_values).strip().lower()
    api_key = resolve_setting("LLM_API_KEY", env_values).strip().lower()
    if "11434" in base_url or api_key == "ollama":
        return "ollama"
    if api_key:
        return "openai_compatible"
    return "mock"


def check_package(package_name: str):
    return importlib.util.find_spec(package_name) is not None


def print_result(label: str, ok: bool, details: str = ""):
    status = "OK" if ok else "FAIL"
    suffix = f" - {details}" if details else ""
    print(f"[{status}] {label}{suffix}")


def check_path(label: str, path_value: str, must_exist: bool = True):
    resolved = os.path.abspath(path_value)
    exists = os.path.exists(resolved)
    ok = exists if must_exist else True
    detail = resolved if exists or not must_exist else f"{resolved} (missing)"
    print_result(label, ok, detail)


def check_http(label: str, url: str, timeout: int = 5):
    try:
        req = request.Request(url, method="GET")
        with request.urlopen(req, timeout=timeout) as response:
            print_result(label, 200 <= response.status < 300, f"{url} -> {response.status}")
    except error.HTTPError as exc:
        print_result(label, False, f"{url} -> HTTP {exc.code}")
    except Exception as exc:
        print_result(label, False, f"{url} -> {exc}")


def check_ollama(env_values: dict):
    provider = infer_llm_provider(env_values)
    if provider != "ollama":
        print_result("Ollama readiness", True, "skipped (LLM_PROVIDER is not ollama)")
        return

    explicit_provider = resolve_setting("LLM_PROVIDER", env_values).strip().lower()
    if explicit_provider == "ollama":
        base_url = resolve_setting("OLLAMA_BASE_URL", env_values).rstrip("/")
        model = resolve_setting("OLLAMA_MODEL", env_values)
        print_result("Ollama config mode", True, "provider_env")
    else:
        base_url = resolve_setting("LLM_BASE_URL", env_values).rstrip("/").removesuffix("/v1")
        model = resolve_setting("LLM_MODEL", env_values)
        print_result("Ollama config mode", True, "legacy_openai_compatible_env")
    tags_url = f"{base_url}/api/tags"
    print_result("Ollama target model", True, model)
    check_http("Ollama endpoint", tags_url)


def check_gpt_sovits(env_values: dict):
    use_sdk = resolve_setting("GPT_SOVITS_USE_SDK", env_values).strip().lower() == "true"
    enable_http_fallback = resolve_setting("GPT_SOVITS_ENABLE_HTTP_FALLBACK", env_values).strip().lower() == "true"
    print_result("TTS provider", True, resolve_setting("TTS_PROVIDER", env_values))
    print_result("GPT-SoVITS mode", True, "sdk" if use_sdk else "http")
    if enable_http_fallback:
        check_http("GPT-SoVITS endpoint", resolve_setting("GPT_SOVITS_API_URL", env_values))
    else:
        print_result("GPT-SoVITS endpoint", True, "skipped (HTTP fallback disabled)")


def main():
    env_values = load_env_file()

    print("== AI Douyin Doctor ==")
    print(f"Python: {sys.version.split()[0]}")
    print(f"LLM provider: {infer_llm_provider(env_values)}")

    for package_name in REQUIRED_PACKAGES:
        print_result(f"Package {package_name}", check_package(package_name))

    check_path("Books dir", resolve_setting("BOOKS_DIR", env_values))
    check_path("Videos dir", resolve_setting("VIDEOS_DIR", env_values), must_exist=False)
    check_path("Ref audio dir", resolve_setting("REF_AUDIO_DIR", env_values))
    check_path("Default BGM", resolve_setting("DEFAULT_BGM_PATH", env_values))
    check_path("Chroma persist dir", resolve_setting("CHROMA_PERSIST_DIR", env_values), must_exist=False)
    check_path("GPT-SoVITS SDK root", resolve_setting("GPT_SOVITS_SDK_ROOT", env_values))
    check_path("GPT-SoVITS default ref audio", resolve_setting("GPT_SOVITS_DEFAULT_REF_AUDIO", env_values))

    check_ollama(env_values)
    check_gpt_sovits(env_values)


if __name__ == "__main__":
    main()
