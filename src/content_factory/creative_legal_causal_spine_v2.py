"""Remove rejected source recommendations from active story duties, preserve hashes."""
from copy import deepcopy
import json
from src.content_factory.creative_legal_causal_spine_v1 import build_wire as prior_wire,spine_schema
from src.content_factory.creative_story_emotion import digest

VERSION='legal_causal_spine_active_sources/v2'

def build_wire(*args,**kwargs):
    w=prior_wire(*args,**kwargs);ctx=json.loads(w['messages'][1]['content']);stage=args[4] if len(args)>4 else kwargs['stage']
    lookup={v['tag_id']:v for v in ctx['tag_catalog']}
    old=ctx['tag_choices'];ctx['original_tag_choice_explanations_sha256']=digest(old)
    ctx['tag_choices']=[{'tag_id':i['tag_id'],'label':lookup[i['tag_id']]['label'],
        'source_kind':lookup[i['tag_id']]['kind'],'role':'topic provenance, not required plot or legal conditions'} for i in old]
    fit=ctx['account_fit'];ctx['original_account_fit_sha256']=digest(fit)
    ctx['account_fit']={'proposed_format':fit['proposed_format'],'role':'allowed case narrative; original conversion recommendation retained on disk, not story ending'}
    strategy=ctx.pop('account_strategy_evidence');ctx['original_account_strategy_sha256']=digest(strategy)
    assignment=ctx['stage_assignment'];publisher=assignment.pop('publisher_later');assignment['publisher_later_source_sha256']=digest(publisher)
    assignment.update(current_stage=stage,creator_goal='same confirmed conflict and two-person narrative; actual company request, pressure, choice and consequence')
    if stage=='spine':
        schema=spine_schema(kwargs['direction'])
        first=deepcopy(schema['properties']['events']['items']);first['properties']['caused_by']={'const':''}
        schema['properties']['events']['prefixItems']=[first]
        w['structured_schema']=schema
    w['messages'][0]['content']+=' 唯一输出工具的准确名称是submit_creative_json，请调用此工具，不能加tool-name-等前缀，不能调用文件读取工具。第一事件caused_by必须为空字符串，随后只引用此前真实事件ID。旧tag_choices的story_relevance和账号导流理由是原失败方向的来源解释，已隔离，不是当前创作要求；不从热门标签推出盖章条件、个案结论或额外场景。'
    w['messages'][1]['content']=json.dumps(ctx,ensure_ascii=False)
    w['input_provenance'].update(source_context_sha256=digest(ctx),original_tag_choice_explanations_sha256=digest(old),
        original_account_fit_sha256=digest(fit),original_account_strategy_sha256=digest(strategy))
    w['operator_version']=VERSION
    return w
