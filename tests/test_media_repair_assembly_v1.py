import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from src.content_factory import media_repair_assembly_v1 as a
from src.content_factory import media_repair_loop_v1 as loop


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        base=loop.PROJECT/'data/qa/media_repair_assembly_v1_tests'
        base.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=base)
        self.root=Path(self.tmp.name)
        self.run=self.root/'run';self.run.mkdir()
        self.count=0
        self.case=self.file('case.json',{})
        self.assets=self.file('assets.json',{})
        self.rows=[]
        for i in range(4):
            media=self.file(f'old{i}.mp4',b'media'+bytes([i]))
            result=self.file(f'old{i}.json',{'prompt_id':f'old{i}'})
            self.rows.append(dict(id=f'S0{i+1}',native_id=f'old{i}',result=result,media=media,
                source_case=self.case,asset_manifest=self.assets,frames=362,fps=24,audio_rate=48000,audio_samples=724000))
        media=self.file('fresh.mp4',b'fresh')
        native=self.file('fresh.json',dict(prompt_id='fresh',technical_status='technical_saved',files={'video':media}))
        self.candidate=dict(attempt_id='A001',native_id='fresh',result=native,media=media,source_case=self.case,asset_manifest=self.assets)
        context=self.file('context.json',dict(run=str(self.run),assembly=dict(schema='media_repair_assembly_config/v1',width=736,height=1312)))
        self.spec=dict(segments=self.rows,repair_segment_id='S03',case_binding=self.case,asset_manifest=self.assets,adapter_context=context)
        self.specbind=self.file('spec.json',self.spec)
        self.audit=self.file('audit.json',dict(decision='accept',candidate_media=media,candidate_result=native,native_id='fresh'))
        selected=[dict(r,kind='preserved_original') for r in self.rows]
        selected[2]=dict(self.rows[2],native_id='fresh',result=native,media=media,kind='accepted_repair')
        self.selection=dict(schema='media_repair_selection/v1',effective_decision='accept',selected_only_after_accept=True,
            segments=selected,original_clock=loop._clock(self.rows),accepted_candidate=self.file('candidate.json',self.candidate),accepted_audit=self.audit)
        sel=self.file('selection.json',self.selection)
        self.request=dict(schema='media_repair_assembly_request/v1',run=str(self.run),spec=self.specbind,
                          selection=sel,segments=selected,expected_clock=loop._clock(self.rows))
        self.adapter=a.build_assembler(self.spec)

    def tearDown(self):self.tmp.cleanup()

    def file(self,name,value):
        p=self.root/name
        p.write_bytes(value if isinstance(value,bytes) else json.dumps(value).encode())
        return loop.bind(p)

    def update_selection(self):
        self.count+=1
        self.request['selection']=self.file(f'selection{self.count}.json',self.selection)

    def test_command_uses_four_full_frame_inputs(self):
        c,f=a._command(self.request['segments'],self.run/'out.mp4',self.run/'filter.txt',736,1312,24,48000)
        self.assertEqual(c.count('-i'),4)
        self.assertEqual(f.count('trim=end_frame=362'),4)
        self.assertNotIn('start_frame',f)
        self.assertIn('concat=n=4:v=1:a=1',f)
        self.assertIn('-n',c)

    def test_target_duration_cut_is_rejected(self):
        self.selection['segments'][2]['frames']=240
        self.update_selection()
        with self.assertRaisesRegex(ValueError,'only_selected_fresh_target'):
            self.adapter.assemble(self.request)

    def test_non_target_swap_is_rejected(self):
        self.selection['segments'][0]['native_id']='other'
        self.update_selection()
        with self.assertRaisesRegex(ValueError,'untargeted_original'):
            self.adapter.assemble(self.request)

    def test_stale_audit_is_rejected(self):
        self.selection['accepted_audit']=self.file('stale.json',dict(decision='accept',candidate_media=self.rows[2]['media'],
            candidate_result=self.rows[2]['result'],native_id='old2'))
        self.update_selection()
        with self.assertRaisesRegex(ValueError,'audit_subject'):
            self.adapter.assemble(self.request)

    def test_context_run_change_is_rejected(self):
        self.request['run']=str(self.root/'wrong')
        with self.assertRaisesRegex(ValueError,'assembly_run'):
            self.adapter.assemble(self.request)

    def test_claimed_unknown_is_not_reexecuted(self):
        d=self.run/'assembly';d.mkdir();(d/'CLAIM.json').write_text('{}')
        with patch.object(a.subprocess,'run',side_effect=AssertionError('must not execute')):
            with self.assertRaisesRegex(ValueError,'outcome_unknown'):
                self.adapter.assemble(self.request)

    def test_complete_and_reentry_only_executes_once(self):
        calls=[]
        def execute(command,**kwargs):
            calls.append(command);Path(command[-1]).write_bytes(b'final')
            return types.SimpleNamespace(returncode=0,stdout='',stderr='',check_returncode=lambda:None)
        with patch.object(a.spatial,'clock_input',return_value={'synthetic':True}), \
             patch.object(a,'_verify_output',return_value={'synthetic':True}), \
             patch.object(a.subprocess,'run',side_effect=execute):
            first=self.adapter.assemble(self.request)
            second=self.adapter.assemble(self.request)
        self.assertEqual(first,second)
        self.assertEqual(len(calls),1)
        receipt=loop.read(first['receipt']['path'])
        self.assertEqual(receipt['clock']['frames'],1448)
        self.assertEqual(receipt['clock']['audio_samples'],2896000)

    def test_completed_cache_checks_nested_clock_evidence(self):
        def execute(command,**kwargs):
            Path(command[-1]).write_bytes(b'final')
            return types.SimpleNamespace(returncode=0,stdout='',stderr='',check_returncode=lambda:None)
        with patch.object(a.spatial,'clock_input',return_value={'synthetic':True}), \
             patch.object(a,'_verify_output',return_value={'synthetic':True}), \
             patch.object(a.subprocess,'run',side_effect=execute):
            self.adapter.assemble(self.request)
        (self.run/'assembly/DECODED_CLOCK.json').write_text('{}')
        with patch.object(a.subprocess,'run',side_effect=AssertionError('must not execute')):
            with self.assertRaisesRegex(ValueError,'bound_file_changed'):
                self.adapter.assemble(self.request)

    def test_short_decoded_audio_is_not_called_negative_padding_success(self):
        clock=dict(frames=2,fps=24,audio_rate=48000,audio_samples=4000)
        meta={'streams':[dict(codec_type='video',width=736,height=1312,nb_read_frames='2',
                   avg_frame_rate='24/1',start_time='0',time_base='1/12288'),
                 dict(codec_type='audio',duration_ts=4000,time_base='1/48000',sample_rate='48000',channels=2,start_time='0')]}
        with patch.object(a.spatial,'_probe',return_value=meta), \
             patch.object(a.spatial,'_probe_frames',return_value={}), \
             patch.object(a.spatial,'_frame_proof',return_value={}), \
             patch.object(a.spatial,'_decode_audio',return_value=b'\0'*(3999*4)):
            with self.assertRaisesRegex(ValueError,'complete_audio_decode'):
                a._verify_output('unused',clock,736,1312)


if __name__=='__main__':unittest.main()
