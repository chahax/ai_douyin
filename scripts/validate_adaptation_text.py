"""Validate a complete text artifact set, without model calls or deployment."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.corpus_screenplay_v1 import read,freeze,digest
from src.content_factory.novel_adaptation.text_validation import verify
from src.content_factory.novel_adaptation.narrative_render import render


def main():
    p=argparse.ArgumentParser()
    for name in ('run','packet','design','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--semantic-review',type=Path)
    p.add_argument('--maximum-seconds',type=float,default=240)
    a=p.parse_args()
    files={'candidate':'CANDIDATE','source':'SOURCE','run_plan':'PLAN','state':'STATE','plan':'PROP_PLAN',
           'presence':'PRESENCE','projection':'PROP_PROJECTION','replay':'COMBINED_REPLAY',
           'uncertainty_review':'UNCERTAINTY_PRIMARY_REVIEW'}
    bundle={key:read(a.run/(value+'.json')) for key,value in files.items()}
    bundle['packet']=read(a.packet);bundle['design']=read(a.design)['design']
    a.output.mkdir(exist_ok=False,parents=True)
    freeze(a.output/'INPUT_MANIFEST.json',{'run':str(a.run.resolve()),'packet':str(a.packet.resolve()),
        'design':str(a.design.resolve()),'artifact_hashes':{k:digest(v) for k,v in bundle.items()},'model_calls':0})
    try:
        report=verify(bundle,semantic_review=read(a.semantic_review) if a.semantic_review else None,
                      maximum_seconds=a.maximum_seconds)
        freeze(a.output/'REPORT.json',report)
        (a.output/'SCREENPLAY_UNAPPROVED.md').write_text(render(bundle['candidate'],estimated_timing=True),encoding='utf-8')
        print(report['status'],report['blocking_reasons'])
    except Exception as exc:
        freeze(a.output/'ERROR.json',{'type':type(exc).__name__,'message':str(exc)[:8000]})
        raise


if __name__=='__main__':main()
