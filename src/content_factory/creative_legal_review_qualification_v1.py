"""Source-bound whole review with explicit qualification of prior objections."""
from copy import deepcopy
import json
from jsonschema import Draft202012Validator
from src.content_factory.creative_legal_confirmed_revision_v2 import build_wire as prior_wire
from src.content_factory.creative_complete_review_ids_v1 import schema as id_schema,evidence_context
from src.content_factory.creative_review_evidence_ids import expand_review_ids
from src.content_factory.creative_emotion_review_v2 import validate_complete_review_v2
from src.content_factory.creative_story_emotion import digest
VERSION='whole_review_issue_qualification/v1'

def schema(script,brief,prior):
    s=id_schema(script,brief);ids=[i['id'] for i in prior['full_text_review']['issues']]
    ref=deepcopy(s['properties']['full_text_review']['properties']['issues']['items']['properties']['evidence_refs'])
    row={'type':'object','additionalProperties':False,'required':['prior_issue_id','disposition','current_issue_id','reason','evidence_refs'],
        'properties':{'prior_issue_id':{'enum':ids},'disposition':{'enum':['upheld_must_fix','optional_improvement','later_director_stage','unsupported_objection']},
            'current_issue_id':{'type':['string','null']},'reason':{'type':'string','minLength':1},'evidence_refs':ref}}
    s['properties']['prior_issue_assessments']={'type':'array','minItems':len(ids),'maxItems':len(ids),'items':row}
    s['required'].append('prior_issue_assessments');return s

def validate(raw,script,brief,prior):
    Draft202012Validator(schema(script,brief,prior)).validate(raw)
    rows=raw['prior_issue_assessments'];ids=[i['id'] for i in prior['full_text_review']['issues']]
    if len({r['prior_issue_id'] for r in rows})!=len(ids):raise ValueError('prior objections omitted or duplicated')
    current={i['id'] for i in raw['full_text_review']['issues']}
    for r in rows:
        if r['disposition']=='upheld_must_fix':
            if r['current_issue_id'] not in current:raise ValueError('upheld objection omitted from current full review')
        elif r['current_issue_id'] is not None:raise ValueError('nonmandatory objection misbound as current must-fix')
    expanded,receipt=expand_review_ids(raw,evidence_context(script))
    effective={k:deepcopy(expanded[k]) for k in ('full_text_review','emotion_review')}
    result=validate_complete_review_v2(effective,script,brief)
    result.update(raw_model_review_sha256=digest(raw),qualification_version=VERSION,prior_review_sha256=digest(prior),
        raw_review_modified=False,automatic_semantic_approval=False)
    receipt.update(qualification_version=VERSION,prior_review_sha256=digest(prior),effective_review=effective,
        effective_review_sha256=digest(effective),expanded_prior_issue_assessments=expanded['prior_issue_assessments'])
    return effective,receipt,result

def build_wire(*args,prior_review=None,**kwargs):
    if prior_review is None:raise ValueError('actual original full review required')
    w=prior_wire(*args,**kwargs);ctx=json.loads(w['messages'][1]['content']);script=kwargs['script'];brief=ctx['emotional_brief']
    ctx['prior_full_review_for_qualification']=deepcopy(prior_review)
    ctx['review_acceptance_contract']={'current_owner':'complete script narrative and legal fact boundary',
        'must_fix':'an actual current source contradiction, missing core confirmed event, impossible necessary transition, scope violation or explicit universal legal assertion',
        'optional':'could be more readable/beautiful; possible audience inference without actual contradicted statement; extra facial or timing design for later director',
        'future_event':'ending today signing pause may leave later facts unresolved; conditional future request need not be enacted within this scene',
        'verdict':'allowed to report zero issues when full narrative obligations fulfilled; no requirement to invent problems',
        'review_stage':'reread full current text, assess all four emotion criteria; all real issues preserved, earlier objections independently qualified with exact current evidence'}
    w['messages'][0]['content']+=' 本次是同稿全文重新审查与原问题资格校准，不是删问题的格式修复。逐项读取当前完整正文及原审查，填写prior_issue_assessments。确有违背当前必修要求的问题保留在full_text_review.issues；风格加强、可能误读、未来留白和后续导演表情/排时归相应建议，不因还能更好就判必修。原审查自己已认可某要求成立时，不得仅因未加额外保险话术而推翻；若仍有确实失败，给当前原文与具体必修依据。不能为减少问题假通过，也不以先前结论替代重新判断。同场催签暂停不是最终案件胜利，后续公司答复可以未发生。每条原问题均有有据判断；原审查和原稿保持不可变。'
    w['messages'][1]['content']=json.dumps(ctx,ensure_ascii=False);w['structured_schema']=schema(script,brief,prior_review)
    w['input_provenance'].update(source_context_sha256=digest(ctx),prior_full_review_sha256=digest(prior_review),review_acceptance_contract_sha256=digest(ctx['review_acceptance_contract']))
    w['operator_version']=VERSION;return w
