"""Story-stage regeneration from the full brief, without old choreography as a template."""
from copy import deepcopy
import json
from .creative_story_emotion import digest, validate_emotional_brief
from .creative_story_emotion_input_v2 import validate_original_brief


def build_fresh_story_input(previous_script, emotional_brief, reference_pack, feedback,
                            *, creative_brief, characters):
    validate_original_brief(creative_brief)
    validate_emotional_brief(emotional_brief)
    if not previous_script.get('beats') or not previous_script.get('selected_candidate_id'):
        raise ValueError('complete prior source is required for audit binding')
    if not reference_pack or not feedback:
        raise ValueError('complete references and original feedback required')
    if (not isinstance(characters, list) or not characters
            or any(not isinstance(c, dict) or not c.get('name') for c in characters)
            or len({c['name'] for c in characters}) != len(characters)):
        raise ValueError('unambiguous source characters required')
    context = {'creative_brief': deepcopy(creative_brief),
        'emotional_brief': deepcopy(emotional_brief), 'characters': deepcopy(characters),
        'reference_pack': deepcopy(reference_pack), 'feedback': deepcopy(feedback),
        'replacement_scope': {'prior_complete_script_sha256': digest(previous_script),
            'selected_candidate_id': previous_script['selected_candidate_id'],
            'complete_model_authored_replacement_required': True,
            'prior_body_is_audit_evidence_not_a_writing_template': True,
            'old_failure_budget_reset': False}}
    prompt = (
        '作为编剧，从完整原简报、用户确认和表达参考创作完整新稿。原稿完整保存在来源档案，不按原拍数和操作重排。'
        '此阶段只负责观众信息、人物关系、因果、选择及情绪变化；对白和可见反应构成steps。'
        '按用户确认的一级阻力：她先说明已有电影安排，他短暂劝留，她坚持；过去反复替他加班的历史须在拒绝前兑现。'
        '先让他实质接回工作，最后收在她赴自己的约。保持两人和克制写实关系。'
        '不写厘米、左右手操作序列、逐秒排时和摄影参数，这些由下游导演与表演模块完成。'
        '借鉴R01的刺激与反应机制，不照搬剧情；完整原简报的constraints与avoid均有效。'
        '输出完整title、premise、selected_candidate_id、beats，每拍包含id、event、trigger、完整steps。'
        '不提交补丁，不拼接旧正文，不把剧情梗概代替全文。')
    bindings = {k + '_sha256': digest(v) for k, v in context.items()}
    bindings['previous_script_sha256'] = digest(previous_script)
    return {'schema': 'complete_emotion_revision_input/v3', 'creator': 'MiniMax',
        'reviewer': 'DeepSeek', 'messages': [{'role': 'system', 'content': prompt},
            {'role': 'user', 'content': json.dumps(context, ensure_ascii=False)}],
        'bindings': bindings, 'automatic_retry': False, 'submitted': False,
        'original_brief_preserved': True,
        'old_choreography_in_writer_context': False}
