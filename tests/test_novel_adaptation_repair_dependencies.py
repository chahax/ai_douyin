from copy import deepcopy
from src.content_factory.novel_adaptation.repair_dependencies import expand_transform_shots


def test_transform_shift_includes_dependent_shot_but_not_audio_or_unselected_fields():
    scene={'beats':[{'id':'before','blocking':[],'shot':{'subjects':['meal']}},
                    {'id':'after','blocking':[{'kind':'transform','recipe':'cook'}],'shot':{'subjects':['meal']}},
                    {'id':'untouched','blocking':[],'shot':{'subjects':['meal']}}]}
    scope={'records':{'before':{'fields':['blocking']},'after':{'fields':['blocking']}}}
    old=deepcopy(scope)
    result,changes=expand_transform_shots(scene,scope,{'recipes':[{'id':'cook','outputs':['meal']}]})
    assert scope==old and len(changes)==2
    assert result['records']=={'before':{'fields':['blocking','shot']},'after':{'fields':['blocking','shot']}}


def test_unrelated_shot_is_not_expanded():
    scene={'beats':[{'id':'a','blocking':[{'kind':'transform','recipe':'cook'}],'shot':{'subjects':['person']}}]}
    scope={'records':{'a':{'fields':['blocking']}}}
    assert expand_transform_shots(scene,scope,{'recipes':[{'id':'cook','outputs':['meal']} ]})==(scope,[])


def test_audio_array_replacement_includes_actions_bound_to_that_audio():
    scene={'beats':[{'id':'a','audio':[{'text':'remove'}],'blocking':[{'kind':'gesture','phase':'after_audio','after_audio_index':0}], 'shot':{'subjects':['person']}}]}
    scope={'records':{'a':{'fields':['audio','source_ids','end']}}}
    out,changes=expand_transform_shots(scene,scope,{'recipes':[]})
    assert out['records']['a']['fields']==['audio','source_ids','end','blocking']
    assert changes[0]['added_field']=='blocking'
