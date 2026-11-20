from copy import deepcopy
import pytest
from src.content_factory.novel_adaptation.contracts import digest,ContractError
from src.content_factory.novel_adaptation.narrative_patch import bind_body,apply
from src.content_factory.novel_adaptation.narrative_render import render


def fixture():
    return {'title':'原稿约1秒','world_and_relationships':'世界','visual_direction':'视觉',
        'condensation_notes':[{'source_ids':['P1'],'treatment':'原估时1秒'}],
        'scenes':[{'id':'S','place':'厨房','entry_continuity':'进入','exit_continuity':'留下',
        'segments':[{'id':'B','seconds':1,'visible_people':['a'],'action':'动作','expression':'神情',
        'camera':'镜头','audio':[{'kind':'inner','speaker':'a','text':'一二三四五六七八'}],
        'source_ids':['P1'],'visual_additions':['细节'],'continuity_obligations':['保持']}]}]}


def test_program_binding_preserves_frozen_identity_and_scope():
    c=fixture();body={'replacements':[{'path':'/scenes/0/segments/0/visual_additions/0','value':'新细节'}]}
    path=['/scenes/0/segments/0/visual_additions/0']
    bound=bind_body(c,body,path,digest(c))
    out=apply(c,bound,path,digest(c))
    assert out['scenes'][0]['segments'][0]['action']=='动作'
    assert out['scenes'][0]['segments'][0]['visual_additions']==['新细节']
    assert 'candidate_sha256' not in body
    with pytest.raises(ValueError,match='candidate_changed'):bind_body(c,body,path,'stale')
    with pytest.raises(ContractError):bind_body(c,{**body,'candidate_sha256':'model_hash'},path,digest(c))


def test_schedule_view_has_one_operational_timeline_and_preserves_prose():
    c=fixture();old=deepcopy(c)
    legacy=render(c);scheduled=render(c,estimated_timing=True)
    assert 'B · 0–1秒' in legacy
    assert 'B · 0–2秒' in scheduled and 'B · 0–1秒' not in scheduled
    assert '原稿标题（保留原估时）：原稿约1秒' in scheduled
    assert '总计 2 秒' in scheduled and '不是实测成片时长' in scheduled
    assert '一二三四五六七八' in scheduled and c==old


def test_duration_patch_is_positive_numeric_and_preserves_other_fields():
    c=fixture();path=['/scenes/0/segments/0/seconds']
    body={'replacements':[{'path':path[0],'value':3}]}
    out=apply(c,bind_body(c,body,path,digest(c)),path,digest(c))
    assert out['scenes'][0]['segments'][0]['seconds']==3
    assert out['scenes'][0]['segments'][0]['audio']==c['scenes'][0]['segments'][0]['audio']
    for bad in (0,-1,True,'3'):
        with pytest.raises(ContractError):
            bind_body(c,{'replacements':[{'path':path[0],'value':bad}]},path,digest(c))
