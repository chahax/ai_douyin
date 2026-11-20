"""CPU/mock editorial tests; no real source media, FFmpeg, model, ASR or HTTP."""
from copy import deepcopy
from fractions import Fraction
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import tempfile
import wave

PROJECT = Path(__file__).resolve().parents[1]
HELPER = PROJECT / 'data/video_generation/h3_s03_audio_cleanup_20261115_v1/repair_and_assemble.py'
spec = importlib.util.spec_from_file_location('cleanup_under_test', HELPER)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class CleanupTests(unittest.TestCase):
    def setUp(self):
        (PROJECT/'data/qa').mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT/'data/qa')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run, self.source = self.root/'repair', self.root/'source'
        self.run.mkdir(); self.source.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(m, 'RUN', self.run).start()
        patch.object(m, 'SOURCE_RUN', self.source).start()
        self.rows=[]
        for i,sid in enumerate(m.IDS):
            folder=self.source/sid;folder.mkdir()
            originals={}
            for role in ('video','audio','first','last'):
                p=folder/role;p.write_bytes(f'{sid}:{role}'.encode())
                originals[role]=dict(local=m.bind(p),native_original=m.bind(p))
            result=folder/'RESULT.json';result.write_text('{}',encoding='utf-8')
            self.rows.append(dict(id=sid,native_id=f'uuid_{sid}',kind='new',
                     result_binding=m.bind(result),originals=originals,file=originals['video']['local']))
        self.movie=self.source/'old.mp4';self.movie.write_bytes(b'completed original')
        self.final=self.source/'FINAL_RESULT.json'
        self.final.write_text(json.dumps(dict(schema='prior/version',file=m.bind(self.movie),segments=self.rows)),encoding='utf-8')
        self.fake_helper=self.source/'helper.py';self.fake_helper.write_text('# frozen',encoding='utf-8')
        self.inputs=dict(source_run=str(self.source),final_result=m.bind(self.final),original_movie=m.bind(self.movie),
                         source_helper=m.bind(self.fake_helper),segments=self.rows,
                         all_sixteen_originals_verified=True,original_media_modified=False,new_native_generation=False)
        original_auth=json.loads((HELPER.parent/'USER_AUTHORIZATION.json').read_text(encoding='utf-8'))
        original_auth.update(source_run=str(self.source),source_movie_sha256=m.bind(self.movie)['sha256'],
                 source_S03_native_id='uuid_S03',source_S03_video_sha256=self.rows[2]['file']['sha256'])
        (self.run/'USER_AUTHORIZATION.json').write_text(json.dumps(original_auth),encoding='utf-8')
        patch.object(m,'source_inputs',side_effect=lambda:deepcopy(self.inputs)).start()
        self.calls=[]

    def approve(self):
        request=m.read(self.run/'LAUNCH_REQUEST.json')
        p=self.run/'APPROVAL.json';p.write_text(json.dumps(dict(schema='h3_s03_audio_cleanup_launch_approval/v1',
                    approved_by='root',request=request)),encoding='utf-8')
        return m.bind(p)

    def fake_tools(self):
        return SimpleNamespace(_clock_tools=lambda:SimpleNamespace(_probe=lambda *a,**kw:{},
                    verify_clock=lambda meta,**kw:dict(frames=kw['frames'],samples=kw['frames']*2000)))

    def wav(self,path,raw):
        with wave.open(str(path),'wb') as w:
            w.setparams((2,2,48000,0,'NONE','not compressed'));w.writeframes(raw)

    def fake_run(self,argv,label):
        self.calls.append(label)
        if label=='NORMALIZE':
            self.wav(argv[-1],b'\x01\x00\x02\x00'*724000)
        elif label=='CLEAN_AUDIO':
            pcm=bytearray(b'\x01\x00\x02\x00'*480000)
            pcm[:1920*4]=b'\0'*(1920*4)
            pcm[455840*4:]=b'\0'*((480000-455840)*4)
            self.wav(argv[-1],pcm)
        else:
            Path(argv[-1]).write_bytes(('derived:'+label).encode())

    def test_exact_fraction_clock_and_safe_fades(self):
        c=m.clock_spec()
        self.assertEqual((c['trim_start_sample'],c['edited_samples'],c['total_frames'],c['total_audio_samples']),
                         (244000,480000,1326,2652000))
        self.assertEqual(c['total_seconds'],'221/4')
        self.assertEqual(c['first_ASR_after_cut_seconds'],'1/6')
        self.assertGreater(Fraction(c['first_ASR_fade_in_clearance_seconds']),0)
        self.assertEqual(c['preserved_tail_source_index'],361)
        self.assertEqual(c['edited_silence_start_sample'],455840)

    def test_command_order_keeps_native_fade_clock_then_rebases(self):
        cmd=m.repair_commands(self.rows[2]['file']['path'],m.paths())
        text=cmd['clean_audio'][cmd['clean_audio'].index('-af')+1]
        self.assertEqual(text,'afade=t=out:st=14.50:d=0.08,atrim=start_sample=244000:end_sample=724000,asetpts=N/SR/TB,afade=t=in:st=0:d=0.04')
        self.assertIn('trim=start_frame=122:end_frame=362',cmd['repair_video'][cmd['repair_video'].index('-filter_complex')+1])
        self.assertTrue(all('-n' in v and '-y' not in v for v in cmd.values()))

    def test_variable_frame_assembly_uses_clean_PCM_not_old_full_movie(self):
        cmd,text=m.assembly_command(['one','two','derived','four'],m.FRAMES,'clean.wav','f.txt','out.mp4')
        self.assertIn('[2:v:0]trim=end_frame=240',text)
        self.assertIn('[4:a:0]aresample=',text)
        self.assertNotIn('[2:a:0]',text)
        self.assertIn('whole_len=480000',text)
        self.assertEqual(cmd.count('-i'),5)
        self.assertNotIn(str(self.movie),cmd)
        with self.assertRaisesRegex(ValueError,'frame_schedule'):
            m.assembly_command(['one']*4,[362]*4,'c','f','o')

    def test_prepare_is_media_free_and_idempotent(self):
        with patch.object(m.subprocess,'run',side_effect=AssertionError('no subprocess')),\
             patch.object(m.spatial,'clock_input',side_effect=AssertionError('no decode')):
            a=m.prepare();b=m.prepare()
        self.assertEqual(a,b)
        self.assertFalse((self.run/'CLAIM.json').exists())
        self.assertFalse(any(Path(p).exists() for p in m.paths().values()))

    def test_scope_and_bindings_refuse_changed_input_or_outside_write(self):
        value=m.bind(self.movie);self.movie.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'bound_input_changed'):m.checked(value)
        with self.assertRaisesRegex(ValueError,'output_outside_new_run'):m.output(self.source/'no.mp4')
        with self.assertRaisesRegex(ValueError,'absolute_local'):m.local('relative.mp4')

    def test_wrong_approval_and_changed_plan_never_execute(self):
        m.prepare();approval=self.approve()
        data=m.read(approval['path']);data['approved_by']='someone_else'
        Path(approval['path']).write_text(json.dumps(data),encoding='utf-8')
        with patch.object(m,'_run',side_effect=AssertionError('must not execute')):
            with self.assertRaisesRegex(ValueError,'Root_exact'):m.execute(m.bind(approval['path']))
        p=self.run/'PLAN.json';data=m.read(p);data['clock']['trim_start_frame']=121;p.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'edit_plan_changed'):m.execute(approval)

    def test_unreceipted_output_preserved(self):
        m.prepare();approval=self.approve();p=Path(m.paths()['clean_audio']);p.write_bytes(b'unknown')
        with self.assertRaisesRegex(ValueError,'unreceipted_output'):m.execute(approval)
        self.assertEqual(p.read_bytes(),b'unknown');self.assertFalse((self.run/'CLAIM.json').exists())

    def test_existing_claim_never_reexecutes(self):
        m.prepare();approval=self.approve();(self.run/'CLAIM.json').write_text('{}',encoding='utf-8')
        with patch.object(m,'_run',side_effect=AssertionError('no repeat')):
            with self.assertRaisesRegex(ValueError,'unknown_do_not_reexecute'):m.execute(approval)

    def test_PCM_keeps_middle_and_silences_only_late_tail(self):
        dest=m.paths();self.fake_run(['',dest['normalized_audio']],'NORMALIZE');self.fake_run(['',dest['clean_audio']],'CLEAN_AUDIO')
        result=m.verify_pcm(dest['normalized_audio'],dest['clean_audio'])
        self.assertEqual(result['unchanged_source_sample_range'],[245920,696000])
        self.assertEqual(result['silent_sample_range'],[455840,480000])
        raw=bytearray(m._pcm(dest['clean_audio'],480000));raw[30000]=0
        self.wav(dest['clean_audio'],raw)
        with self.assertRaisesRegex(ValueError,'normal_audio_samples_changed'):m.verify_pcm(dest['normalized_audio'],dest['clean_audio'])

    def test_nonzero_late_audio_rejected(self):
        dest=m.paths();self.fake_run(['',dest['normalized_audio']],'NORMALIZE');self.fake_run(['',dest['clean_audio']],'CLEAN_AUDIO')
        raw=bytearray(m._pcm(dest['clean_audio'],480000));raw[-1]=1;self.wav(dest['clean_audio'],raw)
        with self.assertRaisesRegex(ValueError,'tail_not_silent'):m.verify_pcm(dest['normalized_audio'],dest['clean_audio'])

    def test_mock_execute_then_reentry_does_not_run_again(self):
        m.prepare();approval=self.approve()
        with patch.object(m,'_run',side_effect=self.fake_run),\
             patch.object(m.spatial,'clock_input',side_effect=lambda *a,**kw:dict(frames=kw['frames'])),\
             patch.object(m,'_source_reader',return_value=self.fake_tools()):
            result=m.execute(approval);self.assertEqual(result['clock'],dict(frames=1326,samples=2652000))
            before=list(self.calls);again=m.execute(approval);self.assertEqual(self.calls,before)
        self.assertEqual(again['status'],'completed_repair_reused_no_execution')
        report=m.read(self.run/'RESULT.json')
        self.assertEqual([r['frames'] for r in report['segments']],[362,362,240,362])
        self.assertEqual([r['kind'] for r in report['segments']],['preserved_original','preserved_original','editorial_derivative','preserved_original'])
        self.assertFalse(report['content_quality_passed']);self.assertEqual(report['ASR_calls'],0)

    def test_execution_failure_preserves_error_and_claim_no_retry(self):
        m.prepare();approval=self.approve()
        with patch.object(m.spatial,'clock_input',return_value={}),\
             patch.object(m,'_run',side_effect=RuntimeError('fake interrupted encode')):
            with self.assertRaisesRegex(RuntimeError,'interrupted'):m.execute(approval)
        self.assertTrue((self.run/'ERROR.json').exists());self.assertTrue((self.run/'CLAIM.json').exists())
        with patch.object(m,'_run',side_effect=AssertionError('no repeat')):
            with self.assertRaisesRegex(ValueError,'unknown_do_not_reexecute'):m.execute(approval)

    def test_live_original_reader_contract_rejects_final_UUID_or_SHA_mismatch(self):
        # Exercise the real source_inputs function using a local, already-verified
        # reader double, while retaining native/final row comparison and SHA checks.
        reader=SimpleNamespace(VERSION='prior/version',__file__=str(self.fake_helper),
                               assembly_inputs=lambda run:dict(segments=deepcopy(self.rows)))
        # Load an independent module to exercise its unpatched source reader.
        isolated=importlib.util.module_from_spec(spec);spec.loader.exec_module(isolated)
        with patch.object(isolated,'SOURCE_RUN',self.source),patch.object(isolated,'_source_reader',return_value=reader):
            good=isolated.source_inputs();self.assertTrue(good['all_sixteen_originals_verified'])
            data=m.read(self.final);data['segments'][2]['native_id']='wrong';self.final.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'native_originals_disagree'):isolated.source_inputs()


if __name__=='__main__':unittest.main()
