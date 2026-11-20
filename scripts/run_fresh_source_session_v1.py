"""Thin CLI for an explicit fresh-source text session; never auto-registers authority."""
import argparse
import json
from pathlib import Path
import sys

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from scripts.creative_fresh_source_session_v1 import Session,SessionConfig,DEFAULT_PROFILE,read,write


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest="command",required=True)
    for action in ("preview","prepare"):
        command=commands.add_parser(action)
        for field in ("root","source-dir","preferences-path","user-goals-path","anchor-path","anchor-sha256",
            "counter-root","round-key","grant-id","authorization-path"):
            command.add_argument("--"+field,required=True)
        command.add_argument("--profile-path",default=str(DEFAULT_PROFILE))
        command.add_argument("--extra-source-file",action="append",default=[])
        if action=="preview":command.add_argument("--output",required=True)
    for action in ("run","status"):
        command=commands.add_parser(action);command.add_argument("--root",required=True)
    args=parser.parse_args(argv)
    if args.command=="status":result=read(Path(args.root)/"STATE.json")
    elif args.command=="run":result=Session.open(args.root).run()
    else:
        values={field:getattr(args,field) for field in SessionConfig.__dataclass_fields__ if field!="extra_source_files"}
        values["extra_source_files"]=tuple(args.extra_source_file)
        session=Session(SessionConfig(**values))
        if args.command=="preview":
            preview=session.preview()
            write(args.output,{"preview":preview,"derived_authorization_template":session.authorization_template(preview)},True)
            result={"preview_path":str(Path(args.output).resolve()),"provider_calls":0,"media_calls":0}
        else:result=session.prepare()
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0


if __name__=="__main__":raise SystemExit(main())
