from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.reference_repair import invalid_references,apply_reference_repair,checkpoint,adopt_checkpoint
from src.content_factory.novel_adaptation import contracts as c

SCENE={'id':'s','beats':[{'id':'b','audio':[{'text':'keep this'}],'blocking':[{'kind':'gesture'}],
    'requires_information':[{'person':'a','event_id':'valid'},{'person':'a','event_id':'typo'}]}]}
PREVIOUS={'information':{'a':[{'id':'valid','text':'known fact'},{'id':'other','text':'other fact'}]}}
PROPOSAL={'verdict':'corrected','corrections':[{'beat_id':'b','index':1,'event_id':'other','reason':'corresponding information'}]}


def test_only_invalid_event_id_changes_all_other_fields_preserved():
    before=deepcopy(SCENE);after=apply_reference_repair(SCENE,PREVIOUS,PROPOSAL,c.digest(SCENE))
    assert invalid_references(SCENE,PREVIOUS)[0]['index']==1
    after['beats'][0]['requires_information'][1]['event_id']='typo'
    assert after==before and SCENE==before


@pytest.mark.parametrize('mode',['valid_index','unknown','drop','duplicate','uncertain','new_field'])
def test_out_of_scope_or_unsupported_repair_rejected(mode):
    p=deepcopy(PROPOSAL)
    if mode=='valid_index':p['corrections'][0]['index']=0
    if mode=='unknown':p['corrections'][0]['event_id']='invented'
    if mode=='drop':p['corrections']=[]
    if mode=='duplicate':p['corrections']*=2
    if mode=='uncertain':p['verdict']='uncertain'
    if mode=='new_field':p['corrections'][0]['person']='b'
    with pytest.raises((ValueError,c.ContractError)):apply_reference_repair(SCENE,PREVIOUS,p,c.digest(SCENE))


@pytest.mark.parametrize('field',['scene','source','design','previous'])
def test_checkpoint_rejects_any_changed_input(field):
    scene=deepcopy(SCENE);source={'v':1};design={'v':2};previous=deepcopy(PREVIOUS)
    entry=checkpoint(scene,source,design,previous)
    assert adopt_checkpoint(entry,source,design,previous)==scene
    if field=='scene':entry['scene']['id']='different'
    else:{'source':source,'design':design,'previous':previous}[field]['changed']=True
    with pytest.raises(ValueError,match='stale_native'):adopt_checkpoint(entry,source,design,previous)
