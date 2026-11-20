"""Whole controller CPU tests with injected adapters, no real media/network."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.content_factory import media_repair_loop_v1 as loop

PROJECT = Path(__file__).resolve().parents[1]


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):path.write_bytes(value)
    else:path.write_text(json.dumps(value), encoding='utf-8')
    return loop.bind(path)


class Executor:
    def __init__(self):self.submits=[];self.collects=[];self.pending=False;self.fail_submit=False;self.candidate_change=None
    def submit(self, req):
        self.submits.append(deepcopy(req))
        if self.fail_submit:raise TimeoutError('unknown submission')
        return dict(status='submitted',native_id='new_'+req['attempt_id'])
    def collect(self, req):
        self.collects.append(deepcopy(req))
        if self.pending:return dict(status='pending')
        folder=Path(req['attempt_dir']);aid=req['attempt_id'];pid=req['native_id']
        media=put(folder/'native.mp4',('fresh '+aid).encode());audio=put(folder/'raw.flac',b'raw audio')
        result=put(folder/'RESULT.json',dict(prompt_id=pid,technical_status='technical_saved',
                    files=dict(video=media,audio=audio)))
        nominal=dict(frames=req['original']['frames'],fps=req['original']['fps'])
        native=dict(rate=32000,samples=482400,media=audio)
        delivery=dict(rate=48000,samples=724000)
        evidence=put(folder/'PROBE.json',dict(actual_raw_samples=482400))
        proof=put(folder/'CLOCK.json',dict(schema='media_repair_candidate_clock/v1',native_id=pid,media=media,
                  result=result,nominal_frame_clock=nominal,native_audio_clock=native,delivery_clock=delivery,
                  normalization_verified=True,content_trimmed=False,evidence=[evidence]))
        value=dict(schema='media_repair_candidate/v1',attempt_id=aid,segment_id=req['segment_id'],native_id=pid,
                   media=media,result=result,source_case=req['case_binding'],asset_manifest=req['asset_manifest'],
                   nominal_frame_clock=nominal,native_audio_clock=native,delivery_clock=delivery,
                   audio_clock_receipt=proof,completion_known=True,outcome_unknown=False)
        if self.candidate_change:self.candidate_change(value)
        return dict(status='saved',candidate=value)


class Auditor:
    def __init__(self,decisions=('accept',)):
        self.decisions=decisions;self.calls=[];self.stale=False;self.fail=False;self.stale_receipt=False
    def detect(self,req):
        self.calls.append(deepcopy(req))
        if self.fail:raise TimeoutError('audit interrupted')
        aid=req['attempt_id'];c=req['candidate'];folder=Path(req['run'])/'detector'/aid
        decision='reject' if aid=='BASELINE' else self.decisions[int(aid[1:])-1]
        evidence=put(folder/'EVIDENCE.json',dict(media=c['media'],decision=decision))
        receipt=put(folder/'DETECTION.json',dict(attempt_id=aid,native_id=c['native_id'],
                    media=req['original']['media'] if self.stale_receipt and aid!='BASELINE' else c['media'],decision=decision))
        audit=dict(schema='media_repair_audit/v1',attempt_id=aid,segment_id=req['segment_id'],native_id=c['native_id'],
                   candidate_result=c['result'],candidate_media=c['media'],case_binding=req['case_binding'],
                   asset_manifest=req['asset_manifest'],fresh_detection=True,decision=decision,
                   evidence=[evidence],findings=[],detector_receipt=receipt)
        if self.stale and aid!='BASELINE':audit['candidate_media']=req['original']['media']
        return put(folder/'AUDIT.json',audit)


class Assembler:
    def __init__(self):self.calls=[];self.fail=False;self.bad_clock=False
    def assemble(self,req):
        self.calls.append(deepcopy(req))
        if self.fail:raise TimeoutError('assembly interrupted')
        folder=Path(req['run'])/'delivery';movie=put(folder/'new.mp4',b'assembled candidate')
        clock=deepcopy(req['expected_clock'])
        if self.bad_clock:clock['frames']-=122
        proof=put(folder/'CLOCK_PROOF.json',dict(file=movie,clock=clock))
        receipt=put(folder/'RECEIPT.json',dict(schema='media_repair_assembly/v1',selection=req['selection'],
                   file=movie,clock=clock,decoded_clock=proof,completion_known=True,outcome_unknown=False))
        return dict(status='complete',file=movie,receipt=receipt)


class RepairLoopTests(unittest.TestCase):
    def setUp(self):
        (PROJECT/'data/qa').mkdir(exist_ok=True,parents=True)
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'data/qa');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.run=self.root/'repair';self.source=self.root/'source'
        self.case=put(self.source/'CASE.json',dict(story='source'))
        self.asset=put(self.source/'ASSETS.json',dict(asset='fixed'))
        self.evidence=put(self.source/'DEFECT.json',dict(confirmed_for='original S03'))
        self.auth=put(self.source/'AUTH.json',dict(max_attempts=2))
        rows=[]
        for sid in ('S01','S02','S03','S04'):
            media=put(self.source/(sid+'.mp4'),sid.encode())
            raw=put(self.source/(sid+'.json'),dict(prompt_id='old_'+sid))
            rows.append(dict(id=sid,native_id='old_'+sid,result=raw,media=media,source_case=self.case,
                             asset_manifest=self.asset,frames=362,fps=24,audio_rate=48000,audio_samples=724000))
        adapter=put(self.source/'adapter.py',b'def build_executor(spec): return {"role":"executor","spec":spec}\ndef build_auditor(spec): return {"role":"auditor","spec":spec}\ndef build_assembler(spec): return {"role":"assembler","spec":spec}\n')
        self.spec=dict(schema=loop.SPEC,case_binding=self.case,asset_manifest=self.asset,evidence=[self.evidence],
             authorization=self.auth,segments=rows,repair_segment_id='S03',max_attempts=1,mode='regen_segment',
             require_fresh_candidate=True,regenerate_on=['reject'],
             adapters={role:dict(module=adapter,factory='build_'+role) for role in ('executor','auditor','assembler')})
        self.specfile=self.root/'SPEC.json'
        self.executor=Executor();self.auditor=Auditor();self.assembler=Assembler()
    def prepare(self):
        return loop.prepare(self.run,put(self.specfile,self.spec))
    def drive(self):
        return loop.drive(self.run,executor=self.executor,auditor=self.auditor,assembler=self.assembler)
    def step(self):
        return loop.step(self.run,executor=self.executor,auditor=self.auditor,assembler=self.assembler)

    def test_full_loop_fresh_fail_retry_fresh_accept_select_assemble_reentry(self):
        self.spec['max_attempts']=2;self.auditor=Auditor(('reject','accept'));self.prepare()
        result=self.drive()
        self.assertEqual(result['status'],'complete');self.assertTrue(result['repair_criteria_passed'])
        self.assertFalse(result['content_quality_passed'])
        self.assertEqual(len(self.executor.submits),2)
        self.assertEqual([r['attempt_id'] for r in self.auditor.calls],['BASELINE','A001','A002'])
        self.assertTrue((self.run/'attempts/A001/CANDIDATE.json').exists())
        selected=loop.read(self.run/'SELECTED_VERSION.json')
        self.assertEqual([r['native_id'] for r in selected['segments']],['old_S01','old_S02','new_A002','old_S04'])
        self.assertEqual(result['clock']['frames'],1448)
        count=(len(self.executor.submits),len(self.auditor.calls),len(self.assembler.calls))
        self.drive();self.assertEqual(count,(len(self.executor.submits),len(self.auditor.calls),len(self.assembler.calls)))

    def test_one_attempt_exhaustion_preserves_candidate_no_selection(self):
        self.auditor=Auditor(('reject',));self.prepare();value=self.drive()
        self.assertEqual(value['status'],'attempts_exhausted')
        self.assertEqual(len(self.executor.submits),1)
        self.assertFalse((self.run/'SELECTED_VERSION.json').exists());self.assertFalse(self.assembler.calls)
        self.drive();self.assertEqual(len(self.executor.submits),1)

    def test_unknown_submission_never_blindly_retries(self):
        self.executor.fail_submit=True;self.prepare()
        self.assertEqual(self.drive()['status'],'outcome_unknown')
        self.assertEqual(self.drive()['status'],'outcome_unknown')
        self.assertEqual(len(self.executor.submits),1)
        self.assertTrue((self.run/'attempts/A001/SUBMIT_CLAIM.json').exists())

    def test_known_ID_pending_collection_reuses_exact_native_id(self):
        self.executor.pending=True;self.prepare();self.assertEqual(self.drive()['status'],'pending')
        self.assertEqual(self.drive()['status'],'pending');self.assertEqual(len(self.executor.submits),1)
        self.assertEqual({r['native_id'] for r in self.executor.collects},{'new_A001'})
        self.executor.pending=False;self.assertEqual(self.drive()['status'],'complete')

    def test_stale_candidate_audit_cannot_select(self):
        self.auditor.stale=True;self.prepare()
        with self.assertRaisesRegex(ValueError,'exact_fresh_detection'):self.drive()
        self.assertFalse((self.run/'SELECTED_VERSION.json').exists());self.assertFalse(self.assembler.calls)
        self.assertTrue((self.run/'attempts/A001/detection/AUDIT.json').exists())

    def test_wrapper_cannot_hide_stale_detector_receipt(self):
        self.auditor.stale_receipt=True;self.prepare()
        with self.assertRaisesRegex(ValueError,'actual_detector_receipt'):self.drive()
        self.assertFalse((self.run/'SELECTED_VERSION.json').exists())

    def test_trimmed_candidate_rejected_even_auditor_would_accept(self):
        self.executor.candidate_change=lambda c:c['nominal_frame_clock'].update(frames=240)
        self.prepare()
        with self.assertRaisesRegex(ValueError,'not_cut_or_shorten'):self.drive()
        self.assertEqual(len(self.executor.submits),1)
        self.assertTrue((self.run/'attempts/A001/COLLECTION_RESULT.json').exists())
        self.assertFalse(self.assembler.calls)

    def test_native_raw_audio_distinct_from_delivery_and_proof_required(self):
        self.prepare();self.drive()
        c=loop.read(self.run/'attempts/A001/CANDIDATE.json')
        self.assertEqual(c['native_audio_clock']['rate'],32000)
        self.assertEqual(c['delivery_clock'],dict(rate=48000,samples=724000))
        self.assertEqual(c['nominal_frame_clock'],dict(frames=362,fps=24))

    def test_fake_audio_normalization_target_rejected(self):
        def change(c):c['delivery_clock']['samples']=480000
        self.executor.candidate_change=change;self.prepare()
        with self.assertRaisesRegex(ValueError,'delivery_audio_target'):self.drive()

    def test_uncertain_fresh_result_waits_review_not_rejected_or_accepted(self):
        self.spec['max_attempts']=2;self.auditor=Auditor(('needs_review','accept'));self.prepare()
        v=self.drive();self.assertEqual(v['status'],'needs_review')
        self.drive();self.assertEqual(len(self.executor.submits),1);self.assertFalse(self.assembler.calls)
        c=loop.read(self.run/'attempts/A001/CANDIDATE.json');a=loop.read(self.run/'attempts/A001/detection/AUDIT.json')['audit']
        review=dict(schema='media_repair_review/v1',decision='accept',reviewed_by='root_actual_review',attempt_id='A001',
                    native_id=c['native_id'],candidate_result=c['result'],candidate_media=c['media'],audit=a,
                    case_binding=self.case,asset_manifest=self.asset,evidence=[self.evidence])
        bound=put(self.run/'ACTUAL_REVIEW.json',review);loop.record_review(self.run,'A001',bound)
        self.assertEqual(self.drive()['status'],'complete');self.assertEqual(len(self.executor.submits),1)
        self.assertEqual(loop.read(self.run/'SELECTED_VERSION.json')['accepted_review'],bound)

    def test_baseline_user_confirmation_cannot_be_applied_to_fresh_review(self):
        self.auditor=Auditor(('needs_review',));self.prepare();self.drive()
        review=dict(schema='media_repair_review/v1',decision='accept',reviewed_by='root',attempt_id='A001',
                   native_id='old_S03',candidate_result=self.spec['segments'][2]['result'],
                   candidate_media=self.spec['segments'][2]['media'],audit=self.evidence,
                   case_binding=self.case,asset_manifest=self.asset,evidence=[self.evidence])
        with self.assertRaisesRegex(ValueError,'this_exact_fresh'):loop.record_review(self.run,'A001',put(self.run/'BAD_REVIEW.json',review))

    def test_auditor_unknown_claim_does_not_run_again(self):
        self.auditor.fail=True;self.prepare();self.assertEqual(self.drive()['status'],'outcome_unknown')
        self.drive();self.assertEqual(len(self.auditor.calls),1);self.assertFalse(self.executor.submits)

    def test_assembly_unknown_not_reassembled_or_native_regenerated(self):
        self.assembler.fail=True;self.prepare();self.assertEqual(self.drive()['status'],'outcome_unknown')
        self.assertEqual(self.drive()['status'],'outcome_unknown')
        self.assertEqual((len(self.executor.submits),len(self.assembler.calls)),(1,1))

    def test_short_final_clock_rejected_and_no_receipt(self):
        self.assembler.bad_clock=True;self.prepare()
        with self.assertRaisesRegex(ValueError,'preserved_clock'):self.drive()
        self.assertFalse((self.run/'FINAL_RECEIPT.json').exists())

    def test_plan_budget_tamper_or_authority_excess_cannot_dispatch(self):
        self.prepare();p=self.run/'PLAN.json';value=loop.read(p);value['max_attempts']=2;put(p,value)
        with self.assertRaisesRegex(ValueError,'frozen_spec_and_budget'):self.drive()
        self.assertFalse(self.executor.submits)
        self.spec['max_attempts']=3
        with self.assertRaisesRegex(ValueError,'one_or_two'):loop.validate_spec(self.spec)

    def test_audio_repair_without_verified_capability_refused(self):
        self.spec['mode']='audio_repair'
        with self.assertRaises(KeyError):self.prepare()

    def test_clock_proof_cannot_be_skipped_even_when_raw_claimed_as_delivery(self):
        def change(c):
            c['native_audio_clock']['rate']=48000;c['native_audio_clock']['samples']=724000
            del c['audio_clock_receipt']
        self.executor.candidate_change=change;self.prepare()
        with self.assertRaises(KeyError):self.drive()
        self.assertFalse(self.assembler.calls)

    def test_cross_process_lock_prevents_concurrent_second_dispatch(self):
        self.prepare()
        with loop.run_lock(self.run,'REPAIR_LOOP.lock'):
            with self.assertRaisesRegex(ValueError,'job_already_executing'):self.drive()
        self.assertFalse(self.executor.submits)

    def test_pinned_factory_modules_load_all_three_roles(self):
        self.prepare();values=loop.load_adapters(self.run)
        self.assertEqual(set(values),{'executor','auditor','assembler'})
        self.assertTrue(all(role==value['role'] for role,value in values.items()))

    def test_optional_adapter_context_is_pinned_without_replacing_source_case(self):
        context=put(self.source/'ROOT_CONTEXT.json',dict(native_run='explicit root adapter context'))
        self.spec['adapter_context']=context;self.prepare()
        self.assertEqual(loop._load(self.run)[2]['case_binding'],self.case)
        Path(context['path']).write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'bound_file_changed'):self.drive()
        self.assertFalse(self.executor.submits)

    def test_completed_cache_deep_checks_fresh_result_media_clock_and_audit_without_calls(self):
        self.prepare();self.drive()
        candidate=loop.read(self.run/'attempts/A001/CANDIDATE.json')
        clock=loop.read(candidate['audio_clock_receipt']['path'])
        audit=loop.read(loop.read(self.run/'attempts/A001/detection/AUDIT.json')['audit']['path'])
        bindings=[candidate['media'],candidate['result'],candidate['native_audio_clock']['media'],
                  candidate['audio_clock_receipt'],clock['evidence'][0],audit['evidence'][0],audit['detector_receipt']]
        count=(len(self.executor.submits),len(self.auditor.calls),len(self.assembler.calls))
        for binding in bindings:
            p=Path(binding['path']);before=p.read_bytes()
            try:
                p.write_bytes(b'changed after complete')
                with self.subTest(artifact=p.name):
                    with self.assertRaisesRegex(ValueError,'bound_file_changed'):self.drive()
                    with self.assertRaisesRegex(ValueError,'bound_file_changed'):loop.status(self.run)
            finally:p.write_bytes(before)
        self.assertEqual(count,(len(self.executor.submits),len(self.auditor.calls),len(self.assembler.calls)))
        self.assertEqual(self.drive()['status'],'complete')

    def test_completed_cache_deep_checks_new_review_and_assembly_proof_without_calls(self):
        self.auditor=Auditor(('needs_review',));self.prepare();self.drive()
        c=loop.read(self.run/'attempts/A001/CANDIDATE.json');a=loop.read(self.run/'attempts/A001/detection/AUDIT.json')['audit']
        observed=put(self.run/'FRESH_REVIEW_EVIDENCE.json',dict(native_id=c['native_id'],media=c['media'],CPU_mock=True))
        reviewed=put(self.run/'ACTUAL_REVIEW.json',dict(schema='media_repair_review/v1',decision='accept',
              reviewed_by='root_CPU_mock',attempt_id='A001',native_id=c['native_id'],candidate_result=c['result'],
              candidate_media=c['media'],audit=a,case_binding=self.case,asset_manifest=self.asset,evidence=[observed]))
        loop.record_review(self.run,'A001',reviewed);self.assertEqual(self.drive()['status'],'complete')
        assembled=loop.read(self.run/'ASSEMBLY_RESULT.json');receipt=loop.read(assembled['receipt']['path'])
        count=(len(self.executor.submits),len(self.auditor.calls),len(self.assembler.calls))
        for binding in (reviewed,observed,receipt['decoded_clock']):
            p=Path(binding['path']);before=p.read_bytes()
            try:
                p.write_bytes(b'changed after complete')
                with self.subTest(artifact=p.name):
                    with self.assertRaisesRegex(ValueError,'bound_file_changed'):self.drive()
            finally:p.write_bytes(before)
        self.assertEqual(count,(len(self.executor.submits),len(self.auditor.calls),len(self.assembler.calls)))
        self.assertEqual(self.drive()['status'],'complete')

    def test_real_CLI_drives_whole_injected_loop_and_requires_execute(self):
        p=PROJECT/'scripts/run_media_repair_loop_v1.py';spec=importlib.util.spec_from_file_location('repair_cli_test',p)
        cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        cli.main(['prepare','--run',str(self.run),'--spec',str(put(self.specfile,self.spec)['path'])])
        with self.assertRaisesRegex(ValueError,'execute_flag'):cli.main(['drive','--run',str(self.run)])
        with patch.object(cli.loop,'load_adapters',return_value=dict(executor=self.executor,auditor=self.auditor,assembler=self.assembler)):
            result=cli.main(['drive','--run',str(self.run),'--execute'])
        self.assertEqual(result['status'],'complete')


if __name__=='__main__':unittest.main()
