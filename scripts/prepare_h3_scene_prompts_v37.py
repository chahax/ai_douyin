"""Freeze source-bound multi-view continuation text; CPU only, user reviews media."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_scene_prompt_v37 as prompts


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,default=prompts.SOURCE)
    p.add_argument('--out',type=Path,default=prompts.OUT);p.add_argument('--node-capability',type=Path)
    a=p.parse_args(argv);cap=prompts.binding(a.node_capability) if a.node_capability else None
    plan=prompts.prepare(a.source,a.out,node_capability=cap);prompts.validate(plan)
    print(json.dumps(plan,ensure_ascii=False,indent=2))


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf8')
    main()
