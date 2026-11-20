"""Program-owned patch binding: models choose IDs, never copy SHA strings."""
from . import contracts as c
from copy import deepcopy
import math


def bind_patches(candidate,proposals,allowed_ids,expected_sha256):
    if c.digest(candidate)!=expected_sha256:raise ValueError('stale_patch_candidate')
    root=next((k for k in ('entities','facts','choices','beats') if k in candidate),None)
    if root is None:raise ValueError('unknown_record_collection')
    rows={r['id']:r for r in candidate[root]};seen=set();bound=[]
    for p in proposals:
        id=p['id']
        if id not in allowed_ids or id not in rows or id in seen or p['replacement']['id']!=id:
            raise ValueError('patch_scope_or_identity')
        seen.add(id)
        bound.append({'id':id,'before_sha256':c.digest(rows[id]),'replacement':p['replacement']})
    return bound


def retime_beats(scene):
    """Translate beat-local/original intervals while preserving all prose fields."""
    out=deepcopy(scene);cursor=0
    for beat in out['beats']:
        origin=beat['start'];duration=beat['end']-origin
        if duration<=0:raise ValueError('invalid_beat_duration')
        for audio in beat['audio']:
            if not origin<=audio['start']<audio['end']<=beat['end']:
                raise ValueError('audio_outside_original_beat')
            audio['start']=round(audio['start']-origin+cursor,4)
            audio['end']=round(audio['end']-origin+cursor,4)
        beat['start']=cursor;beat['end']=round(cursor+duration,4);cursor=beat['end']
    return out,cursor


def mechanical_repair_scope(scene,issues):
    """A mechanical error never authorizes changing story action or camera prose."""
    permissions={};count=len(scene['beats'])
    for issue in issues:
        parts=issue.path.strip('/').split('/')
        if len(parts)<2 or parts[0]!='beats' or not parts[1].isdigit():
            raise ValueError('mechanical_issue_requires_separate_owner')
        index=int(parts[1])
        if issue.code in {'speech_too_fast','audio_overlap','audio_outside_beat'}:
            fields={'audio'};indexes={index}
        elif issue.code in {'presence_mismatch','invalid_move','absent_speaker','information_user_absent'}:
            fields={'moves'};indexes={index,max(0,index-1)}
        elif issue.code in {'prop_transfer_origin','prop_transfer_remote'}:
            fields={'transfers'};indexes={index,max(0,index-1)}
        elif issue.code=='beat_timing':
            fields={'start','end','audio'};indexes={index,max(0,index-1),min(count-1,index+1)}
        else:raise ValueError('mechanical_issue_requires_separate_owner')
        for i in indexes:permissions.setdefault(scene['beats'][i]['id'],set()).update(fields)
    return permissions


def field_patch_schema(scene_schema,permissions):
    variants=[];properties=scene_schema['properties']['beats']['items']['properties']
    for id,fields in permissions.items():
        changes={'type':'object','properties':{k:properties[k] for k in sorted(fields)},
                 'additionalProperties':False,'minProperties':1}
        variants.append(c.obj(id=c.choices([id]),changes=changes))
    return c.obj(patches=c.array({'oneOf':variants},1))


def apply_field_patches(scene,proposals,permissions,expected_sha256,*,audio_kind_permissions=None):
    rows={r['id']:r for r in scene['beats']};replacements=[]
    for proposal in proposals:
        id=proposal['id'];changes=proposal['changes']
        if id not in permissions or not changes or not set(changes)<=permissions[id]:
            raise ValueError('patch_field_not_owned_by_mechanical_issue')
        if 'audio' in changes:
            before=[(a['speaker'],a['kind']) for a in rows[id]['audio']]
            after=[(a['speaker'],a['kind']) for a in changes['audio']]
            if len(before)!=len(after):raise ValueError('mechanical_patch_changed_audio_identity_or_count')
            if id in (audio_kind_permissions or {}):
                for index,(old,new) in enumerate(zip(rows[id]['audio'],changes['audio'])):
                    allowed=(audio_kind_permissions or {})[id].get(str(index),[])
                    expected=deepcopy(old)
                    if allowed and new.get('kind') in allowed:expected['kind']=new['kind']
                    if new!=expected:raise ValueError('audio_kind_patch_changed_unowned_content')
            for index,((old_speaker,old_kind),(new_speaker,new_kind)) in enumerate(zip(before,after)):
                allowed=(audio_kind_permissions or {}).get(id,{}).get(str(index),[])
                if old_speaker!=new_speaker or (old_kind!=new_kind and new_kind not in allowed):
                    raise ValueError('mechanical_patch_changed_audio_identity_or_count')
        replacements.append({'id':id,'replacement':{**deepcopy(rows[id]),**deepcopy(changes)}})
    bound=bind_patches(scene,replacements,set(permissions),expected_sha256)
    return c.apply_record_patches(scene,bound,set(permissions),expected_sha256,lambda _:None)


