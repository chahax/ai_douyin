"""Independent regressions using recorded pixels, never inference or media POST."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT/'scripts'))
import qa_h3_library_continuation as q

NEW=PROJECT/'data/video_generation/h3_library_bound_next_minute_20261113_v1'
OLD=PROJECT/'data/video_generation/h3_library_bound_minute_20261112_v1'


class ContinuationQATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qa=q.for_run(NEW)
        nr=OLD/'visual_h3_v3/h3_library_bound_minute_20261112_v1_S04'
        cls.graph=q.read(nr/'shots/S04/workflow_api.json');p=q.read(nr/'PLAN.json');row=p['shots'][0]
        root=Path(p['config']['input_root'])
        cls.refs=[dict(slot=i,label=f'P{i+1}',source=r['image'],staged=q.bind(root/r['input_name']),node_id=f'ref_{i}',input_name=r['input_name']) for i,r in enumerate(row['reference_map'])]
        cls.actual_guide=q.bind(nr/'shots/S04/artifacts/last_00001_.png')

    def scene(self):
        graph=deepcopy(self.graph)
        graph['scene_start']=dict(class_type='LoadImage',inputs={'image':'scene_start_distinct.png'})
        graph['guide_start']['inputs']['image']=['scene_start',0]
        guide=dict(image=self.actual_guide,staged=self.actual_guide,input_name='scene_start_distinct.png')
        return graph,guide

    def test_ten_load_images_are_nine_positive_refs_plus_separate_guide(self):
        graph,guide=self.scene();r=q.graph_pixel_routes(graph,self.refs,guide)
        self.assertEqual(r['actual_LoadImage_count'],10)
        self.assertEqual(r['actual_positive_reference_count'],9)
        self.assertEqual(r['guide_node'],'scene_start')
        self.assertTrue(r['scene_start_is_independent_of_previous_tail'])

    def test_previous_room_tail_cannot_replace_new_scene_guide(self):
        graph,guide=self.scene();graph['guide_start']['inputs']['image']=['ref_8',0]
        with self.assertRaisesRegex(ValueError,'independent_generated_stage'):
            q.graph_pixel_routes(graph,self.refs,guide)

    def test_positive_tail_context_must_not_be_silently_removed(self):
        graph,guide=self.scene();del graph['condition']['inputs']['ref_images.ref_image_8']
        with self.assertRaisesRegex(ValueError,'every_declared_reference'):
            q.graph_pixel_routes(graph,self.refs,guide)

    def test_changed_staged_identity_pixels_fail(self):
        refs=deepcopy(self.refs);refs[0]['staged']=refs[1]['staged']
        with self.assertRaisesRegex(ValueError,'pixels_changed'):
            q.graph_pixel_routes(self.graph,refs,None)

    def test_official_CPU_protocol_consumes_distinct_stage_not_p9(self):
        refs=q.read(OLD/'segments/S04/LIBRARY_INPUT.json')['references']
        r=self.qa.cpu_source_protocol(refs,guide=self.actual_guide)
        self.assertEqual(r['model_positive_refs'],9)
        self.assertEqual(r['model_positive_keyframes'],1)
        self.assertEqual(r['guide_VAE_call']['tag'],'actual_frame0_guide')
        self.assertNotEqual(r['guide_VAE_call']['source_pixel_sha'],r['reference_VAE_calls'][-1]['source_pixel_sha'])
        self.assertFalse(r['GPU_model_inference'])

    def test_four_source_ranges_and_neutral_narration_are_authentic(self):
        entries={sid:q.source_entry(q.bind(NEW/'segments'/sid/'SOURCE_CASE.json'),sid) for sid in q.IDS}
        self.assertEqual(entries['S01']['full_clip_actor_ids'],['su_mo'])
        self.assertTrue(all(a['mode']=='voiceover' and a['speaker']=='narrator' for a in entries['S01']['audio']))
        self.assertEqual(len(entries['S02']['full_clip_actor_ids']),4)
        self.assertNotEqual(self.qa.EXPECTED_QUOTES, q.base.EXPECTED_QUOTES)
        self.assertEqual(sum(map(len,self.qa.EXPECTED_QUOTES.values())),9)

    def test_shifted_manuscript_evidence_is_rejected(self):
        parent=PROJECT/'data/qa/h3_library_continuation_independent_20261113/cases';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            value=q.read(NEW/'segments/S01/SOURCE_CASE.json')
            original=next(p['original'] for p in value['shots'][0]['source_item_provenance'] if p['kind']=='selected_body_item')
            original['source_start']+=1
            p=Path(folder)/'SOURCE_CASE.json';p.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'manuscript_quote_or_action_offset_changed'):
                q.source_entry(q.bind(p),'S01')

    def test_front_only_selection_needs_explicit_capacity_decision(self):
        plan=q.read(NEW/'PLAN.json');selection=q.read(Path(plan['library_selection']['path']))['segments']['S02']
        index=q.read(Path(plan['library_binding']['path']));actors=q.source_entry(q.bind(NEW/'segments/S02/SOURCE_CASE.json'),'S02')['full_clip_actor_ids'];refs=[]
        for cid in actors:
            for view in selection['actor_views'][cid]:
                p=index['characters'][cid]['images'][view]
                refs.append(dict(feature_card=index['characters'][cid]['feature_card'],actor_id=cid,**{k:p[k] for k in ('entity_id','kind','view','asset_id','version','design_version','identity_group','image')}))
        for view in selection['place_views']:
            p=index['places']['children_room']['images'][view]
            refs.append(dict(feature_card=index['places']['children_room']['feature_card'],actor_id=None,**{k:p[k] for k in ('entity_id','kind','view','asset_id','version','design_version','identity_group','image')}))
        selection=deepcopy(selection);selection.pop('capacity_decision')
        with self.assertRaisesRegex(ValueError,'explicit_capacity_decision'):
            q.library_reference_cards(plan['library_binding'],refs,actors,selection,PROJECT)


if __name__=='__main__':unittest.main()
