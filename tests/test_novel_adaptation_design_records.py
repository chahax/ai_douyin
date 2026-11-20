import pytest
from scripts.repair_adaptation_design_records import apply


def test_only_selected_fields_change():
    old={'scenes':[{'id':'s','objective':'before','place':'kitchen'},{'id':'other','objective':'keep'}],'recipes':[]}
    scope={'records':{'scenes':{'s':{'fields':['objective']}}}}
    patch={'corrections':[{'group':'scenes','id':'s','changes':{'objective':'after'}}]}
    new=apply(old,patch,scope)
    assert old['scenes'][0]['objective']=='before' and new['scenes'][0]['place']=='kitchen'
    assert new['scenes'][1]==old['scenes'][1]
    patch['corrections'][0]['changes']['place']='elsewhere'
    with pytest.raises(ValueError,match='field_scope'):apply(old,patch,scope)


def test_duplicate_record_cannot_replace_missing_record():
    old={'recipes':[{'id':'a'},{'id':'b'}]};scope={'records':{'recipes':{'a':{'fields':['action']},'b':{'fields':['action']}}}}
    row={'group':'recipes','id':'a','changes':{'action':'cook'}}
    with pytest.raises(ValueError,match='record_scope'):apply(old,{'corrections':[row,row]},scope)
