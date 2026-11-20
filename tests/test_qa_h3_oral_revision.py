"""Recorded native evidence and negative cases; no media/ASR/server calls."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'scripts'))
import qa_h3_oral_revision as q

RUN = PROJECT / 'data/video_generation/h3_oral_revision_next_minute_20261113_v1'
OLD = q.OLD


class OralRevisionQATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = PROJECT / 'data/qa/h3_oral_revision_independent_20261113/tests'
        cls.parent.mkdir(parents=True, exist_ok=True)
        cls.rev = q.bind(RUN / 'SCRIPT_REVISION.json')
        cls.voice = q.bind(RUN / 'VOICE_PROFILES.json')

    def temp(self):
        return tempfile.TemporaryDirectory(dir=self.parent)

    def write(self, path, value):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return q.bind(path)

    def test_real_oral_sources_have_factual_evidence_and_full_face_windows(self):
        for sid in q.FRESH:
            entry = q.source_entry(q.bind(RUN / 'segments' / sid / 'SOURCE_CASE.json'), sid, self.rev)
            self.assertTrue(all(a['mode'] == 'onscreen' for a in entry['audio']))
            self.assertNotIn('narrator', [a['speaker'] for a in entry['audio']])

    def test_source_line_offset_tamper_is_rejected(self):
        with self.temp() as folder:
            rev = q.read(self.rev['path']); rev['evidence']['126']['source_start'] += 1
            binding = self.write(Path(folder) / 'revision.json', rev)
            with self.assertRaisesRegex(ValueError, 'line_offsets_or_hash'):
                q.revision(binding)

    def altered_source(self, mutate):
        source = RUN / 'segments/S03/SOURCE_CASE.json'; actual_read = q.read
        def reading(path):
            value = actual_read(path)
            if Path(path).resolve() == source:
                value = deepcopy(value); mutate(value['shots'][0])
            return value
        with patch.object(q, 'read', reading):
            return q.source_entry(q.bind(source), 'S03', self.rev)

    def test_noncast_speaker_cannot_receive_the_child_line(self):
        with self.assertRaises(ValueError):
            self.altered_source(lambda e: e['audio'][0].update(speaker='su_mo'))

    def test_voiceover_label_cannot_replace_onscreen_oral_delivery(self):
        with self.assertRaisesRegex(ValueError, 'oral_speaker_text_window'):
            self.altered_source(lambda e: e['audio'][0].update(mode='voiceover'))

    def test_planned_speaker_face_cannot_disappear_mid_line(self):
        def remove(entry):
            for beat in entry['camera_beats']:
                if .8 <= beat['start'] < 11:
                    beat['actors']['ye_xijue']['visible_parts'] = ['torso', 'hands']
        with self.assertRaises(ValueError):
            self.altered_source(remove)

    def test_all_four_voice_descriptions_must_reach_actual_positive_text(self):
        profiles = q.read(self.voice['path'])['profiles']; prompt = '\n'.join(p['description'] for p in profiles.values())
        context = dict(voice_profiles_binding=self.voice, voice_profiles=profiles); plan = dict(voice_profiles=self.voice)
        self.assertFalse(q.voice_profiles(context, prompt, plan, list(profiles))['exact_voice_identity_verified'])
        with self.assertRaisesRegex(ValueError, 'description_must_reach_positive'):
            q.voice_profiles(context, prompt.replace(profiles['ye_yaner']['description'], ''), plan, list(profiles))

    def prefix(self, folder):
        final = q.read(OLD / 'FINAL_RESULT.json'); rows = []
        for old in final['segments'][:2]:
            row = deepcopy(old); row.pop('kind')
            sid = row['shot_id']; row['source_case'] = q.bind(OLD / 'segments' / sid / 'SOURCE_CASE.json')
            row['library_input'] = q.bind(OLD / 'segments' / sid / 'LIBRARY_INPUT.json')
            nr = OLD / 'visual_h3_v3' / (OLD.name + '_' + sid); part = nr / 'shots' / sid
            row['native_plan'] = q.bind(nr / 'PLAN.json')
            row['native_records'] = dict(plan=row['native_plan'], request=q.bind(part / 'REQUEST.json'), history=q.bind(part / 'HISTORY.json'), result=row['native_result'])
            row['library_binding'] = q.read(row['library_input']['path'])['library_binding']
            native = q.read(row['native_result']['path']); row['last_image'] = {k: native['files']['last'][k] for k in ('path', 'sha256')}
            rows.append(row)
        manifest = dict(schema='library_oral_revision_prefix/v1', source_final_result=q.bind(OLD / 'FINAL_RESULT.json'), segments=rows)
        binding = self.write(Path(folder) / 'PREFIX_IMPORTS.json', manifest)
        return dict(imports=binding, library_binding=rows[0]['library_binding']), manifest

    def test_real_original_prefix_is_authenticated_against_native_history(self):
        with self.temp() as folder:
            plan, _ = self.prefix(folder)
            result = q.prefix_imports(folder, plan)
            self.assertEqual([r['native_id'] for r in result['values']],
                             ['6464a38b-624f-410e-b581-193c8e00c88b', '99759f6b-433d-4198-be09-a174f4024cbd'])
            self.assertTrue(all(r['kind'] == 'imported' for r in result['values']))

    def test_wrong_imported_uuid_or_file_is_rejected(self):
        for key, value in [('prompt_id', 'other'), ('file', q.bind(OLD / 'FINAL_RESULT.json'))]:
            with self.subTest(key=key), self.temp() as folder:
                plan, manifest = self.prefix(folder); manifest['segments'][0][key] = value
                plan['imports'] = self.write(Path(folder) / 'PREFIX_IMPORTS.json', manifest)
                with self.assertRaisesRegex(ValueError, 'imported_UUID_original_file'):
                    q.prefix_imports(folder, plan)

    def test_import_manifest_cannot_point_to_different_original_history(self):
        with self.temp() as folder:
            plan, manifest = self.prefix(folder)
            manifest['segments'][0]['native_records']['history'] = manifest['segments'][1]['native_records']['history']
            plan['imports'] = self.write(Path(folder) / 'PREFIX_IMPORTS.json', manifest)
            with self.assertRaisesRegex(ValueError, 'imported_native_records'):
                q.prefix_imports(folder, plan)

    def test_bound_V2_profiles_are_supported_without_a_fixed_filename(self):
        binding = q.bind(RUN / 'VOICE_PROFILES_V2.json'); profiles = q.read(binding['path'])['profiles']
        result = q.voice_profiles(dict(voice_profiles_binding=binding, voice_profiles=profiles),
                                  '\n'.join(p['description'] for p in profiles.values()), dict(voice_profiles=binding), list(profiles))
        self.assertEqual(result['binding'], binding)

    def test_adult_or_voiceprint_claim_is_rejected(self):
        for mutate in (lambda p: p['profiles']['ye_yaner'].update(type='adult_female'),
                       lambda p: p['profiles']['ye_yaner'].update(description='成年女声'),
                       lambda p: p['profiles']['ye_yaner'].update(fallback='adult_voice'),
                       lambda p: p.update(fixed_voice_identity_verified=True)):
            with self.temp() as folder:
                value = q.read(self.voice['path']); mutate(value); binding = self.write(Path(folder) / 'voice.json', value)
                profiles = value['profiles']; text = '\n'.join(p['description'] for p in profiles.values())
                with self.assertRaises(ValueError):
                    q.voice_profiles(dict(voice_profiles_binding=binding, voice_profiles=profiles), text,
                                     dict(voice_profiles=binding), list(profiles))

    def test_immediate_predecessor_switches_from_imported_S02_to_new_S03(self):
        with self.temp() as folder:
            _, imports = self.prefix(folder); value = dict(manifest=imports)
            self.assertEqual(q.expected_predecessor(folder, 'S03', value), imports['segments'][1]['native_result'])
            new = Path(folder) / 'visual_h3_v3' / (Path(folder).name + '_S03') / 'shots/S03/RESULT.json'
            self.write(new, {'prompt_id': 'new-S03'})
            self.assertEqual(q.expected_predecessor(folder, 'S04', value), q.bind(new))
            self.assertNotEqual(q.expected_predecessor(folder, 'S04', value), q.bind(OLD / 'visual_h3_v3' / (OLD.name + '_S03') / 'shots/S03/RESULT.json'))

    def test_actual_physical_nine_ref_route_rejects_a_silent_drop(self):
        nr = OLD / 'visual_h3_v3' / (OLD.name + '_S03'); plan = q.read(nr / 'PLAN.json'); row = plan['shots'][0]
        graph = q.read(nr / 'shots/S03/workflow_api.json'); root = Path(plan['config']['input_root'])
        refs = [dict(slot=i, label=f'P{i+1}', source=r['image'], staged=q.bind(root / r['input_name']), node_id=f'ref_{i}', input_name=r['input_name'])
                for i, r in enumerate(row['reference_map'])]
        self.assertEqual(q.previous.graph_pixel_routes(graph, refs, None)['actual_positive_reference_count'], 9)
        del graph['condition']['inputs']['ref_images.ref_image_8']
        with self.assertRaisesRegex(ValueError, 'every_declared_reference'):
            q.previous.graph_pixel_routes(graph, refs, None)

    def test_installed_official_CPU_nodes_consume_all_actual_references(self):
        context = q.read(OLD / 'segments/S03/LIBRARY_INPUT.json')
        protocol = q.previous.for_run(OLD).cpu_source_protocol(context['references'], guide=context['first_image'])
        self.assertEqual(protocol['model_positive_refs'], 9)
        self.assertEqual(protocol['model_positive_keyframes'], 1)
        self.assertFalse(protocol['GPU_model_inference'])

    def fresh(self):
        return dict(id='S03', kind='new', native_id='fresh', expected_quotes=['测试'], originals={'video': {'local': {'path': 'video', 'sha256': 'sha'}}})

    def test_unknown_ASR_claim_prevents_another_transcription(self):
        with self.temp() as folder:
            q.claim_asr(self.fresh(), folder)
            with self.assertRaisesRegex(ValueError, 'outcome_unknown_no_retranscription'):
                q.claim_asr(self.fresh(), folder)

    def test_prefix_never_dispatches_ASR_even_when_final_ASR_requested(self):
        row = dict(id='S02', kind='imported')
        with self.temp() as folder, patch.object(q.base.media_qa, 'segment_evidence', return_value=({'asr': {}}, [])) as evidence:
            report, _ = q.segment_report(row, folder, asr=True, protocol=Mock(side_effect=AssertionError('no prefix protocol')))
            self.assertIs(evidence.call_args.kwargs['asr'], False)
            self.assertEqual(report['asr']['status'], 'preserved_prefix_explicit_skip')
            self.assertFalse((Path(folder) / 'ASR_ONCE_CLAIM.json').exists())

    def test_new_ASR_call_has_claim_and_second_unknown_call_is_blocked(self):
        row = self.fresh(); row.update(references=[], first_input={})
        with self.temp() as folder, patch.object(q.base.media_qa, 'segment_evidence', return_value=({}, [])) as evidence:
            q.segment_report(row, folder, asr=True, protocol=lambda *a, **k: {'CPU_only': True})
            self.assertIs(evidence.call_args.kwargs['asr'], True)
            with self.assertRaisesRegex(ValueError, 'outcome_unknown'):
                q.segment_report(row, folder, asr=True, protocol=lambda *a, **k: {})
            self.assertEqual(evidence.call_count, 1)

    def test_sealed_old_QA_files_are_not_modified(self):
        self.assertEqual(q.sha(Path(q.previous.previous.__file__)), q.previous.SEALED_PREVIOUS_SHA)
        self.assertEqual(q.sha(Path(q.base.__file__)), q.previous.previous.SEALED_BASE_QA)


if __name__ == '__main__': unittest.main()
