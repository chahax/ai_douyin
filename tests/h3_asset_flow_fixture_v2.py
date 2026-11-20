"""Archived S04 text/real four-person guide + synthetic CPU voice fixtures."""
from copy import deepcopy
import json
import math
from pathlib import Path
import struct
import wave

from src.content_factory import h3_asset_flow_v2 as flow
from src.content_factory import voice_asset_registry_v1 as voice
from test_shot_actor_continuity_v1 import real_s04_case

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'data/video_generation/h3_oral_revision_next_minute_20261113_v1'

def build_fixture(folder,*,mode='voice_required',reviewed=True):
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    case,_=real_s04_case();old_input=flow.read(OLD/'segments/S04/LIBRARY_INPUT.json')
    old_spec=flow.read(OLD/'RUN_SPEC.json')
    review=deepcopy(flow.read(OLD/'segments/S04/GUIDE_STATE_REVIEW.json'))
    review.update(usable_for_continuation=True,observed_actor_count=4,unexpected_actor_ids=[])
    guide=dict(image=old_input['first_image'],native_result=old_input['predecessor_result'],review=review)
    state=deepcopy(case['state_plan'])
    state['initial_basis']=dict(guide_image=guide['image'],native_result=guide['native_result'],guide_review_sha256=flow.digest(review))
    sb=flow.freeze(folder/'state_plan.json',state)
    library=folder/'voice_library';bindings={}
    source=flow._bound(old_input['source_case'])['shots'][0]
    speakers=list(dict.fromkeys(a['speaker'] for a in source['audio']))
    quotes=flow.core.QUOTE.findall(flow.core.check(source['source']).read_text(encoding='utf-8'))
    for i,cid in enumerate(speakers):
        path=folder/(cid+'.wav');rate=32000
        samples=[int(2000*math.sin(2*math.pi*(230+i*90)*t/rate)) for t in range(rate)]
        with wave.open(str(path),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate)
            wav.writeframes(struct.pack('<'+'h'*len(samples),*samples))
        line=next(a for a in source['audio'] if a['speaker']==cid)
        candidate=voice.register_candidate(library,path,book_id=str(flow._bound(old_spec['library_binding'])['book_id']),
            character_id=cid,reference_text=quotes[line['quote_index']][1:-1],
            source=dict(kind='synthetic_offline_test_signal',human_voice=False),voice_description='TEST SIGNAL ONLY, not a character voice.')
        if reviewed:
            voice.review(library,book_id=candidate['book_id'],asset_id=candidate['asset_id'],version=candidate['version'],
                audio_sha256=candidate['audio']['sha256'],decision='reviewed',reviewer='synthetic_fixture_not_production_approval',
                checks={k:True for k in voice.REVIEW_CHECKS},evidence=dict(audio_sha256=candidate['audio']['sha256'],
                    listening_performed=True,observations=['Mock listening assertion solely exercises the registry contract; this is a sine test signal, not an approved real voice.']))
            bindings[cid]=voice.make_binding(library,book_id=candidate['book_id'],character_id=cid,
                asset_id=candidate['asset_id'],version=candidate['version'])
    spec=dict(schema=flow.SCHEMA,source_case=flow.bind(OLD/'segments/S04/SOURCE_CASE.json'),
        library_binding=old_spec['library_binding'],binding_approval=old_spec['binding_approval'],
        base_workflow=flow.bind(old_spec['config']['base_workflow']),guide=guide,state_plan=sb,
        place=dict(id='children_room',name='孩子们的房间',views=['front','side'],story_time='同一傍晚'),
        voice=dict(library=str(library),book_id=str(flow._bound(old_spec['library_binding'])['book_id']),mode=mode,bindings=bindings),
        profile=deepcopy(flow.PROFILE))
    spec_path=folder/'RUN_SPEC.json';flow.freeze(spec_path,spec)
    return spec_path,folder/'output'
