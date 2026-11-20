"""Explicit appearance scope reuses frozen pixels, never upgrades material failures."""
from copy import deepcopy
from pathlib import Path

from PIL import Image
import pytest

from src.content_factory import visual_asset_pipeline_v3 as p
from src.content_factory import visual_residence_style_v5 as s
from test_visual_residence_style_v5 import fixture,result,StyleReviewer
from test_visual_asset_pipeline_v3 import service


def appearance_result(request):
    receipt=result(request)
    receipt.update(schema='residence_appearance_visual_review/v6',approval_scope='appearance/v1',material_identity_approved=False,
        patch_checks=[dict(slot=q['slot'],usable_color=True,visible_finish=True,layout_free=True,
            evidence='Uniform finish/color is usable; protocol fixture only.') for q in request['patches']])
    return receipt


def setup_v6(tmp_path,service):
    old,packet,config,row,source,parent=fixture(tmp_path,service)
    failed=result(s.reference_request(parent));failed.update(decision='repair_required',style_reference_ready=False)
    failed['checks']['palette']=False;assert not s.accept_reference(parent,failed)
    before=(Path(parent['manifest_path']).parent/'REFERENCE_REVIEW.json').read_bytes()
    config=deepcopy(config);config.update(style_reference_contract='appearance/v1',style_reference_parent_manifest=parent['manifest_path'])
    run=tmp_path/'appearance_run';p.prepare(run,packet,config);plan=p.read(run/'PLAN.json')
    return run,plan,packet,row,source,parent,before


def make_bundle(run,plan,packet,row,source,parent):
    return s.prepare_reference(run,packet['style_groups'][0],packet['places'][0],row,source,
        row['provenance']['environment_guide'],library_path=plan['config']['library'],contract='appearance/v1',parent_manifest=parent['manifest_path'])


def test_new_scope_reuses_master_and_exact_three_crops_without_roi_reselection(tmp_path,service,monkeypatch):
    run,plan,packet,row,source,parent,before=setup_v6(tmp_path,service)
    def forbidden(*args,**kwargs):pytest.fail('A scope change must not reselect or redraw source material pixels.')
    monkeypatch.setattr(s,'_exposed_rectangle',forbidden)
    bundle=make_bundle(run,plan,packet,row,source,parent)
    assert bundle['schema']==s.APPEARANCE_SCHEMA and bundle['reference_contract']=='appearance/v1' and bundle['source_review_limit']==1
    assert bundle['group']==parent['group'] and bundle['master']==parent['master']
    assert [q['sha256'] for q in bundle['patches']]==[q['sha256'] for q in parent['patches']]
    assert bundle['manifest_path']!=parent['manifest_path']
    assert (Path(parent['manifest_path']).parent/'REFERENCE_REVIEW.json').read_bytes()==before
    request=s.reference_request(bundle);assert request['binding']['reference_contract']=='appearance/v1'
    assert s.accept_reference(bundle,appearance_result(request))
    ready=s.read(Path(bundle['manifest_path']).parent/'READY.json')
    assert ready['reference_contract']=='appearance/v1' and ready['material_identity_approved'] is False
    assert p._lookup(plan,dict(entity_id='master',kind='place',view='front',design_version='v5_master'))['status']=='reviewed'


@pytest.mark.parametrize('change',[
    lambda r:r.update(material_identity_approved=True),lambda r:r.update(approval_scope='material/v1'),
    lambda r:r['patch_checks'][0].update(usable_color=None),lambda r:r['patch_checks'][0].update(visible_finish=False),
    lambda r:r['patch_checks'][0].update(layout_free='true'),lambda r:r.update(schema='residence_style_visual_review/v5'),
])
def test_new_scope_cannot_claim_material_identity_or_accept_old_or_null_result(tmp_path,service,change):
    run,plan,packet,row,source,parent,before=setup_v6(tmp_path,service);bundle=make_bundle(run,plan,packet,row,source,parent)
    request=s.reference_request(bundle);receipt=appearance_result(request);change(receipt)
    with pytest.raises(ValueError):s.verify_result(request,receipt)
    assert not (Path(bundle['manifest_path']).parent/'READY.json').exists()


class AppearanceReviewer(StyleReviewer):
    def review_style_materials(self,*args,**kwargs):pytest.fail('Appearance scope must not call the exhausted material route.')
    def review_residence_appearance(self,request,**kwargs):self.style_calls.append(deepcopy(request));return appearance_result(request)


def test_failed_source_scope_is_called_once_and_original_failure_is_not_upgraded(tmp_path,service):
    run,plan,packet,row,source,parent,before=setup_v6(tmp_path,service)
    class Failed(AppearanceReviewer):
        def review_residence_appearance(self,request,**kwargs):
            receipt=super().review_residence_appearance(request,**kwargs);receipt.update(decision='needs_review',style_reference_ready=False)
            receipt['patch_checks'][0]['usable_color']=None;return receipt
    reviewer=Failed();state=p.read(run/'STATE.json')
    p._ensure_style_references(run,plan,state,reviewer);p._ensure_style_references(run,plan,state,reviewer)
    assert len(reviewer.style_calls)==1 and not service.posts
    assert state['style_references']['home']['status']=='style_reference_not_accepted'
    assert (Path(parent['manifest_path']).parent/'REFERENCE_REVIEW.json').read_bytes()==before
    assert p._raw_lookup(plan,dict(entity_id='master',kind='place',view='front',design_version='v5_master'))['version']==row['version']


def test_real_http_scope_reuses_master_and_only_generates_two_sibling_fronts(tmp_path,service):
    run,plan,packet,row,source,parent,before=setup_v6(tmp_path,service);reviewer=AppearanceReviewer();service.auto_complete=True
    original=service.complete
    def complete():
        original()
        for output in service.histories['native_'+str(len(service.posts))]['outputs'].values():
            for item in output['images']:Image.new('RGB',(768,1024),'gray').save(service.output/item['subfolder']/item['filename'])
    service.complete=complete
    state=p.run_until_idle(run,reviewer=reviewer,poll_seconds=0,max_ticks=30)
    assert state['status']=='assets_ready' and len(service.posts)==2
    assert [q['mode'] for q in reviewer.style_calls]==['reference','target','target']
    assert [sum(n['class_type']=='LoadImage' for n in post['prompt'].values()) for post in service.posts]==[4,3]
    assert (Path(parent['manifest_path']).parent/'REFERENCE_REVIEW.json').read_bytes()==before
    assert s.sha(source)==row['sha256']


def test_appearance_requires_explicit_parent_and_unknown_contract_is_rejected():
    assert s.reference_contract({})==s.MATERIAL_CONTRACT
    with pytest.raises(ValueError,match='frozen_parent'):s.reference_contract(dict(style_reference_contract='appearance/v1'))
    with pytest.raises(ValueError,match='unsupported'):s.reference_contract(dict(style_reference_contract='guess/v9'))
