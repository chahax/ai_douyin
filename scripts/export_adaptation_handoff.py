"""Export reviewed text state for a following episode; no model or media calls."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation.handoff import export_handoff

def main():
    parser=argparse.ArgumentParser()
    for key in ("candidate","packet","source","review","output"):parser.add_argument("--"+key,type=Path,required=True)
    for key in ("book-id","episode-id","timeline-id"):parser.add_argument("--"+key,required=True)
    args=parser.parse_args()
    result=export_handoff(read(args.candidate),{"entities":read(args.packet)["entities"]},read(args.source),
        read(args.review),book_id=args.book_id,episode_id=args.episode_id,timeline_id=args.timeline_id)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    freeze(args.output,result)
    print(digest(result))
if __name__=="__main__":main()
