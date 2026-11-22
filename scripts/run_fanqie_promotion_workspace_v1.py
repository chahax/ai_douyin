"""Explicit Fanqie business workspace. Status is read-only; actions are separate."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.services.fanqie_promotion_workspace_v1 import PromotionWorkspace,CLOSED_LOOP_DB_PATH


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    methods={'status':'status','sync':'sync','apply':'apply','migrate':'migrate',
        'register-candidate':'register_candidate','bind-candidate':'bind_candidate','review':'record_review',
        'prepare-publish':'prepare_publish','dispatch-publish':'dispatch_publish','attach-publication':'attach_publication',
        'recover-publish-receipt':'recover_publish_receipt','prepare-backfill':'prepare_backfill',
        'request-publication-metadata':'request_publication_metadata',
        'authorize-backfill':'authorize_backfill','dispatch-backfill':'dispatch_backfill',
        'reconcile-backfill':'reconcile_backfill','backfill-status':'backfill_status'}
    parser.add_argument('action',choices=methods)
    parser.add_argument('--resource')
    parser.add_argument('--ledger',type=Path,default=CLOSED_LOOP_DB_PATH)
    parser.add_argument('--input',type=Path,help='该命名操作的结构化参数JSON；固定文件引用使用path/sha256')
    args=parser.parse_args(argv)
    params=json.loads(args.input.read_text(encoding='utf-8-sig')) if args.input else {}
    if not isinstance(params,dict):parser.error('--input must contain an object')
    if args.resource:
        if 'resource' in params and params['resource']!=args.resource:parser.error('resource mismatch')
        params['resource']=args.resource
    workspace=PromotionWorkspace(args.ledger)
    result=getattr(workspace,methods[args.action])(**params)
    try:
        print(json.dumps(result,ensure_ascii=False,default=str,indent=2))
    except UnicodeEncodeError:
        # Windows pipes may use GBK, including after an operation has committed.
        print(json.dumps(result,ensure_ascii=True,default=str,indent=2))
    return result


if __name__=='__main__':main()
