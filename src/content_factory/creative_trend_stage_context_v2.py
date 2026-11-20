"""Project an immutable account strategy into stage-specific creative responsibilities."""
from copy import deepcopy
import json
from src.content_factory.creative_story_emotion import digest


def project_case_direction_wire(wire, *, findings):
    value = deepcopy(wire)
    context = json.loads(value['messages'][1]['content'])
    profile = context['account_profile']
    if '案例拆解' not in profile.get('allowed_formats', []):
        raise ValueError('case-analysis format not permitted by bound account')
    context['account_strategy_evidence'] = deepcopy(profile)
    opportunity = context['opportunity']
    context['opportunity_metadata_evidence'] = deepcopy(opportunity)
    context['opportunity'] = {k: deepcopy(v) for k, v in opportunity.items() if not k.startswith('recommended_')}
    context['account_profile'] = {k: deepcopy(profile[k]) for k in (
        'account_uuid', 'account_key', 'profile_version', 'domain_strategy_id', 'strategy_version',
        'target_audiences', 'service_scope', 'negative_keywords')}
    context['account_profile']['allowed_formats'] = ['案例拆解']
    context['stage_assignment'] = {
        'current_stage': 'complete story direction, case analysis through fictional events and choices',
        'creator_goal': '情绪表达、事件因果、画面叙事；冲突与选择由人物完成，时长浮动。',
        'selected_format': '案例拆解',
        'role_policy': '本测试使用虚构劳动者与人事两人；不生成真实出镜律师、执业机构或咨询入口。',
        'ending_policy': '现场有可见后果和情绪释放；法律结果取决于具体事实，不许诺胜诉或金额。',
        'legal_focus': '催签自愿离职时先核对真实事实、解除性质；单项违法需具体依据，不能从工资条空栏直接推出社保未缴。',
        'publisher_later': {'business_goals': deepcopy(profile['business_goals']),
                            'cta_policy': deepcopy(profile['cta_policy']),
                            'domain_config': deepcopy(profile['domain_config']),
                            'workflow_profile': profile['workflow_profile']},
        'schema_acceptance': 'creative_brief必须完整包含schema,title,theme,audience,relationships,audience_emotion,visual_style,turn,ending,duration_policy,duration_seconds,constraints,avoid；不能省略audience。',
    }
    context['known_previous_findings'] = deepcopy(findings)
    context['evidence_roles']['account_strategy_evidence'] = 'immutable account source; responsibilities explicitly assigned to current creative stage or later publisher'
    value['messages'][1]['content'] = json.dumps(context, ensure_ascii=False)
    value['input_provenance'].update(source_context_sha256=digest(context),
        account_strategy_evidence_sha256=digest(profile), stage_assignment_sha256=digest(context['stage_assignment']))
    return value
