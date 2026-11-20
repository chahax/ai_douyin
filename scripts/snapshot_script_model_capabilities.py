"""Read provider model metadata without generating content; never save credentials."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from src.content_factory.creative_workflow_roles import role_config
from src.content_factory.corpus_screenplay_v1 import freeze
from src.content_factory.novel_adaptation.agent_capacity_v2 import profiles,official_metadata


def snapshot(output):
    value=profiles();cfg=role_config('director')
    with httpx.Client(timeout=30,follow_redirects=False) as client:
        response=client.get(cfg.base_url.rstrip('/')+'/models',headers={'Authorization':'Bearer '+cfg.api_key})
        response.raise_for_status()
        value['director']=official_metadata(value['director'],response.json())
    freeze(output,value)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    snapshot(a.output)
