"""Fixed literal spans in native prose; untouched text stays byte-for-byte equal."""
from . import contracts as c

def prepare(text,issues):
    slots=[]
    for i,issue in enumerate(issues):
        quote=issue['quote']
        if not quote or text.count(quote)!=1:raise ValueError('prose_span_not_unique')
        start=text.index(quote);end=start+len(quote)
        if any(start<s['end'] and end>s['start'] for s in slots):raise ValueError('prose_spans_overlap')
        slots.append({'key':f'edit_{i}','start':start,'end':end,'quote':quote,'reason':issue['reason']})
    return {'text_sha256':c.digest(text),'slots':slots}

def schema(plan):return c.obj(**{x['key']:{'type':'string'} for x in plan['slots']})

def apply(text,plan,proposal):
    if c.digest(text)!=plan['text_sha256']:raise ValueError('prose_changed')
    issues=c.schema_issues(proposal,schema(plan),'prose_patch')
    if issues:raise c.ContractError(issues)
    result=text
    for slot in sorted(plan['slots'],key=lambda x:x['start'],reverse=True):
        if text[slot['start']:slot['end']]!=slot['quote']:raise ValueError('prose_span_changed')
        result=result[:slot['start']]+proposal[slot['key']]+result[slot['end']:]
    return result
