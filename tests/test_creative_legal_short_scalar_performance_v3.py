from copy import deepcopy
import pytest
from jsonschema import ValidationError
from scripts.run_legal_short_director_performance_v3_20261009 import sources
from src.content_factory import creative_legal_short_scalar_performance_v3 as wire

def raw(beat):
 s=sources()['full_script'];p={'beat_id':beat}
 from src.content_factory.creative_legal_short_director_performance_v1 import own_refs
 for ref in own_refs(s,beat):p[wire.key(ref)]={'before_seconds':0,'before_performance':'不占额外时间','active_seconds':6,'active_performance':'源动作/本句非语言表演原文','after_seconds':1.5,'after_performance':'静止反应'}
 return s,p

def test_deterministic_coarse_state_and_model_prose_unchanged():
 s,p=raw('B1');v=wire.expand(p,s,'B1');assert v['end_state']['paper_location']=='table_middle'
 for r in v['rows']:
  assert {k:r[k] for k in p[wire.key(r['source_ref'])]}==p[wire.key(r['source_ref'])]
def test_b4_only_hr_leaves_and_badge_never_moved():
 s,p=raw('B4');v=wire.expand(p,s,'B4');assert v['end_state']['xiaolin_position']=='seated';assert v['end_state']['zhou_position']=='outside_room';assert v['end_state']['badge_location']=='xiaolin_neck'
def test_model_cannot_reintroduce_bad_state_object():
 s,p=raw('B1');p['B1_S01']['state_changes']={'$text':''}
 with pytest.raises(ValidationError):wire.expand(p,s,'B1')
def test_changed_source_cannot_reuse_frozen_state_map():
 s,p=raw('B1');s=deepcopy(s);s['beats'][0]['steps'][0]['text']='changed'
 with pytest.raises(ValueError,match='exact reviewed'):wire.expand(p,s,'B1')
