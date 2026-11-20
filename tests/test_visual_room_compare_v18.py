"""Compact primary contract, real loopback protocol and persistent boundaries."""
from copy import deepcopy
from pathlib import Path

from PIL import Image
import pytest

from src.content_factory import visual_asset_review_v3 as v
from src.content_factory import visual_room_compare_v18 as r
from src.content_factory import visual_split_observation_v14 as split
from test_visual_asset_review_v3 import provider


def answer(**changes):
    result=dict(checks={k:True for k in r.CHECKS},evidence={k:'Concrete visible fixture relation for '+k+'.' for k in r.CHECKS})
    result.update(changes);return result


@pytest.fixture
def sample_request(tmp_path):
    files=[]
    for name,color in [('target','gray'),('source','silver'),('guide','white')]:
        f=tmp_path/(name+'.png');Image.new('RGB',(64,80),color).save(f);files.append(f)
    inventory={k:0 for k in v.FURNITURE_KINDS};inventory['bed']=1
    exp=dict(kind='place',expected_people=0,room_comparison_scope=r.SCOPE,locate_rois=[],
        furniture_observation_scope=split.SCOPE,layout_object_inventory=inventory,
        appearance_description='ACTOR_SECRET: a full actor story with human face clothing hands.',
        composition_place=dict(id='room',description='One old bed beside the window.'),
        environment_context=dict(layout_design='Fixed room.',space_type='interior',camera_description='Current view.',visible_anchors=[],comparison_rule='Compare actual guide.'))
    return dict(target=files[0],reference=files[1],layout_guide=files[2],expectation=exp)


def test_room_payload_has_only_bounded_checks_and_no_actor_or_roi_instruction(sample_request,tmp_path):
    with provider([answer()]) as (url,calls):
        client=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'))
        result=client.review_many([sample_request],evidence_dir=tmp_path/'review')[0]
        assert result['decision']=='accepted' and len(calls)==3
        body=calls[-1];prompt=body['messages'][0]['content'];schema=body['format']
        assert 'ACTOR_SECRET' not in prompt and 'EXPECTATION_JSON' not in prompt and v.BASE_PROMPT not in prompt
        assert set(schema['properties'])=={'checks','evidence'} and set(schema['properties']['evidence']['properties'])==set(r.CHECKS)
        assert all(x['maxLength']==180 for x in schema['properties']['evidence']['properties'].values())
        assert result['observations']['people_count']==0 and result['prompt_version']==r.VERSION
        r.verify_result(result)
        before=len(calls);assert client.review_many([sample_request],evidence_dir=tmp_path/'review')[0]==result and len(calls)==before


@pytest.mark.parametrize('key',r.CHECKS)
@pytest.mark.parametrize('value',[False,None])
def test_false_and_unknown_primary_never_become_true(sample_request,tmp_path,key,value):
    raw=answer();raw['checks'][key]=value
    with provider([raw]) as (url,calls):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review_many([sample_request],evidence_dir=tmp_path/'review')[0]
    assert result['checks'][key] is value and result['decision']!='accepted'
    changed=deepcopy(result);changed['checks'][key]=True
    with pytest.raises(ValueError,match='verdict_upgraded'):r.verify_result(changed)


@pytest.mark.parametrize('mutation',[
    lambda x:x['evidence'].update(layout='x'*181),lambda x:x['evidence'].pop('view'),
    lambda x:x.update(observations=dict(people_count=0)),lambda x:x['checks'].update(layout='true'),
    lambda x:x.update(evidence=['wrong shape']),lambda x:x['evidence'].update(view=''),
])
def test_schema_violation_is_known_unavailable_not_repaired_into_acceptance(sample_request,tmp_path,mutation):
    raw=answer();mutation(raw)
    with provider([raw]) as (url,calls):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review_many([sample_request],evidence_dir=tmp_path/'review')[0]
    assert result['decision']=='unavailable' and result['completion_known'] is True


def test_two_bed_blind_still_overrules_compact_alltrue(sample_request,tmp_path):
    objects={k:dict(count=0,regions=[],evidence='Absent fixture.') for k in v.FURNITURE_KINDS}
    objects['bed']=dict(count=2,regions=[[0,0,400,1000],[500,0,1000,1000]],evidence='Two fixture beds.')
    with provider([answer()],furniture_observation=dict(object_observations=objects)) as (url,calls):
        result=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test')).review_many([sample_request],evidence_dir=tmp_path/'review')[0]
    assert result['decision']=='repair_required' and result['checks']['layout'] is False
    assert result['object_inventory_check']['exceeds']==['bed']


def test_compact_constructor_is_explicit_and_only_changes_place_prepared(sample_request,tmp_path):
    # The composition's actor requests retain the original independent contracts.
    with provider([]) as (url,calls):
        client=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'),room_comparison_scope=r.SCOPE)
        captured=[]
        def spy(requests,**kwargs):captured.extend(requests);raise RuntimeError('capture only')
        client.review_many=spy
        with pytest.raises(RuntimeError,match='capture only'):
            client.review_composition(sample_request['target'],characters=[dict(id='actor',path=sample_request['reference'])],
                place=dict(id='room',path=sample_request['reference'],layout_guide=sample_request['layout_guide']),
                expectation=dict(expected_people=1,layout_object_inventory=sample_request['expectation']['layout_object_inventory'],furniture_observation_scope=split.SCOPE))
    assert 'room_comparison_scope' not in captured[0]['expectation']
    assert captured[1]['expectation']['room_comparison_scope']==r.SCOPE and not calls


def test_same_attempt_legacy_claim_cannot_be_evaded_by_new_scope(sample_request,tmp_path):
    q=deepcopy(sample_request);q['expectation'].pop('room_comparison_scope')
    with provider([]) as (url,calls):
        client=v.VisualReviewClient(dict(provider='ollama',endpoint=url,model='vision-test'));prepared=v._prepared(q)
        binding=v.digest(dict(config=client.config,requests=[prepared]));folder=tmp_path/'old';folder.mkdir()
        v._write(folder/'REQUEST.json',dict(config=client.config,prepared=[prepared],request_binding_sha256=binding))
        v._write(folder/'CLAIM.json',dict(request_binding_sha256=binding))
        with pytest.raises(ValueError,match='inputs changed'):client.review_many([sample_request],evidence_dir=folder)
        assert not calls and not (folder/'RESULTS.json').exists()
