"""Candidate-bound addresses for access evidence; camera cuts never create hearing."""
from copy import deepcopy
from . import contracts as c


def catalog(candidate):
    result={}
    for scene in candidate['scenes']:
        for b in scene['segments']:
            for field in ('action','camera','continuity_obligations'):
                values=b[field] if isinstance(b[field],list) else [b[field]]
                for i,text in enumerate(values):
                    key=f"{b['id']}:{field}:{i}"
                    result[key]={'segment_id':b['id'],'field':field,'index':i,'text':text,'text_sha256':c.digest(text)}
    return result


def schema(candidate,places):
    beats=[b for s in candidate['scenes'] for b in s['segments']]
    anchors=['before_audio']+[f'audio:{i}' for i in range(max(len(b['audio']) for b in beats))]
    row=c.obj(segment_id=c.choices([b['id'] for b in beats]),kind=c.choices(['camera_cut','sightline','hearing']),
        place=c.choices(places),start=c.choices(anchors),end=c.choices(anchors),
        evidence_ids=c.refs(catalog(candidate)),certainty=c.choices(['explicit','inferred','uncertain']))
    return c.obj(candidate_sha256=c.choices([c.digest(candidate)]),access=c.array(row),uncertainties=c.array(c.TEXT))


def compile_access(candidate,base,proposal,places):
    if base['candidate_sha256']!=c.digest(candidate):raise ValueError('stale_base_projection')
    errors=c.schema_issues(proposal,schema(candidate,places),'access')
    if errors:raise c.ContractError(errors)
    evidence=catalog(candidate);output=deepcopy(base);unresolved=[];receipts=[]
    by={r['id']:r for r in output['segments']}
    for row in by.values():row.pop('sensory_windows',None)
    def index(value):return -1 if value=='before_audio' else int(value.split(':')[1])
    for row in proposal['access']:
        scene,beat=next((s,b) for s in candidate['scenes'] for b in s['segments'] if b['id']==row['segment_id'])
        if row['place']==scene['place']:raise ValueError('access_requires_remote_place')
        if any(index(row[key])>=len(beat['audio']) for key in ('start','end')):raise ValueError('access_anchor_outside_segment')
        if index(row['start'])>index(row['end']):raise ValueError('access_interval_reversed')
        refs=[evidence[key] for key in row['evidence_ids']]
        if any(r['segment_id']!=row['segment_id'] for r in refs):raise ValueError('access_evidence_wrong_segment')
        if row['kind']=='camera_cut' and not any(r['field']=='camera' for r in refs):
            raise ValueError('camera_cut_requires_camera_evidence')
        receipt={'selection':deepcopy(row),'resolved_evidence':deepcopy(refs)};receipts.append(receipt)
        if row['certainty']!='explicit':
            unresolved.append(receipt);continue
        # The selected relation is still subject to semantic review. Program owns text.
        ref=refs[0]
        by[row['segment_id']].setdefault('sensory_windows',[]).append({
            'place':row['place'],'from_audio_index':index(row['start']),
            'through_audio_index':index(row['end']),
            'visible':row['kind'] in ('camera_cut','sightline'),'audible':row['kind']=='hearing',
            'evidence_field':ref['field'],'quote':ref['text']})
    output['uncertainties']+=proposal['uncertainties']
    return output,{'candidate_sha256':c.digest(candidate),'receipts':receipts,
                   'unresolved':unresolved,'semantic_acceptance':False}
