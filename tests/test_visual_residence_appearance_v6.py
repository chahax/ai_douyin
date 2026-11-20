"""New appearance scope does not reinterpret material failures or prove materials."""
from copy import deepcopy
import json
from pathlib import Path
import types

from PIL import Image
import pytest

from src.content_factory import visual_residence_appearance_v6 as a
from src.content_factory import visual_asset_review_v3 as v
from src.content_factory import visual_asset_pipeline_v3 as p
from src.content_factory import visual_residence_review_v5 as material


@pytest.fixture
def appearance_request(tmp_path):
    source=tmp_path/'master.png';Image.new('RGB',(256,320),'gray').save(source)
    patches=[]
    for slot,color,key in [('wall','gray','aged_plaster'),('wood','brown','brown')]:
        path=tmp_path/(slot+'.png');Image.new('RGB',(100,100),color).save(path)
        patches.append(dict(slot=slot,material_key=key,path=str(path),sha256=v.file_sha(path)))
    return dict(mode='reference',target=str(source),source_context=dict(path=str(source),sha256=v.file_sha(source)),
        patches=patches,semantic=dict(shared_style=dict(wall_surface='aged_plaster',wall_color='gray',
            floor_surface='concrete',wood_color='brown',condition='worn',era='contemporary_low_cost_older_home'),
            room_overrides={},material_slots=[{k:x[k] for k in ('slot','material_key')} for x in patches]),
        binding=dict(reference_contract=a.CONTRACT,group_definition_sha256='a'*64,inherited_reference_sha256='b'*64))


def answer(q):
    return dict(checks={k:True for k in a.CHECKS},
        patch_checks=[dict(slot=x['slot'],usable_color=True,visible_finish=True,layout_free=True,
            evidence='The visible uniform color and plain coated finish are usable, without room layout.') for x in q['patches']],
        evidence=['Protocol fixture global appearance evidence, not real visual acceptance.'])


def client(monkeypatch,response):
    c=v.VisualReviewClient(dict(provider='ollama',endpoint='http://127.0.0.1:1',model='appearance-fixture'))
    calls=[]
    monkeypatch.setattr(c,'discover',lambda:dict(available=True,model='appearance-fixture',capabilities=['vision']))
    def infer(payload):
        calls.append(deepcopy(payload))
        if isinstance(response,Exception):raise response
        return dict(text=json.dumps(response),model='appearance-fixture')
    monkeypatch.setattr(c,'_infer_http',infer)
    return c,calls


def test_plain_color_and_plain_finish_are_a_new_appearance_receipt_not_material_identity(appearance_request,monkeypatch,tmp_path):
    c,calls=client(monkeypatch,answer(appearance_request))
    result=c.review_residence_appearance(appearance_request,tmp_path/'new_appearance')
    assert result['decision']=='accepted' and result['style_reference_ready'] and result['approval_scope']==a.CONTRACT
    assert all(result[k] is False for k in ('material_identity_approved','layout_approved','novel_fidelity_approved','production_approved'))
    assert [x['role'] for x in calls[0]['images']]==['master_style_context','appearance_patch_wall','appearance_patch_wood']
    assert set(calls[0]['schema']['properties']['patch_checks']['items']['properties'])=={'slot','usable_color','visible_finish','layout_free','evidence'}
    semantic=json.loads(calls[0]['prompt'].split('SEMANTIC_DATA:\n')[1])
    assert 'floor_surface' not in semantic['shared_style'] and 'wall_surface' not in semantic['shared_style']
    assert 'material_key' not in json.dumps(semantic)
    assert result['source_context_sha256']==appearance_request['source_context']['sha256']
    assert c.review_residence_appearance(appearance_request,tmp_path/'new_appearance')==result and len(calls)==1


@pytest.mark.parametrize('field,value,decision',[
    ('usable_color',False,'repair_required'),('usable_color',None,'needs_review'),
    ('visible_finish',False,'repair_required'),('visible_finish',None,'needs_review'),
    ('layout_free',False,'repair_required'),('layout_free',None,'needs_review'),
])
def test_real_darkness_or_unreadable_finish_or_layout_does_not_get_promoted(appearance_request,monkeypatch,field,value,decision):
    raw=answer(appearance_request);raw['patch_checks'][0][field]=value
    c,_=client(monkeypatch,raw);result=c.review_residence_appearance(appearance_request)
    assert result['decision']==decision and result['patch_checks'][0][field] is value
    assert not result['style_reference_ready'] and result['material_identity_approved'] is False


