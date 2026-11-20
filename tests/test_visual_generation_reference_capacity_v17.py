"""CPU proof/config contracts only; no production preparation or media dispatch."""
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from src.content_factory import visual_asset_pipeline_v3 as p
from src.content_factory import visual_environment_continuation_v6 as continuation
from src.content_factory import visual_generation_reference_v7 as g


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def binding(path):return dict(path=str(path.resolve()),sha256=sha(path))


@pytest.fixture
def case(tmp_path,monkeypatch):
    origin=tmp_path/'origin';origin.mkdir();source=tmp_path/'SOURCE.md';source.write_text('CPU proof fixture.',encoding='utf-8')
    old=dict(library=str(tmp_path/'library'),gpu_lock_root=str(tmp_path/'gpu'),protected_pause_path=str(tmp_path/'PAUSE.json'),
        image_service=dict(service_url='http://127.0.0.1:1',input_root=str(tmp_path/'input'),output_root=str(tmp_path/'output'),allowed_prefix='qa'),
        visual_review=dict(provider='fixture',model='same_model',timeout=900,max_tokens=1800),max_review_attempts=2,max_repair_rounds=1,
        release_comfy_before_review=True)
    new=deepcopy(old);new['visual_review']['max_tokens']=4096
    packet=dict(schema='visual_asset_packet/v3',book_id='QA_BOOK',source=binding(source),style_groups=[],places=[],characters=[],shots=[])
    plan=dict(packet=packet,config=deepcopy(old));p.write(origin/'PLAN.json',plan)
    snapshot=dict(origin_run=str(origin),origin_plan_sha256=sha(origin/'PLAN.json'),origin_reference_root=str(tmp_path/'styles'))
    monkeypatch.setattr(continuation,'_origin_snapshot',lambda run:(deepcopy(snapshot),deepcopy(plan)))
    old_file=tmp_path/'OLD_CONFIG.json';new_file=tmp_path/'NEW_CONFIG.json';p.write(old_file,old);p.write(new_file,new)
    targets=[tmp_path/f'new_target_{i}' for i in range(6)]
    authorization=dict(schema='known_visual_review_capacity_amendment/v17',authorization='Explicit authorized local production repair.',cause='Known non-EOS output at old capacity.',
        old_config=binding(old_file),new_config=binding(new_file),changed_fields={'visual_review.max_tokens':dict(old=1800,new=4096)},
        max_review_attempts=2,source_modified=False,old_run_plan_modified=False,unknown_replay=False)
    auth_file=tmp_path/'AUTHORIZATION.json';p.write(auth_file,authorization)
    proof=dict(schema=g.CAPACITY_SCHEMA,origin_run=str(origin),origin_plan_sha256=snapshot['origin_plan_sha256'],
        old_config=binding(old_file),new_config=binding(new_file),target_runs=[str(x) for x in targets],
        change=dict(field='visual_review.max_tokens',old=1800,new=4096),authorization=dict(evidence=binding(auth_file),text=authorization['authorization']),reason=authorization['cause'])
    proof_file=tmp_path/'REFERENCE_CAPACITY.json';p.write(proof_file,proof)
    return dict(origin=origin,target=targets[0],targets=targets,old=old,new=new,packet=packet,plan=plan,old_file=old_file,new_file=new_file,
                authorization=authorization,auth_file=auth_file,proof=proof,proof_file=proof_file)


def refresh(c):
    p.write(c['old_file'],c['old']);p.write(c['new_file'],c['new'])
    c['proof'].update(old_config=binding(c['old_file']),new_config=binding(c['new_file']))
    c['authorization'].update(old_config=c['proof']['old_config'],new_config=c['proof']['new_config'])
    p.write(c['auth_file'],c['authorization']);c['proof']['authorization']['evidence']=binding(c['auth_file'])
    p.write(c['proof_file'],c['proof']);return binding(c['proof_file'])


def bind(c,**kw):
    return g.bind(c['origin'],kw.pop('target',c['target']),c['packet'],base_config=kw.pop('base_config',c['new']),
                  capacity_amendment=kw.pop('capacity_amendment',binding(c['proof_file'])),**kw)


def test_default_review_equality_remains_strict_and_explicit_amendment_is_readonly(case):
    c=case;old=c['old_file'].read_bytes();origin=(c['origin']/'PLAN.json').read_bytes()
    with pytest.raises(ValueError,match='runtime_or_review_changed:visual_review'):
        g.bind(c['origin'],c['target'],c['packet'],base_config=c['new'])
    config=bind(c);assert config['visual_review']['max_tokens']==4096
    assert config[g.CAPACITY_KEY]==binding(c['proof_file'])
    g.validate(c['target'],c['packet'],config);g.validate(c['target'],c['packet'],config)
    assert not c['target'].exists() and c['old_file'].read_bytes()==old and (c['origin']/'PLAN.json').read_bytes()==origin


def test_new_config_key_passes_temporary_prepare_and_frozen_validation_cannot_change(case):
    c=case;config=bind(c);p.prepare(c['target'],c['packet'],config)
    before=(c['target']/'PLAN.json').read_bytes()
    assert p.status(c['target'])['plan']['config'][g.CAPACITY_KEY]==binding(c['proof_file'])
    with pytest.raises(ValueError,match='first_bind_requires_unprepared'):bind(c)
    wrong=deepcopy(config);wrong['max_repair_rounds']=2
    with pytest.raises(ValueError,match='frozen_run_config_changed'):g.validate(c['target'],c['packet'],wrong)
    assert (c['target']/'PLAN.json').read_bytes()==before


