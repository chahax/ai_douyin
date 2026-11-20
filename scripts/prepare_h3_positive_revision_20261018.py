"""Local positive-content projection only; no network, runtime or POST operation."""
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.h3_positive_prompt_v2 import prepare

if __name__=='__main__':
    result=prepare()
    print(json.dumps({key:result[key] for key in ('state','graph_nodes','media_submissions','api_calls','S01_graph')},ensure_ascii=False))
