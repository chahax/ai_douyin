"""Record actual assistant adjudication for the currently pending text review."""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.content_factory.creative_review_gate import confirmed_issues,digest

def record_decision(run_dir,decision_path):
    root=Path(run_dir).resolve()
    state=json.loads((root/'state.json').read_text(encoding='utf-8'))
    pending=state.get('pending_evidence_review')
    if not pending or state.get('status')!='script_review_pending':raise ValueError('没有待核实的审核包')
    packet_path=(root/pending['packet']).resolve();target=(root/pending['decision']).resolve()
    if packet_path.parent!=root or target.parent!=root:raise ValueError('审核文件必须位于任务目录')
    packet=json.loads(packet_path.read_text(encoding='utf-8'))
    if digest(packet)!=pending['packet_sha256']:raise ValueError('待核实审核包已改变')
    decision=json.loads(Path(decision_path).read_text(encoding='utf-8-sig'))
    issues=confirmed_issues(packet,decision)
    if target.exists():
        if json.loads(target.read_text(encoding='utf-8'))!=decision:raise ValueError('不能覆盖核实回执')
    else:
        with target.open('x',encoding='utf-8') as out:json.dump(decision,out,ensure_ascii=False,indent=2)
    return {'status':'decision_recorded_resume_required','confirmed_issues':len(issues),
            'decision_path':str(target),'automatic_media_submit':False}

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--decision',type=Path,required=True,help='助手阅读全文后填写的核实JSON，不能直接提交未填写的模板')
    args=parser.parse_args();print(json.dumps(record_decision(args.run_dir,args.decision),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
