"""Offline, evidence-bound text/timing checks. This module never transcribes audio.

ASR is recognition evidence, not proof of what a human heard or who spoke. Full
quotes are read from the bound production source, never from voice descriptions.
"""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import unicodedata

PROJECT = Path(__file__).resolve().parents[2]
VERSION = 'h3_audio_conformance/v1'
CASE_SCHEMA = 'h3_audio_conformance_case/v1'
TRANSCRIPT_SCHEMA = 'h3_audio_transcript_receipt/v1'
USER_ISSUE_SCHEMA = 'h3_audio_user_confirmed_issue/v1'
DEFAULT_POLICY = {
    'onset_tolerance_ms': 1500,
    'end_tolerance_ms': 1500,
    'severe_onset_deviation_ms': 3000,
    'severe_end_deviation_ms': 3000,
    'unmapped_gap_ms': 500,
    'allow_de_di_homophones': True,
}
LIMITATIONS = [
    'ASR-only extra tokens do not prove that these exact words were spoken.',
    'An unmatched quote does not by itself prove missing audible speech.',
    'Speaker identity, voice age, voice identity, language, and lip synchronization are not verified.',
    'Only the bound source audio items are checked; this is not a story or visual-quality review.',
    'Limited 得/的/地 matching preserves both original strings and is not exact orthographic or general phonetic proof.',
]


class InputError(ValueError):
    pass


def require(value, code):
    if not value:
        raise InputError(code)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _binding(value):
    require(isinstance(value, dict) and set(value) == {'path', 'sha256'}, 'exact_file_binding_required')
    require(isinstance(value['path'], str) and isinstance(value['sha256'], str)
            and re.fullmatch('[0-9a-f]{64}', value['sha256']), 'invalid_file_binding')
    path = Path(value['path'])
    require(path.is_absolute() and '://' not in value['path'], 'absolute_project_binding_required')
    path = path.resolve()
    require(path.is_relative_to(PROJECT.resolve()), 'binding_outside_project')
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    require(actual == value['sha256'], 'bound_file_sha_changed')
    return path, {'path': str(path), 'sha256': actual}


def _json(value, evidence, kind):
    path, canonical = _binding(value)
    evidence.append({'kind': kind, 'binding': canonical})
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _number(value):
    require(not isinstance(value, bool) and isinstance(value, (int, float, str)), 'numeric_time_required')
    try:
        result = Fraction(str(value))
    except (ValueError, ZeroDivisionError, OverflowError) as error:
        raise InputError('finite_rational_time_required') from error
    return result


def _ms(value):
    return value.numerator if value.denominator == 1 else str(value)


def normalize_text(text):
    """Ignore punctuation/spacing/case; do not paraphrase or rewrite homophones."""
    require(isinstance(text, str), 'text_string_required')
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold()
                   if not unicodedata.category(c).startswith(('P', 'Z', 'C')))


def _source(case, evidence):
    source = _json(case['source_case'], evidence, 'source_case')
    require(isinstance(source, dict) and source.get('schema') == 'h3_continuity_input/v33', 'unsupported_source_case_schema')
    require(isinstance(source.get('shots'), list) and all(isinstance(r, dict) for r in source['shots']),
            'source_shots_required')
    rows = [row for row in source.get('shots', []) if row.get('shot_id') == case['segment_id']]
    require(len(rows) == 1, 'one_matching_source_shot_required')
    row = rows[0]
    path, binding = _binding(row['source'])
    evidence.append({'kind': 'original_source_text', 'binding': binding})
    raw = path.read_text(encoding='utf-8-sig')
    spans = row.get('source_spans')
    require(isinstance(spans, list), 'source_spans_required')
    for span in spans:
        require(isinstance(span, dict) and type(span.get('start')) is int and type(span.get('end')) is int
                and 0 <= span['start'] < span['end'] <= len(raw), 'source_span_location_invalid')
        require(raw[span['start']:span['end']] == span.get('text'), 'source_span_not_in_original')
        require(hashlib.sha256(span['text'].encode()).hexdigest() == span.get('sha256'), 'source_span_sha_changed')
    audio_spans = sorted((s for s in spans if s.get('kind') == 'audio'), key=lambda s: s['start'])
    audio = row.get('audio')
    require(isinstance(audio, list) and audio and all(isinstance(a, dict) for a in audio)
            and len(audio) == len(audio_spans), 'complete_source_audio_items_required')
    require(all(type(a.get('quote_index')) is int for a in audio)
            and [a['quote_index'] for a in audio] == list(range(len(audio))), 'source_quote_order_or_coverage_invalid')
    duration = _number(row['duration']) * 1000
    quotes = []
    for item, span in zip(audio, audio_spans):
        text = span['text']
        require(item.get('quote_sha256') == span['sha256'], 'source_quote_sha_mismatch')
        require(len(text) >= 2 and (text[0], text[-1]) in [('“', '”'), ('"', '"')], 'quoted_audio_span_required')
        start, end = _number(item['start']) * 1000, _number(item['end']) * 1000
        require(0 <= start < end <= duration, 'source_audio_window_invalid')
        require(isinstance(item.get('speaker'), str) and item['speaker'].strip(), 'source_speaker_required')
        normalized = normalize_text(text[1:-1])
        require(normalized, 'empty_expected_quote')
        quotes.append({'quote_index': item['quote_index'], 'text': text[1:-1],
                       'normalized': normalized, 'speaker_from_source': item['speaker'],
                       'source_mode': item.get('mode'), 'start': start, 'end': end,
                       'source_span_id': span.get('id'), 'source_quote_sha256': span['sha256']})
    return quotes


