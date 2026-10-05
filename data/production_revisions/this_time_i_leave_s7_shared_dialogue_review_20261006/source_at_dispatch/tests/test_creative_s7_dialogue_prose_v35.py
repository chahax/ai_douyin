from scripts import run_creative_s7_dialogue_prose_v35 as r

def test_four_same_s7_locals_keep_provenance():
 rows=r.previous.records()
 for i in (1,2,3,4):
  rec=r.previous.latest(f'local_s7_d1_p{i:03}_r');p=r.previous.latest(f'plan_s7_d1_p{i:03}_r');inp=r.physical.build_local_input(r.previous.context(),r.previous.latest('direction_s7_r')['output'],r.previous.local_sources(1,i-1));r.verify_cache_binding(rec,p,inp)
 assert r.previous.local_sources(1,4)[-1]['shot_id']=='SH04'
