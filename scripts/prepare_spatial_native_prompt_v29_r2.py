"""CPU-only explicit English-input correction; original r1 source/artifacts retained."""
from copy import deepcopy
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_spatial_native_prompt_v29 as f

CONTINUATION='Continue the action from the positions and composition in the provided frame-zero guide. '
CHANGES={
    'S01':[
        ('summary_en',None,'their sleeping father','their father lying with his eyes closed'),
        ('visual_en',0,'lies asleep with his eyes closed','lies with his eyes closed'),
        ('visual_en',1,'The father remains asleep on the bed.','The father keeps his eyes closed on the bed.'),
    ],
    'S03':[
        ('visual_en',3,'As this handover finishes, ease back to a full-body view of the three people standing: the father stands holding the single bread bag, and both boys stand before him.',
         'As this handover finishes, ease back to the composition and three-person standing pose in the provided closing guide: the father stands holding the single bread bag, and both boys stand before him.'),
    ],
}


def make_revision(parent_path,out):
    parent=f.speech.read(parent_path);spec=deepcopy(parent);edits=[]
    for row in spec['segments']:
        for field,index,old,new in CHANGES.get(row['id'],[]):
            target=row if index is None else row['events'][index]
            if target[field].count(old)!=1:raise f.NativePromptError('r1_exact_correction_anchor_changed')
            before=target[field];target[field]=before.replace(old,new)
            edits.append(dict(segment=row['id'],field=field,event_index=index,old=old,new=new,
                before_sha256=f.speech.sha(before.encode('utf-8')),after_sha256=f.speech.sha(target[field].encode('utf-8'))))
        row['events'][0]['visual_en']=CONTINUATION+row['events'][0]['visual_en']
        row['task_type']='reference generation + keyframe completion'
    spec['revision']='v29r2'
    spec['parent_spec']=f.speech.binding(parent_path)
    spec['revision_note']='r1 is retained. Closed eyes do not establish sleep; only S02 establishes opening eyes. Each segment continues its actual frame-zero guide, and S03 alone uses a provided closing guide. The five reference slots and ten source quotes are unchanged.'
    spec['revision_input_audit']=dict(exact_english_replacements=edits,first_event_prefix_all_segments=CONTINUATION,
        task_type_all_segments='reference generation + keyframe completion',original_chinese_source_modified=False,original_quote_records_modified=False,reference_slots_modified=False)
    out=Path(out);path=out/'INPUT_SPEC.json';f.speech.freeze_json(path,spec);return path


def main():
    p=argparse.ArgumentParser();p.add_argument('--parent-spec',type=Path,default=f.ROOT/'B_native_v29/INPUT_SPEC.json');p.add_argument('--out',type=Path,default=f.ROOT/'B_native_v29_r2');a=p.parse_args()
    path=make_revision(a.parent_spec,a.out);result=f.prepare(path,a.out)
    print(json.dumps(dict(segments=len(result['segments']),original_quotes=result['total_original_quotes'],model_calls=0,revision='v29r2',out=str(a.out.resolve()))))
if __name__=='__main__':main()
