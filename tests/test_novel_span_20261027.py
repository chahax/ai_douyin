import sys,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import novel_span_patch_20261027 as m
MAT={'facts':[{'statement':'他没说话，大家都认同了。','source_ids':['P1'],'mode':'actual'},{'statement':'另一条不变。','source_ids':['P1'],'mode':'actual'}]}
S=[{'id':'P1','text':'他没说话，大家暂时听从安排。','chapter':9}]
class Tests(unittest.TestCase):
 def test_only_selected_span_changes(self):
  ts=m.targets(MAT,['F001-C02']);e={'edits':[{'target_id':'F001-C02','replacement_text':'大家暂时听从安排。','source_ids':['P1']}]};new,_=m.apply_spans(MAT,ts,e,S)
  self.assertEqual(new['facts'][0]['statement'],'他没说话，大家暂时听从安排。');self.assertEqual(new['facts'][1],MAT['facts'][1]);self.assertEqual(MAT['facts'][0]['statement'],'他没说话，大家都认同了。')
 def test_stale_sha_rejected(self):
  ts=m.targets(MAT,['F001-C02']);modified=copy.deepcopy(MAT);modified['facts'][0]['statement']='他发言了，大家都认同了。'
  with self.assertRaisesRegex(ValueError,'stale'):m.apply_spans(modified,ts,{'edits':[{'target_id':'F001-C02','replacement_text':'大家听从安排。','source_ids':['P1']}]},S)
 def test_expansion_not_silently_accepted(self):
  with self.assertRaisesRegex(ValueError,'expansion'):m.apply_spans(MAT,m.targets(MAT,['F001-C02']),{'edits':[{'target_id':'F001-C02','replacement_text':'他突然说话。'*50,'source_ids':['P1']}]},S)
 def test_unselected_target_rejected(self):
  with self.assertRaisesRegex(ValueError,'scope'):m.apply_spans(MAT,m.targets(MAT,['F001-C02']),{'edits':[{'target_id':'F002-C01','replacement_text':'篡改','source_ids':['P1']}]},S)
 def test_two_targets_keep_middle(self):
  t=m.targets(MAT,['F001-C01','F002-C01']);e={'edits':[{'target_id':'F001-C01','replacement_text':'他保持沉默，','source_ids':['P1']},{'target_id':'F002-C01','replacement_text':'另一句。','source_ids':['P1']}]};v,_=m.apply_spans(MAT,t,e,S);self.assertEqual(v['facts'][0]['statement'],'他保持沉默，大家都认同了。')
if __name__=='__main__':unittest.main()