def _asr(case, media, evidence):
    receipt = _json(case['asr_receipt'], evidence, 'ASR_receipt')
    require(isinstance(receipt, dict) and receipt.get('schema') == TRANSCRIPT_SCHEMA, 'unsupported_ASR_receipt_schema')
    require(receipt.get('native_id') == case['native_id'], 'ASR_native_identity_mismatch')
    _, asr_media = _binding(receipt['media'])
    require(asr_media == media, 'ASR_media_binding_mismatch')
    require(receipt.get('completion_known') is True and receipt.get('outcome_unknown') is False,
            'completed_known_ASR_required')
    if 'attempt_id' in receipt:
        require(receipt['attempt_id'] == case['attempt_id'], 'ASR_attempt_identity_mismatch')
    if 'asr_claim' in receipt:
        claim = _json(receipt['asr_claim'], evidence, 'original_ASR_claim')
        require(isinstance(claim, dict) and claim.get('native_id') == case['native_id'], 'ASR_claim_native_identity_mismatch')
        _, claim_media = _binding(claim.get('video', claim.get('media')))
        require(claim_media == media, 'ASR_claim_media_binding_mismatch')
    raw = _json(receipt['raw_asr'], evidence, 'raw_ASR')
    require(isinstance(raw, dict) and raw.get('schema') == 'local_video_transcript/v1', 'unsupported_raw_ASR_schema')
    results = raw.get('result')
    require(isinstance(results, list) and results, 'ASR_results_required')
    chars, previous_start = [], -1
    for result_index, row in enumerate(results):
        require(isinstance(row, dict), 'ASR_result_object_required')
        text, stamps = row.get('text'), row.get('timestamp')
        require(isinstance(text, str) and isinstance(stamps, list), 'ASR_text_timestamps_required')
        tokens = text.split()
        if len(tokens) != len(stamps):
            normalized = normalize_text(text)
            require(len(normalized) == len(stamps), 'ASR_timestamp_alignment_ambiguous')
            tokens = list(normalized)
        for token_index, (token, interval) in enumerate(zip(tokens, stamps)):
            require(isinstance(interval, list) and len(interval) == 2
                    and all(type(t) is int for t in interval), 'integer_ASR_milliseconds_required')
            start, end = interval
            require(0 <= start <= end and start >= previous_start, 'ASR_timestamp_order_invalid')
            previous_start = start
            for char in normalize_text(token):
                chars.append({'char': char, 'start_ms': start, 'end_ms': end,
                              'result_index': result_index, 'token_index': token_index})
    require(chars, 'nonempty_ASR_recognition_required')
    return chars


def _matches(expected, chars, allow_homophones):
    text, size = ''.join(c['char'] for c in chars), len(expected)
    found = []
    group = {'得', '的', '地'}
    for start in range(len(text) - size + 1):
        changes = []
        for offset, (wanted, recognized) in enumerate(zip(expected, text[start:start + size])):
            if wanted == recognized:
                continue
            if allow_homophones and wanted in group and recognized in group:
                changes.append({'character_offset': offset, 'source': wanted, 'recognized': recognized})
            else:
                break
        else:
            found.append({'start_index': start, 'end_index': start + size,
                          'start_ms': chars[start]['start_ms'], 'end_ms': chars[start + size - 1]['end_ms'],
                          'homophone_substitutions': changes})
    return found


