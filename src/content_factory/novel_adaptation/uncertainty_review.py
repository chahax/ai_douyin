"""Version-bound dispositions for retained historical uncertainty notes.

Checks identity, complete coverage and evidence addresses, not reviewer truth.
Never deletes historical notes or treats a disposition as episode acceptance.
"""
from .contracts import digest
from .narrative_patch import value_at


def inventory(artifacts):
    rows=[]
    for origin in ('presence','projection'):
        for index,text in enumerate(artifacts[origin]['uncertainties']):
            rows.append({'id':f'{origin}:{index}:{digest(text)[:16]}',
                         'origin':origin,'index':index,'text':text})
    for index,text in enumerate(artifacts.get('replay',{}).get('registry_uncertainties',[])):
        rows.append({'id':f'registry:{index}:{digest(text)[:16]}',
                     'origin':'registry','index':index,'text':text})
    return rows


def identity(artifacts):
    return {key:digest(value) for key,value in artifacts.items()}


def evaluate(artifacts,review):
    if review.get('artifact_hashes')!=identity(artifacts):raise ValueError('stale_uncertainty_review')
    rows=inventory(artifacts);expected={r['id'] for r in rows}
    dispositions=review['dispositions'];ids=[d['id'] for d in dispositions]
    if len(ids)!=len(set(ids)) or set(ids)!=expected:raise ValueError('uncertainty_coverage')
    counts={k:0 for k in ('resolved','design_choice','retained_limit','open')}
    for item in dispositions:
        if item['decision'] not in counts or not item.get('reason','').strip():
            raise ValueError('uncertainty_decision_missing')
        if not item.get('evidence'):raise ValueError('uncertainty_evidence_missing')
        for evidence in item['evidence']:
            artifact=evidence['artifact'];path=evidence['path']
            if artifact not in artifacts:raise ValueError('uncertainty_evidence_artifact')
            value=value_at(artifacts[artifact],path)
            if digest(value)!=evidence['value_sha256']:raise ValueError('uncertainty_evidence_changed')
        counts[item['decision']]+=1
    return {'artifact_hashes':identity(artifacts),'counts':counts,
            'open_ids':[d['id'] for d in dispositions if d['decision']=='open'],
            'retained_limit_ids':[d['id'] for d in dispositions if d['decision']=='retained_limit'],
            'status':'dispositions_structurally_verified_not_semantic_acceptance',
            'semantic_acceptance':False,'original_notes_preserved':True}
