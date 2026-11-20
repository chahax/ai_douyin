"""Explicit donor/source reuse contract; CPU fixtures, no model/production IO."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from test_visual_h3_reference_delivery_v20 import make as delivery_make, bundle_setup
from test_visual_h3_reference_delivery_v20 import mock_native
from src.content_factory import visual_asset_pipeline_v3 as assets
from src.content_factory import visual_h3_reference_bundle_v20 as bundles
from src.content_factory import visual_h3_reference_delivery_v20 as delivery
from src.content_factory import visual_h3_reference_reuse_v21 as reuse


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


@pytest.fixture
def case(delivery_make):
    s = delivery_make()
    a = bundles.collect(s['asset_run'], 'shot1')
    packet = deepcopy(s['packet'])
    packet['characters'].append(dict(id='third',name='第三个独立角色',design_version='v1'))
    packet['scenes'][0]['cast'].append('third')
    packet['shots'][0].update(visible_cast=['adult','third'],character_views={'adult':'front','third':'front'})
    s['add']('third','character','front',color='pink')
    second = s['tmp']/'donor_b';assets.prepare(second,packet,assets.read(s['asset_run']/'PLAN.json')['config'])
    b = bundles.collect(second,'shot1')
    root = s['tmp']/'new_minute';root.mkdir()
    auth = root/'USER_AUTHORIZATION.json'
    write(auth,dict(user_statement='CPU protocol fixture only, no actual media permission',max_new_native_submissions=4,
                    publication=False,new_cloud_calls=0))
    audit_rows=[];specs=[]
    for sid in reuse.IDS:
        original='真人写实。承接旧输入首帧。\n角色说：“原台词'+sid+'。”'
        adapted=original.replace('承接旧输入首帧。','人物造型采用具名参考图。')
        request=root/'sources'/(sid+'.REQUEST.json');op=root/'sources'/(sid+'.original.txt');ap=root/'sources'/(sid+'.adapted.txt')
        write(request,dict(content=[dict(type='text',text=original)]));op.write_bytes(original.encode());ap.write_bytes(adapted.encode())
        audit_rows.append(dict(id=sid,original_request=reuse._binding(request),original_prompt_file=reuse._binding(op),
            original_prompt_utf8_sha256=assets.file_sha(op),adapted_prompt_file=reuse._binding(ap),adapted_prompt_utf8_sha256=assets.file_sha(ap),
            changes=[dict(old='承接旧输入首帧。',new='人物造型采用具名参考图。',count=1,reason='protocol reference adaptation')],
            original_dialogue_spans=reuse.dialogue_spans(original),adapted_dialogue_spans=reuse.dialogue_spans(adapted),dialogue_texts_equal=True))
        specs.append(dict(id=sid,request_path=str(request),delivery_run=str(s['tmp']/delivery.PREFIX/('new_'+sid))))
    audit=root/'AUDIT.json';approval=root/'ROOT_APPROVAL.json'
    write(audit,dict(schema='reference_prompt_adaptation/v21',prompt_model_calls=0,segments=audit_rows))
    write(approval,dict(schema='root_reference_prompt_approval/v21',reviewed_by='root_agent',approved_for_generation=True,
        audit=reuse._binding(audit),adapted_prompt_sha256={x['id']:x['adapted_prompt_utf8_sha256'] for x in audit_rows}))
    kwargs=dict(donor_bundles={'A':a,'B':b},role_sources=[
        dict(entity_id='adult',donor_id='A',reference_id='character:adult:front'),
        dict(entity_id='child',donor_id='A',reference_id='character:child:front'),
        dict(entity_id='third',donor_id='B',reference_id='character:third:front')],
        environment=dict(donor_id='A',entity_id='room',view='side',canonical_reference='place:room:front',shot_reference='place:room:side'),
        segments=specs,authorization=reuse._binding(auth),prompt_adaptation_audit=reuse._binding(audit),prompt_approval=reuse._binding(approval))
    return dict(s=s,root=root,kwargs=kwargs,approval=approval,audit=audit)


def manifest(case):
    return reuse.prepare_manifest(case['root'],**case['kwargs'])


def test_three_roles_five_slots_from_full_policy_donors_with_new_source_shot(case):
    bound=manifest(case);bundle=reuse.collect(bound['path'],'S01')
    assert [x['entity_id'] for x in bundle['characters']]==['adult','child','third']
    assert [(r['kind'],r['view']) for r in bundle['references']]==[('character','front')]*3+[('place','front'),('place','side')]
    assert bundle['source_shot']['id']=='S01'
    assert bundle['references'][0]['donor']['source_shot']['id']=='shot1'
    assert bundles.validate(bundle)==bundle
    assert not bundle['production_approved'] and bundle['reuse_contract']==reuse.CONTRACT


def test_prepare_reused_load_disabled_and_claim_unknown_keep_legacy_protections(case,monkeypatch):
    bound=manifest(case);s=case['s'];row=case['kwargs']['segments'][0];run=Path(row['delivery_run'])
    cfg=dict(s['config'],width=736,height=1312,video_enabled=False)
    monkeypatch.setattr(delivery.native,'_http',lambda *a:pytest.fail('CPU prepare/disabled made HTTP call'))
    state=delivery.prepare_reused(bound['path'],'S01',run,cfg)
    assert state['video_enabled'] is False and state['technical_saved']==0
    assert delivery.submit_next(run)['dispatch']=='video_policy_disabled'
    _,plan=delivery._load(run);shot=plan['shots'][0];folder=run/'shots/S01'
    assert plan['asset_run']==case['kwargs']['donor_bundles']['A']['asset_run']
    assert shot['source_shot']['id']=='S01' and shot['timing']['native_frames']==362
    graph=assets.read(folder/'workflow_api.json')
    assets.freeze(folder/'REQUEST.json',dict(prompt=graph,client_id='protocol'))
    assets.freeze(folder/'CLAIM.json',dict(graph_sha256=shot['graph_sha256'],bundle_sha256=shot['bundle_sha256']))
    assert delivery.status(run)['shots'][0]['status']=='outcome_unknown'
    assert not (folder/'RESPONSE.json').exists()


def test_new_scope_cannot_be_prepared_at_another_delivery_path(case):
    bound=manifest(case)
    with pytest.raises(ValueError,match='delivery_scope_changed'):
        delivery.prepare_reused(bound['path'],'S01',case['s']['tmp']/delivery.PREFIX/'wrong',case['s']['config'])


def test_root_approval_and_original_dialogue_are_not_bool_only(case):
    approval=assets.read(case['approval']);approval['approved_for_generation']=False;write(case['approval'],approval)
    case['kwargs']['prompt_approval']=reuse._binding(case['approval'])
    with pytest.raises(ValueError,match='approval_required'):
        manifest(case)


def test_actual_donor_image_change_invalidates_new_bundle(case):
    bound=manifest(case);bundle=reuse.collect(bound['path'],'S01')
    Path(bundle['references'][0]['image']['path']).write_bytes(b'changed source')
    with pytest.raises(ValueError):bundles.validate(bundle)


def test_room_cannot_inject_second_donor_and_role_cannot_take_noncanonical_view(case):
    bad=deepcopy(case['kwargs']);bad['environment']['camera_donor_id']='B'
    with pytest.raises(ValueError,match='single_donor_environment'):
        reuse.prepare_manifest(case['root'],**bad)
    other=case['root'].with_name('other_root')
    bad=deepcopy(case['kwargs']);bad['role_sources'][0]['reference_id']='character:adult:left_profile'
    with pytest.raises(ValueError,match='character_front_required'):
        reuse.prepare_manifest(other,**bad)


def test_new_reused_route_keeps_known_id_when_approved_source_later_changes(case,monkeypatch):
    bound=manifest(case);s=case['s'];run=Path(case['kwargs']['segments'][0]['delivery_run'])
    delivery.prepare_reused(bound['path'],'S01',run,dict(s['config'],width=736,height=1312,video_enabled=True))
    posts,_,_,_=mock_native(monkeypatch,s)
    assert delivery.submit_next(run)['shots'][0]['prompt_id']=='protocol_only_1'
    folder=run/'shots/S01';state=assets.read(folder/'STATE.json');state.update(status='prepared',prompt_id=None);assets.write(folder/'STATE.json',state)
    assert delivery.status(run)['shots'][0]['prompt_id']=='protocol_only_1'
    audit=assets.read(case['audit']);Path(audit['segments'][0]['adapted_prompt_file']['path']).write_bytes(b'changed approved input')
    result=delivery.poll_collect(run)
    assert result['shots'][0]['prompt_id']=='protocol_only_1' and result['shots'][0]['status']=='running'
    assert result['dispatch']=='blocked_upstream_changed'
    with pytest.raises(ValueError):delivery.submit_next(run)
    assert len(posts)==1


def test_dialogue_and_change_replay_are_recomputed_even_with_forged_true_flags(case):
    audit=assets.read(case['audit']);row=audit['segments'][0];path=Path(row['adapted_prompt_file']['path'])
    data=path.read_text(encoding='utf-8').replace('原台词S01','改写后的台词');path.write_text(data,encoding='utf-8')
    row['adapted_prompt_file']=reuse._binding(path);row['adapted_prompt_utf8_sha256']=assets.file_sha(path)
    row['adapted_dialogue_spans']=reuse.dialogue_spans(data);row['dialogue_texts_equal']=True
    write(case['audit'],audit);approval=assets.read(case['approval']);approval['audit']=reuse._binding(case['audit'])
    approval['adapted_prompt_sha256']['S01']=row['adapted_prompt_utf8_sha256'];write(case['approval'],approval)
    with pytest.raises(ValueError,match='changed_original_dialogue_or_unlogged_text'):
        reuse.verify_prompt_adaptation(reuse._binding(case['audit']),reuse._binding(case['approval']))
