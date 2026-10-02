import copy
import pytest
from scripts.compile_cohort_screenplay import compile_body

def candidate():
    return {'title':'synthetic','characters':[{'id':'L','name':'房东','goal':'L goal'},{'id':'T','name':'租客','goal':'T goal'}],
        'space':'synthetic space','props':{'P1':'synthetic phone'},'payment':{'payer':'L','payee':'T','amount':'两千','method':'转账'},
        'scenes':[{'id':f'S{i}','framing':'synthetic','action':'synthetic',
            'dialogue':[{'speaker':'T','text':'甲乙丙丁戊'*5,'delivery':'synthetic'}],
            'after_action':'synthetic','after_action_seconds':.75,'end_state':{'P1':'T'},'result':'synthetic'} for i in range(8)],
        'ending':'synthetic','reference_usage':[]}

def test_timing_exactly_covers_45_without_model_timestamps():
    body,timing=compile_body(candidate(),'short')
    assert timing['characters']==200 and timing['action_seconds']==6
    assert 4.3<=timing['rate']<=5.7
    assert timing['dialogue'][-1]['end']+.75==45
    assert '租客（T goal）' in body

def test_wrong_refund_direction_and_missing_prop_state_rejected():
    wrong=candidate();wrong['payment']['payer']='T'
    with pytest.raises(ValueError,match='Refund'):compile_body(wrong,'short')
    wrong=candidate();wrong['scenes'][0]['end_state']={}
    with pytest.raises(ValueError,match='prop'):compile_body(wrong,'short')

def test_short_material_cannot_be_stretched_to_180():
    with pytest.raises(ValueError,match='cannot fit'):compile_body(candidate(),'long')