def _align(quotes, chars, allow_homophones):
    """Choose an ordered, non-reused full-quote alignment; timing breaks ties."""
    states = {0: ((0, Fraction(0), 0, 0), [])}
    options = []
    for quote in quotes:
        candidates = _matches(quote['normalized'], chars, allow_homophones)
        options.append(candidates)
        following = {}
        for cursor, (cost, path) in states.items():
            choices = [(cursor, (cost[0] + 1, *cost[1:]), path + [None])]
            for match in candidates:
                if match['start_index'] < cursor:
                    continue
                timing = abs(match['start_ms'] - quote['start']) + abs(match['end_ms'] - quote['end'])
                next_cost = (cost[0], cost[1] + timing,
                             cost[2] + len(match['homophone_substitutions']), cost[3] + match['start_index'])
                choices.append((match['end_index'], next_cost, path + [match]))
            for end, next_cost, next_path in choices:
                if end not in following or next_cost < following[end][0]:
                    following[end] = next_cost, next_path
        states = following
    selected = min(states.values(), key=lambda value: value[0])[1]
    return selected, options


def _policy(case):
    custom = case.get('policy', {})
    require(isinstance(custom, dict) and not (set(custom) - set(DEFAULT_POLICY)), 'unsupported_audio_policy_field')
    policy = {**DEFAULT_POLICY, **custom}
    require(type(policy['allow_de_di_homophones']) is bool, 'boolean_homophone_policy_required')
    for key in set(policy) - {'allow_de_di_homophones'}:
        require(type(policy[key]) is int and policy[key] >= 0, 'nonnegative_integer_policy_milliseconds_required')
    require(policy['severe_onset_deviation_ms'] > policy['onset_tolerance_ms']
            and policy['severe_end_deviation_ms'] > policy['end_tolerance_ms'], 'severe_threshold_must_exceed_tolerance')
    return policy


def _user_issue(case, media, evidence):
    if 'user_confirmed_issue' not in case or case['user_confirmed_issue'] is None:
        return None
    issue = _json(case['user_confirmed_issue'], evidence, 'user_confirmed_issue')
    require(isinstance(issue, dict) and issue.get('schema') == USER_ISSUE_SCHEMA and issue.get('confirmed') is True
            and issue.get('confirmed_by') == 'user', 'explicit_user_confirmation_required')
    require(issue.get('native_id') == case['native_id'], 'user_issue_native_identity_mismatch')
    _, issue_media = _binding(issue['media'])
    require(issue_media == media, 'user_issue_media_binding_mismatch')
    require(isinstance(issue.get('description'), str) and issue['description'].strip(), 'user_issue_description_required')
    for interval in issue.get('intervals_ms', []):
        require(isinstance(interval, list) and len(interval) == 2
                and all(type(x) is int for x in interval) and 0 <= interval[0] < interval[1],
                'user_issue_interval_invalid')
    return issue


