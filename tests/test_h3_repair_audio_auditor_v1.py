"""CPU mocks only. The genuine transcriber is pinned but never executed."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from src.content_factory import h3_repair_audio_auditor_v1 as m


class RepairAudioAuditorTests(unittest.TestCase):
    def setUp(self):
        base = m.PROJECT / 'data/test_runs/h3_repair_audio_auditor_v1'
        base.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / 'new_run'
        self.run.mkdir()
        self.addCleanup(patch.stopall)
        for obj, name in [(socket, 'socket'), (socket, 'create_connection'), (subprocess, 'Popen')]:
            patch.object(obj, name, side_effect=AssertionError('no real network/process')).start()
        self.calls = []
        self.source = self.root / 'source.txt'
        quoted = '“你好。”'
        self.source.write_text(quoted, encoding='utf-8')
        sha = hashlib.sha256(quoted.encode()).hexdigest()
        self.source_case = self.write('SOURCE_CASE.json', {'schema': 'h3_continuity_input/v33', 'shots': [{
            'shot_id': 'S03', 'duration': 15, 'source': m.bind(self.source),
            'source_spans': [{'id': 'q0', 'kind': 'audio', 'start': 0, 'end': len(quoted), 'text': quoted, 'sha256': sha}],
            'audio': [{'quote_index': 0, 'quote_sha256': sha, 'speaker': 'child', 'mode': 'onscreen', 'start': .3, 'end': 1.3}]}]})
        self.asset = self.write('ASSETS.json', {'test_only': True})
        self.auth = self.write('AUTH.json', {'max_attempts': 1})
        self.originals = []
        for sid in ['S01', 'S02', 'S03', 'S04']:
            media, result = self.native('old-' + sid, sid)
            self.originals.append({'id': sid, 'native_id': 'old-' + sid, 'result': result, 'media': media,
                                   'source_case': self.source_case, 'asset_manifest': self.asset,
                                   'frames': 362, 'fps': 24, 'audio_rate': 48000, 'audio_samples': 724000})
        self.original = self.originals[2]
        self.old_raw = self.write('old_ASR.json', self.raw('你好', self.root / 'old.wav'))
        self.old_claim = self.write('old_CLAIM.json', {'native_id': 'old-S03', 'video': self.original['media']})
        self.old_report = self.write('old_REPORT.json', {'source': {'video': self.original['media']}, 'raw': self.old_raw})
        old_movie = self.root / 'old_minute.mp4'
        old_movie.write_bytes(b'old minute identity only')
        self.old_final = self.write('OLD_FINAL.json', {'file': m.bind(old_movie), 'segments': [
            {'id': s['id'], 'native_id': s['native_id'], 'file': s['media'], 'result_binding': s['result']}
            for s in self.originals]})
        self.old_qa = self.write('OLD_QA.json', {'file': m.bind(old_movie), 'speech': [{'segment': 'S03', 'ASR': {
            'status': 'CPU_ASR_complete', 'claim': self.old_claim, 'report': self.old_report,
            'raw': self.old_raw, 'artifacts': [self.old_claim, self.old_report, self.old_raw]}}]})
        self.user_issue = self.write('USER_ISSUE.json', {'schema': m.rules.USER_ISSUE_SCHEMA,
            'native_id': 'old-S03', 'media': self.original['media'], 'confirmed': True, 'confirmed_by': 'user',
            'description': '用户确认原片异常。', 'intervals_ms': [[0, 5000]]})
        self.config = {'schema': m.CONFIG, 'baseline_final_result': self.old_final,
            'baseline_final_qa': self.old_qa, 'baseline_user_issue': self.user_issue,
            'transcriber': m.bind(m.PROJECT / 'scripts/transcribe_video_local.py'),
            'python_executable': str(m.PROJECT / '.venv/Scripts/python.exe'), 'max_fresh_asr': 1,
            'asr_timeout_seconds': 1200, 'visual_review_required': False}
        self.context = self.write('CONTEXT.json', {'audio_auditor': self.config})
        self.spec = {'case_binding': self.source_case, 'asset_manifest': self.asset,
                     'adapter_context': self.context, 'authorization': self.auth,
                     'repair_segment_id': 'S03', 'segments': self.originals}

    def write(self, name, value):
        p = self.root / name
        p.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return m.bind(p)

    def native(self, native_id, segment='S03'):
        folder = self.root / native_id
        folder.mkdir(exist_ok=True)
        files = {}
        for role in ['video', 'audio', 'first', 'last']:
            p = folder / role
            p.write_bytes((native_id + ':' + role).encode())
            files[role] = m.bind(p)
        result = folder / 'RESULT.json'
        result.write_text(json.dumps({'prompt_id': native_id, 'technical_status': 'technical_saved', 'files': files}), encoding='utf-8')
        return files['video'], m.bind(result)

    def raw(self, text, wav):
        chars = list(m.rules.normalize_text(text))
        return {'schema': 'local_video_transcript/v1', 'audio': str(wav), 'models': {'punctuation': None},
                'result': [{'text': ' '.join(chars), 'timestamp': [[350 + i * 400, 750 + i * 400] for i in range(len(chars))]}]}

    def request(self, phase='candidate', native_id='fresh-uuid', attempt='A001'):
        if phase == 'baseline':
            candidate = dict(self.original, segment_id='S03', attempt_id='BASELINE')
            attempt = 'BASELINE'
        else:
            media, result = self.native(native_id)
            candidate = {'schema': 'media_repair_candidate/v1', 'attempt_id': attempt, 'segment_id': 'S03',
                         'native_id': native_id, 'result': result, 'media': media,
                         'source_case': self.source_case, 'asset_manifest': self.asset,
                         'completion_known': True, 'outcome_unknown': False}
        spec_binding = self.write('SPEC.json', self.spec)
        return {'schema': 'media_repair_request/v1', 'run': str(self.run), 'spec': spec_binding,
                'attempt_id': attempt, 'attempt_dir': str(self.run / 'attempts' / attempt), 'segment_id': 'S03',
                'phase': phase, 'mode': 'regen_segment', 'original': self.original, 'candidate': candidate,
                'case_binding': self.source_case, 'asset_manifest': self.asset, 'evidence': [self.user_issue],
                'authorization': self.auth}

    def factory(self, visual=False):
        self.config['visual_review_required'] = visual
        self.spec['adapter_context'] = self.write('CONTEXT.json', {'audio_auditor': self.config})
        return m.build_auditor(self.spec)

    def fake_process(self, command, label, run, relative, timeout):
        self.calls.append((label, command))
        if label == 'WAV_EXTRACT':
            with wave.open(command[-1], 'wb') as f:
                f.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                f.writeframes(b'\x01\0' * 240000)
        elif label == 'ASR':
            Path(command[3]).write_text(json.dumps(self.raw('你好', Path(command[2]))), encoding='utf-8')
        return m.freeze(run, relative / (label + '_PROCESS.json'), {'command': command, 'exit_code': 0})

    def test_factory_and_baseline_never_launch_process(self):
        auditor = self.factory()
        before = Path(self.old_raw['path']).read_bytes()
        with patch.object(m, '_run_process', side_effect=AssertionError('baseline must not transcribe')):
            audit = m.read(m.checked(auditor.detect(self.request('baseline'))))
        self.assertEqual(audit['decision'], 'reject')
        self.assertEqual(audit['native_id'], 'old-S03')
        self.assertEqual(before, Path(self.old_raw['path']).read_bytes())
        self.assertFalse((self.run / 'audio_auditor/FRESH_ASR_CLAIM.json').exists())

    def test_fresh_once_full_receipt_and_exact_empty_hotword(self):
        auditor = self.factory()
        request = self.request()
        with patch.object(m, '_run_process', side_effect=self.fake_process):
            binding = auditor.detect(request)
            again = auditor.detect(request)
        self.assertEqual(binding, again)
        self.assertEqual([label for label, _ in self.calls], ['WAV_EXTRACT', 'ASR'])
        command = self.calls[1][1]
        self.assertEqual(command[-3:], ['--without-punctuation', '--hotword', ''])
        audit = m.read(binding['path'])
        self.assertEqual(audit['decision'], 'accept')
        detector = m.read(audit['detector_receipt']['path'])
        self.assertEqual(detector['media'], request['candidate']['media'])
        receipts = list((self.run / 'audio_auditor/asr').glob('*/ASR_RECEIPT.json'))
        self.assertEqual(len(receipts), 1)
        receipt = m.read(receipts[0])
        for item in [receipt['audio_wave'], receipt['raw_asr'], receipt['transcriber'], receipt['asr_claim']]:
            m.checked(item)
        self.assertTrue(receipt['CPU_only'])

    def test_global_max_fresh_one_blocks_second_native(self):
        auditor = self.factory()
        with patch.object(m, '_run_process', side_effect=self.fake_process):
            auditor.detect(self.request())
            second = m.read(m.checked(auditor.detect(self.request(native_id='second-new', attempt='A002'))))
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(second['decision'], 'needs_review')
        self.assertIn('fresh_ASR_budget_exhausted', json.dumps(second))

    def test_claim_without_result_unknown_never_retranscribes(self):
        auditor = self.factory()
        request = self.request()
        with patch.object(m, '_run_process', side_effect=RuntimeError('synthetic interrupted')) as process:
            first = auditor.detect(request)
            second = auditor.detect(request)
        self.assertEqual(process.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(m.read(first['path'])['decision'], 'needs_review')
        detector = m.read(m.read(first['path'])['detector_receipt']['path'])
        self.assertTrue(detector['outcome_unknown'])

    def test_visual_gate_preserves_audio_accept_and_emits_needs_review(self):
        auditor = self.factory(visual=True)
        with patch.object(m, '_run_process', side_effect=self.fake_process):
            audit = m.read(m.checked(auditor.detect(self.request())))
        detector = m.read(audit['detector_receipt']['path'])
        assessment = m.read(detector['audio_assessment']['path'])
        self.assertEqual(assessment['decision'], 'accept')
        self.assertEqual(detector['decision'], 'needs_review')
        self.assertTrue(detector['visual_review_pending'])
        self.assertFalse(detector['actual_visual_review_performed'])

    def test_old_receipt_or_media_mismatch_never_calls_ASR(self):
        auditor = self.factory()
        request = self.request()
        request['candidate']['media'] = self.original['media']
        with patch.object(m, '_run_process', side_effect=AssertionError('must not transcribe')):
            audit = m.read(m.checked(auditor.detect(request)))
        self.assertEqual(audit['decision'], 'needs_review')
        self.assertFalse((self.run / 'audio_auditor/FRESH_ASR_CLAIM.json').exists())

    def test_missing_fourth_original_is_not_transcribed(self):
        auditor = self.factory()
        request = self.request()
        result = m.read(request['candidate']['result']['path'])
        result['files'].pop('last')
        Path(request['candidate']['result']['path']).write_text(json.dumps(result), encoding='utf-8')
        request['candidate']['result'] = m.bind(request['candidate']['result']['path'])
        with patch.object(m, '_run_process', side_effect=AssertionError('must not transcribe')):
            audit = m.read(m.checked(auditor.detect(request)))
        self.assertEqual(audit['decision'], 'needs_review')
        self.assertFalse((self.run / 'audio_auditor/FRESH_ASR_CLAIM.json').exists())

    def test_saved_audit_tamper_refused_no_repeat(self):
        auditor = self.factory()
        request = self.request()
        with patch.object(m, '_run_process', side_effect=self.fake_process):
            binding = auditor.detect(request)
        audit = m.read(binding['path'])
        evidence = next(v for v in audit['evidence'] if v['path'].endswith('AUDIO_ASSESSMENT.json'))
        Path(evidence['path']).write_text('{}', encoding='utf-8')
        with patch.object(m, '_run_process', side_effect=AssertionError('no repeat')):
            with self.assertRaisesRegex(ValueError, 'bound_file_changed'):
                auditor.detect(request)

    def test_actual_process_wrapper_records_failure_without_retry(self):
        with patch.object(m.subprocess, 'run', return_value=SimpleNamespace(returncode=2, stdout='out', stderr='synthetic error')):
            with self.assertRaisesRegex(ValueError, 'process_failed'):
                m._run_process(['ffmpeg', '-n'], 'TEST', self.run, Path('synthetic_process'), 30)
        record = m.read(self.run / 'synthetic_process/TEST_PROCESS.json')
        self.assertEqual(record['exit_code'], 2)
        self.assertEqual(record['stderr'], 'synthetic error')

    def test_no_baseline_user_issue_copied_into_fresh_case(self):
        auditor = self.factory()
        with patch.object(m, '_run_process', side_effect=self.fake_process):
            audit = m.read(m.checked(auditor.detect(self.request())))
        detector = m.read(audit['detector_receipt']['path'])
        assessment = m.read(detector['audio_assessment']['path'])
        self.assertFalse(any(x['code'] == 'same_media_user_confirmed_audio_issue' for x in assessment['issues']))
        self.assertEqual(audit['decision'], 'accept')

    def test_context_changed_and_attempt_mismatch_refused_before_process(self):
        auditor = self.factory()
        request = self.request()
        request['candidate']['attempt_id'] = 'old'
        with self.assertRaisesRegex(ValueError, 'candidate_attempt_mismatch'):
            auditor.detect(request)
        request['candidate']['attempt_id'] = request['attempt_id']
        Path(self.context['path']).write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):
            auditor.detect(request)

    def test_controller_exact_audit_wire_and_detector_subject(self):
        from src.content_factory import media_repair_loop_v1 as controller
        auditor = self.factory()
        request = self.request()
        with patch.object(m, '_run_process', side_effect=self.fake_process):
            result = controller._audit(self.run, 'controller_detection', request, auditor)
        self.assertEqual(result['status'], 'detected')
        self.assertEqual(result['decision'], 'accept')

    def test_changed_source_or_authority_stops_before_ASR_claim(self):
        auditor = self.factory()
        request = self.request()
        Path(self.auth['path']).write_text('{}', encoding='utf-8')
        with patch.object(m, '_run_process', side_effect=AssertionError('no transcription')):
            with self.assertRaisesRegex(ValueError, 'bound_file_changed'):
                auditor.detect(request)
        self.assertFalse((self.run / 'audio_auditor/FRESH_ASR_CLAIM.json').exists())

    def test_transcriber_cannot_change_bound_input_WAV(self):
        auditor = self.factory()
        request = self.request()
        def mutate(command, label, run, relative, timeout):
            result = self.fake_process(command, label, run, relative, timeout)
            if label == 'ASR':
                with Path(command[2]).open('ab') as stream:
                    stream.write(b'changed')
            return result
        with patch.object(m, '_run_process', side_effect=mutate):
            audit = m.read(m.checked(auditor.detect(request)))
        self.assertEqual(audit['decision'], 'needs_review')
        self.assertFalse(list((self.run / 'audio_auditor/asr').glob('*/ASR_RECEIPT.json')))

    def test_cached_audit_revalidates_actual_WAV_not_just_receipt_JSON(self):
        auditor = self.factory()
        request = self.request()
        with patch.object(m, '_run_process', side_effect=self.fake_process):
            auditor.detect(request)
        receipt = m.read(next((self.run / 'audio_auditor/asr').glob('*/ASR_RECEIPT.json')))
        with Path(receipt['audio_wave']['path']).open('ab') as stream:
            stream.write(b'changed after completed audit')
        with patch.object(m, '_run_process', side_effect=AssertionError('no re-ASR')):
            with self.assertRaisesRegex(ValueError, 'bound_file_changed'):
                auditor.detect(request)
        self.assertEqual(len(self.calls), 2)


if __name__ == '__main__':
    unittest.main()
