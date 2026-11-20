"""Joint native identities, cross-field constraints and explicit final stop gates."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests.test_creative_screenplay_world_v1 import fixtures
from src.content_factory import creative_joint_world_screenplay_v3 as m
from scripts import run_h3_joint_world_screenplay_v3 as run


def joint_fixture():
    brief,cast,world,body,review=fixtures()
    schema=m.joint_schema(brief,cast)
    description=schema['properties']['world']['properties']['space_map']['items']['allOf'][0]['then']['properties']['description']['const']
    world.update(schema=m.repair.VERSION+'/world',clock_start='08:00:00',clock_end='08:02:30',planned_duration_seconds=150,
        time_of_day='清晨，既有白天窗光与白色顶灯。',space_map=[{'zone_id':z,'description':description if i==2 else 'fixture'} for i,z in enumerate(m.ZONES)],
        spatial_connections=[{'from_zone':m.ZONES[0],'to_zone':m.ZONES[1],'relation':'fixture'}],
        props=[{'prop_id':p,'name':p,'purpose':'fixture','initial_custody':m.P4_INITIAL if p=='P4' else 'fixture table',
                'final_intended_custody':'fixture'} for p in m.PROPS])
    for i,a in enumerate(world['dramatic_arc']):a.update(start_seconds=i*50,end_seconds=(i+1)*50)
    body.pop('world_sha256')
    for s in body['segments']:
        s['location_zone_id']=m.ZONES[2]
        for state in ('start_state','end_state'):
            for c,row in s[state]['characters'].items():row['zone_id']=m.ZONES[2] if c=='C01' else m.ZONES[1]
            s[state]['props']={p['prop_id']:p['initial_custody'] for p in world['props']}
    parent={'world':world,'screenplay':body}
    review.update(world_sha256=m.base.digest(world),script_sha256=m.base.digest(body),native_parent_sha256=m.base.digest(parent),
        world_pointer='/world',script_pointer='/screenplay')
    return brief,cast,parent,review


class JointFinalContracts(unittest.TestCase):
    def test_complete_parent_never_requires_model_to_compute_fresh_world_hash(self):
        brief,cast,parent,review=joint_fixture();before=deepcopy(parent)
        result=m.validate_joint(parent,brief,cast)
        self.assertTrue(result['valid']);self.assertEqual(parent,before)
        self.assertNotIn('world_sha256',parent['screenplay'])
        self.assertEqual(m.validation_view(parent)['world_sha256'],m.base.digest(parent['world']))
        self.assertFalse(result['mechanical_identity']['identity_view_is_native'])

    def test_joint_cross_field_total_and_native_hash_field_rejected(self):
        brief,cast,parent,review=joint_fixture()
        parent['world']['planned_duration_seconds']=170;parent['world']['clock_end']='08:02:50';parent['world']['dramatic_arc'][-1]['end_seconds']=170
        with self.assertRaises(Exception):m.validate_joint(parent,brief,cast)
        brief,cast,parent,review=joint_fixture();parent['screenplay']['world_sha256']='invented'
        with self.assertRaises(Exception):m.validate_joint(parent,brief,cast)

    def test_static_pocket_scene_and_first_zero_prefix_are_contractual(self):
        for change in ('pocket','scene','first_line'):
            brief,cast,parent,review=joint_fixture()
            if change=='pocket':parent['world']['props'][3]['initial_custody']='left hand'
            elif change=='scene':parent['world']['space_map'][2]['description']='chair on table'
            else:parent['screenplay']['segments'][0]['events'][0]['dialogue'][0]['start_s']=.1
            with self.subTest(change=change),self.assertRaises(Exception):m.validate_joint(parent,brief,cast)

    def test_review_binds_actual_parent_canonical_and_two_native_pointers(self):
        brief,cast,parent,review=joint_fixture()
        self.assertTrue(m.validate_review(review,brief,parent)['accepted'])
        review['native_parent_sha256']='wrong'
        with self.assertRaises(Exception):m.validate_review(review,brief,parent)

    def test_stop_prevents_final_body_claim(self):
        folder=run.PROJECT/'data/qa/h3_screenplay_world_20261015/fixtures';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as directory:
            root=Path(directory);(root/'STOP.json').write_text('{}',encoding='utf8')
            with patch.object(run,'ROOT',root),patch.object(run,'guard',return_value=True),patch.object(run.policy,'new_claim',side_effect=AssertionError('no claim')):
                with self.assertRaisesRegex(RuntimeError,'STOP'):run.invoke('complete_script','fixture',{},lambda x:x)

    def test_body_returns_to_primary_before_any_review(self):
        brief,cast,parent,review=joint_fixture()
        folder=run.PROJECT/'data/qa/h3_screenplay_world_20261015/fixtures'
        with tempfile.TemporaryDirectory(dir=folder) as directory:
            root=Path(directory);run.write(root/'PREVIEW.json',{'brief':brief,'seed':{'fixed_casting':cast},'first_request':{}})
            receipt={'status':'contract_valid','ordinal':640,'validation':{'valid':True}}
            with patch.object(run,'ROOT',root),patch.object(run,'runtime',return_value=object()),patch.object(run,'invoke',return_value=receipt) as invoke,patch.object(run.NativeSession,'known',return_value=parent),patch.object(run,'state',side_effect=lambda rt,status,**kw:{'status':status,**kw}):
                result=run.phase('body');self.assertEqual(result['status'],'awaiting_primary_joint_content_review')
                self.assertEqual(invoke.call_count,1);self.assertFalse((root/'NATIVE_FULL_REVIEW.json').exists())
                self.assertEqual(run.read(root/'NATIVE_JOINT_SCRIPT.json'),parent)

    def test_malformed_original_is_preserved_and_necessary_failure_stops_before_views(self):
        folder=run.PROJECT/'data/qa/h3_screenplay_world_20261015/fixtures'
        with tempfile.TemporaryDirectory(dir=folder) as directory:
            root=Path(directory);run.write(root/'PREVIEW.json',{'brief':{},'seed':{'fixed_casting':{}},'first_request':{}})
            original={'incomplete_native':'preserve exactly'}
            receipt={'status':'contract_rejected','ordinal':640,'validation':{'valid':False,'diagnostics':['missing world']}}
            with patch.object(run,'ROOT',root),patch.object(run,'runtime',return_value=object()),patch.object(run,'invoke',return_value=receipt) as invoke,patch.object(run.NativeSession,'known',return_value=original),patch.object(run,'state',side_effect=lambda rt,status,**kw:{'status':status,**kw}):
                result=run.phase('body');self.assertEqual(result['status'],'halt_final_joint_necessary_contract_rejected')
                self.assertEqual(run.read(root/'NATIVE_JOINT_SCRIPT.json'),original)
                self.assertEqual(run.read(root/'BODY_NECESSARY_DECISION.json')['valid'],False)
                self.assertFalse((root/'NATIVE_IDENTITY_MAP.json').exists());self.assertEqual(invoke.call_count,1)


if __name__=='__main__':unittest.main()
