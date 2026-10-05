from scripts import run_creative_s7_prose_binding_v36 as r

def test_real_current_binding_all_four_and_empty_plan():
 ctx,d=r.previous.context(),r.previous.latest('direction_s7_r')['output']
 ls=r.previous.local_sources(1,4)
 assert len(ls)==4
 plan=r.previous.latest('plan_s7_d1_p005_r');assert plan['output']=={'actions':[]}
 assert (r.previous.decision_root(plan)/'EVENT_PLAN_SOURCE_DECISION_call224.json').exists()
 assert (r.previous.ROOT/'DIRECTION_SOURCE_DECISION.json').exists()
 assert r.director_base.direction_wire and r.window_base.supported_plan_schema
