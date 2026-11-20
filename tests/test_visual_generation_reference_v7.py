"""Explicit native reference isolation and source-bound geometry, no real GPU."""
from copy import deepcopy
import hashlib
from pathlib import Path

from PIL import Image
import pytest

from src.content_factory import visual_generation_reference_v7 as g
from src.content_factory import visual_asset_pipeline_v3 as p
from src.content_factory import visual_asset_registry_v3 as registry
from src.content_factory import visual_image_jobs_v3 as images
from src.content_factory import visual_continuous_stage_v6 as staging
from test_visual_environment_continuation_v6 import setup_origin,tree
from test_visual_asset_pipeline_v3 import service
from test_visual_environment_v4 import place


def policy_run(tmp_path,service):
    origin,run=setup_origin(tmp_path,service);plan=p.read(origin/'PLAN.json');packet=deepcopy(plan['packet'])
    packet['places'][0]['required_views']=['front','reverse']
    config=g.bind(origin,run,packet);config['image_service']['allowed_prefix']='isolated_reference_v7'
    p.prepare(run,packet,config)
    return origin,run,p.read(run/'PLAN.json'),p.read(run/'STATE.json')


def requirement(plan,pid='master',view='reverse'):
    entity=next(e for e in plan['packet']['places'] if e['id']==pid)
    return dict(entity_id=pid,kind='place',view=view,design_version=entity['design_version'])


def test_policy_is_explicit_and_origin_binding_cannot_be_implicitly_inherited():
    assert not g.enabled({})
    for config in [dict(generation_reference_policy='guess/v9'),dict(generation_reference_origin={}),
                   dict(generation_reference_policy=g.POLICY),
                   dict(generation_reference_policy=g.POLICY,generation_reference_origin={},environment_continuation={'x':1})]:
        with pytest.raises(ValueError):g.enabled(config)


def test_same_room_front_is_dependency_and_audit_only_native_graph_is_guide_and_crops(tmp_path,service):
    origin,run,plan,state=policy_run(tmp_path,service);before=tree(origin);posts=len(service.posts)
    req=requirement(plan);front=p._lookup(plan,{**req,'view':'front'})
    assert g.baseline_front(plan,front) and front['status']=='reviewed'
    jid=p._generation(run,plan,state,req);task=state['jobs'][jid];binding=task['generation_reference']
    job=images._read(Path(task['folder'])/'PLAN.json');graph=images._read(Path(task['folder'])/'workflow_api.json')
    assert [q['role'] for q in binding['inputs']]==['geometry','material:wall','material:floor','material:wood']
    assert len(job['inputs'])==4 and len([n for n in graph.values() if n['class_type']=='LoadImage'])==4
    assert all(q['sha256']!=front['sha256'] for q in job['inputs'])
    assert task['dependencies']==[p._asset_identity(front)]
    entity=plan['packet']['places'][0];inputs,roles=p._isolated_place_inputs(plan,entity,task['environment_guide'])
    g.verify_job(plan,binding,'place_asset',inputs,roles)
    assert tree(origin)==before and len(service.posts)==posts # Preparation makes no model request.
    images.submit(task['folder']);images.poll(task['folder']);receipt=images.collect(task['folder'])
    g.verify_job(plan,binding,'place_asset',inputs,roles,receipt=receipt)
    p._collect_generated(run,plan,state,jid,receipt)
    row=p._raw_lookup(plan,req)
    assert row['provenance']['generation_reference']==binding
    assert p._dependencies(plan,row)[1] is True
    assert tree(origin)==before and len(service.posts)==posts+1


