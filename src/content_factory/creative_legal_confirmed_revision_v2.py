"""Complete fact-led revision; review differentiates initial state and transitions."""
from copy import deepcopy
import json
from src.content_factory.creative_legal_confirmed_facts_v1 import build_wire as prior_wire
from src.content_factory.creative_story_emotion import digest
VERSION='confirmed_legal_fact_revision/v2'

def build_wire(*args,revision=None,**kwargs):
    w=prior_wire(*args,**kwargs);ctx=json.loads(w['messages'][1]['content']);stage=args[4] if len(args)>4 else kwargs['stage']
    if stage=='draft':
        if not revision or not revision['review']['full_text_review']['issues']:raise ValueError('accepted whole-source findings required')
        ctx['complete_content_revision']=deepcopy(revision)
        ctx['revision_contract']={'required_issue_ids':[i['id'] for i in revision['review']['full_text_review']['issues']],
            'proposals':'advisory alternatives; choose a consistent resolution, not cumulative additions',
            'preserve':'confirmed company-requested departure conflict and two characters; no unsupported legal certainty',
            'output':'complete new script, no patch or concatenation','raw_review_modified':False}
        w['messages'][0]['content']+=' 当前完整前稿与有效审查在complete_content_revision中：提交解决问题的完整新稿，保留已经发生的公司要求离开核心。删去签字后仲裁只认辞职或权利必然丧失的断言，人物只核对书面与实际事实。审查proposal是备选，不逐条加戏；不需要扩展材料清单或未来案件结果。'
        w['input_provenance'].update(prior_complete_draft_sha256=digest(revision['previous_complete_script']),
            prior_full_review_sha256=digest(revision['review']),old_failed_templates_consumed=True,
            prior_draft_role='current complete repair source, not mandatory scene template')
    else:
        ctx['review_stage_boundaries']={'initial_state':'明确交代的开场桌上物件是合法起态，不必展示所有物品进入房间的历史；人物推纸等动作仍需能从当前起态成立',
            'new_information':'人物可以主动引入新议题作为劝诱或回应；与回指没发生的前文、凭空持有不同',
            'unresolved_request':'公司暂停今日催签可以是明确阶段后果；后续请求未获承诺须清楚留待确认，不要求未来必兑现'}
        w['messages'][0]['content']+=' 依review_stage_boundaries区分明确起态、真实状态改变、主动引入的新信息与虚构前文。不能仅因纸笔在开场桌上就判来历不明；不能仅因反派首次提出诱因就判因果断裂。要求正文能解释每次重要回应和具体结尾，但不把所有未来请求都必须被接受作为通过条件。法律绝对断言仍须列必修。'
    w['messages'][1]['content']=json.dumps(ctx,ensure_ascii=False);w['input_provenance']['source_context_sha256']=digest(ctx);w['operator_version']=VERSION
    return w
