"""Meaningful contract checks using isolated registry assets, never live media APIs."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image

from src.content_factory import visual_asset_feature_cards_v1 as f
from src.content_factory import visual_asset_registry_v3 as registry


class FeatureCardsTests(unittest.TestCase):
    def setUp(self):
        temp_parent = Path(__file__).resolve().parents[1] / 'data/qa/asset_feature_cards_20261112/case_temp'
        temp_parent.mkdir(parents=True, exist_ok=True)
        self.home = tempfile.TemporaryDirectory(dir=temp_parent)
        self.addCleanup(self.home.cleanup)
        self.root = Path(self.home.name)
        self.library = self.root / 'library'
        self.source = self.root / 'script.txt'
        self.source.write_text('fictional supplied source', encoding='utf-8')
        terms = f.FEATURE_TERMS['su_mo']
        self.cast = self.root / 'CAST_PLAN.json'
        self.cast.write_text(json.dumps(dict(source=f.bind(self.source), characters=[dict(
            id='su_mo', name='苏墨', identity_group='adult_su_mo', front_prompt=' '.join(terms.values()),
            fact_age=None, visual_design_age=None, age_evidence={'note':'adult; exact age not asserted'},
            visual_design_is_not_novel_fact=True)])), encoding='utf-8')
        self.manifest = self.root / 'MAP.json'
        self.manifest.write_text(json.dumps({'cast_plan_sha256':f.bind(self.cast)['sha256']}), encoding='utf-8')
        self.selection = {'characters':{'su_mo':{}}, 'places':{'room':{}}}
        for i, (eid, kind, view) in enumerate([
                ('su_mo','character','front'), ('su_mo','character','left_oblique'),
                ('room','place','front'), ('room','place','side')]):
            image = self.root / (str(i)+'.png')
            Image.new('RGB',(24,32),(i*50,20,40)).save(image)
            if kind == 'character':
                provenance = dict(manifest_path=str(self.manifest), manifest_sha256=f.bind(self.manifest)['sha256'], source_script=f.bind(self.source))
            else:
                provenance = dict(entity=dict(id='room',name='房间',design_version='v1',layout_design='old gray concrete room',spatial_layout={'room':{'width':3}},static_materials={'wall':'gray'}),source=f.bind(self.source))
            row = registry.register(self.library,image,book_id='book',entity_id=eid,kind=kind,view=view,
                identity_group='adult_su_mo' if kind=='character' else 'room',provenance=provenance)
            self.selection['characters' if kind=='character' else 'places'][eid][view] = {k:row[k] for k in ('asset_id','version')}
        self.output = self.root / 'binding'

    def prepare(self):
        return f.prepare_binding(self.output,library=self.library,book_id='book',cast_plan=self.cast,selection=self.selection)

    def approve(self, result, *, allow_candidates=True):
        p=self.root/'APPROVAL.json'
        p.write_text(json.dumps(dict(schema=f.APPROVAL_SCHEMA,binding_index=result['binding_index'],
            approved_by='fixture explicit first binding',evidence=['test source/role/image checked'],
            confirmed_entities=['su_mo','room'],allow_candidate_assets=result['candidate_assets'] if allow_candidates else [],
            production_approved=False)),encoding='utf-8')
        return p

    def resolve(self, result, approval):
        return f.resolve_segment(result['binding_index'],actor_ids=['su_mo'],place_id='room',
            angle_by_actor={'su_mo':'left_oblique'},approval_path=approval)

    def test_real_lookup_and_feature_card_are_same_version(self):
        prepared=self.prepare();self.assertEqual(prepared['status'],'binding_prepared')
        value=self.resolve(prepared,self.approve(prepared))
        self.assertEqual(value['status'],'ready');self.assertEqual(len(value['references']),4)
        self.assertEqual([r['view'] for r in value['references']],['front','left_oblique','front','side'])
        card=value['character_descriptions']['su_mo']
        self.assertEqual(card['features']['face'],f.FEATURE_TERMS['su_mo']['face'])
        self.assertIsNone(card['age']['fact_age']);self.assertIsNone(card['age']['visual_design_age'])
        self.assertNotIn('studio',card['description']);self.assertNotIn('front-facing',card['description'])
        for ref in value['references']:
            self.assertEqual(f.bind(ref['image']['path']),ref['image'])
        self.assertEqual(registry.get(self.library,book_id='book',entity_id='su_mo')[0]['status'],'candidate')

    def test_missing_asset_not_replaced_by_latest(self):
        self.selection['characters']['su_mo']['front']['version']=99
        value=self.prepare();self.assertEqual(value['status'],'missing_notice')
        self.assertFalse(value['model_dispatch_allowed']);self.assertFalse((self.output/'BINDING_INDEX.json').exists())

    def test_missing_description_not_guessed(self):
        value=f.prepare_binding(self.output,library=self.library,book_id='book',cast_plan=self.cast,
            selection=self.selection,feature_terms={})
        self.assertEqual(value['status'],'missing_notice')
        self.assertIn('structured_character_features_missing',[n['code'] for n in value['notices']])

    def test_unconfirmed_candidate_is_not_ready(self):
        prepared=self.prepare();value=self.resolve(prepared,self.approve(prepared,allow_candidates=False))
        self.assertEqual(value['status'],'missing_notice')
        self.assertIn('candidate_view_not_confirmed',[n['code'] for n in value['notices']])

    def test_no_initial_binding_confirmation(self):
        prepared=self.prepare();value=self.resolve(prepared,None)
        self.assertEqual(value['status'],'missing_notice')
        self.assertIn('initial_project_binding_confirmation_required',[n['code'] for n in value['notices']])

    def test_missing_design_source_returns_notice(self):
        value=f.prepare_binding(self.output,library=self.library,book_id='book',cast_plan=self.root/'absent.json',selection=self.selection)
        self.assertEqual(value['status'],'missing_notice')
        self.assertEqual(value['notices'][0]['code'],'cast_design_source_unavailable')

    def test_unstructured_confirmation_evidence_is_rejected(self):
        prepared=self.prepare();approval=self.approve(prepared)
        value=f.read(approval);value['evidence']='unstructured yes'
        approval.write_text(json.dumps(value),encoding='utf-8')
        rejected=self.resolve(prepared,approval)
        self.assertEqual(rejected['status'],'missing_notice')
        self.assertEqual(rejected['notices'][0]['code'],'project_binding_confirmation_changed_or_missing')

    def test_modified_picture_or_description_invalidates_packet(self):
        prepared=self.prepare();approval=self.approve(prepared)
        index=f.read(prepared['binding_index']['path']);card_path=Path(index['characters']['su_mo']['feature_card']['path'])
        card=f.read(card_path);card['description']='invented different person'
        card_path.write_text(json.dumps(card),encoding='utf-8')
        value=self.resolve(prepared,approval);self.assertEqual(value['status'],'missing_notice')
        self.assertIn('bound_file_changed',[n['code'] for n in value['notices']])

    def test_new_actor_not_silently_invented_and_capacity_no_truncation(self):
        prepared=self.prepare();approval=self.approve(prepared)
        missing=f.resolve_segment(prepared['binding_index'],actor_ids=['new_person'],place_id='room',
            angle_by_actor={'new_person':'left_oblique'},approval_path=approval)
        self.assertIn('character_binding_missing',[n['code'] for n in missing['notices']])
        capped=f.resolve_segment(prepared['binding_index'],actor_ids=['su_mo'],place_id='room',
            angle_by_actor={'su_mo':'left_oblique'},approval_path=approval,reference_limit=3)
        self.assertEqual(capped['status'],'missing_notice')
        self.assertIn('required_references_exceed_capacity',[n['code'] for n in capped['notices']])

    def test_design_text_cannot_be_copied_to_different_asset_version(self):
        self.manifest.write_text(json.dumps({'cast_plan_sha256':'0'*64}),encoding='utf-8')
        value=self.prepare();self.assertEqual(value['status'],'missing_notice')


if __name__=='__main__':unittest.main()
