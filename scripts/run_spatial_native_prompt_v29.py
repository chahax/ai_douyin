"""CPU-only English official Ref2VA prompt compile; no media or external model."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_spatial_native_prompt_v29 as f

def main():
    p=argparse.ArgumentParser();p.add_argument('--inputs',type=Path,default=f.ROOT/'INPUTS.json');p.add_argument('--speech-spec',type=Path,default=f.ROOT/'B_speech_r2/INPUT_SPEC.json');p.add_argument('--reference-spec',type=Path,default=f.ROOT/'B_CANDIDATE_SPEC.json');p.add_argument('--out',type=Path,default=f.ROOT/'B_native_v29');p.add_argument('--spec',type=Path);a=p.parse_args()
    spec=a.spec or f.make_spec(a.inputs,a.speech_spec,a.reference_spec,a.out);v=f.prepare(spec,a.out)
    print(json.dumps({'segments':len(v['segments']),'original_quotes':v['total_original_quotes'],'prompt_format':v['prompt_format'],'model_calls':0,'out':str(a.out.resolve())}))
if __name__=='__main__':main()
