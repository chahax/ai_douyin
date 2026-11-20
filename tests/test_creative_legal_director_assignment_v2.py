from copy import deepcopy
import pytest
from tests.test_creative_legal_director_performance_v1 import sample
from src.content_factory import creative_legal_director_assignment_v2 as m

def wire(d):
 v=deepcopy(d);v['source_assignments']=[{'source_ref':r,'shot_id':s['shot_id']} for s in v['shots'] for r in s.pop('source_refs')];return v

def test_unique_assignment_preserves_full_direction(sample):
 s,d,p=sample
 assert m.expand(wire(d),s)==d

def test_missing_source_ref_rejected(sample):
 s,d,p=sample;v=wire(d);v['source_assignments'].pop()
 with pytest.raises(Exception):m.expand(v,s)

def test_interleaved_owner_rejected(sample):
 s,d,p=sample;v=wire(d);v['source_assignments'][1]['shot_id']='SH2'
 with pytest.raises(ValueError):m.expand(v,s)

def test_orphan_camera_idea_rejected(sample):
 s,d,p=sample;v=wire(d);v['shots'].append({**v['shots'][0],'shot_id':'unused'})
 with pytest.raises(ValueError,match='orphan'):m.expand(v,s)
