"""Check planned screen time, not acting quality. Media still needs human observation."""


def validate_emotional_focus(stage, value, previous):
    story = value if stage == 'story' else previous.get('story', {})
    focus = story.get('emotional_focus')
    if not focus:  # Preserve replay of historical, immutable authored stages.
        return
    beats = {b['id']: b for b in story['beats']}
    beat_id, actor = focus['beat_id'], focus['actor']
    if beat_id not in beats or actor not in story['characters']:
        raise ValueError('Unknown emotional focus')
    for key in ('pre_line_seconds', 'post_line_seconds', 'resolution_max_seconds'):
        if type(focus.get(key)) not in (int, float) or not 0 < focus[key] <= 10:
            raise ValueError('Invalid emotional focus timing')
    if beats[beat_id]['duration'] <= story['beats'][-1]['duration']:
        raise ValueError('Emotional focus must receive more time than resolution')
    if story['beats'][-1]['duration'] > focus['resolution_max_seconds']:
        raise ValueError('Resolution exceeds emotional focus budget')
    if stage != 'performance':
        return
    performance = next(b for b in value['beats'] if b['id'] == beat_id)
    lines = performance['lines']
    if not lines or any(line['speaker'] != actor for line in lines):
        raise ValueError('Focus dialogue speaker mismatch')
    start, end = lines[0]['start'], lines[-1]['end']
    if start < focus['pre_line_seconds'] or beats[beat_id]['duration'] - end < focus['post_line_seconds']:
        raise ValueError('Missing before/after dialogue reaction time')
    left, right = start - focus['pre_line_seconds'], end + focus['post_line_seconds']
    shots = previous['visual']['shots']
    cursor = left
    for shot in shots:
        if shot['beat_id'] != beat_id or shot['end'] <= cursor or shot['start'] >= right:
            continue
        if shot['start'] > cursor or shot['subject'] != actor or shot['size'] not in ('medium', 'close'):
            raise ValueError('Focus face loses coverage before reaction completes')
        cursor = min(right, shot['end'])
    if cursor < right:
        raise ValueError('Focus face loses coverage before reaction completes')
