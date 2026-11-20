import pytest
from src.content_factory.novel_adaptation import contracts as c
from src.content_factory.novel_adaptation.patching import mechanical_repair_scope,apply_field_patches

SCENE={'beats':[{'id':'exit','action':'两个孩子跑了出去。','audio':[],'moves':[]},
    {'id':'alone','action':'苏墨独自回到床边。','audio':[],'present':['su']}]}

def test_presence_error_cannot_rewrite_story_to_keep_children_in_room():
    issue=c.Issue('continuity','/beats/1','presence_mismatch','expected children also')
    scope=mechanical_repair_scope(SCENE,[issue])
    assert set(scope)=={'exit','alone'}
    with pytest.raises(ValueError,match='not_owned'):
        apply_field_patches(SCENE,[{'id':'alone','changes':{'action':'孩子跑到门口又刹住脚。'}}],scope,c.digest(SCENE))
    out=apply_field_patches(SCENE,[{'id':'exit','changes':{'moves':[{'person':'child','origin':'room','destination':'other','action':'跑出去'}]}}],scope,c.digest(SCENE))
    assert out['beats'][0]['action']==SCENE['beats'][0]['action']
    assert out['beats'][1]==SCENE['beats'][1]

def test_speech_speed_repair_cannot_change_speaker_or_drop_line():
    scene={'beats':[{'id':'b','action':'说话','audio':[{'speaker':'child','kind':'dialogue','text':'哥哥给你钱','start':0,'end':1}]}]}
    scope=mechanical_repair_scope(scene,[c.Issue('timing','/beats/0','speech_too_fast','')])
    with pytest.raises(ValueError,match='identity_or_count'):
        apply_field_patches(scene,[{'id':'b','changes':{'audio':[]}}],scope,c.digest(scene))

def test_only_source_reviewed_audio_index_can_change_kind_not_speaker_or_count():
    from copy import deepcopy
    scene={'beats':[{'id':'b','audio':[{'speaker':'child','kind':'inner','text':'不行。','start':0,'end':2},
        {'speaker':'brother','kind':'dialogue','text':'好。','start':2,'end':3}]}]}
    changes=deepcopy(scene['beats'][0]['audio']);changes[0]['kind']='dialogue'
    proposal=[{'id':'b','changes':{'audio':changes}}]
    permission={'b':{'audio'}}
    with pytest.raises(ValueError):
        apply_field_patches(scene,proposal,permission,c.digest(scene))
    allowed={'b':{'0':['dialogue']}}
    out=apply_field_patches(scene,proposal,permission,c.digest(scene),audio_kind_permissions=allowed)
    assert out['beats'][0]['audio'][0]['kind']=='dialogue'
    changes[1]['kind']='inner'
    with pytest.raises(ValueError):
        apply_field_patches(scene,proposal,permission,c.digest(scene),audio_kind_permissions=allowed)
    changes[1]['kind']='dialogue';changes[0]['speaker']='brother'
    with pytest.raises(ValueError):
        apply_field_patches(scene,proposal,permission,c.digest(scene),audio_kind_permissions=allowed)

def test_kind_only_patch_rejects_same_speaker_line_swap_and_timing_change():
    from copy import deepcopy
    scene={'beats':[{'id':'b','audio':[
        {'speaker':'child','kind':'dialogue','text':'怎么办？','start':0,'end':2},
        {'speaker':'child','kind':'inner','text':'不行。','start':2,'end':4}]}]}
    lines=deepcopy(scene['beats'][0]['audio']);lines[1]['kind']='dialogue'
    permissions={'b':{'audio'}};kinds={'b':{'1':['dialogue']}}
    for bad in ([lines[1],lines[0]],[{**lines[0],'start':0.1},lines[1]]):
        with pytest.raises(ValueError,match='unowned_content'):
            apply_field_patches(scene,[{'id':'b','changes':{'audio':bad}}],permissions,c.digest(scene),audio_kind_permissions=kinds)

def test_kind_submission_cannot_reorder_or_rewrite_audio():
    from copy import deepcopy
    from src.content_factory.novel_adaptation.patching import apply_audio_kinds
    scene={'beats':[{'id':'b','audio':[{'kind':'inner','speaker':'kid','text':'不行','start':0,'end':2}]}]}
    before=deepcopy(scene)
    out=apply_audio_kinds(scene,[{'beat_id':'b','index':0,'kind':'dialogue'}],{'b':{'0':['dialogue']}},c.digest(scene))
    expected=deepcopy(scene);expected['beats'][0]['audio'][0]['kind']='dialogue'
    assert out==expected and scene==before
    with pytest.raises(c.ContractError):
        apply_audio_kinds(scene,[{'beat_id':'b','index':0,'kind':'dialogue','text':'改了'}],{'b':{'0':['dialogue']}},c.digest(scene))

def test_visual_patch_cannot_change_source_facts_or_unselected_design():
    from src.content_factory.novel_adaptation.patching import apply_visual_patches
    from copy import deepcopy
    design={'world_framework':'原文已审核事实','visual_design':[
        {'aspect':'灯光','basis':'adaptation_design','description':'油灯'},
        {'aspect':'布局','basis':'adaptation_design','description':'窄床'}]}
    original=deepcopy(design)
    result=apply_visual_patches(design,[{'index':0,'description':'白炽吊灯'}],[0],c.digest(design))
    assert result['world_framework']==design['world_framework']
    assert result['visual_design'][1]==design['visual_design'][1]
    assert design==original
    with pytest.raises(c.ContractError):
        apply_visual_patches(design,[{'index':1,'description':'大床'}],[0],c.digest(design))
    with pytest.raises(c.ContractError):
        apply_visual_patches(design,[{'index':0,'description':'新灯','world_framework':'新增事实'}],[0],c.digest(design))

def test_text_only_patch_preserves_audio_identity_order_timing_and_other_text():
    from copy import deepcopy
    from src.content_factory.novel_adaptation.patching import apply_audio_texts
    scene={'beats':[{'id':'b','audio':[
        {'kind':'inner','speaker':'su','text':'我打他','start':0,'end':2},
        {'kind':'dialogue','speaker':'kid','text':'爸爸','start':2,'end':3}]}]}
    original=deepcopy(scene);permission={'b':[0]}
    out=apply_audio_texts(scene,[{'beat_id':'b','index':0,'text':'原主打他'}],permission,c.digest(scene))
    expected=deepcopy(scene);expected['beats'][0]['audio'][0]['text']='原主打他'
    assert out==expected and scene==original
    with pytest.raises(c.ContractError):
        apply_audio_texts(scene,[{'beat_id':'b','index':1,'text':'改错人'}],permission,c.digest(scene))
    with pytest.raises(c.ContractError):
        apply_audio_texts(scene,[{'beat_id':'b','index':0,'text':'原主打他','speaker':'kid'}],permission,c.digest(scene))
    with pytest.raises(ValueError,match='stale'):
        apply_audio_texts(scene,[{'beat_id':'b','index':0,'text':'原主打他'}],permission,'stale')
