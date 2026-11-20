"""Exact original-source citation transport for complete emotion reviews."""
from copy import deepcopy
import json
from jsonschema import Draft202012Validator
from src.content_factory.creative_review_evidence_ids import build_evidence_catalog, expand_review_ids
from src.content_factory.creative_story_emotion import digest
from src.content_factory.creative_emotion_review_v2 import validate_complete_review_v2
from src.content_factory.creative_confirmed_case_active_scope_v2 import build_wire as native_wire
from scripts.run_creative_emotion_revision_v1 import review_schema

VERSION='complete_review_source_ids/v1'

def evidence_context(script):return {'script':deepcopy(script)}

def catalog(script):
    c=build_evidence_catalog(evidence_context(script))
    c['entries']={k:v for k,v in c['entries'].items() if v['path'].startswith('script.beats.') and '.steps.' in v['path'] and v['path'].endswith('.text')}
    return c

def schema(script,brief):
    out=review_schema(script,brief)
    ref={'type':'object','additionalProperties':False,'required':['ref_id'],
         'properties':{'ref_id':{'type':'string','enum':list(catalog(script)['entries'])}}}
    out['properties']['full_text_review']['properties']['issues']['items']['properties']['evidence_refs']['items']=deepcopy(ref)
    out['properties']['emotion_review']['properties']['criteria']['items']['properties']['evidence_refs']['items']=deepcopy(ref)
    return out

def expand(raw,script,brief):
    Draft202012Validator(schema(script,brief)).validate(raw)
    effective,receipt=expand_review_ids(raw,evidence_context(script))
    validation=validate_complete_review_v2(effective,script,brief)
    receipt.update(transport_version=VERSION,script_sha256=digest(script),brief_sha256=digest(brief))
    validation.update(raw_model_review_sha256=digest(raw),effective_review_sha256=digest(effective),
                      reference_transport=VERSION,conclusions_modified=False)
    return effective,receipt,validation

def build_wire(*args,**kwargs):
    w=native_wire(*args,**kwargs)
    stage=args[4] if len(args)>4 else kwargs['stage']
    if stage!='review':return w
    ctx=json.loads(w['messages'][1]['content']);script=kwargs['script'];brief=ctx['emotional_brief']
    c=catalog(script)
    ctx['source_evidence_directory']={k:{'path':v['path'],'excerpt':v['quote'][:100]} for k,v in c['entries'].items()}
    ctx['evidence_catalog_sha256']=digest(c)
    w['messages'][0]['content']+=' 本次引用外观使用complete_review_source_ids/v1：evidence_refs每项仅为{ref_id:目录ID}，不返回path/quote。选择目录对应的完整原文，excerpt只作导航；完整script是判断依据。程序展开原文后仍进行原完整验收，不能因编号存在就判通过。每条问题必须选对应正文证据，状态矛盾须选前后双方；审查全部出场人物、持有物和事件兑现。'
    w['messages'][1]['content']=json.dumps(ctx,ensure_ascii=False)
    w['structured_schema']=schema(script,brief)
    w['input_provenance'].update(source_evidence_catalog_sha256=digest(c),source_context_sha256=digest(ctx))
    w['operator_version']=VERSION
    return w
