"""Separate diagnosed obligations from advisory alternatives; keep complete originals."""
from copy import deepcopy
import json
from src.content_factory.creative_complete_review_ids_v1 import build_wire as prior_wire
from src.content_factory.creative_story_emotion import digest

VERSION='complete_revision_roles/v1'

def build_wire(*args,revision_obligations=None,**kwargs):
    w=prior_wire(*args,**kwargs)
    stage=args[4] if len(args)>4 else kwargs['stage']
    if stage=='draft' and kwargs.get('revision'):
        ctx=json.loads(w['messages'][1]['content']);revision=ctx['complete_content_revision'];review=revision['review']
        ctx['revision_contract']={'schema':VERSION,
            'previous_script_role':'complete source for diagnosis, not an immutable scene template',
            'review_role':'all issues are obligations to resolve; proposals and suggestions are advisory alternatives, not additional required events',
            'must_resolve_issue_ids':[i['id'] for i in review['full_text_review']['issues']],
            'advisory_alternatives_must_not_be_accumulated':True,
            'can_rebuild_beats_and_remove_incidental_props_or_extras':True,
            'preserve':'confirmed conflict, two-person relationship, emotional goal and legal boundaries',
            'required_output':'one internally consistent complete new script; every event and trigger is played in steps',
            'original_complete_review_sha256':digest(review),'manual_content_patch':False}
        if revision_obligations is not None:ctx['verified_operator_findings']=deepcopy(revision_obligations)
        w['messages'][0]['content']+=' 返修按revision_contract分工：解决所有真实问题，审查proposal是备选办法，不是逐条加戏清单。重新选择一条完整因果链，允许重组拍数并删除无叙事作用的道具与旁人，不能局部打补丁。完整前稿与原审查保持来源原文，不要求机械保留其失败场景。所有物件的必要状态与正文一致；事件/触发写发生的事，不能在metadata里另写一版剧情。'
        w['messages'][1]['content']=json.dumps(ctx,ensure_ascii=False)
        w['input_provenance'].update(source_context_sha256=digest(ctx),revision_contract_sha256=digest(ctx['revision_contract']))
        if revision_obligations is not None:w['input_provenance']['verified_operator_findings_sha256']=digest(revision_obligations)
        w['operator_version']=VERSION
    return w
