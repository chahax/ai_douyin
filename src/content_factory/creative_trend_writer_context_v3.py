"""Keep confirmed case-story creation/review separate from later account conversion."""
from copy import deepcopy
import json
from scripts.run_trend_creative_text_trial_v1 import build_wire
from src.content_factory.creative_story_emotion import digest


def build_confirmed_case_wire(packet, facts, stage, *, now, direction, confirmation, script=None):
    if stage not in ('draft','review') or direction['account_fit']['proposed_format'] != '案例拆解':
        raise ValueError('confirmed case story or whole-text review required')
    # Actual confirmation/source/freshness checks happen before any projection.
    wire = build_wire(packet,facts,stage,now=now,direction=direction,confirmation=confirmation,script=script)
    context = json.loads(wire['messages'][1]['content'])
    original = context['account_profile']
    context['account_strategy_evidence'] = deepcopy(original)
    context['account_profile'] = {k:deepcopy(original[k]) for k in (
        'account_uuid','account_key','profile_version','domain_strategy_id','strategy_version',
        'target_audiences','service_scope','negative_keywords')}
    context['account_profile']['allowed_formats'] = ['案例拆解']
    context['stage_assignment'] = {
        'current_stage':'complete original story' if stage=='draft' else 'whole-source text review',
        'creator_goal':'完整事件、因果、人物主动选择、可见刺激反应和情绪收束；不排逐秒表演。',
        'publisher_later':{k:deepcopy(original[k]) for k in ('business_goals','cta_policy','domain_config','workflow_profile')},
        'confirmed_user_decision':deepcopy(confirmation),
        'confirmation_priority':'若用户确认原提案同时明确修正点，完整新稿须落实实际原话；保留原方向为来源，不手改其字段，不把被指出的缺点当强制条件。',
    }
    context['evidence_roles']['account_strategy_evidence']='original frozen account source; conversion handled by subsequent publishing stage'
    wire['messages'][1]['content']=json.dumps(context,ensure_ascii=False)
    wire['input_provenance'].update(source_context_sha256=digest(context),
        account_strategy_evidence_sha256=digest(original),stage_assignment_sha256=digest(context['stage_assignment']))
    wire['operator_version']='confirmed_case_story_stage_projection/v3'
    return wire
