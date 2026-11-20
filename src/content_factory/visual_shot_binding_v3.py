"""Per-shot references. Scene membership never implies camera visibility."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

AUDIO_MODES=('onscreen','inner_voice','voiceover','offscreen_dialogue')

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def requirements(packet):
    """Only explicitly staged views are sent to the shot; full turnarounds stay in library."""
    chars={c['id']:c for c in packet['characters']}
    places={p['id']:p for p in packet.get('places',[])}
    result={}
    ids=[s['id'] for s in packet.get('shots',[])]
    if len(ids)!=len(set(ids)):raise ValueError('duplicate_shot_id')
    for shot in packet.get('shots',[]):
        visible=shot.get('visible_cast')
        if not isinstance(visible,list) or len(visible)!=len(set(visible)):
            raise ValueError('explicit_visible_cast_required')
        if not set(visible)<=set(chars):raise ValueError('unknown_visible_person')
        if not shot.get('visual_prompt','').strip():raise ValueError('shot_visual_required')
        if set(shot.get('character_views',{}))!=set(visible):raise ValueError('one_view_per_visible_person')
        if shot['place_id'] not in places:raise ValueError('unknown_shot_place')
        for a in shot.get('audio',[]):
            if a['mode'] not in AUDIO_MODES:raise ValueError('unknown_audio_mode')
            if a['mode']=='onscreen' and a['speaker'] not in visible:
                raise ValueError('onscreen_speaker_not_visible')
        for cid in visible:
            c=chars[cid];view=shot['character_views'][cid]
            if view not in ('front','left_oblique','right_oblique','left_profile','right_profile','back','face','clothing','hands'):
                raise ValueError('unknown_character_view')
            row=dict(entity_id=cid,kind='character',view=view,design_version=c.get('design_version','v1'))
            result[(cid,'character',view,row['design_version'])]=row
        place=places[shot['place_id']]
        row=dict(entity_id=place['id'],kind='place',view=shot.get('place_view','front'),design_version=place.get('design_version','v1'))
        result[(place['id'],'place',row['view'],row['design_version'])]=row
    return list(result.values())


def compile_bindings(packet, lookup):
    """lookup(requirement) returns exactly the current reviewed asset version."""
    wanted=requirements(packet);selected={}
    for req in wanted:
        asset=lookup(req)
        if not asset or asset.get('status')!='reviewed':raise ValueError('required_asset_not_reviewed:'+req['entity_id']+'/'+req['view'])
        if str(asset['book_id'])!=str(packet['book_id']):raise ValueError('cross_book_asset')
        if any(asset.get(k)!=req[k] for k in ('entity_id','kind','view','design_version')):raise ValueError('asset_scope_changed')
        selected[(req['entity_id'],req['kind'],req['view'])]=deepcopy(asset)
    output=[]
    for shot in packet['shots']:
        refs=[selected[(cid,'character',shot['character_views'][cid])] for cid in shot['visible_cast']]
        refs.append(selected[(shot['place_id'],'place',shot.get('place_view','front'))])
        if len(refs)>3:raise ValueError('first_frame_pilot_supports_max_two_people_plus_place')
        row=deepcopy(shot);row['references']=refs
        row['binding_sha256']=fingerprint(dict(shot=shot,assets=refs,source=packet['source']))
        row['render_text']=False;row['subtitles_stage']='postproduction'
        # A validated tail can only continue this same physical scene and version.
        tail=shot.get('previous_tail')
        if tail:
            if tail.get('place_id')!=shot['place_id'] or tail.get('scene_id')!=shot['scene_id'] or tail.get('reviewed') is not True:
                raise ValueError('unreviewed_or_cross_scene_tail')
            if tail.get('asset_versions')!={a['entity_id']:a['version'] for a in refs}:
                raise ValueError('tail_asset_version_changed')
            p=Path(tail['path'])
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=tail.get('sha256'):
                raise ValueError('tail_file_changed')
        output.append(row)
    return dict(schema='visual_shot_bindings/v3',book_id=packet['book_id'],packet_sha256=fingerprint(packet),shots=output,media_generated=False)


def packet_from_episode(accepted,bible,book_id,source,shot_specs):
    """Existing accepted text handoff; camera staging stays explicit and source-bound."""
    bound=accepted['bound'];scenes={s['id']:s for s in bound['script']['scenes']}
    known={c['id'] for c in bible['characters']};places={p['id'] for p in bible['places']}
    if not shot_specs:raise ValueError('staging_specs_required')
    shots=[]
    for spec in shot_specs:
        scene=scenes[spec['scene_id']]
        if not set(spec['visible_cast'])<=set(scene['cast']) or scene['place_id'] not in places:
            raise ValueError('staging_outside_accepted_scene')
        if spec['place_id']!=scene['place_id']:raise ValueError('place_change_without_text_revision')
        if not (0<=spec['start']<spec['end']<=scene['seconds']):raise ValueError('shot_time_outside_scene')
        def strings(value):
            if isinstance(value,str):yield value
            elif isinstance(value,dict):
                for v in value.values():yield from strings(v)
            elif isinstance(value,list):
                for v in value:yield from strings(v)
        original_strings=list(strings(scene))
        if not spec.get('evidence') or any(not q.strip() or not any(q in s for s in original_strings) for q in spec['evidence']):
            raise ValueError('staging_evidence_missing')
        shots.append(spec)
    if not {cid for s in shots for cid in s['visible_cast']}<=known:raise ValueError('unknown_bible_character')
    packet=dict(schema='visual_asset_packet/v3',book_id=str(book_id),source=source,
                accepted_sha256=fingerprint(accepted),characters=deepcopy(bible['characters']),
                places=deepcopy(bible['places']),shots=deepcopy(shots))
    requirements(packet)
    return packet


def read_bound_artifact(run,name):
    run=Path(run).resolve();index=json.loads((run/'ARTIFACT_INDEX.json').read_text(encoding='utf-8'));row=index[name]
    path=(run/row['path']).resolve()
    if not path.is_relative_to(run):raise ValueError('artifact_outside_text_run')
    value=json.loads(path.read_text(encoding='utf-8'))
    legacy_digest=hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    if legacy_digest!=row['sha256']:raise ValueError('text_artifact_changed')
    return value
