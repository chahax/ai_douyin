"""Single material policy shared by prompts, schema and validation; v1 frozen."""
from copy import deepcopy
import json
from jsonschema import Draft202012Validator
from .serial_story_contract_v1 import *

VERSION = 'serial_story_contract/v4'
COVERAGE_RULES = {
    'covered': 'status=covered，claim_ids至少一个且去重，不能带reason/omission_reason；每条claim必须在evidence中直接引用该source_id。',
    'omitted': 'status=omitted，只包含source_id、status、非空reason，不能带claim_ids；说明为何无可提取材料。',
    'coverage': '本章每个非空原段恰好登记一次。不要用语义相关代替该claim真实绑定的证据地址。',
    'evidence': '原段ID来自目录，quote必须是该原段连续原文。不要为通过校验编造引文。',
}
COVERED = obj(source_id=TEXT,status={'type':'string','const':'covered'},claim_ids=IDS)
OMITTED = obj(source_id=TEXT,status={'type':'string','const':'omitted'},reason={**STR,'pattern':r'\S'})
MATERIAL = obj(chapter_index={'type':'integer'},claims=arr(CLAIM,1),
               coverage=arr({'oneOf':[COVERED,OMITTED]},1))
MATERIAL['description'] = '\n'.join(COVERAGE_RULES.values())


class ContractErrors(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__(json.dumps(errors,ensure_ascii=False,separators=(',',':')))


def material_schema(chapter):
    schema=deepcopy(MATERIAL)
    ids=[p['id'] for p in paragraphs({'chapters':[chapter]})]
    schema['properties']['chapter_index']={'type':'integer','const':chapter['index']}
    schema['properties']['coverage']['minItems']=len(ids)
    schema['properties']['coverage']['maxItems']=len(ids)
    for branch in schema['properties']['coverage']['items']['oneOf']:
        branch['properties']['source_id']={'enum':ids}
    schema['properties']['claims']['items']['properties']['evidence']['items']['properties']['source_id']={'enum':ids}
    return schema


def material_valid(raw, chapter):
    schema=material_schema(chapter)
    errors=[{'path':'/'+ '/'.join(str(p) for p in e.absolute_path),'code':'schema',
             'rule':e.validator,'expected':e.validator_value if e.validator in ('const','type','enum','required','pattern') else e.validator,
             'actual':e.instance if isinstance(e.instance,(str,int,float,bool,type(None))) else {'type':type(e.instance).__name__},'schema_path':'/'.join(str(p) for p in e.absolute_schema_path)}
             for e in Draft202012Validator(schema).iter_errors(raw)]
    if not isinstance(raw,dict): raise ContractErrors(errors)
    catalog={p['id']:p['text'] for p in paragraphs({'chapters':[chapter]})}
    claims=raw.get('claims',[]); rows=raw.get('coverage',[])
    if not isinstance(claims,list) or not isinstance(rows,list): raise ContractErrors(errors)
    facts={}; seen=set()
    for i,claim in enumerate(claims):
        if not isinstance(claim,dict): continue
        fid=claim.get('id')
        if not isinstance(fid,str): continue
        if fid in facts: errors.append({'path':f'/claims/{i}/id','code':'duplicate_claim_id','id':fid})
        facts[fid]=claim
        for j,e in enumerate(claim.get('evidence',[]) if isinstance(claim.get('evidence'),list) else []):
            if not isinstance(e,dict): continue
            sid=e.get('source_id'); quote=e.get('quote')
            if not isinstance(sid,str) or not isinstance(quote,str): continue
            if sid not in catalog or not quote or quote not in catalog[sid]:
                errors.append({'path':f'/claims/{i}/evidence/{j}','code':'quote_not_in_bound_source','source_id':sid})
    for i,row in enumerate(rows):
        if not isinstance(row,dict): continue
        sid=row.get('source_id')
        if not isinstance(sid,str): continue
        if sid in seen: errors.append({'path':f'/coverage/{i}','code':'duplicate_paragraph','source_id':sid})
        seen.add(sid)
        ids=row.get('claim_ids',[])
        if not isinstance(ids,list): continue
        for j,fid in enumerate(ids):
            if not isinstance(fid,str): continue
            claim=facts.get(fid)
            actual=[e.get('source_id') for e in claim.get('evidence',[]) if isinstance(e,dict)] if claim and isinstance(claim.get('evidence'),list) else []
            if not claim or sid not in actual:
                errors.append({'path':f'/coverage/{i}/claim_ids/{j}', 'code':'claim_missing' if not claim else 'coverage_without_evidence',
                               'source_id':sid,'claim_id':fid,'claim_evidence_ids':actual})
    if set(catalog)!=seen:
        errors.append({'path':'/coverage','code':'paragraph_coverage','missing':sorted(set(catalog)-seen),'extra':sorted(seen-set(catalog))})
    if errors: raise ContractErrors(errors)
    return raw
