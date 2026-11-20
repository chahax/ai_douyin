"""Precise image-disposition preparation and original successor collection only."""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_service_exit_image_successor_v35 as f
from src.content_factory import visual_h3_continuity_minute_v34 as minute

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['request-disposition','verify','prepare','approval-request','collect','select'])
    p.add_argument('--run',type=Path,default=minute.RUN);p.add_argument('--shot',choices=minute.IDS,default='S01')
    p.add_argument('--service-attempt',type=Path);p.add_argument('--readonly-audit',type=Path);a=p.parse_args()
    if a.action=='request-disposition':
        if not a.service_attempt or not a.readonly_audit:p.error('request-disposition needs --service-attempt and --readonly-audit')
        value=f.disposition_request(a.run,a.shot,a.service_attempt,minute.bind(a.readonly_audit))
    elif a.action=='verify':value=f.verify(a.run,a.shot)
    elif a.action=='prepare':value=f.prepare_successor(a.run,a.shot)
    elif a.action=='approval-request':value=f.image_approval_request(a.run,a.shot)
    elif a.action=='collect':f.collect_known(a.run);value=f.view(a.run,a.shot)
    else:value=f.selection(a.run,a.shot)
    print(json.dumps(value,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
