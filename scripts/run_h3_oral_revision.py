"""Explicit two-shot oral revision; imported originals can never be submitted."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_oral_revision_v1 as revision

PROJECT = Path(__file__).resolve().parents[1]
RUN = PROJECT/'data/video_generation/h3_oral_revision_next_minute_20261113_v1'


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['prepare','prepare-video','review-request','status','video','submit','collect','assemble','verify-imports'])
    p.add_argument('--run', type=Path, default=RUN); p.add_argument('--shot', choices=revision.NEW)
    p.add_argument('--poll-seconds', type=int, default=30); p.add_argument('--max-seconds', type=int, default=21600)
    a = p.parse_args(argv)
    if a.run.resolve() != RUN.resolve(): p.error('this CLI is scoped to the authorized oral revision')
    f = revision.for_run(a.run)
    if a.action == 'prepare': result = revision.prepare(a.run, revision.read(a.run/'RUN_SPEC.json'))
    elif a.action == 'assemble': result = f.assemble(a.run)
    elif a.action == 'verify-imports': result = revision.verify_imports(a.run)
    else:
        if a.shot is None: p.error('this action requires --shot')
        if a.action == 'prepare-video': result = f.prepare_video(a.run, a.shot, code_files=[__file__])
        elif a.action == 'video': result = f.execute(a.run, a.shot, poll_seconds=a.poll_seconds, max_seconds=a.max_seconds)
        else: result = {'review-request':f.review_request,'status':f.status,'submit':f.submit,'collect':f.collect_known}[a.action](a.run,a.shot)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    main()
