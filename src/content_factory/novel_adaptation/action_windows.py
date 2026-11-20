"""Report action timing evidence; never infer physical feasibility from duration alone."""


def action_windows(scene):
    rows = []
    for beat in scene['beats']:
        for ref in beat.get('action_order', []):
            event = beat[ref['field']][ref['index']]
            phase = event.get('phase', 'start')
            if phase == 'start':
                earliest = beat['start']
            elif phase == 'end':
                earliest = beat['end']
            elif phase == 'after_audio':
                index = event.get('after_audio_index')
                if type(index) is not int or not 0 <= index < len(beat['audio']):
                    raise ValueError('action_audio_anchor_missing')
                earliest = beat['audio'][index]['end']
            else:
                raise ValueError('unknown_action_phase')
            if not beat['start'] <= earliest <= beat['end']:
                raise ValueError('action_anchor_outside_beat')
            rows.append({
                'scene_id': scene['id'], 'beat_id': beat['id'],
                'field': ref['field'], 'index': ref['index'], 'phase': phase,
                'earliest_start': earliest, 'latest_end': beat['end'],
                'maximum_available_seconds': round(beat['end'] - earliest, 6),
                'interpretation': 'shared_upper_bound_not_reserved_duration',
            })
    return rows
