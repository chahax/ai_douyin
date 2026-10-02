#!/usr/bin/env python3
"""Validate creative-agent role configuration without printing credentials."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "creative_agent_models.json"
ENV_PATH = ROOT / ".env"


def _load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip()
    return values


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--allow-missing-tokens",
        action="store_true",
        help="Validate the non-secret template before local tokens are entered.",
    )
    args = parser.parse_args()

    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    env_values = _load_env(ENV_PATH)
    errors: list[str] = []

    expected = {
        "writer": (
            "minimax",
            "MiniMax-M3",
            "https://api.minimaxi.com/v1",
            "WRITER_AGENT_API_KEY",
        ),
        "director": (
            "deepseek",
            "deepseek-flash",
            "https://api.deepseek.com/v1",
            "DIRECTOR_AGENT_API_KEY",
        ),
    }
    configured_roles = payload.get("roles", {})
    if set(configured_roles) != set(expected):
        errors.append("roles 只能包含 writer 和 director；不配置第三审核模型槽位")
    for role, (provider, model, base_url, key_name) in expected.items():
        row = configured_roles.get(role, {})
        if row.get("provider") != provider:
            errors.append(f"{role}: provider 应为 {provider}")
        if row.get("model") != model:
            errors.append(f"{role}: model 应为 {model}")
        if row.get("base_url") != base_url:
            errors.append(f"{role}: base_url 应为 {base_url}")
        if row.get("api_key_env") != key_name:
            errors.append(f"{role}: api_key_env 应为 {key_name}")

        token = env_values.get(key_name, "")
        configured = bool(token and not token.lower().startswith("your_"))
        print(
            f"{role}: provider={provider}, model={model}, "
            f"token={'configured' if configured else 'missing'}"
        )
        if not configured and not args.allow_missing_tokens:
            errors.append(f"{role}: {key_name} 未配置")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("配置结构有效；未输出任何 Token。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