def schedule_audio(scene,max_rate=6,max_beat_seconds=15):
    """Repair arithmetic by scheduling, not by asking a model to rewrite lines.

    This is a conservative text-length estimate, not a measured voice duration.
    All wording, speakers and actions stay byte-for-byte identical.
    """
    result=deepcopy(scene);changed=[]
    for beat in result['beats']:
        lines=beat['audio'];last=beat['start'];invalid=False
        for a in lines:
            duration=a['end']-a['start']
            invalid|=not beat['start']<=a['start']<a['end']<=beat['end'] or a['start']<last
            invalid|=duration<=0 or (len(a['text'])/duration>max_rate if duration>0 else True)
            last=a['end']
        if not invalid:continue
        minimum=[math.ceil((len(a['text'])/max_rate+.01)*100)/100 for a in lines]
        needed=sum(minimum)+.15*max(0,len(lines)-1)+.2
        duration=max(beat['end']-beat['start'],math.ceil(needed*10)/10)
        if duration>max_beat_seconds:raise ValueError('audio_requires_story_timing_revision')
        slack=(duration-needed)/len(lines) if lines else 0
        cursor=beat['start']+.1
        for a,seconds in zip(lines,minimum):
            a['start']=round(cursor,4);a['end']=round(cursor+seconds+slack,4);cursor=a['end']+.15
        beat['end']=round(beat['start']+duration,4);changed.append(beat['id'])
    result,total=retime_beats(result)
    return result,{'changed_beats':changed,'duration_seconds':total,'max_characters_per_second':max_rate,
                   'timing_origin':'program_estimate_not_voice_measurement','source_scene_sha256':c.digest(scene)}


def audio_kind_patch_schema(permissions):
    variants=[]
    for beat_id,indexes in permissions.items():
        for index,kinds in indexes.items():
            variants.append(c.obj(beat_id=c.choices([beat_id]),index={'type':'integer','const':int(index)},kind=c.choices(kinds)))
    return c.obj(corrections=c.array({'oneOf':variants},1))


def apply_audio_kinds(scene,corrections,permissions,expected_sha256):
    if c.digest(scene)!=expected_sha256:raise ValueError('stale_audio_candidate')
    schema=audio_kind_patch_schema(permissions)
    errors=c.schema_issues({'corrections':corrections},schema,'audio_kind')
    if errors:raise c.ContractError(errors)
    result=deepcopy(scene);rows={b['id']:b for b in result['beats']};seen=set()
    for item in corrections:
        key=(item['beat_id'],item['index'])
        if key in seen:raise ValueError('duplicate_audio_correction')
        seen.add(key)
        rows[key[0]]['audio'][key[1]]['kind']=item['kind']
    expected={(b,int(i)) for b,indexes in permissions.items() for i in indexes}
    if seen!=expected:raise ValueError('incomplete_audio_kind_correction')
    return result


def visual_patch_schema(indexes):
    return c.obj(corrections=c.array({'oneOf':[
        c.obj(index={'type':'integer','const':i},description=c.TEXT) for i in indexes]},1))


def apply_visual_patches(design,corrections,indexes,expected_sha256):
    if c.digest(design)!=expected_sha256:raise ValueError('stale_visual_candidate')
    errors=c.schema_issues({'corrections':corrections},visual_patch_schema(indexes),'visual')
    if errors:raise c.ContractError(errors)
    result=deepcopy(design);seen=set()
    for row in corrections:
        index=row['index']
        if index in seen:raise ValueError('duplicate_visual_patch')
        seen.add(index)
        result['visual_design'][index]['description']=row['description']
    if seen!=set(indexes):raise ValueError('incomplete_visual_patch')
    return result


def audio_text_patch_schema(permissions):
    return c.obj(corrections=c.array({'oneOf':[
        c.obj(beat_id=c.choices([beat_id]),index={'type':'integer','const':int(index)},text=c.TEXT)
        for beat_id,indexes in permissions.items() for index in indexes]},1))


def apply_audio_texts(scene,corrections,permissions,expected_sha256):
    if c.digest(scene)!=expected_sha256:raise ValueError('stale_audio_candidate')
    errors=c.schema_issues({'corrections':corrections},audio_text_patch_schema(permissions),'audio_text')
    if errors:raise c.ContractError(errors)
    result=deepcopy(scene);rows={b['id']:b for b in result['beats']};seen=set()
    for item in corrections:
        key=(item['beat_id'],item['index'])
        if key in seen:raise ValueError('duplicate_audio_correction')
        seen.add(key);rows[key[0]]['audio'][key[1]]['text']=item['text']
    expected={(b,int(i)) for b,indexes in permissions.items() for i in indexes}
    if seen!=expected:raise ValueError('incomplete_audio_text_correction')
    return result