def test_existing_unamended_plan_cannot_be_silently_upgraded(case):
    c=case;old=g.bind(c['origin'],c['target'],c['packet'],base_config=c['old']);p.prepare(c['target'],c['packet'],old)
    before=(c['target']/'PLAN.json').read_bytes()
    with pytest.raises(ValueError,match='first_bind_requires_unprepared'):bind(c)
    upgraded=deepcopy(old);upgraded['visual_review']=c['new']['visual_review'];upgraded[g.CAPACITY_KEY]=binding(c['proof_file'])
    with pytest.raises(ValueError,match='frozen_run_config_changed'):g.validate(c['target'],c['packet'],upgraded)
    assert (c['target']/'PLAN.json').read_bytes()==before


@pytest.mark.parametrize('change',[
    lambda c:c['new']['visual_review'].update(model='other_model'),
    lambda c:c['new']['visual_review'].update(provider='other_provider'),
    lambda c:c['new']['visual_review'].update(timeout=1200),
    lambda c:c['new']['visual_review'].update(max_tokens=4097),
    lambda c:c['new']['visual_review'].update(max_tokens=1024),
    lambda c:c['new']['visual_review'].update(max_tokens=4096.0),
    lambda c:c['new'].update(max_review_attempts=3),
    lambda c:c['new']['image_service'].update(service_url='http://127.0.0.1:2'),
    lambda c:c['old']['visual_review'].update(max_tokens=1800.0),
])
def test_even_rehashed_proof_cannot_authorize_other_config_or_capacity_changes(case,change):
    c=case;change(c);proof=refresh(c)
    with pytest.raises(ValueError):bind(c,capacity_amendment=proof)
    assert not c['target'].exists()


@pytest.mark.parametrize('change',[
    lambda c:c['proof']['target_runs'].append(str(c['target'].with_name('seventh'))),
    lambda c:c['proof']['target_runs'].pop(),
    lambda c:c['proof']['target_runs'].__setitem__(1,c['proof']['target_runs'][0]),
    lambda c:c['proof']['target_runs'].__setitem__(1,str(c['origin']/'nested')),
    lambda c:c['proof'].update(origin_plan_sha256='f'*64),
    lambda c:c['proof'].update(reason='unbound reason'),
    lambda c:c['proof']['authorization'].update(text='unbound authorization'),
    lambda c:c['authorization'].update(unknown_replay=True),
    lambda c:c['authorization'].update(old_run_plan_modified=True),
    lambda c:c['authorization'].update(max_review_attempts=3),
])
def test_scope_authorization_and_original_evidence_are_mandatory(case,change):
    c=case;change(c);proof=refresh(c)
    with pytest.raises(ValueError):bind(c,capacity_amendment=proof)
    assert not c['target'].exists()


def test_unlisted_run_tampered_evidence_or_implicit_amendment_never_passes(case):
    c=case
    with pytest.raises(ValueError,match='target_not_authorized'):bind(c,target=c['target'].with_name('unlisted'))
    raw=binding(c['proof_file']);c['proof_file'].write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError,match='proof_changed'):bind(c,capacity_amendment=raw)
    for config in [{g.CAPACITY_KEY:raw},dict(c['new'],**{g.CAPACITY_KEY:raw})]:
        with pytest.raises(ValueError):g.enabled(config)


def test_valid_amendment_does_not_bypass_existing_runtime_guards(case):
    c=case;config=bind(c);config['library']='different_library'
    with pytest.raises(ValueError,match='other_runtime_changed|runtime_or_review_changed:library'):g.validate(c['target'],c['packet'],config)
    config=bind(c);config['visual_review']['model']='different_model'
    with pytest.raises(ValueError,match='review_model_or_runtime_changed'):g.validate(c['target'],c['packet'],config)


@pytest.mark.parametrize('change',[
    lambda config:config.update(max_review_attempts=3),
    lambda config:config.update(release_comfy_before_review=False),
    lambda config:config.update(max_repair_rounds=999),
    lambda config:config['image_service'].update(output_root='elsewhere'),
])
def test_current_runtime_cannot_expand_proof_even_when_config_files_are_unchanged(case,change):
    config=deepcopy(case['new']);change(config)
    with pytest.raises(ValueError):bind(case,base_config=config)
    assert not case['target'].exists()


def test_rehashed_old_and_new_files_cannot_redefine_the_original_review_budget(case):
    c=case;c['old']['max_review_attempts']=3;c['new']['max_review_attempts']=3
    proof=refresh(c)
    with pytest.raises(ValueError,match='old_config_not_origin'):bind(c,capacity_amendment=proof)
    assert not c['target'].exists()


def test_rehashed_old_and_new_files_cannot_omit_original_runtime_switches(case):
    c=case;c['old'].pop('release_comfy_before_review');c['new'].pop('release_comfy_before_review')
    proof=refresh(c)
    with pytest.raises(ValueError,match='old_config_not_origin'):bind(c,capacity_amendment=proof)
    assert not c['target'].exists()
