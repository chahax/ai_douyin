"""Append-only local image imports retain evidence baselines and null approvals."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('personal_asset_imports', ROOT/'scripts/manage_personal_assets_v1.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class PersonalAssetImportTests(unittest.TestCase):
    def setUp(self):
        fixtures = m.OUT/'validation_fixtures'
        fixtures.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=fixtures)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.imports = self.root/'data/visual_asset_library/personal_catalog_v1/imports'
        self.imports.mkdir(parents=True)
        self.output = self.imports.parent

    def manifest(self, name='one', **changes):
        image = self.root/f'{name}.png'
        image.write_bytes(b'\x89PNG\r\n\x1a\nsynthetic-header-fixture')
        receipt = self.root/f'{name}_receipt.json'
        receipt.write_text('{"fixture":true}', encoding='utf-8')
        asset = {'asset_id':f'test.scene.{name}.v1', 'name':'同一场景', 'kind':'scene',
                 'style':'photoreal', 'series_id':f'test.scene.{name}', 'version':'v1',
                 'image':{'path':image.name, 'sha256':m.sha(image)},
                 'source':{'service':'test_only', 'receipt':{'path':receipt.name, 'sha256':m.sha(receipt)}},
                 'selection':{'status':'assistant_selected','scope':'Synthetic fixture; no real asset'},
                 'user_media_approval':None}
        asset.update(changes)
        path = self.imports/f'{name}.json'
        m.write_json(path, {'schema':'personal_local_asset_import/v1','assets':[asset]})
        return path, asset

    def collect(self, root=None):
        assets, evidence = [], {}
        def evidence_file(path, expected=None):
            evidence[str(path)] = m.identity(path, expected)
            return str(path)
        def add(asset_id, name, kind, series, version, style, image, expected, manifest, details, history, refs):
            assets.append({'asset_id':asset_id,'name':name,'kind':kind,'series_id':series,'version':version,
                           'style':style,'image':m.identity(image,expected),'mime':m.image_mime(image),
                           'source_manifest':manifest,'details':details,'historical_review':history,
                           'evidence_paths':refs,'current_casting':{'status':'unbound'},'current_media_approval':None})
        m.collect_imports(self.root, evidence_file, add)
        if len({a['asset_id'] for a in assets}) != len(assets):
            raise ValueError('Duplicate stable asset IDs')
        return {'schema':'personal_local_asset_catalog/v1','created_at':m.now(),'assets':assets,
                'evidence_files':list(evidence.values())}

    def build(self):
        with patch.object(m, 'collect', side_effect=self.collect):
            return m.build(root=self.root, output=self.output)

    def test_append_new_batch_preserves_first_import_and_separate_approval(self):
        first, _ = self.manifest()
        self.assertEqual(self.build()['status'], 'ok')
        before = m.load(self.output/'CATALOG.json')['assets'][0]
        self.manifest('two')
        self.assertEqual(self.build()['status'], 'ok')
        catalog = m.load(self.output/'CATALOG.json')
        self.assertEqual(len(catalog['assets']), 2)
        self.assertEqual(catalog['assets'][0], before)
        self.assertIn(str(first.resolve()), [r['path'] for r in catalog['evidence_files']])
        self.assertIsNone(before['current_media_approval'])
        self.assertIsNone(before['historical_review']['human_identity_approval'])
        self.assertEqual(before['details']['selection']['status'], 'assistant_selected')

    def test_changed_manifest_blocks_build_without_catalog_rebaseline(self):
        path, _ = self.manifest()
        self.assertEqual(self.build()['status'], 'ok')
        before = (self.output/'CATALOG.json').read_bytes()
        path.write_text(path.read_text(encoding='utf-8')+'\n', encoding='utf-8')
        with patch.object(m, 'collect', side_effect=AssertionError('must not rebaseline')):
            result = m.build(root=self.root, output=self.output)
        self.assertEqual(result['issues'][0]['kind'], 'evidence')
        self.assertEqual((self.output/'CATALOG.json').read_bytes(), before)

    def test_conflicting_stable_id_refuses_new_batch_preserves_catalog(self):
        _, first = self.manifest()
        self.assertEqual(self.build()['status'], 'ok')
        before = (self.output/'CATALOG.json').read_bytes()
        self.manifest('two', asset_id=first['asset_id'])
        self.assertEqual(self.build()['status'], 'needs_attention')
        self.assertEqual((self.output/'CATALOG.json').read_bytes(), before)

    def test_missing_provenance_and_approval_promotion_are_rejected(self):
        path, asset = self.manifest(source={})
        with self.assertRaisesRegex(ValueError, 'source receipt or evidence'):
            self.collect()
        asset['source'] = {'evidence':[{'path':'one_receipt.json','sha256':m.sha(self.root/'one_receipt.json')}]}
        asset['user_media_approval'] = True
        m.write_json(path, {'schema':'personal_local_asset_import/v1','assets':[asset]})
        with self.assertRaisesRegex(ValueError, 'null user media'):
            self.collect()

    def test_external_and_parent_paths_refused(self):
        for path in ['https://example.invalid/x.png', '../outside.png', '//server/share/x.png']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                m.import_path(path, self.root)

    def test_wrong_hash_and_mime_rejected_before_import(self):
        path, asset = self.manifest()
        asset['image']['sha256'] = '0'*64
        m.write_json(path, {'schema':'personal_local_asset_import/v1','assets':[asset]})
        with self.assertRaisesRegex(ValueError, 'hash_mismatch'):
            self.collect()
        image = self.root/'one.png'
        image.write_bytes(b'\xff\xd8\xff\xe0not-a-png')
        asset['image']['sha256'] = m.sha(image)
        m.write_json(path, {'schema':'personal_local_asset_import/v1','assets':[asset]})
        with self.assertRaisesRegex(ValueError, 'MIME/extension mismatch'):
            self.collect()


if __name__ == '__main__':
    unittest.main()
