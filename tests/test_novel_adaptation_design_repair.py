from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation import design_repair as dr,contracts as c
from test_novel_adaptation_workflow import DESIGN,PACKET,SOURCE


def proposal():
    return {'scenes':deepcopy(DESIGN['scenes']),'new_places':[],'new_props':[],
            'planned_props':[],'container_actions':True,'recipes':[]}


def test_design_repair_cannot_rewrite_assets_world_or_opening():
    old=deepcopy(DESIGN);p=proposal()
    p['scenes'][0]['objective']='new staging'
    out=dr.apply(DESIGN,p,PACKET,SOURCE,c.digest(DESIGN))
    assert DESIGN==old
    for key in DESIGN:
        if key!='scenes':assert out[key]==DESIGN[key]
    assert out['scenes'][0]['objective']=='new staging'


def test_repair_rejects_asset_collision_and_invented_source():
    p=proposal();p['new_props']=[deepcopy(DESIGN['props'][0])]
    with pytest.raises(ValueError,match='asset_redefinition'):dr.apply(DESIGN,p,PACKET,SOURCE,c.digest(DESIGN))
    p=proposal();p['recipes']=[{'id':'r','action':'cook','inputs':['bread'],'outputs':['dish'],
         'retained_inputs':[],'source_ids':['CH99-P001']}]
    with pytest.raises(ValueError,match='recipe_source_unknown'):dr.apply(DESIGN,p,PACKET,SOURCE,c.digest(DESIGN))


def test_unselected_field_is_not_writable():
    p=proposal();p['world_fact_ids']=[]
    with pytest.raises(c.ContractError):dr.apply(DESIGN,p,PACKET,SOURCE,c.digest(DESIGN))


def test_missing_planned_instances_are_reported_together():
    p=proposal();p['planned_props']=['portion1','portion2']
    with pytest.raises(ValueError,match='planned_props:portion1,planned_props:portion2'):
        dr.apply(DESIGN,p,PACKET,SOURCE,c.digest(DESIGN))
