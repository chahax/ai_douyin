"""Explicit single-record scope CLI; preview creates no production claim."""
import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts.creative_single_scope_probe_v2 import Probe, read, write, digest
from scripts.creative_single_scope_probe_spend_anchor_v2 import build_probe_spend_anchor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["preview", "authorization-template", "prepare", "run", "spend-anchor"])
    parser.add_argument("--config", required=True); parser.add_argument("--output")
    args = parser.parse_args(); config = read(args.config)
    if args.action == "spend-anchor": result = build_probe_spend_anchor(config["root"])
    else:
        probe = Probe(config)
        if args.action == "preview": result = probe.prepare_preview()
        elif args.action == "authorization-template": result = probe.authorization_template(probe.prepare_preview())
        elif args.action == "prepare": result = probe.prepare()
        else: result = probe.run()
    if args.output:
        write(args.output, result, True)
        print(json.dumps({"saved": str(Path(args.output).resolve()), "canonical_sha256": digest(result)}, ensure_ascii=False))
    else: print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
