"""Immutable image-scoped review ledgers; fake local transports, no GPU."""
from copy import deepcopy
import json
from pathlib import Path

from PIL import Image
import pytest

from src.content_factory import visual_first_frame_review_paths_v16 as paths
from src.content_factory import visual_asset_pipeline_v3 as p
from src.content_factory import visual_asset_review_v3 as v
from test_visual_asset_pipeline_v3 import service,setup,accept_direct,register_candidate,FakeReviewer
from test_visual_asset_review_v3 import provider


BINDING='a'*64
A='b'*64
B='c'*64


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding='utf-8')


def ledger(folder,target,*,decision='repair_required',known=True,style=False):
    prepared=[dict(target=dict(path='retained-original.png',sha256=target),expectation={})]
    config=dict(provider='test_fixture')
    binding=p.fingerprint(dict(config=config,**(dict(prepared=prepared[0]) if style else dict(requests=prepared))))
    request=dict(config=config,prepared=prepared,request_binding_sha256=binding)
    if style:request['review_mode']='residence_appearance_visual_review/v6'
    value=dict(binding_sha256=p.fingerprint(prepared[0]),target_sha256=target,decision=decision,
        completion_known=known,outcome_unknown=not known)
    write(folder/'REQUEST.json',request);write(folder/'CLAIM.json',dict(request_binding_sha256=binding))
    write(folder/'RESULTS.json',dict(request_binding_sha256=binding,results=[value],results_sha256=p.fingerprint([value])))
    return request


def history(target,decision='repair_required'):
    return [dict(binding_sha256=BINDING,sha256=target,review=dict(target_sha256=target,decision=decision,
        completion_known=True,outcome_unknown=False))]


def test_fresh_image_namespace_is_pure_and_does_not_create_directory(tmp_path):
    result=paths.select(tmp_path,BINDING,A,0)
    assert result==tmp_path/BINDING/A/'0' and not any(tmp_path.iterdir())


@pytest.mark.parametrize('style',[False,True])
def test_accepted_legacy_v14_and_style_keep_their_original_directory(tmp_path,style):
    old=tmp_path/BINDING/'0';ledger(old,A,decision='accepted',style=style)
    before={str(f):f.read_bytes() for f in old.iterdir()}
    assert paths.select(tmp_path,BINDING,A,0)==old
    assert before=={str(f):f.read_bytes() for f in old.iterdir()}
    assert not (tmp_path/BINDING/A).exists()


@pytest.mark.parametrize('style',[False,True])
def test_known_repaired_A_to_B_never_overwrites_legacy_A(tmp_path,style):
    old=tmp_path/BINDING/'0';ledger(old,A,style=style)
    before={str(f):f.read_bytes() for f in old.iterdir()}
    assert paths.select(tmp_path,BINDING,B,0,repair_history=history(A))==tmp_path/BINDING/B/'0'
    assert before=={str(f):f.read_bytes() for f in old.iterdir()}


@pytest.mark.parametrize('has_result',[False,True])
def test_different_legacy_unknown_blocks_even_if_history_claims_repair(tmp_path,has_result):
    old=tmp_path/BINDING/'0';ledger(old,A,known=False)
    if not has_result:(old/'RESULTS.json').unlink()
    with pytest.raises(ValueError,match='prior_outcome_unknown'):
        paths.select(tmp_path,BINDING,B,0,repair_history=history(A))
    assert not (tmp_path/BINDING/B).exists()


@pytest.mark.parametrize('change',[
    lambda h:h.clear(),lambda h:h[0]['review'].update(decision='accepted'),
    lambda h:h[0]['review'].update(completion_known=False),lambda h:h[0].update(binding_sha256='d'*64),
])
def test_known_other_image_requires_exact_known_repair_history(tmp_path,change):
    ledger(tmp_path/BINDING/'0',A);h=history(A);change(h)
    with pytest.raises(ValueError,match='prior_image_not_known_repair'):
        paths.select(tmp_path,BINDING,B,0,repair_history=h)


def test_tampered_results_cannot_settle_an_unknown_legacy(tmp_path):
    old=tmp_path/BINDING/'0';ledger(old,A)
    value=p.read(old/'RESULTS.json');value['results'][0]['decision']='accepted';write(old/'RESULTS.json',value)
    with pytest.raises(ValueError,match='binding_changed'):
        paths.select(tmp_path,BINDING,B,0,repair_history=history(A))


def test_unknown_same_image_cannot_escape_via_incremented_attempt(tmp_path):
    old=tmp_path/BINDING/A/'0';ledger(old,A,known=False)
    with pytest.raises(ValueError,match='prior_outcome_unknown'):paths.select(tmp_path,BINDING,A,1)
    assert not (tmp_path/BINDING/A/'1').exists()


