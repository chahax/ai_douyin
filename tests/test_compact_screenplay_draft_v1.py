"""Offline schema/renderer design evidence, not production candidate creation."""
from copy import deepcopy
import unittest
from src.content_factory import creative_compact_screenplay_draft_v1 as m
from scripts import preview_compact_screenplay_draft_v1 as design


def fixture():
    ids=[f'S{i:02}' for i in range(1,11)]
    text='# 世界框架\nsynthetic fixture only\n# 连续时间总表\nfixture\n# 分段剧本\n'
    text+='\n'.join('## '+sid+'\n'+'synthetic test fixture; not generated screenplay. '*2 for sid in ids)
    return {'schema':m.VERSION+'/native_text','title':'test fixture only','total_seconds':150,
        'timeline':[{'segment_id':sid,'start_seconds':i*15,'end_seconds':(i+1)*15} for i,sid in enumerate(ids)],
        'screenplay_markdown':text}


class CompactDraftTests(unittest.TestCase):
    def test_native_string_renderer_preserves_exact_bytes_not_rebuilds(self):
        document=fixture();before=deepcopy(document)
        self.assertEqual(m.render_native_markdown(document),document['screenplay_markdown'])
        self.assertEqual(document,before)
        result=m.validate_necessary(document)
        self.assertTrue(result['valid']);self.assertTrue(result['full_semantic_review_still_required'])
        self.assertFalse(result['creative_quality_passed'])

    def test_missing_full_text_sections_and_numeric_timeline_gap_fail(self):
        document=fixture();document['screenplay_markdown']=document['screenplay_markdown'].replace('## S10','## S99')
        self.assertFalse(m.validate_necessary(document)['valid'])
        document=fixture();document['timeline'][1]['start_seconds']=16
        self.assertFalse(m.validate_necessary(document)['valid'])
        document=fixture();document['timeline'][0]['start_seconds']='0'
        with self.assertRaises(Exception):m.validate_necessary(document)

    def test_single_prose_content_field_plus_small_metadata(self):
        schema=m.output_schema()
        self.assertEqual(set(schema['properties']),{'schema','title','total_seconds','timeline','screenplay_markdown'})
        self.assertNotIn('world_sha256',str(schema));self.assertNotIn('start_state',str(schema))

    def test_actual_draft_is_unapproved_zero_dispatch_and_omits_failed_fulltexts(self):
        value=design.design_preview()
        self.assertEqual(value['provider_calls'],0);self.assertEqual(value['new_claims'],0)
        self.assertFalse(value['production_dispatch_enabled'])
        self.assertEqual(value['new_creative_candidates'],0)
        self.assertEqual(value['request_size_evidence']['full_failed_history_documents_in_new_request'],0)
        self.assertLess(value['request_size_evidence']['compact_expected_wire_utf8_bytes'],value['request_size_evidence']['old640_actual_request_body_bytes']/4)


if __name__=='__main__':unittest.main()
