from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation.repair import apply_proposal

SOURCE={'chapters':[{'index':1,'text':'甲在屋内。\n乙在另一间屋子。'}]}
ENTITY={'id':'a','kind':'character','display_name':'甲','source_ids':['CH1-P001']}
FACT={'id':'f','entity_ids':['a'],'statement':'在屋内','temporal_scope':'current','certainty':'explicit','source_ids':['CH1-P001']}

def fixture():
    banks={'identity':{'entities':[deepcopy(ENTITY)]},'character':{'facts':[deepcopy(FACT)]}}
    replacement={**FACT,'statement':'甲在屋内'}
    proposal={'replacements':[{'bank':'character','id':'f','record':replacement}],
      'additions':[{'id':'room2','kind':'place','display_name':'另一间屋子','source_ids':['CH1-P002']}]}
    return banks,proposal

def test_scoped_repair_and_addition_preserve_original():
    banks,p=fixture();before=deepcopy(banks)
    after=apply_proposal(banks,p,{'character':{'f':'明确主体'}},{'room2'},SOURCE)
    assert banks==before
    assert after['identity']['entities'][0]==ENTITY
    assert after['character']['facts'][0]['statement']=='甲在屋内'

@pytest.mark.parametrize('mode',['missing','duplicate','wrong_identity','extra_addition'])
def test_repair_cannot_expand_or_omit_authorized_scope(mode):
    banks,p=fixture()
    if mode=='missing':p['replacements']=[]
    if mode=='duplicate':p['replacements']*=2
    if mode=='wrong_identity':p['replacements'][0]['record']['id']='different'
    if mode=='extra_addition':p['additions'].append({**ENTITY,'id':'b'})
    with pytest.raises((ValueError,c.ContractError)):
        apply_proposal(banks,p,{'character':{'f':'明确主体'}},{'room2'},SOURCE)
