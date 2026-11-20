"""Carry a source dialogue's own performance annotation to video, without rewriting it."""
import hashlib


def source_direction(shot, audio):
    """Return the exact source prefix for one position-bound quoted utterance.

    Legacy, unpositioned audio has no inferred direction. Narrative action and
    another utterance are never repurposed as voice casting instructions.
    """
    if not all(key in audio for key in ('source_start', 'source_end')):
        return None
    start, end = audio['source_start'], audio['source_end']
    if type(start) is not int or type(end) is not int or end <= start:
        raise ValueError('invalid_source_audio_range')
    units = [u for u in shot.get('source_evidence', [])
             if type(u.get('start')) is int and type(u.get('end')) is int
             and u['start'] <= start < end <= u['end']]
    if not units:
        return None
    if len(units) != 1:
        raise ValueError('ambiguous_source_audio_direction')
    unit = units[0]
    text = unit['text']
    if hashlib.sha256(text.encode('utf-8')).hexdigest() != unit['sha256']:
        raise ValueError('source_audio_direction_evidence_changed')
    a, b = start - unit['start'], end - unit['start']
    if text[a:b] != audio['text']:
        raise ValueError('source_audio_direction_text_mismatch')
    prefix = text[:a]
    # A quoted dialogue label is data. Narrative prose before a spoken fragment
    # is not a performance label and is deliberately omitted.
    if len(prefix) > 200 or not prefix.endswith(('「', '“', '"')):
        return None
    prefix = prefix[:-1].rstrip('：: \t')
    if not (('（' in prefix and prefix.endswith('）')) or
            ('(' in prefix and prefix.endswith(')'))):
        return None
    if any(mark in prefix for mark in ('」', '”', '。', '\n')):
        return None
    return prefix or None
