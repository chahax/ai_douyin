"""Query and backfill the central local Seedance/Seedream call ledger."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.services.provider_call_ledger import (  # noqa: E402
    DEFAULT_LEDGER_PATH,
    ProviderCallLedger,
    backfill_receipts,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_LEDGER_PATH))
    commands = parser.add_subparsers(dest="command", required=True)

    backfill = commands.add_parser("backfill")
    backfill.add_argument(
        "roots",
        nargs="*",
        default=[str(ROOT / "data" / "video_generation")],
    )

    listing = commands.add_parser("list")
    listing.add_argument("--provider")
    listing.add_argument("--operation")
    listing.add_argument("--status")
    listing.add_argument("--limit", type=int, default=100)

    commands.add_parser("summary")
    export = commands.add_parser("export")
    export.add_argument(
        "--output",
        default=str(ROOT / "data" / "provider_calls.json"),
    )

    args = parser.parse_args(argv)
    ledger = ProviderCallLedger(args.db)
    if args.command == "backfill":
        value = {
            "database": str(ledger.path),
            "backfill": backfill_receipts(ledger, args.roots),
            "summary": ledger.summary(),
        }
    elif args.command == "list":
        value = ledger.list_calls(
            provider=args.provider,
            operation=args.operation,
            status=args.status,
            limit=args.limit,
        )
    elif args.command == "summary":
        value = ledger.summary()
    else:
        output = ledger.export_json(args.output)
        value = {"database": str(ledger.path), "export": str(output)}
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
