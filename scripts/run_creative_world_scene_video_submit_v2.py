"""Fixed media-v3 entry into the unchanged one-video submitter and claim scope."""
from pathlib import Path
import sys
PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path: sys.path.insert(0, str(PROJECT))
from scripts import creative_world_scene_video_submit_v1 as base
from scripts import creative_world_scene_media_probe_v3 as media

VERSION = "creative_world_scene_video_submit_entry/v2"
AUTHORIZATION_ID = base.AUTHORIZATION_ID


def _verify_prepared(root):
    checked = media.verify_prepared(root)
    # The authorization and submission freeze bind the fixed selection code too.
    checked["source_files"][str(Path(__file__).resolve())] = base.sha(__file__)
    return checked


def submitter(config, **kwargs):
    if "verifier" in kwargs: raise ValueError("only the fixed media-v3 verifier is supported")
    return base.Submitter(config, verifier=_verify_prepared, **kwargs)


def main(argv=None):
    import argparse, json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "authorization", "native-validate", "run", "poll", "finalize"))
    parser.add_argument("path"); args = parser.parse_args(argv)
    if args.action == "native-validate": result = base.native_validate(args.path)
    else:
        caller = submitter(base.Config(**base.read(args.path)))
        action = {"authorization": "authorization_template", "run": "submit"}.get(args.action, args.action)
        result = getattr(caller, action)()
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
