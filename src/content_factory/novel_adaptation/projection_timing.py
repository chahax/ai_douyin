"""Compile reviewed timing directives without rewriting generated prose/events.

The caller supplies a version-bound interpretation. This is a deterministic
state adjustment, not a model-generated replacement or semantic approval.
"""
from copy import deepcopy
from .contracts import digest
from .narrative_patch import value_at


def retime(candidate,presence,projection,directive):
    identities={'candidate':digest(candidate),'presence':digest(presence),'projection':digest(projection)}
    if directive['artifact_hashes']!=identities:raise ValueError('stale_timing_directive')
    if presence['candidate_sha256']!=identities['candidate'] or projection['candidate_sha256']!=identities['candidate']:
        raise ValueError('timing_candidate_binding')
    evidence=directive['evidence'];text=value_at(candidate,evidence['path'])
    if not isinstance(text,str) or not evidence['quote'] or evidence['quote'] not in text:
        raise ValueError('timing_evidence_not_exact')
    sid=directive['segment_id']
    segment=next(b for s in candidate['scenes'] for b in s['segments'] if b['id']==sid)
    parts=evidence['path'].split('/')
    if (len(parts) not in (6,7) or parts[1]!='scenes' or parts[3]!='segments'
            or parts[5] not in ('action','camera','continuity_obligations')
            or candidate['scenes'][int(parts[2])]['segments'][int(parts[4])]['id']!=sid):
        raise ValueError('timing_evidence_wrong_segment')
    p=deepcopy(presence);e=deepcopy(projection)
    pr=next(x for x in p['segments'] if x['id']==sid)
    er=next(x for x in e['segments'] if x['id']==sid)
    seen=set();receipts=[]
    for change in directive['changes']:
        key=(change['kind'],change['index'])
        if key in seen:raise ValueError('duplicate_timing_target')
        seen.add(key)
        if type(change['index']) is not int or change['index']<0:raise ValueError('invalid_timing_index')
        if change['kind']=='move':target=pr['moves'][change['index']]
        elif change['kind']=='event':target=er['events'][change['index']]['event']
        else:raise ValueError('invalid_timing_kind')
        before={'phase':target.get('phase','start'),'after_audio_index':target.get('after_audio_index')}
        if before!=change['before']:raise ValueError('timing_before_changed')
        after=change['after']
        if set(after)!={'phase','after_audio_index'}:raise ValueError('timing_fields_only')
        phase=after['phase'];anchor=after['after_audio_index']
        if phase not in ('start','end','after_audio'):raise ValueError('invalid_timing_phase')
        if phase=='after_audio':
            if type(anchor) is not int or not 0<=anchor<len(segment['audio']):raise ValueError('invalid_audio_anchor')
        elif anchor is not None:raise ValueError('unexpected_audio_anchor')
        target.update(after)
        if change['kind']=='event' and anchor is None:target.pop('after_audio_index',None)
        receipts.append(deepcopy(change))
    if not receipts:raise ValueError('empty_timing_directive')
    return p,e,{'artifact_hashes':identities,'directive_sha256':digest(directive),
        'segment_id':sid,'changes':receipts,'prose_unchanged':True,
        'method':'deterministic_reviewed_timing_directive','semantic_acceptance':False}
