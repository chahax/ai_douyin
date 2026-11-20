"""Camera visibility/asset-scope regressions; no image quality claims."""
from copy import deepcopy
import hashlib
import json

import pytest

from src.content_factory import visual_shot_binding_v3 as b


def packet():
    return dict(schema='visual_asset_packet/v3',book_id='book1',source=dict(path='script.md',sha256='a'*64),
        characters=[dict(id='actor',design_version='v1'),dict(id='voice_only',design_version='v1'),dict(id='third',design_version='v1')],
        places=[dict(id='room',design_version='v1')],
        # scene.cast is deliberately broader than this camera's visible list.
        scenes=[dict(id='scene1',cast=['actor','voice_only','third'])],
        shots=[dict(id='shot1',scene_id='scene1',place_id='room',visible_cast=['actor'],
            character_views={'actor':'face'},visual_prompt='The actor lowers their eyes.',
            audio=[dict(mode='voiceover',speaker='voice_only',text='Are you listening?')])])


def lookup(req):
    return dict(asset_id=req['entity_id']+'_'+req['view'],version=1,book_id='book1',status='reviewed',
        sha256=hashlib.sha256((req['entity_id']+req['view']).encode()).hexdigest(),file='asset.png',**req)


def test_only_visible_actor_and_selected_single_view_not_entire_scene_cast():
    p=packet();calls=[]
    def record(req):calls.append(req);return lookup(req)
    out=b.compile_bindings(p,record)
    assert [(x['entity_id'],x['view']) for x in calls]==[('actor','face'),('room','front')]
    assert [x['entity_id'] for x in out['shots'][0]['references']]==['actor','room']
    assert out['shots'][0]['audio']==p['shots'][0]['audio']
    assert out['shots'][0]['render_text'] is False and out['shots'][0]['subtitles_stage']=='postproduction'
    assert p['shots'][0].get('references') is None


def test_empty_actor_frame_allows_narration_and_scene_plate_only():
    p=packet();s=p['shots'][0];s['visible_cast']=[];s['character_views']={}
    s['audio']=[dict(mode='voiceover',speaker='narrator',text='The room was empty.')]
    out=b.compile_bindings(p,lookup)
    assert [(r['kind'],r['entity_id']) for r in out['shots'][0]['references']]==[('place','room')]


@pytest.mark.parametrize('change,message',[
    (lambda s:s.pop('visible_cast'),'explicit_visible_cast'),
    (lambda s:s.update(visible_cast=['actor','actor']),'explicit_visible_cast'),
    (lambda s:s.update(visible_cast=['unknown'],character_views={'unknown':'front'}),'unknown_visible'),
    (lambda s:s.update(character_views={'actor':'face','voice_only':'front'}),'one_view_per'),
    (lambda s:s.update(character_views={'actor':'unknown'}),'unknown_character_view'),
    (lambda s:s.update(place_id='imagined_room'),'unknown_shot_place'),
    (lambda s:s.update(visual_prompt=''),'shot_visual'),
    (lambda s:s.update(audio=[dict(mode='onscreen',speaker='voice_only',text='Hello')]),'onscreen_speaker'),
])
def test_incorrect_staging_fails_before_media(change,message):
    p=packet();change(p['shots'][0])
    with pytest.raises(ValueError,match=message):b.compile_bindings(p,lookup)


def test_invalid_audio_mode_is_not_silently_treated_as_offscreen():
    p=packet();p['shots'][0]['audio'][0]['mode']='typo_on_screen'
    with pytest.raises(ValueError):b.compile_bindings(p,lookup)


def test_duplicate_shot_ids_cannot_share_and_overwrite_one_first_frame():
    p=packet();p['shots'].append(deepcopy(p['shots'][0]))
    with pytest.raises(ValueError):b.compile_bindings(p,lookup)


@pytest.mark.parametrize('mode',['missing','candidate','rejected','cross_book','wrong_view','wrong_version_design'])
def test_missing_unreviewed_or_wrong_scope_never_becomes_reference(mode):
    p=packet()
    def bad(req):
        row=lookup(req)
        if req['kind']=='place':
            if mode=='missing':return None
            if mode in ('candidate','rejected'):row['status']=mode
            if mode=='cross_book':row['book_id']='otherbook'
            if mode=='wrong_view':row['view']='reverse'
            if mode=='wrong_version_design':row['design_version']='old'
        return row
    with pytest.raises(ValueError):b.compile_bindings(p,bad)