def test_native_provenance_rejects_changed_input_graph_or_receipt(tmp_path,service):
    _,run,plan,state=policy_run(tmp_path,service);jid=p._generation(run,plan,state,requirement(plan));task=state['jobs'][jid]
    entity=plan['packet']['places'][0];inputs,roles=p._isolated_place_inputs(plan,entity,task['environment_guide'])
    paths=[Path(task['folder'])/'workflow_api.json',Path(task['folder'])/'PLAN.json',Path(inputs[0]['path'])]
    original={path:path.read_bytes() for path in paths}
    for mutation in ['binding','graph','plan','receipt','input','missing_receipt']:
        binding=deepcopy(task['generation_reference']);receipt=None
        if mutation=='binding':binding['inputs'][0]['role']='complete_room'
        elif mutation=='graph':
            path=paths[0];graph=p.read(path)
            next(node for node in graph.values() if node['class_type']=='LoadImage')['inputs']['image']='hidden_fullfront.png'
            p.write(path,graph)
        elif mutation=='plan':
            value=p.read(paths[1]);value['job_id']='another_job';p.write(paths[1],value)
        elif mutation=='receipt':receipt=dict(job_id='unknown',graph_sha256='bad',inputs_sha256='bad')
        elif mutation=='input':paths[2].write_bytes(b'changed')
        with pytest.raises(ValueError):
            g.verify_job(plan,binding,'place_asset',inputs,roles,receipt=receipt,require_receipt=mutation=='missing_receipt')
        for path,raw in original.items():path.write_bytes(raw)


def test_old_fullfront_generated_view_has_no_new_policy_qualification(tmp_path,service):
    _,run,plan,state=policy_run(tmp_path,service);req=requirement(plan);front=p._lookup(plan,{**req,'view':'front'})
    guide=p._environment_guide(run,plan['packet']['places'][0],'reverse')
    path=tmp_path/'old_reverse.png';Image.new('RGB',(768,1024),'blue').save(path)
    row=registry.register(plan['config']['library'],path,book_id='book1',**req,
        provenance=dict(environment_guide=guide,dependencies=[p._asset_identity(front)],
                        dependency_fingerprint=p.fingerprint([p._asset_identity(front)])))
    assert p._dependencies(plan,row)==([],False)
    assert p._lookup(plan,req)['dependency_stale'] is True


def test_scope_expansion_or_unbound_staging_stops_before_new_run_write(tmp_path,service):
    origin,run=setup_origin(tmp_path,service);base=deepcopy(p.read(origin/'PLAN.json')['packet']);base_config=g.bind(origin,run,base)
    for change in [lambda packet,config:packet.update(book_id='another_book'),
                   lambda packet,config:packet['places'][0].update(design_version='unbound_revision'),
                   lambda packet,config:packet['style_groups'][0].update(style_version='changed'),
                   lambda packet,config:config['visual_review'].update(model='different'),
                   lambda packet,config:config.update(style_reference_root='different_root'),
                   lambda packet,config:packet['characters'].append(dict(id='actor'))]:
        packet=deepcopy(base);config=deepcopy(base_config);change(packet,config)
        with pytest.raises((ValueError,KeyError)):p.prepare(run,packet,config)
        assert not run.exists()


def test_new_policy_firstframe_keeps_actor_pixels_guide_crops_but_omits_room_pixels(tmp_path,service,monkeypatch):
    origin,run=setup_origin(tmp_path,service);old=p.read(origin/'PLAN.json');packet=deepcopy(old['packet'])
    actor=dict(id='actor',design_version='v1',required_views=['front'],front_prompt='One fictional adult.',age_band='adult')
    packet['characters']=[actor];packet['stage_contract']='continuous_source_home_staging/v6'
    monkeypatch.setattr(staging,'validate_packet',lambda value:True) # Protocol fixture, not semantic staging approval.
    config=g.bind(origin,run,packet);p.prepare(run,packet,config);plan=p.read(run/'PLAN.json');state=p.read(run/'STATE.json')
    path=tmp_path/'actor.png';Image.new('RGB',(768,1024),'red').save(path)
    row=registry.register(config['library'],path,book_id='book1',entity_id='actor',kind='character',view='front',design_version='v1')
    front=p._lookup(plan,requirement(plan,view='front'))
    shot=dict(id='first',place_id='master',place_view='front',visible_cast=['actor'],visual_prompt='The actor stands near the bed.',
              home_style_sha256=packet['style_groups'][0]['definition_sha256'],references=[row,front],binding_sha256='a'*64)
    jid=p._prepare_first_frame(run,plan,state,shot);task=state['jobs'][jid];binding=task['generation_reference']
    assert [q['role'] for q in binding['inputs']]==['geometry','character:actor','material:wall','material:floor','material:wood']
    assert all(q['sha256']!=front['sha256'] for q in binding['inputs'])
    assert any(q['sha256']==row['sha256'] for q in binding['inputs'])
    images.submit(task['folder']);images.poll(task['folder']);receipt=images.collect(task['folder'])
    p._collect_generated(run,plan,state,jid,receipt);frame=state['first_frames'][shot['id']]
    p._verify_first_frame_generation(plan,shot,frame)
    frame['generation_reference']['full_room_images_in_generation']=True
    with pytest.raises(ValueError,match='binding_changed'):p._verify_first_frame_generation(plan,shot,frame)


