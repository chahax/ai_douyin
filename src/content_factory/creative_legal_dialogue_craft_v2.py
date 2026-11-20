"""Reduced review field burden and calibrated craft criteria; v1 receipts stay immutable."""
from copy import deepcopy
import json
from jsonschema import Draft202012Validator
from scripts.creative_resume_dispatch_v3 import digest
from src.content_factory.creative_legal_dialogue_craft_v1 import build_wire as prior,STANDARDS,CONTRACT,validate_script,craft_schema as prior_schema
from src.content_factory.creative_complete_review_ids_v1 import catalog,expand as base_expand
VERSION='legal_dialogue_craft/v2'
QUALIFICATION='人事请求小林帮交差就是关系压力，不要求新增拒签处罚或承诺；小林说不能替你签成自己辞职可以回应这层压力，不能按重复事实直接判失败。一个连续动作中明确看清个人原因再反应即有刺激，不强制拆成看纸、聚焦、确认三个源动作；正文阶段不要求实际窗口。仍必须检出真正空泛绕口、不接对方压力、没刺激或物理指代错误，禁止用这些资格规则自动判通过。'
DIAGNOSIS=[
 {'kind':'assistant_editorial_finding_not_valid_DeepSeek_review','source_ordinal':341,'path':'script.beats.1.steps.2.text','finding':'人事仍用这一轮、方式、办这批、按这个走。句子较短仍迂回：直接说公司希望把离开办成员工自己辞职，以及现在想让小林签哪份申请。不复用旧句框架只换词；不是全项目禁词表。'},
 {'kind':'assistant_editorial_target','source_ordinal':341,'path':'script.beats.2.steps.1.text','finding':'跑腿的和这一单是口语词，但仍用流程代称。私人求情应直接向小林提出帮她签字交差的请求，不增加处罚、工资或额外关系情节。两轮不同功能拒绝保留。'},
 {'kind':'summary_step_consistency','source_ordinal':341,'path':'script.beats.3.event','finding':'没碰过笔的纸和笔修饰对象错位；steps已限定小林未碰笔。event/premise与完整steps一起由模型写清主语和时段，不能只修一个字段。'},
 {'kind':'keep_improvements','source_ordinal':341,'finding':'保留已经减去的串行动作、去掉半寸、小林未触笔的边界、开场有意不答递纸、只有周姐离开。不强制哭、理解对方或新代价。'},
]
def craft_schema(script,brief):
 out=prior_schema(script,brief)
 out['properties']['dialogue_craft_review']['properties']['schema']={'const':VERSION}
 row=out['properties']['dialogue_craft_review']['properties']['criteria']['items']
 row['required'].remove('issue_ids');row['properties'].pop('issue_ids')
 return out

def build_wire(*args,**kwargs):
 req=prior(*args,**kwargs);ctx=json.loads(req['messages'][1]['content']);ctx['revision_contract']['review_qualification']=QUALIFICATION
 ctx['creative_brief']['constraints']=list(ctx['revision_contract'].values())
 stage=args[4]
 if stage=='draft':
  ctx['complete_revision_source']['current_editorial_diagnosis']=deepcopy(DIAGNOSIS)
  ctx['complete_revision_source'].pop('previous_complete_review',None)
  req['messages'][0]['content']+='本次明确目标由current_editorial_diagnosis给出：旧341公司台词几乎只同义换词，必须整句重组织人物诉求，少用按这个走、方式、这一单等代称，不用换一套流程空话。B4.event和steps主语一致。旧342完整回执因格式未通过，不作为有效审查，也不照它加关系后果或拆读字三步。'
 else:
  req['messages'][0]['content']='DeepSeek独立全文及专业对白审查，不代写。读取完整script、原用户反馈、dialogue_craft_standards和revision_contract。重点检查口语是否仍靠方式、安排、按这个走等空泛代称遮蔽诉求，而非只因词短判自然；每轮是否回应对方压力，event/premise是否与steps一致。'+QUALIFICATION+' 七项专业审查均给criterion、finding、reason、evidence_refs四字段，严格不要issue_ids字段；needs_revision的具体问题也必须列全文issues，引用同一真实正文。satisfied/suggestion不强加必修，uncertain不作为通过。压力选择后果释放、每拍全文覆盖仍完整审查。只调用submit_creative_json，输出full_text_review、emotion_review、dialogue_craft_review三个Schema对象，不添加别的键。全部evidence_refs仅{ref_id:当前目录ID}，依据完整正文不依赖excerpt。不要格式外分析，不改正文，不硬设句数字数动作条数或最低时长。'
  req['structured_schema']=craft_schema(kwargs['script'],ctx['emotional_brief'])
 req['messages'][1]['content']=json.dumps(ctx,ensure_ascii=False)
 req['operator_version']=VERSION
 req['input_provenance'].update(source_context_sha256=digest(ctx),revision_contract_sha256=digest(ctx['revision_contract']),active_emotional_brief_sha256=digest(ctx['emotional_brief']),review_qualification_calibrated=True)
 return req

def expand_review(raw,script,brief):
 Draft202012Validator(craft_schema(script,brief)).validate(raw)
 effective,receipt,validation=base_expand({k:deepcopy(raw[k]) for k in ('full_text_review','emotion_review')},script,brief)
 craft=deepcopy(raw['dialogue_craft_review']);rows=craft['criteria']
 if set(r['criterion'] for r in rows)!=set(STANDARDS):raise ValueError('professional criteria duplicated or omitted')
 entries=catalog(script)['entries'];issues=raw['full_text_review']['issues'];uncertain=False
 issue_refs=[set(r['ref_id'] for r in i['evidence_refs']) for i in issues]
 for row in rows:
  refs=set(r['ref_id'] for r in row['evidence_refs'])
  if row['finding']=='needs_revision' and not any(refs.intersection(i) for i in issue_refs):raise ValueError('professional mandatory finding absent from evidence-bound full-text issues')
  if row['finding']=='uncertain':uncertain=True
  row['evidence_refs']=[{'path':entries[r['ref_id']]['path'],'quote':entries[r['ref_id']]['quote']} for r in row['evidence_refs']]
 effective['dialogue_craft_review']=craft
 receipt.update(dialogue_craft_standards_sha256=digest(STANDARDS),professional_conclusions_modified=False)
 validation.update(professional_review_complete=True,professional_uncertainty=uncertain,needs_revision=validation['needs_revision'] or uncertain,raw_model_review_sha256=digest(raw),effective_review_sha256=digest(effective),professional_criteria_count=len(rows),conclusions_modified=False)
 return effective,receipt,validation
