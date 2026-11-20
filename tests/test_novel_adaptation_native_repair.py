from copy import deepcopy
import pytest
from scripts.repair_adaptation_native_scene import apply
from src.content_factory.novel_adaptation.contracts import digest


def test_exact_array_envelope_decode_preserves_native_and_rejects_ambiguous_shape():
    from scripts.repair_adaptation_native_scene import decode_blocking_arrays
    raw={'records':{'a':{'blocking':{'item':[{'kind':'gesture'}]}},'b':{'blocking':{'item':[],'extra':True}}}}
    old=deepcopy(raw);out,changed=decode_blocking_arrays(raw)
    assert raw==old and changed==['a'] and out['records']['a']['blocking']==[{'kind':'gesture'}]
    assert out['records']['b']==raw['records']['b']


def test_dialogue_can_move_between_selected_beats_but_cannot_change_or_duplicate():
    line={'kind':'dialogue','speaker':'a','text':'快吃','start':1,'end':2}
    raw={'beats':[{'id':'a','audio':[]},{'id':'b','audio':[line]}]}
    scope={'native_sha256':digest(raw),'preserve_selected_audio_content':True,'records':{'a':{'fields':['audio']},'b':{'fields':['audio']}}}
    moved={'a':{'audio':[line]},'b':{'audio':[]}}
    assert apply(raw,moved,scope)['beats'][0]['audio']==[line]
    moved['b']['audio']=[line]
    with pytest.raises(ValueError,match='audio_content_changed'):apply(raw,moved,scope)


def test_audio_text_patch_preserves_identity_timing_and_unselected_fields():
    raw={'beats':[{'id':'b','audio':[{'speaker':'a','kind':'inner','text':'bad','start':0,'end':2}],
                  'blocking':[{'kind':'move'}]},{'id':'keep','audio':[]}]}
    old=deepcopy(raw);scope={'native_sha256':digest(raw),'records':{'b':{'audio_indexes':[0]}}}
    out=apply(raw,{'b':{'audio_texts':{'0':'correct'}}},scope)
    assert raw==old and out['beats'][1]==raw['beats'][1]
    assert out['beats'][0]['blocking']==raw['beats'][0]['blocking']
    assert out['beats'][0]['audio'][0]=={**raw['beats'][0]['audio'][0],'text':'correct'}
    with pytest.raises(ValueError,match='native_field_scope'):
        apply(raw,{'b':{'audio_texts':{'0':'correct'},'blocking':[]}},scope)
