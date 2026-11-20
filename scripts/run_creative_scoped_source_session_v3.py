"""Thin CLI; preview does not claim, construct a client, or dispatch."""
import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts.creative_scoped_source_session_v3 import Session, read, write, digest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "authorization-template", "prepare", "run", "status"))
    parser.add_argument("--config", required=True); parser.add_argument("--output")
    args = parser.parse_args(argv); config = read(args.config)
    if args.action == "status": result = read(Path(config["root"]) / "STATE.json")
    else:
        session = Session(config)
        if args.action == "preview": result = session.preview()
        elif args.action == "authorization-template": result = session.authorization_template(session.preview())
        elif args.action == "prepare": result = session.prepare()
        else: result = session.run()
    if args.output:
        write(args.output, result, True)
        print(json.dumps({"saved": str(Path(args.output).resolve()), "canonical_sha256": digest(result)}, ensure_ascii=False))
    else: print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
