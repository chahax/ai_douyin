"""Cast metadata order can vary; missing, duplicate or swapped identities cannot."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT/'scripts'))
import qa_h3_library_continuation_v2 as q

RUN=PROJECT/'data/video_generation/h3_library_bound_next_minute_20261113_v1'
NR=RUN/'visual_h3_v3'/(RUN.name+'_S02')


class ContinuationV2CastTests(unittest.TestCase):
    def test_permuted_unique_actor_metadata_and_actual_S02_pass(self):
        actual=['ye_dong','ye_nan','ye_xijue','ye_yaner']
        source=['ye_dong','ye_nan','ye_yaner','ye_xijue']
        self.assertTrue(q.same_unique_cast(actual,source))
        result=q.prepared_graph(NR,'S02')
        self.assertEqual(result['routes']['actual_positive_reference_count'],9)
        self.assertEqual(result['routes']['actual_LoadImage_count'],10)
        self.assertEqual(result['routes']['guide_node'],'scene_start')
        self.assertNotEqual(result['routes']['actual_guide_image'],result['context']['references'][-1]['image'])

    def altered_cast(self, actors):
        original_read=q._ns['read'];target=RUN/'segments/S02/LIBRARY_INPUT.json'
        def changed(path):
            value=original_read(path)
            if Path(path).resolve()==target:
                value=deepcopy(value);value['required_actor_assets']=actors
            return value
        with patch.dict(q._ns,{'read':changed}):
            with self.assertRaisesRegex(ValueError,'full_cast_and_explicit_per_segment_selection_required'):
                q.prepared_graph(NR,'S02')

    def test_missing_actor_is_still_rejected_by_real_prepared_QA(self):
        self.altered_cast(['ye_dong','ye_nan','ye_xijue'])

    def test_duplicated_actor_cannot_satisfy_required_cast(self):
        self.altered_cast(['ye_dong','ye_nan','ye_xijue','ye_xijue'])

    def test_wrong_actor_cannot_replace_the_selected_actor(self):
        self.altered_cast(['ye_dong','ye_nan','ye_xijue','su_mo'])

    def test_physical_actor_picture_swap_is_rejected(self):
        value=q.read(RUN/'segments/S02/LIBRARY_INPUT.json');refs=deepcopy(value['references'][:-1])
        refs[0]['image'],refs[1]['image']=refs[1]['image'],refs[0]['image']
        with self.assertRaisesRegex(ValueError,'exact_selected_registry_image_changed'):
            q.library_reference_cards(value['library_binding'],refs,value['required_actor_assets'],value['segment_selection'],PROJECT)

    def test_old_sealed_source_and_namespace_are_not_changed(self):
        self.assertEqual(q.previous.sha(Path(q.previous.__file__)),q.SEALED_PREVIOUS_SHA)
        self.assertNotIn('same_unique_cast',q.previous.prepared_graph.__globals__)
        self.assertFalse(q.same_unique_cast(['a','a'],['a']))
        self.assertFalse(q.same_unique_cast(['a'],['a','a']))


if __name__=='__main__':unittest.main()
