"""Apply proposed card edits only to explicit records, retaining original banks."""
from copy import deepcopy
from . import contracts as c


def schema_for(source, banks, findings, addition_ids):
    variants=[]
    for bank,ids in findings.items():
        record_schema=(c.entity_schema(source)['properties']['entities']['items'] if bank=='identity'
            else c.fact_schema(source,banks['identity'],bank)['properties']['facts']['items'])
        variants.append(c.obj(bank=c.choices([bank]),id=c.choices(ids),record=record_schema))
    return c.obj(replacements=c.array({'oneOf':variants}),
        additions=c.array(c.entity_schema(source)['properties']['entities']['items']))


def apply_proposal(banks, proposal, findings, addition_ids, source):
    schema=schema_for(source,banks,findings,addition_ids)
    errors=c.schema_issues(proposal,schema,'repair')
    if errors:raise c.ContractError(errors)
    required={(bank,id) for bank,rows in findings.items() for id in rows}
    actual=[(p['bank'],p['id']) for p in proposal['replacements']]
    if set(actual)!=required or len(actual)!=len(required):raise ValueError('repair_target_coverage')
    if {r['id'] for r in proposal['additions']}!=set(addition_ids):raise ValueError('addition_target_coverage')
    output=deepcopy(banks)
    for bank in findings:
        root='entities' if bank=='identity' else 'facts'
        original={r['id']:r for r in banks[bank][root]}
        patch=[{'id':p['id'],'before_sha256':c.digest(original[p['id']]),'replacement':p['record']}
               for p in proposal['replacements'] if p['bank']==bank]
        validator=(lambda x:c.validate_entities(x,source)) if bank=='identity' else (
            lambda x,b=bank:c.validate_facts(x,source,output['identity'],b))
        output[bank]=c.apply_record_patches(banks[bank],patch,set(findings[bank]),c.digest(banks[bank]),validator)
    output['identity']=c.append_records(output['identity'],proposal['additions'],addition_ids,
        c.digest(output['identity']),lambda x:c.validate_entities(x,source))
    return output