def test_old_material_nulls_and_false_cannot_be_consumed_as_appearance_checks(appearance_request,monkeypatch):
    old=dict(checks={k:None for k in material.CHECKS},patch_checks=[dict(slot=p['slot'],material_match=None,
        texture_only=True,identifiable=False,evidence='Old material request was not approved.') for p in appearance_request['patches']],
        evidence=['Old material failure.'])
    before=deepcopy(old);c,_=client(monkeypatch,old);result=c.review_residence_appearance(appearance_request)
    assert result['decision']=='unavailable' and not result['style_reference_ready'] and old==before


def test_new_scope_must_be_explicit_and_cannot_reuse_an_old_scope_evidence_directory(appearance_request,monkeypatch,tmp_path):
    q=deepcopy(appearance_request);q['binding'].pop('reference_contract')
    with pytest.raises(ValueError,match='explicit_appearance'):a._prepared(q)
    c,calls=client(monkeypatch,answer(appearance_request));c.review_residence_appearance(appearance_request,tmp_path/'claimed')
    changed=deepcopy(appearance_request);changed['binding']['inherited_reference_sha256']='c'*64
    with pytest.raises(ValueError,match='saved residence style'):c.review_residence_appearance(changed,tmp_path/'claimed')
    assert len(calls)==1


def test_functional_floor_override_is_an_allowed_visual_role_not_a_chemical_check(appearance_request):
    appearance_request['semantic']['room_overrides']['floor_surface']='ceramic_tile'
    semantic=a._prepared(appearance_request)['appearance_semantic']
    assert semantic['functional_surface_overrides']==['floor']
    assert 'ceramic_tile' not in json.dumps(semantic) and 'concrete' not in json.dumps(semantic)


def test_appearance_unknown_retains_native_claim_without_replay(appearance_request,monkeypatch,tmp_path):
    c,calls=client(monkeypatch,v.ReviewOutcomeUnknown('unknown new appearance call'))
    result=c.review_residence_appearance(appearance_request,tmp_path/'unknown')
    assert result['outcome_unknown'] and not result['retryable'] and not result['style_reference_ready']
    assert result['prompt_version']==a.PROMPT_VERSION
    assert c.review_residence_appearance(appearance_request,tmp_path/'unknown')==result and len(calls)==1
    assert (tmp_path/'unknown/item_0000/APPEARANCE_ERROR.json').is_file()


def test_appearance_local_worker_uses_distinct_review_mode_and_receipt(appearance_request,monkeypatch,tmp_path):
    c=v.VisualReviewClient(dict(provider='transformers_local',model_path=str(tmp_path/'fake_model')))
    monkeypatch.setattr(c,'discover',lambda:dict(available=True,model='fixture-no-gpu'))
    def run(command,**kwargs):
        folder=Path(command[command.index('--request')+1]).parent;saved=v._read(folder/'REQUEST.json')
        assert saved['review_mode']==a.VERSION
        result=a._review_one(saved['prepared'][0],lambda _:dict(text=json.dumps(answer(appearance_request))),saved['model_binding'],folder/'item_0000')
        v._write(folder/'RESULTS.json',dict(request_binding_sha256=saved['request_binding_sha256'],results_sha256=v.digest([result]),results=[result]))
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(material.subprocess,'run',run)
    assert c.review_residence_appearance(appearance_request,tmp_path/'worker')['schema']==a.VERSION


def test_pipeline_explicitly_dispatches_appearance_without_replaying_material_route(appearance_request,monkeypatch,tmp_path):
    from src.content_factory import visual_residence_style_v5 as storage
    plan=dict(packet=dict(style_groups=[dict(id='home',master_place_id='master')]))
    entity=dict(id='room',style_group_id='home');appearance_request['mode']='target'
    monkeypatch.setattr(p,'_style_reference_for_entity',lambda *a:dict(fixture=True))
    monkeypatch.setattr(storage,'target_request',lambda *args:deepcopy(appearance_request))
    monkeypatch.setattr(storage,'verify_result',lambda *args,**kwargs:True)
    c,_=client(monkeypatch,answer(appearance_request))
    monkeypatch.setattr(c,'review_style_materials',lambda *args,**kwargs:pytest.fail('Appearance must not replay material verification.'))
    result=p._residence_style_review(tmp_path,plan,entity,appearance_request['target'],c,tmp_path/'target')
    assert result['result']['schema']==a.VERSION and result['result']['approval_scope']==a.CONTRACT
