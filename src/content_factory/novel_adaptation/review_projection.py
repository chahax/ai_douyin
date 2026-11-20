"""Review what the production text actually emits, with explicit scope.

Original candidate and native audit annotations remain immutable evidence.
"""
from copy import deepcopy
from .contracts import digest


def review_projection(candidate,brief):
    projected=deepcopy(candidate)
    projected['end_state']={k:v for k,v in projected['end_state'].items() if k!='information'}
    excluded=[]
    for scene in projected['scenes']:
        for beat in scene['beats']:
            if 'adaptation_detail' in beat:
                excluded.append({'scene_id':scene['id'],'beat_id':beat['id'],'field':'adaptation_detail',
                    'sha256':digest(beat.pop('adaptation_detail'))})
    return {'candidate':projected,'candidate_sha256':digest(candidate),
        'review_scope':{'objective':brief.get('objective',''),'target_chapters':brief.get('target_chapters',[]),
            'scene_count':len(projected['scenes']),'pacing_policy':deepcopy(brief.get('pacing_policy',{})),
            'note':'target_chapters indicates source provenance, not automatic full-chapter coverage. Evaluate the stated objective.'},
        'excluded_audit_only_fields':excluded,
        'render_contract':'Action, camera, emotion and audio are emitted. adaptation_detail is audit-only and is not a performance instruction. Internal state placeholders are not new film locations.'}
