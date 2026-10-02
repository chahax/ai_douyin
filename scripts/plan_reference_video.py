"""Map reviewed narrative shots to serial generation segments; no network calls."""
import argparse
import copy
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_reference_director import STAGES,read,digest,approved,validate,check

def build_plan(run):
    options_path=run/'delivery/generation_options.json'
    options=read(options_path) if options_path.exists() else None
    if options is not None:
        check(options.get('schema')=='reference_generation_options/v1', 'Unknown generation options')
        check(options.get('opening_mode') in ('reviewed_opening_image','text_only'), 'Unknown opening mode')
        check(isinstance(options.get('rationale'),str) and options['rationale'].strip(), 'Opening mode needs rationale')
    opening_mode=options['opening_mode'] if options else 'reviewed_opening_image'
    selection=read(run/'stage_selection.json')
    layers={};sources={}
    for stage in STAGES:
        folder=run/selection.get(stage,stage)
        value=approved(folder)
        validate(stage,value,layers)
        layers[stage]=value
        sources[stage]={'candidate_path':str(folder/'candidate.json'),'candidate_sha256':digest(folder/'candidate.json'),'review_path':str(folder/'review.json'),'review_sha256':digest(folder/'review.json')}
    segments=[];offset=0
    for index,beat in enumerate(layers['story']['beats']):
        original=[s for s in layers['visual']['shots'] if s['beat_id']==beat['id']]
        camera=copy.deepcopy(original)
        boundary=None
        if index:
            # The original tail must be the first image. Reserve three 24fps frames
            # before an authored cut; do not rewrite dialogue/action time windows.
            hold=0.125
            check(camera[0]['start']==0 and camera[0]['end']>hold,'First shot too short for tail carry')
            camera[0]['start']=hold
            boundary={'kind':'raw_tail_carry','start':0,'end':hold,'source_segment':segments[-1]['id'],
                      'source_visual_shot':segments[-1]['authored_camera'][-1]['id'],
                      'requires_actual_approved_tail':True}
        segments.append({'id':f'S{index+1:02}','beat_id':beat['id'],'duration':beat['duration'],'timeline_start':offset,
                         'reference':opening_mode if index==0 else 'immediately_previous_approved_raw_tail',
                         'boundary_camera':boundary,'authored_camera':original,'proposed_camera':camera,
                         'performance':layers['performance']['beats'][index],
                         'editorial_projection_review':'pending','media_review':'not_generated'})
        offset+=beat['duration']
    result={'schema':'reference_video_execution_plan/v1','title':layers['story']['title'],'duration':offset,'sources':sources,
            'space':layers['visual']['space'],'segments':segments,'media_calls':0,'ready_to_submit':False,
            'required_before_submission':['Review the 0.125-second boundary camera projection against the unchanged action and dialogue timing.',
                                          'Lock character appearance and voices, then inspect an actual opening image for doorway layout and initial states.',
                                          'Register the revised screenplay through the campaign entry point, preserving prior failures and pending receipts.',
                                          'Bind this schema to the serial executor and verify source hashes and actual upstream media review before each submission.']}
    if options is not None:
        result['generation_options']={'path':str(options_path),'sha256':digest(options_path),**options}
    if opening_mode=='text_only':
        result['required_before_submission'][1]='Lock character appearance and voices; review explicit doorway geometry in the text-only S01 prompt. Inspect the actual generated video before any continuation.'
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',required=True)
    args=parser.parse_args();run=Path(args.run_dir).resolve();output=run/'delivery/execution_plan.json'
    check(not output.exists(),'Do not overwrite an existing execution plan')
    output.write_text(json.dumps(build_plan(run),ensure_ascii=False,indent=2),encoding='utf-8')
    print(output)
