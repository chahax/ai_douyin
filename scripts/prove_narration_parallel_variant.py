"""CPU-only source-evidenced listening reaction; preserve the strict split."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.content_factory import narration_source_case_adapter_v1 as a
from src.content_factory import narration_placement_policy_v2 as p


def main():
    run=ROOT/'data/corpus_production_trials/20261113_narration_placement_v1'
    old=ROOT/'data/video_generation/h3_library_bound_next_minute_20261113_v1'
    folder=run/'source_case_parallel_variant/S04'
    variant=a.reaction_schedule_variant(folder,p.bind(run/'CASE_V2.json'),p.bind(run/'RECEIPT_V2.json'))
    result=a.materialize(folder,p.bind(old/'segments/S04/SOURCE_CASE.json'),p.bind(run/'CASE_V2.json'),p.bind(run/'RECEIPT_V2.json'),
        ['Q_NAN','Q_GIRL','N_S04'],action_span_map={'s010':'Q_NAN','s012':'Q_GIRL','s014':'A_STOP'},scheduling_variant=variant)
    if result.get('source_case'):
        result=a.prove_graph(folder,result['source_case'],p.bind(old/'segments/S04/LIBRARY_INPUT.json'),p.bind(old/'H3_CONFIG.json'))
    print(json.dumps(dict(result=result,specific_schedule_reviewed_by_MiniMax=False,replaces_strict_split=False),ensure_ascii=False,indent=2))


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
