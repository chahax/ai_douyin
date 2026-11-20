from copy import deepcopy
import pytest
from test_novel_adaptation_scenes import PLAN,ENT,SOURCE,SCENE
from src.content_factory.novel_adaptation.scenes import initial_state,advance
from src.content_factory.novel_adaptation.repair_context import reconstruct,REPAIR_PROMPT


def case():
    design=deepcopy(PLAN);design['scenes'][0]['fact_ids']=['f']
    design['scenes'].append({'id':'s2','place':'room','duration_seconds':4,'fact_ids':['f']})
    initial=initial_state(design,ENT)
    end=advance(SCENE,design['scenes'][0],design,ENT,['f'],SOURCE,initial)
    files={'s1_FINAL.json':SCENE,'s1_END_STATE.json':end}
    return design,initial,files


def test_middle_scene_gets_executed_prop_owner_and_audio_history():
    design,initial,files=case()
    result,proof=reconstruct(design,ENT,SOURCE,initial,'s2',files.__getitem__,[])
    assert initial['props']['bread1']=='a' and result['props']['bread1']=='b'
    assert result==files['s1_END_STATE.json']
    assert len(proof['replayed'])==1


def test_stale_recorded_state_is_rejected_not_used_as_input():
    design,initial,files=case();files['s1_END_STATE.json']=initial
    with pytest.raises(ValueError,match='repair_predecessor_state_mismatch'):
        reconstruct(design,ENT,SOURCE,initial,'s2',files.__getitem__,[])


def test_missing_predecessor_does_not_fall_back_to_initial():
    design,initial,files=case();del files['s1_FINAL.json']
    with pytest.raises(KeyError):reconstruct(design,ENT,SOURCE,initial,'s2',files.__getitem__,[])


def test_first_scene_uses_initial_without_loading_later_files():
    design,initial,files=case()
    result,proof=reconstruct(design,ENT,SOURCE,initial,'s1',lambda _:pytest.fail('unexpected load'),[])
    assert result==initial and proof['replayed']==[]
    assert '叶东' not in REPAIR_PROMPT and '米袋' not in REPAIR_PROMPT
