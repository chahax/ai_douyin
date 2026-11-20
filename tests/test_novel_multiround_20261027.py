import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import novel_multiround_20261027 as m
SRC=[{'id':'CH9-P001','chapter':9,'text':'甲把钱交给乙。'}]
MAT={'facts':[{'statement':'乙把钱交给甲。','source_ids':['CH9-P001'],'mode':'actual'}]}
ISSUE={'fact_id':'F001','kind':'contradiction','reason':'方向反了','evidence':[{'source_id':'CH9-P001','quote':'甲把钱交给乙'}],'repair_instruction':'按原文修正方向'}
REVIEW={'checked_fact_ids':['F001'],'issues':[ISSUE]}
def ruling(decision):return {'rulings':[{'issue_id':'I001','decision':decision,'reason':'核对方向','evidence':[{'source_id':'CH9-P001','quote':'甲把钱交给乙'}]}]}
class Tests(unittest.TestCase):
    def test_real_repair_then_review_same_candidate(self):
        calls=[];saved={};fixed={'facts':[{**MAT['facts'][0],'statement':'甲把钱交给乙。'}]}
        def call(name,prompt,payload,output):
            calls.append(name)
            if name=='REVIEW_0':return REVIEW
            if name=='JUDGE_0':return ruling('upheld')
            if name=='REPAIR_0':self.assertEqual(len(payload['validated_issues']),1);return fixed
            self.assertEqual(payload['candidate_sha256'],m.sha(fixed));return {'checked_fact_ids':['F001'],'issues':[]}
        result=m.drive(SRC,call,lambda n,v:saved.update({n:v}),MAT)
        self.assertEqual(calls,['REVIEW_0','JUDGE_0','REPAIR_0','REVIEW_1']);self.assertEqual(result['rounds'],1);self.assertEqual(MAT['facts'][0]['statement'],'乙把钱交给甲。')
    def test_rejected_issue_not_repaired(self):
        calls=[]
        def call(n,*a):calls.append(n);return REVIEW if n=='REVIEW_0' else ruling('rejected')
        result=m.drive(SRC,call,lambda *a:None,MAT)
        self.assertEqual(result['status'],'review_disagreement');self.assertNotIn('REPAIR_0',calls)
    def test_uncertain_not_repaired(self):
        result=m.drive(SRC,lambda n,*a:REVIEW if n=='REVIEW_0' else ruling('uncertain'),lambda *a:None,MAT)
        self.assertEqual(result['status'],'review_uncertain')
    def test_bad_quote_rejected(self):
        bad={**ISSUE,'evidence':[{'source_id':'CH9-P001','quote':'乙把钱交给甲'}]}
        with self.assertRaisesRegex(ValueError,'evidence_not_exact'):m.validate_review({'checked_fact_ids':['F001'],'issues':[bad]},MAT,SRC)
    def test_coverage_and_unknown_fact(self):
        with self.assertRaisesRegex(ValueError,'review_coverage'):m.validate_review({'checked_fact_ids':[],'issues':[]},MAT,SRC)
        with self.assertRaisesRegex(ValueError,'review_unknown_fact'):m.validate_review({'checked_fact_ids':['F001'],'issues':[{**ISSUE,'fact_id':'F002'}]},MAT,SRC)
    def test_two_repair_limit(self):
        calls=[]
        def call(n,*a):
            calls.append(n)
            if n.startswith('REVIEW'):return REVIEW
            if n.startswith('JUDGE'):return ruling('upheld')
            return MAT
        result=m.drive(SRC,call,lambda *a:None,MAT)
        self.assertEqual(result['status'],'repair_round_limit');self.assertEqual(len(calls),7)
    def test_all_facts_kept_no_thirty_limit(self):
        self.assertEqual(len(m.validate_material({'facts':MAT['facts']*42},SRC)['facts']),42)
    def test_rejected_part_never_sent_for_repair(self):
        review={'checked_fact_ids':['F001'],'issues':[ISSUE,{**ISSUE,'reason':'错误意见'}]};captured=[]
        def call(n,p,payload,o):
            if n=='REVIEW_0':return review
            if n=='JUDGE_0':return {'rulings':[ruling('upheld')['rulings'][0],{**ruling('rejected')['rulings'][0],'issue_id':'I002'}]}
            if n=='REPAIR_0':captured.extend(payload['validated_issues']);return MAT
            return {'checked_fact_ids':['F001'],'issues':[]}
        m.drive(SRC,call,lambda *a:None,MAT);self.assertEqual([x['id'] for x in captured],['I001'])
    def test_known_wrapper_exact_and_material_unmodified(self):
        from novel_multiround_continue_20261027 import parse_native_wrapper
        import json
        native={'model':m.MODEL,'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'result':MAT}),'tool_calls':None}}]}
        self.assertEqual(parse_native_wrapper(native,SRC),MAT)
        native['choices'][0]['message']['content']=json.dumps({'result':MAT,'extra':'ignored?'})
        with self.assertRaisesRegex(ValueError,'exact_dspy_wrapper_required'):parse_native_wrapper(native,SRC)
    def test_length_wrapper_never_adopted(self):
        from novel_multiround_continue_20261027 import parse_native_wrapper
        import json
        native={'model':m.MODEL,'choices':[{'finish_reason':'length','message':{'content':json.dumps({'result':MAT})}}]}
        with self.assertRaises(ValueError):parse_native_wrapper(native,SRC)
    def test_append_state_keeps_prior_snapshot(self):
        from novel_multiround_resume_known_20261027 import AppendSession
        import tempfile,json
        with tempfile.TemporaryDirectory(dir=m.ROOT/'data/qa') as d:
            session=AppendSession(Path(d));session.save();first=(Path(d)/'STATE_001.json').read_bytes()
            session.count=1;session.save()
            self.assertEqual((Path(d)/'STATE_001.json').read_bytes(),first)
            self.assertEqual(json.loads((Path(d)/'STATE_002.json').read_text())['calls'],1)
if __name__=='__main__':unittest.main()
