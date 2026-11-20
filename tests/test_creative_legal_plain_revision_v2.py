import json
import unittest
from pathlib import Path
from copy import deepcopy
from scripts.run_legal_plain_script_revision_v2_20261009 import SCRIPT_SOURCE, FEEDBACK
from scripts.creative_resume_dispatch_v3 import read
from src.content_factory.creative_legal_plain_revision_v2 import build_wire, validate_plain_dialogue
from src.content_factory.creative_complete_review_ids_v1 import schema

class PlainRevisionTests(unittest.TestCase):
    def request(self, stage='draft', script=None):
        packet, facts, graph, scope, direction, confirmation = [read(SCRIPT_SOURCE/n) for n in ('SOURCE_PACKET.json','LEGAL_CONTEXT.json','GRAPH_PACKET.json','CONTENT_SCOPE.json','DIRECTION.json','HUMAN_DIRECTION_CONFIRMATION.json')]
        return build_wire(packet,facts,graph,scope,stage,now='2026-10-09T05:45:00+00:00',direction=direction,confirmation=confirmation,feedback=FEEDBACK,script=script)
    def test_full_reference_and_six_criteria_reach_request(self):
        context=json.loads(self.request()['messages'][1]['content'])
        packet=read(SCRIPT_SOURCE/'SOURCE_PACKET.json')
        self.assertEqual(context['reference_fulltext'],packet['inputs']['reference_fulltext'])
        self.assertEqual(len(context['writer_expression_criteria']),6)
        self.assertEqual(context['human_revision_request'],FEEDBACK)
    def test_old_duration_and_story_goal_do_not_remain_active(self):
        context=json.loads(self.request()['messages'][1]['content'])
        self.assertNotIn('核对',context['emotional_brief']['audience_goal'])
        self.assertNotIn('40–90',str(context['emotional_brief']))
        self.assertNotIn('社保分项与',str(context['emotional_brief']))
        self.assertIn('仅周姐离开',context['confirmed_case_facts']['ending'])
    def test_rejected_wording_never_silently_patched(self):
        script={'beats':[{'id':'B1','steps':[{'kind':'dialogue','text':'先核对。'}]}]}
        original=deepcopy(script)
        with self.assertRaises(ValueError):validate_plain_dialogue(script)
        self.assertEqual(script,original)
    def test_review_contains_exact_whole_current_script(self):
        script=read(SCRIPT_SOURCE/'DRAFT_r8.json')
        wire=self.request('review',script)
        context=json.loads(wire['messages'][1]['content'])
        self.assertEqual(context['script'],script)
        self.assertEqual(wire['structured_schema'],schema(script,context['emotional_brief']))
        self.assertEqual(wire['model'],'deepseek-flash')
    def test_models_and_source_are_unchanged(self):
        path=SCRIPT_SOURCE/'DIRECTION.json'
        original=path.read_bytes()
        req=self.request()
        self.assertEqual(req['model'],'MiniMax-M3')
        self.assertEqual(req['parameters'],{'max_completion_tokens':8000,'temperature':.4,'thinking':'disabled'})
        self.assertEqual(path.read_bytes(),original)
        self.assertFalse(req['input_provenance']['human_new_script_adopted'])
if __name__=='__main__':unittest.main()
