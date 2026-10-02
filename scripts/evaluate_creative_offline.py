"""Score already-recorded evaluations. No model calls or automatic spending."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.content_factory.creative_rule_registry import digest,file_hash
from src.content_factory.creative_evaluation import DEFAULT_CONFIG,score_review_runs,score_repair_runs,score_production_runs


def evaluate(dataset_path,runs_path,output,config_path=None):
    data=json.loads(Path(dataset_path).read_text(encoding='utf-8'));cases=data['cases']
    runs=[json.loads(line) for line in Path(runs_path).read_text(encoding='utf-8').splitlines() if line.strip()]
    cfg=json.loads(Path(config_path).read_text(encoding='utf-8'))['config'] if config_path else DEFAULT_CONFIG
    result=score_review_runs(cases,runs,cfg)
    report={'schema_version':'creative_offline_evaluation/v1','source_hash':digest({'dataset':file_hash(dataset_path),'runs':file_hash(runs_path),'config':digest(cfg)}),
            'created_at':datetime.now(timezone.utc).isoformat(),'implementation_status':'offline_scoring_only','automatic_paid_execution':False,'result':result}
    out=Path(output)
    if out.exists():raise RuntimeError('Evaluation report already exists; use a new immutable path')
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def main():
    p=argparse.ArgumentParser();p.add_argument('--dataset',required=True);p.add_argument('--runs',required=True);p.add_argument('--output',required=True);p.add_argument('--config');a=p.parse_args()
    report=evaluate(a.dataset,a.runs,a.output,a.config)
    print(json.dumps({'path':a.output,'qualified':report['result']['holdout_repeated_validation_passed'],'automatic_paid_execution':False}))
    return 0 if report['result']['holdout_repeated_validation_passed'] else 2

if __name__=='__main__':raise SystemExit(main())
