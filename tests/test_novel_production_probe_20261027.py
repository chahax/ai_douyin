import sys,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import novel_production_probe_20261027 as m
SRC=[{'id':'P1','text':'甲说你好。','chapter':1}];FOUND={'people':[{'id':'A'}],'places':[{'id':'ROOM'}]}
def episode():return {'episode':1,'title':'试验','shots':[{'id':f'S{i}','duration_seconds':15,'location_id':'ROOM','timeline':'current','cast':['A'],'opening_positions':'屋内','actions':[{'actor_id':'A','action':'站立'}],'speech':[{'speaker_id':'A','kind':'dialogue','text':'你好。','source_ids':['P1']}],'camera':'中景','ending_state':'屋内','source_ids':['P1']} for i in range(6)]}
class Tests(unittest.TestCase):
 def test_timing_exact(self):self.assertEqual(len(m.validate_episode(episode(),FOUND,SRC,1)['shots']),6)
 def test_duration_does_not_silently_extend(self):
  e=episode();e['shots'][0]['duration_seconds']=14
  with self.assertRaisesRegex(ValueError,'duration_total'):m.validate_episode(e,FOUND,SRC,1)
 def test_dialogue_absent_speaker_rejected(self):
  e=episode();e['shots'][0]['speech'][0]['speaker_id']='B'
  with self.assertRaisesRegex(ValueError,'unknown_speaker'):m.validate_episode(e,FOUND,SRC,1)
 def test_voice_capacity(self):
  e=episode();e['shots'][0]['speech'][0]['text']='话'*61
  with self.assertRaisesRegex(ValueError,'speech_over'):m.validate_episode(e,FOUND,SRC,1)
 def test_local_shot_repair_keeps_others(self):
  e=episode();s=copy.deepcopy(e['shots'][0]);s['camera']='近景';n=m.replace_shots(e,{'shots':[s]},{'S0'},FOUND,SRC)
  self.assertEqual(n['shots'][1:],e['shots'][1:]);self.assertEqual(e['shots'][0]['camera'],'中景')
 def test_outside_shot_scope_rejected(self):
  with self.assertRaisesRegex(ValueError,'repair_scope'):m.replace_shots(episode(),{'shots':[episode()['shots'][1]]},{'S0'},FOUND,SRC)
 def test_review_cannot_skip_shots(self):
  with self.assertRaisesRegex(ValueError,'coverage'):m.check_review({'checked_shot_ids':['S0'],'issues':[]},episode(),SRC)
 def test_echo_unchanged_extra_is_safe(self):
  from novel_production_echo_continue_20261027 import extract_changed_only
  e=episode();raw=copy.deepcopy(e);raw['shots'][0]['camera']='近景';p=extract_changed_only(e,{'shots':raw['shots']},{'S0'});self.assertEqual(len(p['shots']),1)
 def test_echo_changed_extra_rejected(self):
  from novel_production_echo_continue_20261027 import extract_changed_only
  e=episode();raw=copy.deepcopy(e);raw['shots'][1]['camera']='不同'
  with self.assertRaisesRegex(ValueError,'unrequested'):extract_changed_only(e,{'shots':raw['shots']},{'S0'})
 def test_repair_prompt_does_not_require_patch_total_90(self):
  from novel_production_echo_continue_20261027 import REPAIR_PROMPT
  self.assertIn('无需让本次修订列表合计90秒',REPAIR_PROMPT);self.assertNotIn('本集独立总时长恰好90秒',REPAIR_PROMPT)
if __name__=='__main__':unittest.main()