def revision_fixture(tmp_path):
    source=tmp_path/'source.md';text='Before. He put the bread on an old wooden table. After.';source.write_text(text,encoding='utf-8')
    quote='He put the bread on an old wooden table.';start=text.index(quote)
    evidence=[dict(id='source_table',start=start,end=start+len(quote),text=quote,sha256=hashlib.sha256(quote.encode()).hexdigest())]
    entity=place();entity['spatial_layout']['objects']=entity['spatial_layout']['objects'][:1]
    packet=dict(source=dict(path=str(source),sha256=p.file_sha(source)),places=[entity])
    table=dict(id='source_table',kind='table',description='One old wooden table.',center=[3,3.6],size=[.8,.7,.75],yaw=0,base_z=0,color='brown')
    return packet,table,evidence


def test_source_bound_table_revision_changes_version_and_preserves_every_old_layout_field(tmp_path):
    packet,table,evidence=revision_fixture(tmp_path);before=deepcopy(packet)
    revision=g.add_source_table(packet,'room',table,evidence,'Table size/position are explicit art choices, not source measurements.')
    new=g.validate_place_revision(packet['places'][0],revision,packet['source'])
    assert packet==before and new['design_version']!=before['places'][0]['design_version']
    assert new['spatial_layout']['objects'][:-1]==before['places'][0]['spatial_layout']['objects']
    assert new['spatial_layout']['cameras']==before['places'][0]['spatial_layout']['cameras']
    revision['new_place']['spatial_layout']['cameras']['front']['fov']=60
    with pytest.raises(ValueError,match='only_add_one_table'):g.validate_place_revision(packet['places'][0],revision,packet['source'])


@pytest.mark.parametrize('change',[
    lambda packet,table,evidence:evidence[0].update(text='He guessed there was a table.'),
    lambda packet,table,evidence:evidence[0].update(start=0),
    lambda packet,table,evidence:evidence[0].update(sha256='0'*64),
    lambda packet,table,evidence:table.update(center=[.9,2.6]),
    lambda packet,table,evidence:table.update(kind='cabinet'),
    lambda packet,table,evidence:packet['places'][0]['spatial_layout']['objects'].append(deepcopy(table)),
])
def test_unbound_quote_duplicate_table_or_colliding_art_choice_are_rejected(tmp_path,change):
    packet,table,evidence=revision_fixture(tmp_path);change(packet,table,evidence)
    with pytest.raises(ValueError):g.add_source_table(packet,'room',table,evidence,'Explicit art placement.')


def test_revision_artifact_and_exact_baseline_design_are_independently_bound(tmp_path,service,monkeypatch):
    origin,run=setup_origin(tmp_path,service);old=p.read(origin/'PLAN.json');packet=deepcopy(old['packet'])
    pid='room2';entity=next(x for x in packet['places'] if x['id']==pid)
    config=g.bind(origin,run,packet);plan=dict(packet=packet,config=config)
    row=p._lookup(old,requirement(old,pid,view='front'));assert g.baseline_front(plan,row)
    entity['design_version']='revised_with_no_valid_delta';assert not g.baseline_front(plan,row)
    with pytest.raises(ValueError):g.validate(run,packet,config)
    entity['design_version']=row['design_version']
    # The synthetic room already has a table; a malformed or no-op revision may not become permission.
    packet['stage_contract']='continuous_source_home_staging/v6';monkeypatch.setattr(staging,'validate_packet',lambda value:True)
    artifact=tmp_path/'revision.json';p.write(artifact,dict(schema=g.REVISION,place_id=pid))
    packet['asset_revision']=dict(revisions=[dict(path=str(artifact),sha256=p.file_sha(artifact))])
    with pytest.raises((ValueError,KeyError)):g.bind(origin,run,packet)
    artifact.write_bytes(b'changed')
    with pytest.raises(ValueError,match='revision_file_changed'):g.bind(origin,run,packet)
