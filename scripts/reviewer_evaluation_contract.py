"""Check reviewer response structure and literal citations, never semantic correctness."""
from __future__ import annotations
import json

CATEGORIES={'requirements','causality','timing','props','space','dialogue','ending'}

def inspect_review(review,samples):
    errors=[];citations=[]
    lookup={s['sample_id']:s for s in samples}
    if len(lookup)!=len(samples):raise ValueError('duplicate input sample_id')
    def error(path,kind):errors.append({'path':path,'kind':kind})
    rows=review.get('reviews') if isinstance(review,dict) else None
    if not isinstance(rows,list):
        return {'errors':[{'path':'reviews','kind':'expected_array'}],'citations':[],'automatic_approval':False}
    ids=[r.get('sample_id') if isinstance(r,dict) else None for r in rows]
    if len(ids)!=len(lookup) or any(not isinstance(x,str) for x in ids) or set(x for x in ids if isinstance(x,str))!=set(lookup):error('reviews','sample_coverage')
    for ri,row in enumerate(rows):
        rp=f'reviews.{ri}'
        if not isinstance(row,dict):error(rp,'expected_object');continue
        sid=row.get('sample_id');sample=lookup.get(sid) if isinstance(sid,str) else None
        if not isinstance(row.get('strength'),str) or not row['strength'].strip():error(rp+'.strength','missing_text')
        issues=row.get('issues')
        if not isinstance(issues,list):error(rp+'.issues','expected_array');continue
        for ii,issue in enumerate(issues):
            ip=f'{rp}.issues.{ii}'
            if not isinstance(issue,dict):error(ip,'expected_object');continue
            if issue.get('severity') not in ('major','minor'):error(ip+'.severity','invalid_enum')
            if not isinstance(issue.get('category'),str) or issue['category'] not in CATEGORIES:error(ip+'.category','invalid_enum')
            for key in ('impact','proposal'):
                if not isinstance(issue.get(key),str) or not issue[key].strip():error(ip+'.'+key,'missing_text')
            ev=issue.get('evidence')
            if not isinstance(ev,list) or not ev:error(ip+'.evidence','missing_evidence');continue
            for ei,e in enumerate(ev):
                ep=f'{ip}.evidence.{ei}';valid=False;reason='invalid_reference'
                try:
                    if not isinstance(e,dict) or not isinstance(e.get('path'),str) or not isinstance(e.get('quote'),str) or not e['quote']:raise ValueError()
                    parts=e['path'].split('.')
                    value=sample if parts[0] in ('brief','script') else sample['script']
                    for part in parts:
                        if isinstance(value,list):
                            if not part.isdecimal():raise ValueError()
                            value=value[int(part)]
                        elif isinstance(value,dict):value=value[part]
                        else:raise ValueError()
                    if isinstance(value,str):valid=e['quote'] in value
                    elif isinstance(value,(int,float)) and not isinstance(value,bool):valid=e['quote']==json.dumps(value)
                    else:reason='citation_target_not_scalar'
                    if not valid and reason=='invalid_reference':reason='quote_not_literal'
                except (KeyError,TypeError,ValueError,IndexError):pass
                citations.append({'location':ep,'sample_id':sid,'issue_index':ii,'valid':valid,'reference':e})
                if not valid:error(ep,reason)
    return {'errors':errors,'citations':citations,'automatic_approval':False}
