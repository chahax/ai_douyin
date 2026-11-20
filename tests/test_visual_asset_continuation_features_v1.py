"""Isolated registry checks for source-exact continuation descriptions."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from src.content_factory import visual_asset_continuation_features_v1 as f
from src.content_factory import visual_asset_feature_cards_v1 as original
from src.content_factory import visual_asset_registry_v3 as registry


class ContinuationFeaturesTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / 'data/qa/continuation_features_20261113/cases'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'script.txt'
        self.source.write_text('source fixture', encoding='utf-8')
        self.cast = self.root / 'CAST_PLAN.json'
        ids = ('su_mo', 'ye_dong', 'ye_yaner')
        self.cast.write_text(json.dumps(dict(source=original.bind(self.source), characters=[dict(
            id=eid, name=eid, identity_group=eid,
            front_prompt=' '.join(v for v in f.FEATURE_TERMS[eid].values() if v is not None),
            fact_age=None, visual_design_age=None, visual_design_is_not_novel_fact=True)
            for eid in ids])), encoding='utf-8')
        self.manifest = self.root / 'MAP.json'
        self.manifest.write_text(json.dumps(dict(cast_plan_sha256=original.bind(self.cast)['sha256'])), encoding='utf-8')
        self.library = self.root / 'library'
        self.output = self.root / 'binding'
        self.selection = {'characters': {}, 'places': {'room': {}}}
        for eid in ids:
            self.selection['characters'][eid] = {}
            for view in ('front', 'left_oblique'):
                row = self.register(eid, view)
                self.selection['characters'][eid][view] = {k: row[k] for k in ('asset_id', 'version')}
        for i, view in enumerate(('front', 'side')):
            image = self.root / f'room_{view}.png'
            Image.new('RGB', (16, 24), (i*30, 100, 90)).save(image)
            row = registry.register(self.library, image, book_id='book', entity_id='room', kind='place', view=view,
                identity_group='room', provenance=dict(entity=dict(id='room', name='room', design_version='v1',
                    layout_design='old gray room', spatial_layout={'room': {'width': 3}}, static_materials={'wall': 'gray'}),
                    source=original.bind(self.source)))
            self.selection['places']['room'][view] = {k: row[k] for k in ('asset_id', 'version')}

    def register(self, eid, view, identity_group=None):
        image = self.root / f'{eid}_{view}_{identity_group}.png'
        Image.new('RGB', (16, 24), ((sum(map(ord,eid+view)) % 250), 20, 40)).save(image)
        return registry.register(self.library, image, book_id='book', entity_id=eid, kind='character', view=view,
            identity_group=identity_group or eid, provenance=dict(manifest_path=str(self.manifest),
                manifest_sha256=original.bind(self.manifest)['sha256'], source_script=original.bind(self.source)))

    def prepare(self, terms=None):
        return f.prepare_binding(self.output, library=self.library, book_id='book', cast_plan=self.cast,
                                 selection=self.selection, feature_terms=terms)

    def card(self, result, eid):
        index = original.read(result['binding_index']['path'])
        return original.read(index['characters'][eid]['feature_card']['path'])

    def test_missing_eyes_stays_unknown_expression_is_separate(self):
        result = self.prepare()
        self.assertEqual(result['status'], 'binding_prepared')
        dong = self.card(result, 'ye_dong')
        self.assertIsNone(dong['features']['eyes'])
        self.assertEqual(dong['feature_status']['eyes'], 'not_specified_in_source')
        self.assertEqual(dong['features']['expression'], 'serious protective expression')
        self.assertNotIn('studio', dong['description'])
        self.assertNotIn('eyes', dong['description'])
        self.assertFalse(dong['production_approved'])

    def test_new_unquoted_trait_is_rejected_before_card_output(self):
        terms = deepcopy(f.FEATURE_TERMS)
        terms['ye_dong']['eyes'] = 'invented blue eyes'
        result = self.prepare(terms)
        self.assertEqual(result['status'], 'missing_notice')
        self.assertIn('features_not_exact_design_evidence', [n['code'] for n in result['notices']])
        self.assertFalse((self.output/'BINDING_INDEX.json').exists())

    def test_existing_description_is_byte_identical_and_no_global_patch(self):
        function = original._character_description
        result = self.prepare()
        card = self.card(result, 'su_mo')
        row = registry.get(self.library, book_id='book', entity_id='su_mo', view='front')[0]
        expected = function(row, original.read(self.cast), original.bind(self.cast), original.FEATURE_TERMS)
        self.assertEqual({k: card[k] for k in expected}, expected)
        self.assertIs(original._character_description, function)
        self.assertNotIn('ye_dong', original.FEATURE_TERMS)

    def test_angle_identity_mismatch_is_not_replaced(self):
        row = self.register('ye_dong', 'left_oblique', 'another_person')
        self.selection['characters']['ye_dong']['left_oblique'] = {k: row[k] for k in ('asset_id', 'version')}
        result = self.prepare()
        self.assertEqual(result['status'], 'missing_notice')
        self.assertIn('selected_views_different_identity_or_design_version', [n['code'] for n in result['notices']])

    def test_changed_generation_source_is_not_accepted(self):
        self.manifest.write_text(json.dumps({'cast_plan_sha256': '0'*64}), encoding='utf-8')
        result = self.prepare()
        self.assertEqual(result['status'], 'missing_notice')
        self.assertFalse(result['model_dispatch_allowed'])

    def test_missing_angle_exact_version_is_reported(self):
        self.selection['characters']['ye_yaner']['left_oblique']['version'] = 99
        result = self.prepare()
        self.assertEqual(result['status'], 'missing_notice')
        self.assertIn('corresponding_library_asset_missing', [n['code'] for n in result['notices']])


if __name__ == '__main__':
    unittest.main()