@pytest.mark.parametrize('legacy',[True,False])
def test_same_image_original_unknown_reaches_original_client_without_inference(tmp_path,legacy):
    target=tmp_path/'image.png';Image.new('RGB',(32,48),'silver').save(target)
    image_sha=v.file_sha(target);old=tmp_path/BINDING/('0' if legacy else image_sha+'/0')
    with provider([]) as (url,calls):
        client=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'))
        expectation=dict(kind='character',locate_rois=[])
        prepared=[v._prepared(dict(target=target,expectation=expectation))]
        binding=v.digest(dict(config=client.config,requests=prepared))
        write(old/'REQUEST.json',dict(config=client.config,prepared=prepared,request_binding_sha256=binding))
        write(old/'CLAIM.json',dict(request_binding_sha256=binding))
        chosen=paths.select(tmp_path,BINDING,image_sha,0)
        assert chosen==old
        result=client.review(target,expectation=expectation,evidence_dir=chosen)
        assert result['outcome_unknown'] is True and result['completion_known'] is False and not calls
        assert not (old/'RESULTS.json').exists()


def test_same_image_changed_expectation_is_rejected_not_given_a_new_directory(tmp_path):
    target=tmp_path/'image.png';Image.new('RGB',(32,48),'silver').save(target)
    image_sha=v.file_sha(target);old=tmp_path/BINDING/'0'
    with provider([]) as (url,calls):
        client=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'))
        prepared=[v._prepared(dict(target=target,expectation=dict(kind='character',locate_rois=[])))]
        binding=v.digest(dict(config=client.config,requests=prepared))
        write(old/'REQUEST.json',dict(config=client.config,prepared=prepared,request_binding_sha256=binding))
        write(old/'CLAIM.json',dict(request_binding_sha256=binding))
        chosen=paths.select(tmp_path,BINDING,image_sha,0)
        with pytest.raises(ValueError,match='review job inputs changed'):
            client.review(target,expectation=dict(kind='character',age_band='adult',locate_rois=[]),evidence_dir=chosen)
        assert not calls and not (tmp_path/BINDING/image_sha).exists()


def test_pipeline_auto_repair_reuses_collected_B_and_keeps_both_image_ledgers(tmp_path,service,monkeypatch):
    run,packet,config=setup(tmp_path,service,shots=True)
    accept_direct(config,register_candidate(tmp_path,config))
    accept_direct(config,register_candidate(tmp_path,config,entity='room',kind='place',color='white'))
    class FrozenReviewer(FakeReviewer):
        def review_composition(self,path,**kwargs):
            folder=Path(kwargs['evidence_dir']);target=p.file_sha(path)
            if (folder/'REQUEST.json').exists():
                assert p.read(folder/'REQUEST.json')['prepared'][0]['target']['sha256']==target,'collision with older image'
            self.decision='repair_required' if not self.compositions else 'accepted'
            value=super().review_composition(path,**kwargs)
            ledger(folder,target,decision=value['decision'])
            return value
    reviewer=FrozenReviewer();service.auto_complete=True;style_dirs=[]
    monkeypatch.setattr(p,'_residence_style_review',lambda *args,**kwargs:style_dirs.append(Path(args[5])) or None)
    assert p.tick(run)['status']=='first_frame_prepared'
    assert p.tick(run)['status']=='image_submitted'
    assert p.tick(run,reviewer=reviewer)['status']=='first_frame_prepared'
    old_frame=deepcopy(p.status(run)['state']['first_frame_history']['shot1'][0])
    # Reproduce an actual pre-fix legacy ledger without changing its content.
    old_path=Path(reviewer.compositions[0]['evidence_dir']);legacy=old_path.parent.parent/'0'
    old_path.rename(legacy);before={x.name:x.read_bytes() for x in legacy.iterdir()}
    assert p.tick(run)['status']=='image_submitted'
    state=p.tick(run,reviewer=reviewer)
    assert state['status']=='h3_inputs_ready' and len(service.posts)==2
    current=state['first_frames']['shot1'];new_path=Path(reviewer.compositions[1]['evidence_dir'])
    assert current['sha256']!=old_frame['sha256'] and current['review_attempts']==1
    assert new_path==run/'first_frame_reviews'/current['binding_sha256']/current['sha256']/'0'
    assert before=={x.name:x.read_bytes() for x in legacy.iterdir()}
    assert style_dirs==[run/'first_frame_style_reviews'/current['binding_sha256']/current['sha256']/'0']
