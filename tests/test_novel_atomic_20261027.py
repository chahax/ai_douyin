import sys,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import novel_atomic_review_20261027 as m
S=[{'id':'CH9-P001','chapter':9,'text':'再不还钱就离开。'}]
F={'id':'F001','statement':'再还钱就离开。','mode':'actual','source_ids':['CH9-P001']}
L=[{'issue_id':'I1','fact_id':'F001','status':'open','finding':'否定漏字','history':[]}]
def row():return {'fact_id':'F001','atoms':[{'span':F['statement'],'subject':'未明示','action':'离开','object':'','negation_condition':'再还钱','information_origin':'叙述','decision':'contradicted','reason':'否定漏字','source_ids':['CH9-P001']}],'obligations':[{'issue_id':'I1','decision':'unresolved','reason':'仍漏字','source_ids':['CH9-P001']}],'replacement':{'statement':S[0]['text'],'mode':'actual','source_ids':['CH9-P001']}}
class Tests(unittest.TestCase):
 def test_partition_cannot_skip_negation(self):
  r=row();r['atoms'][0]['span']='还钱就离开。'
  with self.assertRaisesRegex(ValueError,'partition'):m.validate_batch({'rows':[r]},[F],S,L)
 def test_missing_obligation_fails(self):
  r=row();r['obligations']=[]
  with self.assertRaisesRegex(ValueError,'obligation'):m.validate_batch({'rows':[r]},[F],S,L)
 def test_proposed_fix_does_not_close_issue(self):
  r=row();r['obligations'][0]['decision']='resolved';out=m.update_ledger(L,[r],0)
  self.assertEqual(out[0]['status'],'open');self.assertEqual(len(out),2);self.assertEqual(len(L),1)
 def test_verified_clean_closes_and_keeps_history(self):
  r=row();r['atoms'][0]['decision']='supported';r['replacement']=None;r['obligations'][0]['decision']='resolved'
  out=m.update_ledger(L,[r],1);self.assertEqual(out[0]['status'],'resolved');self.assertEqual(len(out[0]['history']),1)
 def test_unknown_reference_rejected(self):
  r=row();r['atoms'][0]['source_ids']=['BAD']
  with self.assertRaisesRegex(ValueError,'unknown_source'):m.validate_batch({'rows':[r]},[F],S,L)
 def test_bad_atom_requires_proposal(self):
  r=row();r['replacement']=None
  with self.assertRaisesRegex(ValueError,'without_proposal'):m.validate_batch({'rows':[r]},[F],S,L)
 def test_valid_real_error_shape(self):
  self.assertEqual(m.validate_batch({'rows':[row()]},[F],S,L)['rows'][0]['replacement']['statement'],S[0]['text'])
 def test_optional_proposal_does_not_hide_bad_atom(self):
  from novel_atomic_continue_20261027 import normalize
  r=row();del r['replacement'];v=normalize({'rows':[r]})
  with self.assertRaisesRegex(ValueError,'without_proposal'):m.validate_batch(v,[F],S,L)
 def test_native_omission_keeps_original_immutable(self):
  from novel_atomic_continue_20261027 import normalize
  r=row();del r['replacement'];r['atoms'][0]['decision']='supported';original=copy.deepcopy(r)
  v=normalize({'rows':[r]});self.assertIsNone(v['rows'][0]['replacement']);self.assertEqual(r,original)
 def test_alignment_only_restores_punctuation(self):
  from novel_atomic_alignment_20261027 import align
  r=row();r['atoms'][0]['span']=F['statement'][:-1];v=align({'rows':[r]},[F])
  self.assertEqual(v['rows'][0]['atoms'][0]['span'],F['statement']);self.assertEqual(r['atoms'][0]['span'],F['statement'][:-1])
 def test_alignment_never_inserts_missing_negation(self):
  from novel_atomic_alignment_20261027 import align
  f={**F,'statement':'再不还钱就离开。'}
  with self.assertRaisesRegex(ValueError,'changed_atom'):align({'rows':[row()]},[f])
 def test_full_fix_requires_fresh_review_and_resolves_stable_ids(self):
  seen=[];saved={}
  def call(name,prompt,payload,output):
   seen.append(name)
   if name=='CONTENT_CHECK':return {'checks':[{'check_id':x['check_id'],'decision':'supported','reason':'有据且保留','evidence':[{'source_id':'CH9-P001'}]} for x in payload['checks']]}
   r=row()
   if name=='R1_B00':
    self.assertEqual(payload['facts'][0]['statement'],S[0]['text']);self.assertEqual(len(payload['unresolved']),2)
    r['atoms'][0].update(span=S[0]['text'],decision='supported');r['replacement']=None
    r['obligations']=[{'issue_id':x['issue_id'],'decision':'resolved','reason':'已保留不字','source_ids':['CH9-P001']} for x in payload['unresolved']]
   return {'rows':[r]}
  final,ledger,status=m.drive_atomic({'facts':[{k:v for k,v in F.items() if k!='id'}]},S,L,call,lambda n,v:saved.update({n:v}))
  self.assertEqual(seen,['R0_B00','CONTENT_CHECK','R1_B00']);self.assertTrue(all(x['status']=='resolved' for x in ledger));self.assertEqual(status,'machine_pass_pending_primary')
 def test_program_clauses_reconstruct_full_statement(self):
  from novel_atomic_ids_20261027 import clauses
  text='他说“再不还钱，就离开。”；她摇头，没走。'
  self.assertEqual(''.join(x['text'] for x in clauses([{**F,'statement':text}])[0]['clauses']),text)
 def test_clause_ids_cannot_skip_or_duplicate(self):
  from novel_atomic_ids_20261027 import materialize
  r=row();r['atoms'][0].pop('span');r['atoms'][0]['clause_id']='F001-C02'
  with self.assertRaisesRegex(ValueError,'clause_coverage'):materialize({'rows':[r]},[F])
if __name__=='__main__':unittest.main()
