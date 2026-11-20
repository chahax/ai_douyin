"""First narrative frame, independent of the clip's later identity coverage.

This is a source projection, not a visual detector or a video trimmer. Existing
plans keep their legacy requirements unless they explicitly select POLICY.
"""
from copy import deepcopy
import hashlib
import json

POLICY = 'first_camera_beat/v1'
SCHEMA = 'story_opening_frame/v1'
FRAMING_EN = {
    'face_close': 'a head-and-shoulders close-up',
    'hands_close': 'a close-up of the hands and the source-established held object',
    'medium': 'a medium shot',
    'wide': 'a wide shot',
    'detail': 'the specified detail shot',
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def contract(entry):
    policy = entry.get('first_frame_policy')
    if policy is None:
        return None
    if policy != POLICY:
        raise ValueError('unsupported_first_frame_policy')
    beat = entry['camera_beats'][0]
    if beat['start'] != 0 or beat['cut'] is not False or beat['framing'] not in FRAMING_EN:
        raise ValueError('first_camera_beat_required')
    actors = sorted(beat['actors'])
    all_actors = sorted({who for item in entry['camera_beats'] for who in item['actors']})
    spans = {item['id']: item for item in entry['source_spans']}
    return dict(
        schema=SCHEMA, policy=POLICY, shot_id=entry['shot_id'], source=entry['source'],
        source_scope=entry['source_scope'], opening_camera_beat=deepcopy(beat),
        opening_visible_actors=actors, clip_visible_actors=all_actors,
        later_identity_context_only=[who for who in all_actors if who not in actors],
        canonical_characters=deepcopy(entry['canonical_characters']),
        canonical_room=deepcopy(entry['canonical_room']),
        source_start_state=[deepcopy(spans[s]) for s in entry.get('source_state_span_ids', [])],
        actions_to_begin_after_first_instant=[deepcopy(spans[s]) for s in beat['source_span_ids']],
        required_faces=sorted(who for who, item in beat['actors'].items()
                              if set(item['visible_parts']) & {'face', 'mouth'}),
        room_required=beat['framing'] in ('medium', 'wide'),
        camera_rule='Frame the first scripted shot at time zero; later cuts and camera motion remain in the video.',
        identity_limit='Off-frame canonical images remain identity assets; they are not independent H3 I2V inputs.',
    )


def requirements(entry, validated):
    """Return a first-image projection without deleting any whole-clip data."""
    opening = contract(entry)
    if opening is None:
        return validated
    return dict(validated, required_faces=opening['required_faces'],
                visible_actors=opening['opening_visible_actors'],
                room_required=opening['room_required'], opening_frame=opening)


def review_reasons(opening, review):
    """Consume an actual image observer's result; never invent visual approval."""
    observation = review.get('opening_frame', {})
    checks = observation.get('checks', {})
    reasons = []
    if observation.get('contract_sha256') != digest(opening):
        reasons.append('opening_frame_observation_missing_or_stale')
    if observation.get('visible_actor_ids') != opening['opening_visible_actors']:
        reasons.append('opening_visible_cast_mismatch_or_unknown')
    if observation.get('framing') != opening['opening_camera_beat']['framing']:
        reasons.append('opening_framing_mismatch_or_unknown')
    for key in ('source_start_state_matches', 'source_attention_matches'):
        if checks.get(key) is not True:
            reasons.append('opening_' + key + '_bad_or_unknown')
    # A close-up need not prove the entire room, but an observed contradiction
    # in the part that is visible must not be ignored.
    if review.get('checks', {}).get('room_identity') is False:
        reasons.append('opening_visible_room_conflict')
    return reasons


def render_state(shot, state):
    """Depiction-only selection: the authoritative world state stays intact."""
    opening = shot.get('opening_frame')
    if opening is None:
        return state
    chosen = opening['in_frame_actor_ids']
    if (opening.get('policy') != POLICY or not isinstance(chosen, list)
            or len(chosen) != len(set(chosen)) or not set(chosen) <= set(state['actors'])):
        raise ValueError('valid_opening_depiction_cast_required')
    result = deepcopy(state)
    for who, actor in result['actors'].items():
        actor['visible'] = actor['visible'] and who in chosen
    holder = result['props']['bread_bag']['holder']
    beat = opening.get('camera_beat', {})
    result['_opening_bread_visible'] = (holder in chosen and 'hands' in
        beat.get('actors', {}).get(holder, {}).get('visible_parts', []))
    return result


def validate_selection(value):
    """Authenticate the producer descriptor against its own first source beat."""
    beat = value.get('camera_beat', {})
    ids = value.get('in_frame_actor_ids')
    if (value.get('policy') != POLICY or beat.get('start') != 0 or beat.get('cut') is not False
            or value.get('framing') != beat.get('framing') or beat.get('framing') not in FRAMING_EN
            or value.get('camera_beat_sha256') != digest(beat)
            or not isinstance(ids, list) or len(ids) != len(set(ids))
            or sorted(ids) != sorted(beat.get('actors', {}))):
        raise ValueError('opening_selection_not_bound_to_first_beat')
    return value


def still_instruction(opening):
    """Positive composition instruction; the stage carries the actual pose."""
    validate_selection(opening)
    return ('This is the first cinematic instant of the scripted shot, framed as '
            + FRAMING_EN[opening['framing']] + '. The reference stage defines '
            'the current pose, held objects and attention between the story subjects. '
            'Compose the photographed body parts within that framing; other people '
            'in the scene remain outside this shot. Subsequent actions occur in the video. ')
