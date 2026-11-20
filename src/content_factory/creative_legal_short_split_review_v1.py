"""Separate source and actual performance citations, model complete review unchanged."""
from copy import deepcopy
from jsonschema import Draft202012Validator
from src.content_factory import creative_legal_short_director_performance_v1 as base
VERSION='legal_split_source_review/v2'
def schema(context):
 s=base.review_schema(context);cat=base.evidence_catalog(context)
 for i,row in enumerate(s['properties']['coverage']['prefixItems']):
  beat=context['script']['beats'][i]['id'];indexes=[j for j,r in enumerate(context['compiled']['schedule']) if r['beat_id']==beat]
  original=[e for e,v in cat.items() if v['path'].startswith(f'script.beats.{i}.')]
  current=[e for e,v in cat.items() if any(v['path'].startswith(f'compiled.schedule.{j}.') for j in indexes)]
  row['properties'].pop('evidence_refs');row['required'].remove('evidence_refs')
  row['properties']['script_evidence_refs']=base.arr({'enum':original},1,3)
  row['properties']['performance_evidence_refs']=base.arr({'enum':current},1,3)
  row['required']+=['script_evidence_refs','performance_evidence_refs']
 return s

def expand(raw,context):
 Draft202012Validator(schema(context)).validate(raw);value=deepcopy(raw)
 for row in value['coverage']:
  row['evidence_refs']=row.pop('script_evidence_refs')+row.pop('performance_evidence_refs')
 return base.validate_review(value,context)

def compact_catalog(context):
 return [{'id':e,'path':v['path'],'excerpt':v['quote'][:48]} for e,v in base.evidence_catalog(context).items()]
