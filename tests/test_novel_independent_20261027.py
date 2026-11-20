import sys,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import novel_independent_review_20261027 as m
F=[{'id':'F001','statement':'他点头。','mode':'actual','source_ids':['P1']}]
S=[{'id':'P1','chapter':9,'text':'他点头。'}]
def review():return {'rows':[{'fact_id':'F001','findings':[{'clause_id':'F001-C01','decision':'supported','source_ids':['P1'],'source_meaning':'点头','candidate_extra_claim':'','alternative_consistent_with_source':'','reason':'直接写出'}]}]}
class Tests(unittest.TestCase):
 def test_old_diagnostic_not_in_payload(self):
  p=m.payload_for(S,F);self.assertEqual(set(p),{'complete_source','current_facts','clauses','candidate_sha256'});self.assertNotIn('unresolved',p)
 def test_review_schema_has_no_edit_branch(self):
  s=json.dumps(m.CurrentReview.model_json_schema());self.assertNotIn('replacement',s)
 def test_empty_edit_not_accepted(self):
  with self.assertRaises(Exception):m.validate_edits({'edits':[{'fact_id':'F001','replacement':{}}]},['F001'],S)
 def test_unspecified_fact_cannot_be_edited(self):
  with self.assertRaisesRegex(ValueError,'edit_scope'):m.validate_edits({'edits':[{'fact_id':'F002','replacement':{k:v for k,v in F[0].items() if k!='id'}}]},['F001'],S)
 def test_old_error_not_reopened_when_current_passes(self):
  old=[{'issue_id':'OLD','fact_id':'F001','status':'open','finding':'旧稿摇头'}];r=m.reconcile(old,review(),'current')
  self.assertEqual(r[0]['status'],'resolved_by_current_review');self.assertEqual(old[0]['status'],'open')
 def test_unreviewed_issue_cannot_close(self):
  old=[{'issue_id':'OLD','fact_id':'F002','status':'open'}];self.assertEqual(m.reconcile(old,review(),'sha')[0]['status'],'open')
 def test_unknown_evidence_fails(self):
  r=review();r['rows'][0]['findings'][0]['source_ids']=['bad']
  with self.assertRaisesRegex(ValueError,'unknown_source'):m.validate_review(r,F,S)
 def test_insufficient_needs_specific_difference(self):
  r=review();r['rows'][0]['findings'][0]['decision']='insufficient'
  with self.assertRaisesRegex(ValueError,'specific_difference'):m.validate_review(r,F,S)
 def test_expected_not_sent(self):
  source,facts,expected=m.holdout();p=m.payload_for(source,facts);self.assertEqual(len(facts),8);self.assertNotIn('expected',json.dumps(p))
if __name__=='__main__':unittest.main()
