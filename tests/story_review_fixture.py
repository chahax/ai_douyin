"""Synthetic protocol records for offline tests, never production approvals."""
import copy

from src.trend_intelligence.script_screenplay import STORY_REVIEW_CHECKS, STORY_REVIEW_SCHEMA


def enrich_story_review(report, story):
    result = copy.deepcopy(report)
    result['schema'] = STORY_REVIEW_SCHEMA
    result['checks'] = {key: True for key in STORY_REVIEW_CHECKS}
    shots = story['version']['shots']
    spoken = [s for s in shots if s['dialogue'].strip()]
    for row, shot in zip(result['shot_reviews'], shots):
        row.update(dialogue_quote=shot['dialogue'],
                   dialogue_action_finding='Synthetic dialogue/action protocol coverage only.',
                   conflict_focus_finding='Synthetic scope coverage, not a semantic verdict.',
                   spatial_finding='Synthetic staging coverage, not a real spatial review.')
    result['focus_review'] = {'decision': 'passed', 'core_quote': story['core_message'],
        'question_quote': story['version']['dramatic_question'], 'goal_quote': story['version']['goal'],
        'spoken_shot_ids': [s['shot_id'] for s in spoken], 'finding': 'Synthetic focus record only.'}
    result['spatial_review'] = {'decision': 'passed', 'layout_quote': story['version']['spatial_layout'],
                               'finding': 'Synthetic spatial record only.'}
    result['character_reviews'] = [{'name': c['name'], 'decision': 'passed',
        'voice_quote': c['voice'], 'performance_arc_quote': c['performance_arc'],
        'dialogue_quotes': [{'shot_id': s['shot_id'], 'quote': s['dialogue']} for s in spoken
                           if s['dialogue_speaker'] == c['name']],
        'finding': 'Synthetic character coverage only, not an audio certification.'} for c in story['characters']]
    return result
