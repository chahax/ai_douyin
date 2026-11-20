"""Explicit single-segment contact repair; no automatic submission retries."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['prepare','submit','collect','status'])
    p.add_argument('--run',required=True,type=Path);p.add_argument('--draft',type=Path);p.add_argument('--config',type=Path)
    p.add_argument('--prompt-profiles',type=Path);p.add_argument('--authorization',type=Path);p.add_argument('--prompt-id')
    a=p.parse_args()
    from src.content_factory import h3_contact_execution_v1 as wrapper
    from src.content_factory import h3_asset_flow_v2 as flow
    api=wrapper.for_run(a.run)
    if a.action=='prepare':
        if not all((a.draft,a.config,a.prompt_profiles,a.authorization)):p.error('prepare requires draft,config,prompt-profiles,authorization')
        result=api.prepare(a.run,a.draft,flow.read(a.config),prompt_profiles=flow.bind(a.prompt_profiles),
            authorization=flow.bind(a.authorization),code_files=[__file__])
    elif a.action=='collect':result=api.collect_known(a.run,a.prompt_id)
    elif a.action=='submit':result=api.submit(a.run)
    else:result=api.status(a.run)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
