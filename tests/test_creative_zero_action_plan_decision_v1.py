from copy import deepcopy
import pytest
from scripts import creative_zero_action_plan_decision_v1 as z
from scripts import run_creative_s7_scalar_performance_v34 as r


def fixture():
 ctx,d=r.direction_source(1);inp=r.physical.build_local_input(ctx,d,r.local_sources(1,4));return r.latest('plan_s7_d1_p005_r'),inp


def test_original_two_dialogue_empty_plan_has_structural_and_real_source_evidence():
 rec,inp=fixture();before=deepcopy(rec['output']);proof=z.build(rec,inp)
 assert proof['plan_sha256']==r.control.digest({'actions':[]}) and rec['output']==before
 r.source.verify_assistant_evidence(inp['context'],proof['evidence'])
 assert len(proof['evidence'])==2 and proof['human_quality_approval'] is False


def test_added_action_or_changed_start_state_or_non_dialogue_source_is_rejected():
 rec,inp=fixture();bad=deepcopy(rec);bad['output']['actions']=[{}]
 with pytest.raises(ValueError):z.build(bad,inp)
 bad=deepcopy(inp);bad['start_state']['C01']['position']='changed'
 with pytest.raises(ValueError):z.build(rec,bad)
 bad=deepcopy(inp);bad['context']['raw_linear_script']['beats'][4]['steps'][0]['kind']='action';rec=deepcopy(rec);rec['request']['input_provenance']['local_input_sha256']=r.control.digest(bad);rec['request']['input_provenance']['raw_script_sha256']=r.control.digest(bad['context']['raw_linear_script'])
 with pytest.raises(Exception):z.build(rec,bad)
