"""Integrity failures, preserved baselines, separate identities and safe local HTML."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('personal_assets',ROOT/'scripts/manage_personal_assets_v1.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class PersonalAssetIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (m.OUT/'validation_fixtures').mkdir(exist_ok=True)
        cls.catalog=m.load(m.OUT/'CATALOG.json')

    def fixture(self,directory):
        output=Path(directory)
        image=output/'image.png'
        image.write_bytes(b'original-local-fixture')
        catalog=copy.deepcopy(self.catalog)
        catalog['assets']=catalog['assets'][:1]
        catalog['assets'][0]['image']=m.identity(image)
        catalog['evidence_files']=[]
        m.write_json(output/'CATALOG.json',catalog)
        return output,image,catalog

    def test_exact_sources_and_style_identity_separation(self):
        # These counts describe the immutable discovery seed, not later import batches.
        seed_prefixes=('legacy.', 'nativeboard.', 'scene.photoreal.20261006.', 'direction.3d.')
        assets=[a for a in self.catalog['assets'] if a['asset_id'].startswith(seed_prefixes)]
        self.assertEqual(len(assets),32)
        self.assertEqual(sum(a['style']=='photoreal' for a in assets),11)
        chen=[a for a in assets if a['name']=='陈默']
        self.assertEqual({a['style'] for a in chen},{'photoreal','3d_soft_doll'})
        self.assertEqual(len({a['asset_id'] for a in chen}),len(chen))
        self.assertTrue(all(a['current_casting']['status']=='unbound' for a in assets))
        self.assertTrue(all(a['current_media_approval'] is None for a in assets))

    def test_changed_source_blocks_build_preserving_expected_hash(self):
        with tempfile.TemporaryDirectory(dir=m.OUT/'validation_fixtures') as d:
            output,image,catalog=self.fixture(d)
            before=(output/'CATALOG.json').read_bytes()
            image.write_bytes(b'changed-without-approval')
            with patch.object(m,'collect',side_effect=AssertionError('must not rebaseline')):
                result=m.build(output=output)
            self.assertEqual(result['issues'][0]['actual']['integrity'],'hash_mismatch')
            self.assertEqual((output/'CATALOG.json').read_bytes(),before)
            self.assertEqual(m.load(output/'CATALOG.json')['assets'][0]['image']['expected_sha256'],catalog['assets'][0]['image']['expected_sha256'])

    def test_missing_image_is_reported_and_not_reaccepted(self):
        with tempfile.TemporaryDirectory(dir=m.OUT/'validation_fixtures') as d:
            output,image,catalog=self.fixture(d)
            before=(output/'CATALOG.json').read_bytes()
            image.unlink()
            result=m.build(output=output)
            self.assertEqual(result['issues'][0]['actual']['integrity'],'missing')
            self.assertEqual((output/'CATALOG.json').read_bytes(),before)
            self.assertNotIn('<img ',(output/'INDEX.html').read_text(encoding='utf-8'))

    def test_evidence_hash_change_blocks_verification(self):
        with tempfile.TemporaryDirectory(dir=m.OUT/'validation_fixtures') as d:
            output,image,catalog=self.fixture(d)
            source=output/'review.json';source.write_text('old',encoding='utf-8')
            catalog['evidence_files']=[m.identity(source)]
            catalog['assets'][0]['evidence_paths']=[str(source)]
            source.write_text('new',encoding='utf-8')
            report=m.verify_catalog(catalog)
            self.assertEqual(report['issues'][0]['kind'],'evidence')
            self.assertEqual(report['issues'][0]['actual']['integrity'],'hash_mismatch')
            page=m.render(catalog,output,report)
            self.assertIn('evidence_missing_or_hash_mismatch',page)
            self.assertIn('异常 1 项',page)

    def test_html_escapes_metadata_and_has_no_external_or_dynamic_html(self):
        catalog=copy.deepcopy(self.catalog)
        catalog['assets'][0]['name']='</script><img src=x onerror=alert(1)>"'
        page=m.render(catalog,m.OUT,m.verify_catalog(catalog))
        self.assertIn('&lt;/script&gt;&lt;img',page)
        self.assertNotIn('</script><img',page)
        self.assertNotIn('innerHTML',page)
        self.assertNotIn('https://',page)
        self.assertNotIn('http://',page)

    def test_board_review_scopes_preserve_original_disagreement(self):
        board=next(a for a in self.catalog['assets'] if a['asset_id'].endswith('r1.C01'))
        review=board['historical_review']
        self.assertIs(review['latest_sample_original']['human_identity_approval'],True)
        self.assertIsNone(review['generation_receipt_original']['human_identity_approval'])
        self.assertIsNone(review['confirmation_asset_human_identity_approval'])
        self.assertIs(review['identity_confirmation_original']['human_identity_and_clothing_approval'],True)
        self.assertIs(review['identity_confirmation_original']['video_content_approval'],False)

    def test_magic_mime_detects_mislabeled_extension_without_image_decoding(self):
        with tempfile.TemporaryDirectory(dir=m.OUT/'validation_fixtures') as d:
            path=Path(d)/'wrong.png'
            path.write_bytes(b'\xff\xd8\xff\xe0fixture')
            self.assertEqual(m.image_mime(path),'image/jpeg')

    def test_scene_approval_remains_limited_to_sample(self):
        scenes=[a for a in self.catalog['assets'] if a['asset_id'].startswith('scene.photoreal.20261006')]
        self.assertEqual(len(scenes),2)
        for scene in scenes:
            review=scene['historical_review']
            self.assertIs(review['sample_manifest_original']['human_aesthetic_approval'],True)
            self.assertIs(review['sample_manifest_original']['human_visible_layout_approval'],True)
            self.assertIs(review['confirmation_original']['exact_physical_geometry_verified'],False)
            self.assertIs(review['confirmation_original']['video_content_approval'],False)


if __name__=='__main__':
    (m.OUT/'validation_fixtures').mkdir(exist_ok=True)
    unittest.main()
