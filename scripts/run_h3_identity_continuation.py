"""Prepare or run the explicitly approved S03/S04 actual-tail continuation."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_identity_continuation_v1 as flow

PROJECT=Path(__file__).resolve().parents[1]
RUN=PROJECT/'data/video_generation/h3_identity_continuation_from_s03_20261111_v1'
PREVIOUS=PROJECT/'data/video_generation/h3_story_opening_minute_20261111_v1'


def specification():
    imported=flow.read(PREVIOUS/'imported/S02/IMPORT.json')
    return dict(prefix_results=dict(S01=flow.bind(PREVIOUS/'visual_h3_v3'/(PREVIOUS.name+'_S01')/'shots/S01/RESULT.json'),
                                   S02=imported['native_result']),
        sources={sid:flow.bind(PREVIOUS/'segments'/sid/'SOURCE_CASE.json') for sid in flow.NEW},
        config=flow.read(PREVIOUS/'H3_CONFIG.json'),authorization=dict(
            user_statement='修复人物身份断裂，从30秒处重新开始，前两段保留',
            engineering_limits=dict(new_video_submissions=2,new_image_submissions=0,cloud_calls=0),
            original_source=flow.bind(PREVIOUS/'PLAN.json'),publication=False,unknown_replay=False))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['prepare','prepare-video','status','video','collect','assemble'])
    p.add_argument('--run',type=Path,default=RUN);p.add_argument('--shot',choices=flow.NEW)
    p.add_argument('--poll-seconds',type=int,default=30);p.add_argument('--max-seconds',type=int,default=21600);a=p.parse_args()
    if a.run.resolve()!=RUN.resolve():p.error('this CLI is scoped to the explicitly approved new run')
    if a.action=='prepare':v=flow.prepare(a.run,specification())
    elif a.action=='assemble':v=flow.assemble(a.run)
    else:
        if a.shot is None:p.error('this action requires --shot')
        if a.action=='prepare-video':v=flow.prepare_video(a.run,a.shot,code_files=[__file__])
        elif a.action=='video':v=flow.execute(a.run,a.shot,poll_seconds=a.poll_seconds,max_seconds=a.max_seconds)
        else:v={'status':flow.status,'collect':flow.collect_known}[a.action](a.run,a.shot)
    print(json.dumps(v,ensure_ascii=False,indent=2))


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
