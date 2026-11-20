"""Thin CLI for a frozen known-complete native planning continuation."""
import argparse
import json
from pathlib import Path
import sys
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from scripts.creative_fresh_source_session_v2 import Session,SessionConfig,DEFAULT_PROFILE,read,write


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest="command",required=True)
    for action in ("preview","prepare"):
        cmd=commands.add_parser(action)
        for field in ("root","source-dir","preferences-path","user-goals-path","anchor-path","anchor-sha256","counter-root","round-key","grant-id","authorization-path"):
            cmd.add_argument("--"+field,required=True)
        cmd.add_argument("--profile-path",default=str(DEFAULT_PROFILE));cmd.add_argument("--extra-source-file",action="append",default=[])
        if action=="preview":cmd.add_argument("--output",required=True)
    for action in ("run","status"):
        cmd=commands.add_parser(action);cmd.add_argument("--root",required=True)
    args=parser.parse_args(argv)
    if args.command=="status":result=read(Path(args.root)/"STATE.json")
    elif args.command=="run":result=Session.open(args.root).run()
    else:
        values={f:getattr(args,f) for f in SessionConfig.__dataclass_fields__ if f!="extra_source_files"};values["extra_source_files"]=tuple(args.extra_source_file)
        session=Session(SessionConfig(**values))
        if args.command=="preview":
            value=session.preview();write(args.output,{"preview":value,"derived_authorization_template":session.authorization_template(value)},True)
            result={"preview_path":str(Path(args.output).resolve()),"provider_calls":0,"media_calls":0}
        else:result=session.prepare()
    print(json.dumps(result,ensure_ascii=False),flush=True);return 0


if __name__=="__main__":raise SystemExit(main())