def test_two_people_plus_place_supported_but_seven_people_is_explicitly_unsupported():
    p=packet();s=p['shots'][0];s['visible_cast']=['actor','voice_only'];s['character_views']={'actor':'front','voice_only':'left_profile'}
    assert len(b.compile_bindings(p,lookup)['shots'][0]['references'])==3
    p['characters']=[dict(id=f'p{i}',design_version='v1') for i in range(7)]
    s['visible_cast']=[f'p{i}' for i in range(7)];s['character_views']={cid:'front' for cid in s['visible_cast']}
    with pytest.raises(ValueError,match='max_two_people'):b.compile_bindings(p,lookup)


def test_changed_asset_version_changes_binding_and_invalidates_old_tail():
    p=packet();original=b.compile_bindings(p,lookup)
    s=p['shots'][0];s['previous_tail']=dict(place_id='room',scene_id='scene1',reviewed=True,asset_versions={'actor':1,'room':1})
    def new(req):
        row=lookup(req)
        if req['entity_id']=='actor':row.update(version=2,sha256='f'*64)
        return row
    with pytest.raises(ValueError,match='tail_asset_version_changed'):b.compile_bindings(p,new)
    s.pop('previous_tail');changed=b.compile_bindings(p,new)
    assert changed['shots'][0]['binding_sha256']!=original['shots'][0]['binding_sha256']


@pytest.mark.parametrize('tail',[
    dict(place_id='other_room',scene_id='scene1',reviewed=True,asset_versions={'actor':1,'room':1}),
    dict(place_id='room',scene_id='yesterday_dinner',reviewed=True,asset_versions={'actor':1,'room':1}),
    dict(place_id='room',scene_id='scene1',reviewed=False,asset_versions={'actor':1,'room':1}),
])
def test_cross_scene_or_unreviewed_tail_rejected_even_if_same_physical_room(tail):
    p=packet();p['shots'][0]['previous_tail']=tail
    with pytest.raises(ValueError):b.compile_bindings(p,lookup)


def accepted_episode():
    scene=dict(id='scene1',place_id='room',cast=['actor','voice_only'],seconds=15,action='The actor sits in the room.')
    accepted={'bound':{'script':{'scenes':[scene]}}}
    bible=dict(characters=[dict(id='actor'),dict(id='voice_only')],places=[dict(id='room')])
    spec=dict(id='shot1',scene_id='scene1',place_id='room',visible_cast=['actor'],character_views={'actor':'front'},
        start=0,end=10,evidence=['The actor sits in the room.'],visual_prompt='The actor sits in the room.',audio=[])
    return accepted,bible,spec


def test_episode_handoff_preserves_explicit_camera_scope_and_text_source():
    accepted,bible,spec=accepted_episode();source=dict(path='final.md',sha256='c'*64)
    p=b.packet_from_episode(accepted,bible,'book',source,[spec])
    assert p['shots'][0]['visible_cast']==['actor']
    assert p['accepted_sha256']==b.fingerprint(accepted) and p['source']==source


@pytest.mark.parametrize('change',[
    lambda s:s.update(place_id='other'),lambda s:s.update(end=16),
    lambda s:s.update(visible_cast=['new_person'],character_views={'new_person':'front'}),
    lambda s:s.update(evidence=['This never appeared in the accepted text.']),
])
def test_handoff_cannot_invent_person_place_timeline_or_evidence(change):
    accepted,bible,spec=accepted_episode();change(spec)
    with pytest.raises(ValueError):b.packet_from_episode(accepted,bible,'book',{},[spec])


def test_bound_artifact_read_detects_tampered_final_text(tmp_path):
    value={'bound':{'script':{'scenes':[]}}}
    file=tmp_path/'EP01_ACCEPTED.json';file.write_text(json.dumps(value))
    legacy_sha=hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    (tmp_path/'ARTIFACT_INDEX.json').write_text(json.dumps({file.name:dict(path=file.name,sha256=legacy_sha)}))
    assert b.read_bound_artifact(tmp_path,file.name)==value
    file.write_text('{}')
    with pytest.raises(ValueError,match='text_artifact_changed'):b.read_bound_artifact(tmp_path,file.name)
