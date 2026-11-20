"""All evidence is synthetic bytes/JSON. No audio/video decode or ASR invocation."""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from src.content_factory import h3_audio_conformance_v1 as module


class AudioConformanceTests(unittest.TestCase):
    def setUp(self):
        folder = module.PROJECT / 'data/test_runs/h3_audio_conformance_v1'
        folder.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.calls = []
        self.addCleanup(patch.stopall)
        for obj, name in [(socket, 'socket'), (socket, 'create_connection'), (subprocess, 'Popen')]:
            patch.object(obj, name, side_effect=self.forbidden).start()

    def forbidden(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError('No network, subprocess, ASR, or model allowed')

    def bind(self, path):
        return {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return self.bind(path)

    def asr_chars(self, text, start, end):
        chars = list(module.normalize_text(text))
        count = len(chars)
        return [(char, start + i * (end - start) // count, start + (i + 1) * (end - start) // count)
                for i, char in enumerate(chars)]

    def fixture(self, quotes=None, recognized=None):
        quotes = quotes or [('你好。', .3, 1.3), ('别去了！', 3, 4)]
        recognized = recognized if recognized is not None else [
            *self.asr_chars('你好', 350, 1200), *self.asr_chars('别去了', 3100, 3900)]
        media = self.root / 'candidate.mp4'
        media.write_bytes(b'synthetic media identity only; never decoded')
        source_raw = '声音：稍稳、清晰的男童声。\n'
        spans = []
        for index, (text, start, end) in enumerate(quotes):
            quoted = '“' + text + '”'
            offset = len(source_raw)
            source_raw += quoted + '\n'
            spans.append({'id': f'q{index}', 'kind': 'audio', 'start': offset, 'end': offset + len(quoted),
                          'text': quoted, 'sha256': hashlib.sha256(quoted.encode()).hexdigest()})
        source_path = self.root / 'source.txt'
        source_path.write_text(source_raw, encoding='utf-8')
        source = {'schema': 'h3_continuity_input/v33', 'shots': [{
            'shot_id': 'S03', 'duration': 15, 'source': self.bind(source_path), 'source_spans': spans,
            'audio': [{'quote_index': index, 'quote_sha256': span['sha256'], 'speaker': 'child' + str(index),
                       'mode': 'onscreen', 'start': quotes[index][1], 'end': quotes[index][2]}
                      for index, span in enumerate(spans)]}]}
        raw = {'schema': 'local_video_transcript/v1', 'result': [{
            'text': ' '.join(row[0] for row in recognized),
            'timestamp': [[row[1], row[2]] for row in recognized]}]}
        self.raw_binding = self.write('ASR.json', raw)
        self.source_binding = self.write('SOURCE_CASE.json', source)
        receipt = {'schema': module.TRANSCRIPT_SCHEMA, 'attempt_id': 'fresh-1', 'native_id': 'uuid-fresh',
                   'media': self.bind(media), 'raw_asr': self.raw_binding,
                   'completion_known': True, 'outcome_unknown': False}
        self.receipt_binding = self.write('ASR_RECEIPT.json', receipt)
        self.case = {'schema': module.CASE_SCHEMA, 'attempt_id': 'fresh-1', 'segment_id': 'S03',
                     'native_id': 'uuid-fresh', 'media': self.bind(media), 'source_case': self.source_binding,
                     'asr_receipt': self.receipt_binding}
        return self.case

    def rewrite_receipt(self, **updates):
        data = json.loads(Path(self.case['asr_receipt']['path']).read_text(encoding='utf-8'))
        data.update(updates)
        self.case['asr_receipt'] = self.write('ASR_RECEIPT.json', data)

    def user_issue(self, **updates):
        issue = {'schema': module.USER_ISSUE_SCHEMA, 'native_id': self.case['native_id'],
                 'media': self.case['media'], 'confirmed': True, 'confirmed_by': 'user',
                 'description': '用户确认这段开头有异常人声。', 'intervals_ms': [[0, 5010]]}
        issue.update(updates)
        self.case['user_confirmed_issue'] = self.write('USER_ISSUE.json', issue)

    def test_clean_complete_accept_and_read_only(self):
        case = self.fixture()
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        result = module.evaluate(case)
        self.assertEqual(result['decision'], 'accept')
        self.assertEqual(result['coverage_summary']['fully_recognized_quotes'], 2)
        self.assertEqual(result['unmapped_recognized_spans'], [])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
        self.assertFalse(self.calls)
        self.assertFalse(result['speaker_identity_verified'])
        self.assertFalse(result['content_quality_passed'])

    def test_chinese_punctuation_width_case_normalization(self):
        self.assertEqual(module.normalize_text('“ＡＢＣ，你 好！。”\n'), 'abc你好')
        self.assertNotEqual(module.normalize_text('我'), module.normalize_text('你'))

    def test_de_di_only_limited_not_rewrite_or_exact(self):
        case = self.fixture([('疼得起不来。', .3, 2.3)], self.asr_chars('疼的起不来', 350, 2200))
        raw_before = Path(self.raw_binding['path']).read_bytes()
        result = module.evaluate(case)
        self.assertEqual(result['decision'], 'accept')
        item = result['expected_coverage'][0]
        self.assertEqual(item['text'], '疼得起不来。')
        self.assertEqual(item['recognized_text'], '疼的起不来')
        self.assertEqual(item['match_kind'], 'limited_de_di_homophone')
        self.assertTrue(item['homophone_substitutions'])
        self.assertEqual(raw_before, Path(self.raw_binding['path']).read_bytes())

    def test_homophone_rule_can_be_disabled(self):
        case = self.fixture([('疼得起不来。', .3, 2.3)], self.asr_chars('疼的起不来', 350, 2200))
        case['policy'] = {'allow_de_di_homophones': False}
        self.assertEqual(module.evaluate(case)['decision'], 'needs_review')

    def test_unrelated_homophone_not_silently_equivalent(self):
        case = self.fixture([('我在这里。', .3, 2.3)], self.asr_chars('我再这里', 350, 2200))
        self.assertEqual(module.evaluate(case)['decision'], 'needs_review')

    def test_ASR_extra_tokens_alone_uncertain_not_confirmed_words(self):
        case = self.fixture(recognized=[*self.asr_chars('啊', 50, 150),
                                       *self.asr_chars('你好别去了', 350, 3900)])
        result = module.evaluate(case)
        self.assertEqual(result['decision'], 'needs_review')
        self.assertEqual(result['route'], 'review')
        self.assertFalse(result['unmapped_recognized_spans'][0]['actual_spoken_words_confirmed'])

    def test_same_media_user_confirmed_issue_rejects_and_routes_regen(self):
        self.fixture()
        self.user_issue()
        result = module.evaluate(self.case)
        self.assertEqual((result['decision'], result['route']), ('reject', 'regen'))
        self.assertTrue(any(x['code'] == 'same_media_user_confirmed_audio_issue' for x in result['issues']))

    def test_user_issue_on_old_identity_cannot_reject_fresh(self):
        self.fixture()
        self.user_issue(native_id='old-uuid')
        result = module.evaluate(self.case)
        self.assertEqual(result['decision'], 'needs_review')
        self.assertFalse(result['input_valid'])

    def test_stale_media_receipt_refused(self):
        self.fixture()
        other = self.root / 'old.mp4'
        other.write_bytes(b'old source')
        self.rewrite_receipt(media=self.bind(other))
        result = module.evaluate(self.case)
        self.assertFalse(result['input_valid'])
        self.assertEqual(result['decision'], 'needs_review')

    def test_stale_native_attempt_or_unknown_receipt_refused(self):
        for updates in [{'native_id': 'old'}, {'attempt_id': 'old'}, {'outcome_unknown': True}, {'completion_known': False}]:
            with self.subTest(updates=updates):
                self.fixture()
                self.rewrite_receipt(**updates)
                self.assertFalse(module.evaluate(self.case)['input_valid'])

    def test_changed_raw_ASR_SHA_refused(self):
        self.fixture()
        Path(self.raw_binding['path']).write_text('{}', encoding='utf-8')
        result = module.evaluate(self.case)
        self.assertFalse(result['input_valid'])
        self.assertEqual(result['decision'], 'needs_review')

    def test_small_delay_accepted_and_intermediate_minor_nonblocking(self):
        for delay, status in [(1000, 'within_tolerance'), (2000, 'minor_nonblocking')]:
            with self.subTest(delay=delay):
                case = self.fixture([('你好。', 0, 1)], self.asr_chars('你好', delay, 1000 + delay))
                result = module.evaluate(case)
                self.assertEqual(result['decision'], 'accept')
                self.assertEqual(result['timing'][0]['status'], status)

    def test_major_timing_deviation_rejects(self):
        case = self.fixture([('你好。', .3, 1.3)], self.asr_chars('你好', 5250, 6250))
        result = module.evaluate(case)
        self.assertEqual((result['decision'], result['route']), ('reject', 'regen'))
        self.assertEqual(result['timing'][0]['onset_error_ms'], 4950)

    def test_configurable_threshold_and_fraction_times(self):
        case = self.fixture([('你好。', '1/3', '4/3')], self.asr_chars('你好', 1400, 2400))
        case['policy'] = {'onset_tolerance_ms': 500, 'end_tolerance_ms': 500,
                          'severe_onset_deviation_ms': 1000, 'severe_end_deviation_ms': 1000}
        result = module.evaluate(case)
        self.assertEqual(result['decision'], 'reject')
        self.assertEqual(Fraction(result['expected_coverage'][0]['expected_start_ms']), Fraction(1000, 3))

    def test_missing_quote_is_located_without_proving_omission(self):
        case = self.fixture(recognized=self.asr_chars('你好', 350, 1200))
        result = module.evaluate(case)
        self.assertEqual(result['decision'], 'needs_review')
        self.assertEqual(result['expected_coverage'][1]['quote_index'], 1)
        self.assertIsNone(result['expected_coverage'][1]['actual_start_ms'])
        self.assertEqual(result['coverage_summary']['fully_recognized_quotes'], 1)

    def test_cross_quote_alignment_does_not_reuse_same_recognition(self):
        case = self.fixture([('你好。', 0, 1), ('你好！', 3, 4)], self.asr_chars('你好', 350, 1200))
        result = module.evaluate(case)
        self.assertEqual(result['decision'], 'needs_review')
        self.assertEqual(result['coverage_summary']['fully_recognized_quotes'], 1)

    def test_repeated_quotes_align_separately_and_in_order(self):
        case = self.fixture([('你好。', 0, 1), ('你好！', 3, 4)],
                            [*self.asr_chars('你好', 100, 900), *self.asr_chars('你好', 3100, 3900)])
        result = module.evaluate(case)
        self.assertEqual(result['decision'], 'accept')
        self.assertEqual([x['actual_start_ms'] for x in result['expected_coverage']], [100, 3100])

    def test_out_of_order_quotes_not_falsely_complete(self):
        case = self.fixture(recognized=[*self.asr_chars('别去了', 350, 1200), *self.asr_chars('你好', 3100, 3900)])
        result = module.evaluate(case)
        self.assertEqual(result['decision'], 'needs_review')
        self.assertLess(result['coverage_summary']['fully_recognized_quotes'], 2)

    def test_profile_like_recognition_does_not_prove_prompt_reading(self):
        case = self.fixture(recognized=[*self.asr_chars('稍稳清晰', 0, 250),
                                       *self.asr_chars('你好', 350, 1200), *self.asr_chars('别去了', 3100, 3900)])
        result = module.evaluate(case)
        self.assertEqual(result['decision'], 'needs_review')
        self.assertFalse(result['speaker_identity_verified'])
        self.assertFalse(result['language_verified'])
        self.assertNotIn('prompt_reading_confirmed', json.dumps(result))

    def test_source_quote_deletion_does_not_make_case_appear_complete(self):
        self.fixture()
        source = json.loads(Path(self.source_binding['path']).read_text(encoding='utf-8'))
        source['shots'][0]['audio'].pop()
        self.case['source_case'] = self.write('SOURCE_CASE.json', source)
        self.assertFalse(module.evaluate(self.case)['input_valid'])

    def test_source_span_or_original_text_tamper_refused(self):
        self.fixture()
        source = json.loads(Path(self.source_binding['path']).read_text(encoding='utf-8'))
        source['shots'][0]['source_spans'][0]['text'] = '“再见。”'
        self.case['source_case'] = self.write('SOURCE_CASE.json', source)
        self.assertFalse(module.evaluate(self.case)['input_valid'])

    def test_malformed_timestamps_invalid_policy_empty_issue_are_not_accept(self):
        self.fixture()
        self.case['policy'] = {'severe_onset_deviation_ms': 1}
        self.assertFalse(module.evaluate(self.case)['input_valid'])
        self.case.pop('policy')
        self.case['user_confirmed_issue'] = {}
        self.assertFalse(module.evaluate(self.case)['input_valid'])
        self.case.pop('user_confirmed_issue')
        raw = {'schema': 'local_video_transcript/v1', 'result': [{'text': '你 好', 'timestamp': [[500, 700], [100, 200]]}]}
        self.rewrite_receipt(raw_asr=self.write('bad_asr.json', raw))
        self.assertFalse(module.evaluate(self.case)['input_valid'])

    def test_bound_case_SHA_and_evidence_pin(self):
        case = self.fixture()
        binding = self.write('CASE.json', case)
        result = module.evaluate_bound(binding)
        self.assertEqual(result['decision'], 'accept')
        self.assertEqual(result['case_binding'], binding)
        Path(binding['path']).write_text('{}', encoding='utf-8')
        self.assertFalse(module.evaluate_bound(binding)['input_valid'])

    def test_known_S03_failure_realistic_synthetic_recognition(self):
        first = '我被踹倒了，疼得半天起不来。有人扔给我一块面包，我就拿回来给爸爸了。'
        words = [*self.asr_chars('嗯住谁这里啊是人你汝释尼基盔甲', 70, 5010),
                 *self.asr_chars(first.replace('得', '的'), 5250, 12230),
                 *self.asr_chars('我找爸去', 12730, 13470), *self.asr_chars('爸爸', 14690, 15060)]
        case = self.fixture([(first, .3, 10.8), ('我找爸去！', 11.3, 12.6)], words)
        self.user_issue()
        result = module.evaluate(case)
        self.assertEqual((result['decision'], result['route']), ('reject', 'regen'))
        self.assertEqual(result['expected_coverage'][0]['match_kind'], 'limited_de_di_homophone')
        self.assertEqual(result['timing'][0]['onset_error_ms'], 4950)
        self.assertEqual(result['coverage_summary']['fully_recognized_quotes'], 2)
        self.assertTrue(result['unmapped_recognized_spans'])
        self.assertTrue(any(x['code'] == 'same_media_user_confirmed_audio_issue' for x in result['issues']))


if __name__ == '__main__':
    unittest.main()
