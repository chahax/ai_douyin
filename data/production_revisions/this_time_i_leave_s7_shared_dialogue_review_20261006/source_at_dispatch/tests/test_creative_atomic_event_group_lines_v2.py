import pytest
from scripts import run_creative_s7_group_translation_v41 as r
from scripts.creative_atomic_event_group_lines_v2 import decode

def test_indices_program_assigned_original_values_preserved():
 c,d=r.previous.direction_source(1);inp=r.physical.build_local_input(c,d,r.previous.local_sources(1,6));text='A|C02|gaze|-|at_P05|-|原看向目标\nA|C02|hold|-|-|-|原右手写一笔'
 doc=decode(text,inp);slots=r.split.slots(doc);assert [x['slot'] for x in slots]==['A0E0','A0E1'];assert slots[1]['intent']=='原右手写一笔';assert slots[1]['operation'] is None
 for bad in (text.replace('A|','B|',1),text.replace('hold|-|-','hold|P07|right_hand')):
  with pytest.raises(ValueError):decode(bad,inp)
 assert r.AUTH['automatic_retry'] is False
