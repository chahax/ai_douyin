"""Registered A/B diagnostic CLI; preview is read-only and creates no client."""
import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts.creative_registered_review_ab_probe_v1 import Probe, read, write, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "authorization-template", "prepare", "run", "status"))
    parser.add_argument("--config", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(); probe = Probe(read(args.config))
    result = probe.authorization_template(probe.preview()) if args.action == "authorization-template" else getattr(probe, args.action)()
    if args.output:
        write(args.output, result, True)
        print(json.dumps({"path": str(Path(args.output).resolve()), "canonical_sha256": digest(result)}, ensure_ascii=False))
    else: print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
