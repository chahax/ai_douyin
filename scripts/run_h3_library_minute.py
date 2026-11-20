"""Four fresh H3 clips from one version-pinned library binding and feature cards."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_library_minute_v2 as flow

PROJECT=Path(__file__).resolve().parents[1]
RUN=PROJECT/'data/video_generation/h3_library_bound_minute_20261112_v1'
PREVIOUS=PROJECT/'data/video_generation/h3_story_opening_minute_20261111_v1'


def specification():
    """Read run-owned settings; prepare never silently selects a different asset."""
    settings=flow.read(RUN/'RUN_SPEC.json')
    return dict(sources={sid:flow.bind(PREVIOUS/'segments'/sid/'SOURCE_CASE.json') for sid in flow.IDS},
        library_binding=settings['library_binding'],binding_approval=settings['binding_approval'],
        library_selection=settings['library_selection'],config=flow.read(PREVIOUS/'H3_CONFIG.json'),
        authorization=settings['authorization'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['prepare','prepare-video','review-request','status','video','collect','assemble'])
    p.add_argument('--run',type=Path,default=RUN);p.add_argument('--shot',choices=flow.IDS)
    p.add_argument('--poll-seconds',type=int,default=30);p.add_argument('--max-seconds',type=int,default=21600)
    a=p.parse_args()
    if a.run.resolve()!=RUN.resolve():p.error('this CLI is scoped to the explicitly authorized fresh minute')
    if a.action=='prepare':value=flow.prepare(a.run,specification())
    elif a.action=='assemble':value=flow.assemble(a.run)
    else:
        if a.shot is None:p.error('this action requires --shot')
        if a.action=='prepare-video':value=flow.prepare_video(a.run,a.shot,code_files=[__file__])
        elif a.action=='video':value=flow.execute(a.run,a.shot,poll_seconds=a.poll_seconds,max_seconds=a.max_seconds)
        else:value={'review-request':flow.review_request,'status':flow.status,'collect':flow.collect_known}[a.action](a.run,a.shot)
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
