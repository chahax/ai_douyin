"""Once-only reserve/review/apply with real local HTTP, no model or image POST."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import json

from PIL import Image
import pytest

from src.content_factory import visual_asset_review_v3 as v
from src.content_factory import visual_asset_pipeline_v3 as p
from src.content_factory import visual_asset_registry_v3 as library
from src.content_factory import visual_taxonomy_refresh_v12 as f
from src.content_factory import visual_furniture_taxonomy_v12 as taxonomy
from test_visual_asset_review_v3 import provider,place_observation
from test_visual_asset_pipeline_v3 import service
from test_visual_environment_v4 import place
from test_visual_furniture_taxonomy_v12 import double_label,response


@contextmanager
def scenario(tmp_path,service,monkeypatch):
    run=tmp_path/'run';run.mkdir();entity=place();source=tmp_path/'script.md';source.write_text('Fixture source.')
    image=tmp_path/'target.png';reference=tmp_path/'front.png';guide=tmp_path/'guide.png'
    for path,color in [(image,'gray'),(reference,'silver'),(guide,'white')]:Image.new('RGB',(128,160),color).save(path)
    root=tmp_path/'library'
    front=library.register(root,reference,book_id='book',entity_id='room',kind='place',view='front',design_version=entity['design_version'])
    front=library.review(root,book_id='book',asset_id=front['asset_id'],version=front['version'],file_sha256=front['sha256'],decision='accepted',
        reviewer='protocol_fixture',checks=dict.fromkeys(v.PLACE_CHECKS,True),evidence=dict(image_sha256=front['sha256'],observations=['Fixture only.']))
    row=library.register(root,image,book_id='book',entity_id='room',kind='place',view='reverse',design_version=entity['design_version'])
    blind=dict(observations=dict(people_count=0,age_band='unknown',orientation='unknown',framing='environment',pose_view='unknown'),
        rois=dict.fromkeys(v.ROI_NAMES),evidence=['Fixture only.'],object_observations=double_label())
    with provider([place_observation(0),response(),place_observation(0)],blind=blind) as (url,received):
        config=dict(library=str(root),generation_reference_policy='geometry_materials_only/v1',max_review_attempts=2,
            gpu_lock_root=str(tmp_path/'gpu_lock'),image_service=dict(service_url=service.url,input_root=str(service.input)),
            visual_review=dict(provider='ollama',endpoint=url,model='vision-test'))
        plan=dict(packet=dict(book_id='book',places=[entity],characters=[],shots=[],source=dict(path=str(source),sha256=p.file_sha(source))),config=config)
        p.write(run/'PLAN.json',plan)
        q=dict(target=str(root/row['file']),reference=str(root/front['file']),layout_guide=str(guide),expectation=dict(kind='place',view='reverse',locate_rois=[],
            expected_people=0,layout_object_inventory=v.inventory_from_layout(entity['spatial_layout'])))
        client=v.VisualReviewClient(config['visual_review'])
        with monkeypatch.context() as patch:
            patch.setattr(taxonomy,'candidate',lambda value:None) # Simulates the pre-taxonomy v11 observation contract.
            old=client.review_many([q],evidence_dir=run/'reviews/old')[0]
        assert old['decision']=='repair_required'
        row=library.review(root,book_id='book',asset_id=row['asset_id'],version=row['version'],file_sha256=row['sha256'],decision='repair_required',
            reviewer='local_visual_model',checks=old['checks'],evidence=dict(image_sha256=row['sha256'],observations=old['visual_evidence'],review=p.fingerprint(old),source_review=old))
        key=f"{row['asset_id']}:v{row['version']}:{row['sha256']}"
        p.write(run/'STATE.json',dict(status='blocked_review_or_design',jobs={},reviews={key:old},review_attempts={key:1}))
        monkeypatch.setattr(p,'_dependencies',lambda *args:([],True)) # Native generation binding has separate v7 tests.
        monkeypatch.setattr(p,'_lookup',lambda *args,**kwargs:front)
        monkeypatch.setattr(p,'_environment_guide',lambda *args,**kwargs:dict(path=str(guide),sha256=p.file_sha(guide)))
        folder=run/'taxonomy_refreshes/case'
        yield run,folder,row,key,old,client,received


def prepare(args):
    run,folder,row,*_=args
    return f.prepare_refresh(run,folder,asset_id=row['asset_id'],version=row['version'],file_sha256=row['sha256'])


def test_once_only_budget_new_native_and_explicit_registry_apply(tmp_path,service,monkeypatch):
    with scenario(tmp_path,service,monkeypatch) as args:
        run,folder,row,key,old,client,requests=args;before=(run/'PLAN.json').read_bytes()
        original_native=p.file_sha(run/'reviews/old/item_0000/BLIND_NATIVE.json')
        plan=prepare(args);assert plan['budget']['before']==1 and plan['budget']['reserved']==2
        assert len(requests)==2 and p.read(run/'STATE.json')['reviews'][key]==old
        assert p.read(run/'STATE.json')['review_attempts'][key]==2
        with pytest.raises(ValueError):prepare(args)
        reviewed=f.review_refresh(folder,client)
        assert reviewed['combined']['decision']=='accepted' and len(requests)==5
        assert library.get(tmp_path/'library',book_id='book',asset_id=row['asset_id'])[0]['status']=='candidate'
        with pytest.raises(ValueError,match='already_dispatched'):f.review_refresh(folder,client)
        result=f.apply_refresh(folder);assert result['status']=='applied'
        saved=p.read(run/'STATE.json');assert saved['review_history'][key]==[old] and saved['reviews'][key]['decision']=='accepted'
        assert library.get(tmp_path/'library',book_id='book',asset_id=row['asset_id'])[0]['status']=='reviewed'
        assert f.apply_refresh(folder)==result and p.read(run/'STATE.json')['review_history'][key]==[old]
        assert p.file_sha(run/'reviews/old/item_0000/BLIND_NATIVE.json')==original_native
        assert (run/'PLAN.json').read_bytes()==before and service.posts==[]


@pytest.mark.parametrize('mode',['unknown','other_issue','budget','state_changed','old_primary_false','missing_generation_binding'])
def test_prepare_rejects_unqualified_or_unknown_old_failure(tmp_path,service,monkeypatch,mode):
    with scenario(tmp_path,service,monkeypatch) as args:
        run,folder,row,key,old,*_=args;state=p.read(run/'STATE.json')
        if mode=='unknown':state['reviews'][key]['outcome_unknown']=True
        elif mode=='other_issue':state['reviews'][key]['issues'].append(dict(kind='layout',severity='uncertain',evidence='Other defect.'))
        elif mode=='budget':state['review_attempts'][key]=2
        elif mode=='state_changed':state['status']='image_running'
        elif mode=='old_primary_false':
            path=run/'reviews/old/item_0000/MODEL_NATIVE.json';raw=p.read(path);body=json.loads(raw['text']);body['checks']['layout']=False;raw['text']=json.dumps(body);p.write(path,raw)
        else:monkeypatch.setattr(p,'_dependencies',lambda *args:([],False))
        p.write(run/'STATE.json',state)
        with pytest.raises(ValueError):prepare(args)
        assert not folder.exists() and service.posts==[]


@pytest.mark.parametrize('mode',['new_version','old_native_changed','case_budget_changed'])
def test_new_scope_binding_changes_stop_before_model_call(tmp_path,service,monkeypatch,mode):
    with scenario(tmp_path,service,monkeypatch) as args:
        run,folder,row,key,old,client,requests=args;prepare(args)
        if mode=='old_native_changed':(run/'reviews/old/item_0000/BLIND_NATIVE.json').write_text('changed')
        elif mode=='case_budget_changed':
            state=p.read(run/'STATE.json');state['review_attempts'][key]=1;p.write(run/'STATE.json',state)
        else:
            image=tmp_path/'new.png';Image.new('RGB',(128,160),'blue').save(image)
            library.register(tmp_path/'library',image,book_id='book',entity_id='room',kind='place',view='reverse',design_version=row['design_version'])
        with pytest.raises(ValueError):f.review_refresh(folder,client)
        assert len(requests)==2 and service.posts==[]


def test_new_unknown_scope_is_not_dispatched_again_or_applied(tmp_path,service,monkeypatch):
    with scenario(tmp_path,service,monkeypatch) as args:
        run,folder,row,key,old,client,requests=args;prepare(args)
        class Unknown:
            def review_many(self,*args,**kwargs):raise v.ReviewOutcomeUnknown('Fixture new request unknown')
        with pytest.raises(v.ReviewOutcomeUnknown):f.review_refresh(folder,Unknown())
        with pytest.raises(ValueError,match='already_dispatched'):f.review_refresh(folder,client)
        with pytest.raises(FileNotFoundError):f.apply_refresh(folder)
        assert p.read(run/'STATE.json')['reviews'][key]==old and len(requests)==2 and service.posts==[]


def test_apply_rechecks_real_roi_pixels_and_never_grants_missing_style(tmp_path,service,monkeypatch):
    with scenario(tmp_path,service,monkeypatch) as args:
        run,folder,row,key,old,client,requests=args;prepare(args);result=f.review_refresh(folder,client)
        Path(result['combined']['object_taxonomy_recheck']['artifacts']['crop']['path']).write_bytes(b'changed')
        with pytest.raises(ValueError):f.apply_refresh(folder)
        assert library.get(tmp_path/'library',book_id='book',asset_id=row['asset_id'])[0]['status']=='candidate'


def test_registry_previous_review_cas_refuses_newer_same_version_event(tmp_path):
    image=tmp_path/'x.png';Image.new('RGB',(32,32),'gray').save(image);root=tmp_path/'lib'
    row=library.register(root,image,book_id='book',entity_id='room',kind='place',view='front',design_version='v1')
    old=library.review(root,book_id='book',asset_id=row['asset_id'],version=1,file_sha256=row['sha256'],decision='repair_required',reviewer='fixture',
        checks=dict.fromkeys(v.PLACE_CHECKS,True),evidence=dict(image_sha256=row['sha256'],observations=['Fixture.']))
    stale=p.fingerprint(old['review'])
    library.review(root,book_id='book',asset_id=row['asset_id'],version=1,file_sha256=row['sha256'],decision='unavailable',reviewer='other_fixture',
        checks={},evidence=dict(image_sha256=row['sha256'],observations=['Newer event.']))
    before=(root/'INDEX.json').read_bytes()
    with pytest.raises(ValueError,match='stale_review_previous_event'):
        library.review(root,book_id='book',asset_id=row['asset_id'],version=1,file_sha256=row['sha256'],decision='accepted',reviewer='fixture',
            checks=dict.fromkeys(v.PLACE_CHECKS,True),evidence=dict(image_sha256=row['sha256'],observations=['Fixture.']),expected_review_sha256=stale)
    assert (root/'INDEX.json').read_bytes()==before


def test_new_exact_target_style_is_checked_once_and_unknown_never_applies(tmp_path,service,monkeypatch):
    with scenario(tmp_path,service,monkeypatch) as args:
        run,folder,row,key,old,client,requests=args;prepare(args);calls=[]
        def unknown_style(run,plan,entity,target,reviewer,evidence_dir):
            calls.append(str(target));assert p.file_sha(target)==row['sha256']
            return dict(result=dict(decision='unavailable',target_sha256=row['sha256'],completion_known=False,outcome_unknown=True,retryable=False))
        monkeypatch.setattr(p,'_residence_style_review',unknown_style)
        value=f.review_refresh(folder,client)
        assert len(calls)==1 and value['combined']['outcome_unknown'] is True
        with pytest.raises(ValueError,match='known_accepted'):f.apply_refresh(folder)
        with pytest.raises(ValueError,match='already_dispatched'):f.review_refresh(folder,client)
        assert service.posts==[]
