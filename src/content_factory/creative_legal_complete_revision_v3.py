"""Complete revision of an authored spine and its expansion; calibrated source review."""
from copy import deepcopy
import json
from src.content_factory.creative_legal_causal_spine_v2 import build_wire as prior_wire
from src.content_factory.creative_story_emotion import digest

VERSION='legal_complete_revision_active_sources/v3'

def build_wire(*args,revision=None,operator_findings=None,**kwargs):
    w=prior_wire(*args,**kwargs);ctx=json.loads(w['messages'][1]['content']);stage=args[4] if len(args)>4 else kwargs['stage']
    if stage=='draft':
        if revision is None:raise ValueError('complete actual previous draft and accepted full review required')
        ctx['complete_content_revision']=deepcopy(revision)
        ctx['prior_spine_role']='immutable model-authored diagnostic source; repair its missing facts and unsupported information; not a scene template'
        ctx['verified_operator_findings']=deepcopy(operator_findings)
        ctx['current_stage_contract'].update(event_order='rebuild one consistent chain; every event/trigger must be played in actual steps; original spine may be corrected in complete new draft')
        ctx['revision_contract']={'must_resolve_issue_ids':[i['id'] for i in revision['review']['full_text_review']['issues']],
            'proposals':'advisory alternatives; choose a compatible solution, do not accumulate examples',
            'complete_model_authored_rewrite':True,'manual_content_patch':False}
        w['messages'][0]['content']='本次根据已确认双人冲突、完整前稿和全文审查提交完整新稿。原事件链是需要修正的来源，不是逐句模板；自行选择一条清晰因果链。公司实际要求小林离开这一事实必须在场上明确发生，再以“自愿”表述、当天催签和对方继续劝签造成阻力，小林坚持后产生当天可见后果和释放；不需要法律终局。原审查问题要解决，proposal只是备选例子，第三人/额外威胁/材料清单并非必加。不把没章文件当翻转理由，不把角色要求说明变成普遍法律条件。全文动作与对白兑现所有event/trigger，必要物件起态及去向一致，不从不存在的前文引用信息。可减少拍数和无叙事作用的道具。时长浮动，普通话对白，完整R01只借机制不抄剧情。唯一工具名submit_creative_json，提交全文，不返回补丁，不拼接。'
    else:
        ctx['review_calibration']={'confirmed_case_outcome_unresolved':True,
            'consequence_scope':'on-scene interruption of today signing, concrete response and next action; not a winning case or guaranteed future employment',
            'spoken_requests':'a character asking for a written statement is not by itself a universal legal precondition',
            'two_characters_only':True,'review_proposals_must_obey_confirmed_scope':True,
            'literal_source_duties':['company request occurs in played text','referenced earlier words actually occur','necessary object acquisition/holder is traceable','event and trigger agree with steps']}
        w['messages'][0]['content']+=' 审查范围是当前正文，不预设前稿错误仍存在。公司今日催签被人物坚持打断可以是阶段后果，不要求最终胜诉或保证未来岗位；角色要求书面材料不自动等于普遍法律前置条件。审查建议遵守双人关系，不以新增第三人或重大威胁作为唯一修复办法。核对所有回指的前文事实与工牌纸笔等必要物件，按实际发生的动作与对白判断，不把metadata替代正文。'
    w['messages'][1]['content']=json.dumps(ctx,ensure_ascii=False)
    w['input_provenance'].update(source_context_sha256=digest(ctx))
    w['operator_version']=VERSION
    return w
