"""Small successor gates and necessary timing schema; no real calls."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,MagicMock
from tests.test_creative_screenplay_world_v1 import fixtures
from src.content_factory import creative_screenplay_world_source_repair_v2 as m
from scripts import run_h3_world_source_repair_v2 as run


class SourceRepairTests(unittest.TestCase):
    def fixture(self):
        brief,cast,world,body,review=fixtures()
        world.update(schema=m.VERSION+'/world',clock_start='08:00:00',clock_end='08:02:30',planned_duration_seconds=150,
                     time_of_day='清晨，既有白天窗光与白色顶灯。')
        for i,a in enumerate(world['dramatic_arc']):a.update(start_seconds=i*50,end_seconds=(i+1)*50)
        body['world_sha256']=m.prior.digest(world)
        return brief,cast,world,body

    def test_contiguous_world_arc_clock_and_total_bind(self):
        brief,cast,world,body=self.fixture()
        self.assertTrue(m.validate_world(world,brief,cast)['valid'])
        world['dramatic_arc'][-1]['end_seconds']=230
        self.assertFalse(m.validate_world(world,brief,cast)['valid'])
        world['dramatic_arc'][-1]['end_seconds']=150;world['clock_end']='08:03:50'
        self.assertFalse(m.validate_world(world,brief,cast)['valid'])

    def test_first_manager_line_must_be_exactly_zero_at_schema_level(self):
        brief,cast,world,body=self.fixture()
        self.assertTrue(m.validate_script(body,brief,world)['valid'])
        body['segments'][0]['events'][0]['dialogue'][0]['start_s']=.1
        with self.assertRaises(Exception):m.validate_script(body,brief,world)
        body['segments'][0]['events'][0]['dialogue'][0].update(start_s=0,speaker='C01')
        with self.assertRaises(Exception):m.validate_script(body,brief,world)

    def test_body_total_must_match_reviewed_world(self):
        brief,cast,world,body=self.fixture();world['planned_duration_seconds']=170
        body['world_sha256']=m.prior.digest(world)
        with self.assertRaises(Exception):m.validate_script(body,brief,world)

    def test_stop_is_checked_before_a_new_phase_claim(self):
        folder=run.PROJECT/'data/qa/h3_screenplay_world_20261015/fixtures';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as directory:
            root=Path(directory);(root/'STOP.json').write_text('{}',encoding='utf8')
            with patch.object(run,'ROOT',root),patch.object(run,'guard',return_value=True),patch.object(run.policy,'new_claim',side_effect=AssertionError('no claim')):
                with self.assertRaisesRegex(RuntimeError,'STOP'):run.invoke('goal_plan','fixture',{},lambda x:x)

    def test_body_needs_actual_nonempty_source_bound_primary_review(self):
        folder=run.PROJECT/'data/qa/h3_screenplay_world_20261015/fixtures'
        with tempfile.TemporaryDirectory(dir=folder) as directory:
            root=Path(directory);template={'schema':'fixture','decision':'accepted_for_body','actual_content_findings':[]}
            run.write(root/'WORLD_PRIMARY_DECISION.json',template)
            with patch.object(run,'ROOT',root),patch.object(run,'world_decision_template',return_value=template):
                with self.assertRaisesRegex(RuntimeError,'findings'):run.check_control('complete_script')
                template['actual_content_findings']=['actual primary read']
                run.write(root/'WORLD_PRIMARY_DECISION.json',template)
                self.assertTrue(run.check_control('complete_script'))
                run.write(root/'WORLD_PRIMARY_DECISION.json',{**template,'decision':'rejected'})
                with self.assertRaisesRegex(RuntimeError,'not accepted'):run.check_control('complete_script')

    def test_world_phase_returns_before_any_automatic_body_dispatch(self):
        brief,cast,world,body=self.fixture()
        folder=run.PROJECT/'data/qa/h3_screenplay_world_20261015/fixtures'
        with tempfile.TemporaryDirectory(dir=folder) as directory:
            root=Path(directory)
            run.write(root/'PREVIEW.json',{'brief':brief,'seed':{'fixed_casting':cast},'first_request':{}})
            receipt={'status':'contract_valid','ordinal':639}
            with patch.object(run,'ROOT',root),patch.object(run,'runtime',return_value=object()),patch.object(run,'invoke',return_value=receipt) as invoke,patch.object(run.NativeSession,'known',return_value=world),patch.object(run,'state',side_effect=lambda rt,status,**kw:{'status':status,**kw}):
                result=run.phase('world')
                self.assertEqual(result['status'],'awaiting_primary_world_content_review');self.assertEqual(invoke.call_count,1)
                self.assertFalse((root/'NATIVE_SCRIPT.json').exists())

    def test_body_then_review_reuses_identical_primary_snapshot(self):
        folder=run.PROJECT/'data/qa/h3_screenplay_world_20261015/fixtures'
        with tempfile.TemporaryDirectory(dir=folder) as directory:
            root=Path(directory);decision={'schema':'fixture','decision':'accepted_for_body','actual_content_findings':['primary actual read']}
            run.write(root/'WORLD_PRIMARY_DECISION.json',decision)
            rt=MagicMock();rt.dispatch.return_value={'fixture':True}
            with patch.object(run,'ROOT',root),patch.object(run,'guard',return_value=True),patch.object(run,'runtime',return_value=rt),patch.object(run,'world_decision_template',return_value=decision):
                run.invoke('complete_script','body_fixture',{'request_sha256':'first','request':{'stage':'complete_script'}},lambda x:x)
                before=(root/'WORLD_PRIMARY_DECISION_SNAPSHOT.json').read_bytes()
                run.invoke('full_review','review_fixture',{'request_sha256':'second','request':{'stage':'full_review'}},lambda x:x)
                self.assertEqual(rt.dispatch.call_count,2)
                self.assertEqual((root/'WORLD_PRIMARY_DECISION_SNAPSHOT.json').read_bytes(),before)


if __name__=='__main__':unittest.main()
