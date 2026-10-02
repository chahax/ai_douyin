"""Fail-closed readiness check used by container startup and health probes."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.shared.migration import ensure_migrated
from src.shared.llm_providers.mock_provider import MockProvider


def readiness(*, health_url: str | None = None) -> dict:
    checks = {
        "migration_at_head": ensure_migrated(strict=True),
        "offline_llm_contract": False,
        "web_liveness": None,
    }
    try:
        MockProvider().chat_with_tools([], [], tool_choice="none")
    except Exception:
        checks["offline_llm_contract"] = False
    else:
        checks["offline_llm_contract"] = True
    if health_url:
        try:
            with urllib.request.urlopen(health_url, timeout=5) as response:
                checks["web_liveness"] = 200 <= response.status < 300
        except Exception:
            checks["web_liveness"] = False
    ready = all(value is True for value in checks.values() if value is not None)
    return {
        "schema": "service_readiness/v1",
        "ready": ready,
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--migration-only", action="store_true")
    parser.add_argument(
        "--health-url",
        default="http://localhost:8501/_stcore/health",
    )
    args = parser.parse_args(argv)
    result = readiness(health_url=None if args.migration_only else args.health_url)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
