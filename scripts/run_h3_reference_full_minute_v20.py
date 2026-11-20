"""Explicit independent reference movie commands; default is readonly status."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_reference_full_minute_v20 as flow


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',nargs='?',default='status',choices=['prepare','status','tick','execute','qa','assemble','preview-enable','assemble-preview'])
    p.add_argument('--run',type=Path,default=flow.RUN)
    p.add_argument('--manifest',type=Path)
    p.add_argument('--audit',type=Path);p.add_argument('--prompt-approval',type=Path);p.add_argument('--authorization',type=Path)
    p.add_argument('--segment',default='S01',choices=flow.IDS)
    p.add_argument('--request',type=Path,help='Explicit local user diagnostic-preview request, never production approval')
    p.add_argument('--poll-seconds',type=float,default=30);p.add_argument('--max-seconds',type=float,default=86400)
    a=p.parse_args(argv)
    if a.command=='prepare':
        if not all((a.manifest,a.audit,a.prompt_approval,a.authorization)):p.error('prepare requires manifest, audit, prompt-approval and authorization files')
        manifest=flow.native.read(a.manifest)
        segments=[]
        for s in manifest['segments']:
            row=dict(s);shot=s.get('shot_id',s.get('source_shot'))
            row['shot_id']=shot.get('id') if isinstance(shot,dict) else shot
            segments.append(row)
        result=flow.prepare(a.run,segments,adaptation_audit=a.audit,prompt_approval=a.prompt_approval,authorization=a.authorization)
    elif a.command in ('preview-enable','assemble-preview'):
        from src.content_factory import visual_h3_diagnostic_preview_v23 as diagnostic
        if a.command=='preview-enable':
            if not a.request:p.error('preview-enable requires --request')
            result=diagnostic.enable(a.run,request=a.request)
        else:result=diagnostic.assemble(a.run)
    elif a.command=='execute':result=flow.execute(a.run,poll_seconds=a.poll_seconds,max_seconds=a.max_seconds)
    elif a.command=='qa':result=flow.qa(a.run,a.segment)
    else:result=getattr(flow,a.command)(a.run)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf8')
    main()
