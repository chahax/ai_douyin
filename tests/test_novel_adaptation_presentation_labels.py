from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.presentation import apply_labels,display_names
from src.content_factory.novel_adaptation import contracts as c
from test_novel_adaptation_scenes import SOURCE,ENT,PLAN


def test_prop_display_label_does_not_change_identity_or_registry():
    old=deepcopy(PLAN);proposal={'labels':[{'id':'bread1','label':'一块面包','source_ids':['CH1-P001']}]}
    updated=apply_labels(PLAN,proposal,['bread1'],SOURCE,c.digest(PLAN))
    assert PLAN==old and updated['props']==old['props'] and updated['initial_locations']==old['initial_locations']
    assert display_names(updated,ENT)['bread1']=='一块面包'


@pytest.mark.parametrize('mode',['actor','wrong_source','duplicate','missing','stale'])
def test_label_scope_and_source_are_bound(mode):
    proposal={'labels':[{'id':'bread1','label':'面包','source_ids':['CH1-P001']}]};sha=c.digest(PLAN)
    if mode=='actor':proposal['labels'][0]['id']='a'
    if mode=='wrong_source':proposal['labels'][0]['source_ids']=['made-up']
    if mode=='duplicate':proposal['labels']*=2
    if mode=='missing':proposal['labels']=[]
    if mode=='stale':sha='wrong'
    with pytest.raises((ValueError,c.ContractError)):apply_labels(PLAN,proposal,['bread1'],SOURCE,sha)
