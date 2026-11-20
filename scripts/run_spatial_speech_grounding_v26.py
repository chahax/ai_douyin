"""CPU-only source-bound speaker/mode prompt compiler; no media/model calls."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_spatial_speech_grounding_v26 as flow

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--spec',type=Path);p.add_argument('--trusted-inputs',type=Path)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if bool(a.spec)==bool(a.trusted_inputs):p.error('provide exactly one of --spec or --trusted-inputs')
    spec=flow.make_trusted_spec(a.trusted_inputs,a.out) if a.trusted_inputs else a.spec
    result=flow.prepare(spec,a.out)
    print(json.dumps({'segments':len(result['segments']),'original_quotes':result['total_original_quotes'],'output':str(a.out.resolve()),'model_calls':0,'production_approved':False},ensure_ascii=False))
if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
