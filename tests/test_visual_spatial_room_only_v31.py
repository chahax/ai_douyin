"""Fixed-scope room-reference comparison; CPU/filesystem only, no HTTP or GPU."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from PIL import Image
from src.content_factory import visual_spatial_delivery_v24 as f
from test_visual_spatial_delivery_v24 import case, put, minute

REAL_ROOT=f.ROOT


@pytest.fixture
def room(case,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('No HTTP or GPU in room-only CPU contracts')
    monkeypatch.setattr(f.native,'_http',forbidden);monkeypatch.setattr(f.native,'_gpu',forbidden)
    baseline,_,_,_=minute(case);root=case['root'];put(root/'A_SPEC.json',baseline)
    donor=deepcopy(baseline);donor['variant']='B'
    for i in (3,4):
        path=root/('donor_room_'+str(i)+'.png');Image.new('RGB',(64,80),(i*20,10,200)).save(path)
        image=f.binding(path);provenance=put(root/('donor_provenance_'+str(i)+'.json'),dict(cpu_fixture=True))
        review=put(root/('donor_review_'+str(i)+'.json'),dict(reviewed_by='root_agent',accepted_for_reference=True,image=image,entity_id='su_mo_room',provenance=provenance))
        donor['references'][i].update(image=image,provenance=provenance,root_review=review,description='donor description must not be copied',view='donor view must not be copied',reference_id='donor'+str(i))
    put(root/'B_NATIVE_SPEC.json',donor)
    auth=dict(schema='spatial_room_only_authorization/v31',user_statement='好',approved_proposal='Only replace the two room references.',interpretation='One new local minute; preserve baseline A settings.',engineering_scope_not_user_quoted_numeric_limit=True,baseline_a_spec=f.binding(root/'A_SPEC.json'),spatial_room_donor_spec=f.binding(root/'B_NATIVE_SPEC.json'),max_full_video_submissions=4,max_probe_video_submissions=0,new_cloud_media_calls=0,publication=False,old_authorization_and_usage_preserved=True,service_restarts=False,downloads=False,unknown_native_replay=False)
    authorization=put(root/'C_ROOM_ONLY_USER_AUTHORIZATION.json',auth)
    spec=deepcopy(baseline);spec.update(variant=f.ROOM_ONLY_VARIANT,authorization=authorization)
    for i in (3,4):
        for key in ('image','provenance','root_review'):spec['references'][i][key]=deepcopy(donor['references'][i][key])
    path=root/'C_ROOM_ONLY_SPEC.json';put(path,spec);approval=root/'C_APPROVAL.json'
    put(approval,dict(reviewed_by='root_agent',approved_for_generation=True,diagnostic_only=True,spec=f.binding(path)))
    run=root/'variants'/f.ROOM_ONLY_VARIANT
    return dict(case=case,root=root,baseline=baseline,donor=donor,auth=auth,spec=spec,path=path,approval=approval,run=run)


def prepare(room):return f.prepare(room['path'],room['approval'],room['run'])


def plan(room):
    return dict(schema=f.SCHEMA,variant=f.ROOM_ONLY_VARIANT,profile='minute',authorization=room['spec']['authorization'],settings=room['spec'])


def claim(root,variant,sid,value):
    run=root/'variants'/variant;put(run/'PLAN.json',value);put(run/'shots'/sid/'CLAIM.json',dict(outcome='unknown',cpu_fixture=True))


def test_fixed_room_only_prepare_filesystem_no_http_or_gpu(room):
    result=prepare(room)
    assert result['total']==4 and result['technical_saved']==0 and result['profile']=='minute'
    assert all(x['status']=='prepared' and x['prompt_id'] is None for x in result['shots'])
    assert not list(room['run'].glob('shots/*/CLAIM.json'))
    assert f.native.read(room['run']/'PLAN.json')['settings']==room['spec']


def test_actual_prompt_and_graph_contract_stay_identical_to_a(room):
    base=room['case']['base'];a=room['baseline'];c=room['spec']
    for i,(sa,sc) in enumerate(zip(a['segments'],c['segments'])):
        assert sa==sc
        ga=f.build_graph(base,a,sa,'cpu_same_scope',a['initial_guide'],a['seed']+i)
        gc=f.build_graph(base,c,sc,'cpu_same_scope',c['initial_guide'],c['seed']+i)
        assert ga==gc
    assert all(a['references'][i]['image']!=c['references'][i]['image'] for i in (3,4))
    assert a['references'][:3]==c['references'][:3]


def test_current_actual_root_created_auth_and_spec_readonly_contract():
    spec_path=REAL_ROOT/'C_ROOM_ONLY_SPEC.json';auth_path=REAL_ROOT/'C_ROOM_ONLY_USER_AUTHORIZATION.json'
    before={p:f.binding(p) for p in (spec_path,auth_path,REAL_ROOT/'A_SPEC.json',REAL_ROOT/'B_NATIVE_SPEC.json')}
    value=f.native.read(spec_path)
    assert f._validate_spec(value,REAL_ROOT/'variants'/f.ROOM_ONLY_VARIANT)==value
    assert all(f.binding(p)==b for p,b in before.items())


@pytest.mark.parametrize('field,value',[('seed',999),('seed',12345.0),('width',288),('width',736.0),('frames',124),('profile','probe'),('prompt_format','official_ref2va_v29'),('unknown_extra_field',True)])
def test_every_nonwhitelisted_top_level_change_rejected(room,field,value):
    room['spec'][field]=value
    with pytest.raises(ValueError,match='outside_exact_six'):f._validate_spec(room['spec'],room['run'])


@pytest.mark.parametrize('field,value',[('description','new description'),('view','other'),('reference_id','donor'),('display_name','new name'),('entity_id','other')])
def test_room_identity_and_prompt_metadata_stay_exactly_a(room,field,value):
    room['spec']['references'][3][field]=value
    with pytest.raises(ValueError,match='outside_exact_six'):f._validate_spec(room['spec'],room['run'])


@pytest.mark.parametrize('mutation',['cast','prompt','initial_guide','end_guide','config','order','partial_room_donor','donor_review_only'])
def test_only_complete_two_room_payload_triplets_may_change(room,mutation):
    s=room['spec']
    if mutation=='cast':s['references'][0]['image']=s['references'][1]['image']
    elif mutation=='prompt':s['segments'][0]['prompt']=s['segments'][1]['prompt']
    elif mutation=='initial_guide':s['initial_guide']['role']='last'
    elif mutation=='end_guide':s['segments'][2]['end_guide']=deepcopy(s['initial_guide'])
    elif mutation=='config':s['config']['timeout']=99
    elif mutation=='order':s['segments'].reverse()
    elif mutation=='partial_room_donor':s['references'][4]['image']=room['baseline']['references'][4]['image']
    elif mutation=='donor_review_only':s['references'][3]['root_review']=room['baseline']['references'][3]['root_review']
    with pytest.raises(ValueError,match='outside_exact_six'):f._validate_spec(s,room['run'])


def test_fixed_authorization_and_variant_paths_cannot_be_cloned(room):
    cloned=put(room['root']/'different_auth.json',room['auth']);room['spec']['authorization']=cloned
    with pytest.raises(ValueError,match='fixed_authorization'):f._authorization(room['spec'],room['run'])
    room['spec']['authorization']=f.binding(room['root']/'C_ROOM_ONLY_USER_AUTHORIZATION.json')
    with pytest.raises(ValueError,match='fixed_variant_scope'):f._authorization(room['spec'],room['root']/'variants/C_other')


@pytest.mark.parametrize('field,value',[('max_full_video_submissions',5),('max_full_video_submissions',True),('max_probe_video_submissions',1),('max_probe_video_submissions',False),('new_cloud_media_calls',False),('publication',True),('unknown_native_replay',True),('service_restarts',True),('downloads',True),('old_authorization_and_usage_preserved',False),('engineering_scope_not_user_quoted_numeric_limit',False),('user_statement','user never said this'),('approved_proposal','')])
def test_bound_authorization_is_exact_four_zero_engineering_scope(room,field,value):
    room['auth'][field]=value;room['spec']['authorization']=put(room['root']/'C_ROOM_ONLY_USER_AUTHORIZATION.json',room['auth'])
    with pytest.raises(ValueError,match='four_formal_zero_probe'):f._authorization(room['spec'],room['run'])


@pytest.mark.parametrize('field,name',[('baseline_a_spec','A_SPEC.json'),('spatial_room_donor_spec','B_NATIVE_SPEC.json')])
def test_donor_or_baseline_alternate_path_and_tamper_rejected(room,field,name):
    value=f.native.read(room['root']/name);other=put(room['root']/('copy_'+name),value)
    room['auth'][field]=other;room['spec']['authorization']=put(room['root']/'C_ROOM_ONLY_USER_AUTHORIZATION.json',room['auth'])
    with pytest.raises(ValueError,match='fixed_baseline_and_donor'):f._authorization(room['spec'],room['run'])


@pytest.mark.parametrize('name',['A_SPEC.json','B_NATIVE_SPEC.json'])
def test_frozen_baseline_or_donor_file_modified_after_authorization_rejects(room,name):
    path=room['root']/name;value=f.native.read(path);value['seed']=888;put(path,value)
    with pytest.raises(ValueError,match='fixed_baseline_and_donor'):f._authorization(room['spec'],room['run'])


def test_new_authorization_cannot_be_used_for_old_a_or_b(room):
    for variant in ('A','B','canary_A','canary_B'):
        s=deepcopy(room['spec']);s['variant']=variant
        with pytest.raises(ValueError,match='explicit_bounded_local'):f._authorization(s,room['root']/'variants'/variant)


def test_budget_ignores_old_usage_but_counts_all_four_c_claims_even_unknown(room):
    p=plan(room);legacy=dict(authorization=room['baseline']['authorization'],variant='A',profile='minute')
    for sid in f.IDS:claim(room['root'],'A',sid,legacy)
    legacy['variant']='B'
    for sid in f.IDS:claim(room['root'],'B',sid,legacy)
    f._budget(room['run'],p)
    for sid in f.IDS[:3]:claim(room['root'],f.ROOM_ONLY_VARIANT,sid,p)
    f._budget(room['run'],p)
    claim(room['root'],f.ROOM_ONLY_VARIANT,'S04',p)
    with pytest.raises(ValueError,match='budget_exhausted'):f._budget(room['run'],p)


@pytest.mark.parametrize('variant,sid',[('C_clone','S01'),('C_room_only_20261108_v1','S05')])
def test_same_c_authorization_in_other_variant_or_unknown_shot_refused(room,variant,sid):
    p=plan(room);claim(room['root'],variant,sid,p)
    with pytest.raises(ValueError,match='outside_fixed_run'):f._budget(room['run'],p)


def test_c_claim_with_wrong_authorization_refused(room):
    p=plan(room);wrong=deepcopy(p);wrong['authorization']=room['baseline']['authorization']
    claim(room['root'],f.ROOM_ONLY_VARIANT,'S01',wrong)
    with pytest.raises(ValueError,match='outside_fixed_run'):f._budget(room['run'],p)


def test_old_budget_does_not_gain_access_to_c_allowance(room):
    p=plan(room);claim(room['root'],f.ROOM_ONLY_VARIANT,'S01',p)
    old=dict(settings=room['baseline'],authorization=room['baseline']['authorization'],profile='minute')
    with pytest.raises(ValueError,match='shared_budget_authorization_mismatch'):f._budget(room['root']/'variants/A',old)


@pytest.mark.parametrize('known',[False,True])
def test_existing_unknown_or_known_original_state_never_reposts(room,known):
    prepare(room);folder=room['run']/'shots/S01';state=f.native.read(folder/'STATE.json')
    # Exercise the existing early-state boundary with its full recorded request/claim contract.
    graph={'cpu_fixture':dict(class_type='NotAModelNode',inputs={})};digest=f.native.fingerprint(graph)
    put(folder/'workflow_api.json',graph);put(folder/'GRAPH_BINDING.json',dict(graph_sha256=digest));put(folder/'REQUEST.json',dict(prompt=graph));put(folder/'CLAIM.json',dict(graph_sha256=digest))
    state.update(graph_sha256=digest,status='prepared',prompt_id=None);f.native.write(folder/'STATE.json',state)
    if known:put(folder/'RESPONSE.json',dict(prompt_id='known_original_c_cpu_fixture'))
    result=f.submit_next(room['run'])
    assert result['shots'][0]['status']==('submitted' if known else 'outcome_unknown')
    assert (folder/'CLAIM.json').exists()
