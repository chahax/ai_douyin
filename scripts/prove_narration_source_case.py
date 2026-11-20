"""Consume the approved narration plan into fresh actual H3 SOURCE_CASE probes."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.content_factory import narration_source_case_adapter_v1 as a
from src.content_factory import narration_placement_policy_v2 as p


def main():
    run=ROOT/'data/corpus_production_trials/20261113_narration_placement_v1'
    old=ROOT/'data/video_generation/h3_library_bound_next_minute_20261113_v1'
    values=[]
    for sid,quotes,mapping in [('S03',['N_S03'],{'s010':'A_LEAVE'}),('S04',['Q_NAN','Q_GIRL','N_S04'],{'s010':'Q_NAN','s012':'Q_GIRL','s014':'A_STOP'})]:
        folder=run/'source_case_consumers_after_split_v2'/sid
        result=a.materialize(folder,p.bind(old/'segments'/sid/'SOURCE_CASE.json'),p.bind(run/'CASE_V2.json'),p.bind(run/'RECEIPT_V2.json'),quotes,action_span_map=mapping)
        if result['status']=='fresh_source_case_ready_for_actual_asset_tail_gate':
            result=a.prove_graph(folder,result['source_case'],p.bind(old/'segments'/sid/'LIBRARY_INPUT.json'),p.bind(old/'H3_CONFIG.json'))
        elif sid=='S04' and result['status']=='needs_segment_split':
            split=a.split_warning_segment(run/'source_case_consumers_after_split_v2/S04_SPLIT',p.bind(old/'segments'/sid/'SOURCE_CASE.json'),p.bind(run/'CASE_V2.json'),p.bind(run/'RECEIPT_V2.json'))
            for part in split['parts']:
                source=part['result'].get('source_case')
                if source:part['CPU_proof']=a.prove_graph(Path(source['path']).parent,source,p.bind(old/'segments'/sid/'LIBRARY_INPUT.json'),p.bind(old/'H3_CONFIG.json'))
            result=dict(split_notice=result,split_consumption=split)
        values.append(result)
    p.freeze(run/'SOURCE_CONSUMER_FINAL_V2.json',values)
    print(json.dumps(dict(status='CPU_source_consumers_complete_no_post',evidence=p.bind(run/'SOURCE_CONSUMER_FINAL_V2.json'),
        results=[v.get('status','deterministic_split_sources') for v in values],global_default_changed=False),ensure_ascii=False,indent=2))


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
