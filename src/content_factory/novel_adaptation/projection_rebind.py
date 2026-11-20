"""Invalidate evidence explicitly when rebinding a narrowly edited narrative.

No semantic acceptance is inherited. Existing moves and prop actions are copied
only for renewed validation against the new candidate.
"""
from copy import deepcopy
from .contracts import digest
from .narrative_patch import value_at,apply


def rebind(old,new,presence,plan,projection,approved_paths):
    if presence['candidate_sha256']!=digest(old) or projection['candidate_sha256']!=digest(old) or projection['plan_sha256']!=digest(plan):
        raise ValueError('rebind_original_identity_mismatch')
    edits=[];affected=[];changes=[]
    for path in approved_paths:
        tokens=path.split('/')
        scene_field=(len(tokens)==6 and tokens[5] in ('action','camera'))
        obligation=(len(tokens)==7 and tokens[5] in ('continuity_obligations','visual_additions')
                    and tokens[6].isascii() and tokens[6].isdecimal()
                    and str(int(tokens[6]))==tokens[6])
        timing=(len(tokens)==6 and tokens[5]=='seconds')
        audio=(len(tokens)==8 and tokens[5]=='audio' and tokens[7]=='text')
        segment_path=(len(tokens)>=6 and tokens[1]=='scenes' and tokens[3]=='segments'
                      and (scene_field or obligation or timing or audio))
        exit_path=(len(tokens)==4 and tokens[1]=='scenes' and tokens[3]=='exit_continuity')
        note_path=(len(tokens)==4 and tokens[1]=='condensation_notes' and tokens[3]=='treatment')
        if not (segment_path or exit_path or note_path):
            raise ValueError('rebind_only_approved_scene_prose')
        before=value_at(old,path);after=value_at(new,path)
        if timing and segment_path:
            if type(before) not in (int,float) or type(after)!=type(before) or after<=0:
                raise ValueError('rebind_duration_type')
        elif not isinstance(before,str) or not isinstance(after,str):raise ValueError('rebind_prose_type')
        if before!=after:
            if segment_path:affected.append(old['scenes'][int(tokens[2])]['segments'][int(tokens[4])]['id'])
            elif exit_path:affected.append(old['scenes'][int(tokens[2])]['segments'][-1]['id'])
            changes.append({'path':path,'before_sha256':digest(before),'after_sha256':digest(after)})
        edits.append({'path':path,'value':after})
    expected=apply(old,{'candidate_sha256':digest(old),'replacements':edits},approved_paths,digest(old))
    if expected!=new or not changes:raise ValueError('rebind_unapproved_or_empty_change')
    new_presence=deepcopy(presence);new_presence['candidate_sha256']=digest(new)
    new_projection=deepcopy(projection);new_projection['candidate_sha256']=digest(new)
    receipt={'old_candidate_sha256':digest(old),'new_candidate_sha256':digest(new),
        'original_presence_sha256':digest(presence),'original_projection_sha256':digest(projection),
        'plan_sha256':digest(plan),'changed_fields':changes,'affected_segment_ids':list(dict.fromkeys(affected)),
        'status':'rebound_for_revalidation_only','semantic_acceptance':False,
        'prior_uncertainties_retained':True,'prior_acceptance_inherited':False}
    return new_presence,new_projection,receipt