def _assess(case, report):
    require(isinstance(case, dict) and case.get('schema') == CASE_SCHEMA, 'audio_conformance_case_schema_required')
    for key in ('attempt_id', 'segment_id', 'native_id'):
        require(isinstance(case.get(key), str) and case[key].strip(), 'case_identity_required')
        report[key] = case[key]
    _, media = _binding(case['media'])
    report['media'] = media
    report['evidence'].append({'kind': 'candidate_media', 'binding': media})
    policy = _policy(case)
    report['policy'] = policy
    quotes = _source(case, report['evidence'])
    chars = _asr(case, media, report['evidence'])
    issue = _user_issue(case, media, report['evidence'])
    selected, options = _align(quotes, chars, policy['allow_de_di_homophones'])
    used, major, uncertain = set(), False, False
    for quote, match, candidates in zip(quotes, selected, options):
        item = {key: value for key, value in quote.items() if key not in ('normalized', 'start', 'end')}
        item.update(expected_start_ms=_ms(quote['start']), expected_end_ms=_ms(quote['end']),
                    recognized_match=match is not None, speaker_identity_verified=False)
        if match is None:
            uncertain = True
            item.update(match_kind='not_recognized', actual_start_ms=None, actual_end_ms=None)
            report['issues'].append({'code': 'expected_quote_not_recognized', 'severity': 'uncertain',
                                     'quote_index': quote['quote_index'], 'candidate_full_match_count': len(candidates),
                                     'fact': 'No ordered full ASR match; this does not prove audible omission.'})
        else:
            used.update(range(match['start_index'], match['end_index']))
            substitutions = match['homophone_substitutions']
            item.update(match_kind='limited_de_di_homophone' if substitutions else 'normalized_exact',
                        actual_start_ms=match['start_ms'], actual_end_ms=match['end_ms'],
                        recognized_text=''.join(c['char'] for c in chars[match['start_index']:match['end_index']]),
                        homophone_substitutions=substitutions)
            onset, end = Fraction(match['start_ms']) - quote['start'], Fraction(match['end_ms']) - quote['end']
            severe = abs(onset) >= policy['severe_onset_deviation_ms'] or abs(end) >= policy['severe_end_deviation_ms']
            minor = abs(onset) > policy['onset_tolerance_ms'] or abs(end) > policy['end_tolerance_ms']
            timing = {'quote_index': quote['quote_index'], 'onset_error_ms': _ms(onset), 'end_error_ms': _ms(end),
                      'status': 'major_deviation' if severe else 'minor_nonblocking' if minor else 'within_tolerance'}
            report['timing'].append(timing)
            if severe or minor:
                report['issues'].append({'code': 'expected_quote_timing_deviation',
                                         'severity': 'major' if severe else 'minor', **timing})
            major |= severe
        report['expected_coverage'].append(item)
    group = []
    for index, char in enumerate(chars):
        if index in used:
            if group:
                report['unmapped_recognized_spans'].append(group)
                group = []
        else:
            if group and char['start_ms'] - group[-1]['end_ms'] > policy['unmapped_gap_ms']:
                report['unmapped_recognized_spans'].append(group)
                group = []
            group.append(char)
    if group:
        report['unmapped_recognized_spans'].append(group)
    report['unmapped_recognized_spans'] = [
        {'recognized_text': ''.join(x['char'] for x in group), 'start_ms': group[0]['start_ms'],
         'end_ms': max(x['end_ms'] for x in group), 'evidence_kind': 'ASR_recognition_only',
         'actual_spoken_words_confirmed': False}
        for group in report['unmapped_recognized_spans']]
    if report['unmapped_recognized_spans']:
        uncertain = True
        report['issues'].append({'code': 'unmapped_ASR_recognition', 'severity': 'uncertain',
                                 'fact': 'Unmapped recognition requires review; no exact words or language are asserted.'})
    if issue is not None:
        major = True
        report['issues'].append({'code': 'same_media_user_confirmed_audio_issue', 'severity': 'major',
                                 'description': issue['description'], 'intervals_ms': issue.get('intervals_ms', [])})
    report['decision'] = 'reject' if major else 'needs_review' if uncertain else 'accept'
    report['route'] = {'reject': 'regen', 'needs_review': 'review', 'accept': 'accept'}[report['decision']]
    report['input_valid'] = True
    report['coverage_summary'] = {'expected_quotes': len(quotes), 'fully_recognized_quotes': sum(m is not None for m in selected),
                                  'unmapped_ASR_character_count': len(chars) - len(used)}


def evaluate(case):
    """Evaluate JSON data, using only bound files. No files are changed or created."""
    report = {'schema': VERSION, 'decision': 'needs_review', 'route': 'review', 'input_valid': False,
              'evidence': [], 'expected_coverage': [], 'timing': [], 'unmapped_recognized_spans': [], 'issues': [],
              'limitations': list(LIMITATIONS), 'human_listening_performed': False,
              'speaker_identity_verified': False, 'voice_identity_verified': False, 'language_verified': False,
              'new_ASR_calls': 0, 'new_model_calls': 0, 'HTTP_calls': 0, 'content_quality_passed': False}
    try:
        report['case_digest'] = digest(case)
        _assess(case, report)
    except (InputError, OSError, KeyError, TypeError, ValueError, OverflowError) as error:
        report['decision'], report['route'], report['input_valid'] = 'needs_review', 'review', False
        report['issues'].append({'code': 'invalid_or_stale_audio_evidence', 'severity': 'uncertain', 'reason': str(error)})
    return report


def evaluate_bound(case_binding):
    """Evaluate a pinned case JSON; the returned evidence includes that exact file."""
    evidence = []
    try:
        case = _json(case_binding, evidence, 'conformance_case')
    except (InputError, OSError, KeyError, TypeError, ValueError) as error:
        result = evaluate(None)
        result['issues'] = [{'code': 'invalid_or_stale_case_binding', 'severity': 'uncertain', 'reason': str(error)}]
        return result
    result = evaluate(case)
    result['case_binding'] = evidence[0]['binding']
    result['evidence'] = evidence + result['evidence']
    return result
