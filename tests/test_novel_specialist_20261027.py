import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import novel_specialist_review_20261027 as m
SOURCE=[{'id':'CH9-P001','chapter':9,'text':'甲把钱交给乙。'},{'id':'CH8-P001','chapter':8,'text':'昨天领工资。'}]
OLD={'statement':'乙把钱交给甲。','mode':'actual','source_ids':['CH9-P001']}
NEW={**OLD,'statement':'甲把钱交给乙。'}
E=[{'source_id':'CH9-P001','quote':'甲把钱交给乙'}]
PATCH={'id':'actors-001','role':'actors','fact_id':'F001','bad_span':'乙把钱交给甲','reason':'方向','evidence':E,'replacements':[NEW]}
MAT={'facts':[OLD,{**OLD,'statement':'未受影响内容'}]}
def checks(tasks):return {'checks':[{'check_id':t['check_id'],'decision':'supported','reason':'原文支持','evidence':E} for t in tasks]}
class TestSpecialists(unittest.TestCase):
    def test_literal_span(self):
        p={k:v for k,v in PATCH.items() if k not in ('id','role')};p['bad_span']='改写过的片段'
        with self.assertRaisesRegex(ValueError,'span_not_literal'):m.validate_audit({'checked_fact_ids':['F001','F002'],'patches':[p]},MAT,SOURCE)
    def test_target_cannot_delete(self):
        p={k:v for k,v in PATCH.items() if k not in ('id','role')};p['replacements']=[]
        with self.assertRaisesRegex(ValueError,'cannot_be_deleted'):m.validate_audit({'checked_fact_ids':['F001','F002'],'patches':[p]},MAT,SOURCE)
    def test_only_confirmed_patch_others_exact(self):
        tasks=m.tasks_for([PATCH],MAT);new,log=m.apply_patches(MAT,[PATCH],tasks,checks(tasks))
        self.assertEqual(new['facts'][0],NEW);self.assertEqual(new['facts'][1],MAT['facts'][1]);self.assertEqual(MAT['facts'][0],OLD)
    def test_one_bad_atom_blocks_entire_patch(self):
        patch={**PATCH,'replacements':[NEW,{**NEW,'statement':'原文未写的细节'}]};tasks=m.tasks_for([patch],MAT);c=checks(tasks);c['checks'][-1]['decision']='rejected'
        new,log=m.apply_patches(MAT,[patch],tasks,c);self.assertEqual(new,MAT);self.assertFalse(log['applied'])
    def test_missing_check_denies_patch(self):
        tasks=m.tasks_for([PATCH],MAT);c=checks(tasks);c['checks'].pop()
        with self.assertRaisesRegex(ValueError,'check_coverage'):m.validate_checks(c,tasks,SOURCE)
        self.assertEqual(m.apply_patches(MAT,[PATCH],tasks,c)[0],MAT)
    def test_conflict_deferred_not_combined(self):
        other={**PATCH,'id':'logic-001','replacements':[{**NEW,'statement':'另一版本'}]};tasks=m.tasks_for([PATCH,other],MAT);new,log=m.apply_patches(MAT,[PATCH,other],tasks,checks(tasks))
        self.assertEqual(new['facts'][0],NEW);self.assertEqual(log['deferred'],['logic-001'])
    def test_all_three_rescan_after_patch(self):
        names=[];saves={}
        def call(n,p,payload,o):
            names.append(n)
            if n.endswith('judge'):return checks(payload['checks'])
            patches=[{k:v for k,v in PATCH.items() if k not in ('id','role')}] if n=='R0_actors' else []
            return {'checked_fact_ids':['F001','F002'],'patches':patches}
        final,status,rounds=m.drive(MAT,SOURCE,call,lambda n,v:saves.update({n:v}))
        self.assertEqual(names,['R0_actors','R0_logic','R0_continuity','R0_judge','R1_actors','R1_logic','R1_continuity']);self.assertEqual(rounds,1);self.assertEqual(final['facts'][0],NEW)
    def test_neighbor_moved_not_lost(self):
        material={'facts':[OLD,{'statement':'昨天领工资。','mode':'actual','source_ids':['CH8-P001']}]}
        patch={**PATCH,'fact_id':'F002','bad_span':'昨天领工资','replacements':[]};tasks=m.tasks_for([patch],material)
        new,log=m.apply_patches(material,[patch],tasks,checks(tasks));self.assertEqual(len(new['facts']),1);self.assertEqual(log['moved_to_context'][0]['statement'],'昨天领工资。')
    def test_persistent_states_append_only(self):
        with tempfile.TemporaryDirectory(dir=m.ROOT/'data/qa') as d:
            g=m.AppendGateway(Path(d));g.save();first=(Path(d)/'STATE_001.json').read_bytes();g.pending=1;g.save();self.assertEqual(first,(Path(d)/'STATE_001.json').read_bytes())
    def test_program_grounding_not_model_quote_edit(self):
        import novel_specialist_v2_20261027 as v2
        raw={'patches':[{'evidence':[{'source_id':'CH9-P001'}]}]};grounded=v2.ground(raw,SOURCE,'patches')
        self.assertNotIn('quote',raw['patches'][0]['evidence'][0]);self.assertEqual(grounded['patches'][0]['evidence'][0]['quote'],SOURCE[0]['text'])
        with self.assertRaisesRegex(ValueError,'unknown_source_id'):v2.ground({'patches':[{'evidence':[{'source_id':'CH9-P999'}]}]},SOURCE,'patches')
    def test_content_check_never_receives_diagnostic_prose(self):
        import novel_specialist_v2_20261027 as v2
        import json
        tasks=v2.content_tasks([{**PATCH,'reason':'LEAKED_REVIEWER_CLAIM'}],MAT)
        self.assertNotIn('LEAKED_REVIEWER_CLAIM',json.dumps(tasks));self.assertEqual({t['kind'] for t in tasks},{'retention','replacement'})
    def test_content_uncertain_still_cannot_apply(self):
        import novel_specialist_v2_20261027 as v2
        tasks=v2.content_tasks([PATCH],MAT);c=checks(tasks);c['checks'][-1]['decision']='uncertain'
        self.assertEqual(m.apply_patches(MAT,[PATCH],tasks,c)[0],MAT)
if __name__=='__main__':unittest.main()
