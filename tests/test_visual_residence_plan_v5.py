"""CPU-only shared art style contracts; no model or media quality claims."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
import test_visual_novel_rerun_v4 as old_test
from src.content_factory import visual_residence_plan_v5 as flow


class StyleClient:
    def __init__(self,mode='valid'):self.calls=[];self.mode=mode
    def binding(self):return dict(provider='fixture_only',model='not_a_real_model')
    def call(self,messages,schema):
        self.calls.append(deepcopy(messages))
        if self.mode=='unknown':raise TimeoutError('Interrupted without a terminal native receipt')
        material=json.loads(messages[1]['content'])['materials']['source_materials']
        candidate=dict(shared_style={k:values[0] for k,values in flow.STYLE_ENUMS.items()},
            choice_basis=[dict(field=k,source_kind='visual_choice',source_ids=[]) for k in flow.STYLE_ENUMS],functional_overrides=[])
        if self.mode=='wrong_layer':candidate['choice_basis'][0]=dict(field='wall_surface',source_kind='novel_fact',source_ids=[material['screenplay_constraints'][0]['id']])
        if self.mode=='invented_override':candidate['functional_overrides']=[dict(place_id='bedroom',field='floor_surface',value='ceramic_tile',source_ids=[material['screenplay_constraints'][0]['id']])]
        return dict(text=json.dumps(candidate),native=dict(fixture=True),metadata=dict(finish_reason='stop'),completion_known=True)


def setup(tmp_path,*,novel=True):
    origin,data,source=old_test.fixture(tmp_path/'legacy');fake=old_test.Fake();flow.legacy.plan(origin,client=fake)
    # Add an explicit screenplay visual profile without altering source content:
    # the first fixed paragraph already exists and is indexed as a global profile.
    novel_sources=[]
    if novel:
        path=tmp_path/'raw_001.json';text='The family is poor. His bedsheet is dirty. Another room is nearby.'
        old_test.write(path,dict(book_id='fixture_book',index=1,title='Raw chapter',text=text,sha256=hashlib.sha256(text.encode()).hexdigest()))
        novel_sources=[path]
    # The fixture's intro does not claim a specific style. Insert no new fact;
    # test style fields remain visual_choices, and raw paragraphs stay separate.
    run=tmp_path/'visual_residence_plans_v5'/'home_trial'
    flow.prepare(run,origin,home_id='home_a',place_ids=['bedroom','kitchen'],master_place_id='bedroom',
        user_statement='Authorized QA shared style only.',novel_sources=novel_sources)
    return run,origin,source


def test_shared_style_one_call_preserves_all_geometry_and_source_audio(tmp_path):
    run,origin,source=setup(tmp_path);before={str(p):p.read_bytes() for p in origin.rglob('*') if p.is_file()}
    client=StyleClient();flow.plan(run,client=client);assert len(client.calls)==1
    packet=flow.packet(run);group=packet['style_groups'][0]
    assert group['definition_sha256']==flow.fingerprint({k:v for k,v in group.items() if k!='definition_sha256'})
    old=flow.files.read(origin/'PACKET_ALL.json');assert packet['shots']==old['shots']
    assert {r['shot_id'] for r in packet['shot_invalidations']}=={s['id'] for s in old['shots']}
    assert all(r['status']=='needs_restage' for r in packet['shot_invalidations'])
    assert all('home_style_sha256' not in s for s in packet['shots'])
    for place in packet['places']:
        original=next(p for p in old['places'] if p['id']==place['id'])
        assert place['home_style_sha256']==group['definition_sha256']
        assert place['spatial_layout']['room']==original['spatial_layout']['room']
        assert place['spatial_layout']['cameras']==original['spatial_layout']['cameras']
        assert place['spatial_layout']['openings']==original['spatial_layout']['openings']
        for actual,expected in zip(place['spatial_layout']['objects'],original['spatial_layout']['objects']):
            assert {k:actual[k] for k in ('kind','center','size','yaw','base_z')}=={k:expected[k] for k in ('kind','center','size','yaw','base_z')}
        assert place['static_materials']==group['room_materials'][place['id']]
        assert place['design_version']!=original['design_version'] and place['production_approved'] is False
    assert before=={str(p):p.read_bytes() for p in origin.rglob('*') if p.is_file()}
    flow.plan(run,client=client);assert len(client.calls)==1


def test_original_novel_and_screenplay_layers_have_exact_offsets(tmp_path):
    run,origin,source=setup(tmp_path);index=flow._read(run,'SOURCE_INDEX.json')
    assert {r['source_kind'] for r in index.values()}=={'novel_fact'}
    for r in index.values():
        raw=flow.files.read(r['source']['path'])['text']
        assert raw[r['start']:r['end']]==r['text']
        assert hashlib.sha256(r['text'].encode()).hexdigest()==r['sha256']


def test_exact_global_paragraph_index_is_not_a_model_summary():
    text='**世界与时代**：当代中国破旧出租屋。\n\n**画风**：偏冷灰褐。\n\n普通动作。'
    records=flow._paragraphs(text,'SP','screenplay_constraint',dict(path='QA',sha256='QA'))
    assert len(records)==3 and records[0]['text']=='**世界与时代**：当代中国破旧出租屋。'
    assert all(text[r['start']:r['end']]==r['text'] for r in records)


def test_screenplay_concrete_floor_is_scope_bound_and_program_override_wins(tmp_path):
    text='**画风**：破旧住宅。\n\n厨房里的凳脚刮在水泥地上。'
    records=flow._paragraphs(text,'SP','screenplay_constraint',dict(path='QA',sha256='QA'))
    fixed=flow._fixed_materials([dict(id='kitchen',source_facts=dict(scene_ids=['S2']))],
        dict(scenes=[dict(id='S2',metadata=[],blocks=[dict(text=text,start=0)])]),records,{'kitchen'})
    assert fixed==[dict(place_id='kitchen',field='floor_surface',value='concrete',source_ids=[records[1]['id']],source_kind='screenplay_constraint')]
    run,origin,source=setup(tmp_path)
    materials=flow._read(run,'SOURCE_MATERIALS.json');materials['fixed_room_materials']=fixed
    index=flow._read(run,'SOURCE_INDEX.json');index.update({r['id']:r for r in records})
    # Known source fixtures stand in for extraction input; bind each changed QA artifact.
    for name,value in [('SOURCE_INDEX.json',index),('SOURCE_MATERIALS.json',materials)]:
        old_test.write(run/name,value);old_test.write(run/(name+'.binding'),dict(content_sha256=flow.fingerprint(value),plan_sha256=flow.files.file_sha(run/'PLAN.json')))
    flow.plan(run,client=StyleClient())
    packet=flow.packet(run);kitchen=next(p for p in packet['places'] if p['id']=='kitchen')
    assert kitchen['static_materials']['floor_surface']=='concrete'
    assert packet['style_groups'][0]['room_materials']['bedroom']['floor_surface']=='worn_wood'
    home=flow._read(run,'HOME_STYLE.json');assert home['fixed_room_materials'][0]['source_kind']=='screenplay_constraint'


@pytest.mark.parametrize('mode',['wrong_layer','invented_override'])
def test_novel_layer_and_functional_override_are_not_guessed(tmp_path,mode):
    run,origin,source=setup(tmp_path);materials=flow._read(run,'SOURCE_MATERIALS.json');index=flow._read(run,'SOURCE_INDEX.json')
    # A clearly labelled screenplay constraint cannot be promoted to novel_fact.
    r=dict(id='SP_QA',source_kind='screenplay_constraint',text='A screenplay visual choice.',start=0,end=26,sha256='QA',source=dict(path='QA',sha256='QA'))
    materials['screenplay_constraints']=[r];index[r['id']]=r
    for name,value in [('SOURCE_INDEX.json',index),('SOURCE_MATERIALS.json',materials)]:
        old_test.write(run/name,value);old_test.write(run/(name+'.binding'),dict(content_sha256=flow.fingerprint(value),plan_sha256=flow.files.file_sha(run/'PLAN.json')))
    client=StyleClient(mode)
    with pytest.raises(flow.ResidenceBlocked,match='known_shared_style_validation_failed'):flow.plan(run,client=client)
    assert len(client.calls)==2 and not (run/'HOME_STYLE.json').exists()


def test_unknown_shared_call_never_replayed(tmp_path):
    run,origin,source=setup(tmp_path);first=StyleClient('unknown')
    with pytest.raises(flow.ResidenceBlocked,match='unknown_shared_style_call'):flow.plan(run,client=first)
    second=StyleClient()
    with pytest.raises(flow.ResidenceBlocked,match='unknown_shared_style_call'):flow.plan(run,client=second)
    assert len(first.calls)==1 and not second.calls


def test_raw_source_change_blocks_before_model(tmp_path):
    run,origin,source=setup(tmp_path);p=flow.status(run)['plan'];raw=Path(p['novel_sources'][0]['path']);raw.write_text('{}',encoding='utf-8');client=StyleClient()
    with pytest.raises(flow.ResidenceBlocked,match='residence_input_changed'):flow.plan(run,client=client)
    assert not client.calls


def test_unprovided_novel_is_never_claimed_as_read(tmp_path):
    run,origin,source=setup(tmp_path,novel=False);flow.plan(run,client=StyleClient())
    assert flow._read(run,'HOME_STYLE.json')['novel_evidence_status']=='not_supplied'


def test_status_cli_readonly(tmp_path):
    run,origin,source=setup(tmp_path);before={str(p):p.read_bytes() for p in run.rglob('*') if p.is_file()}
    result=subprocess.run([sys.executable,'scripts/run_visual_residence_plan_v5.py','status','--run',str(run)],cwd=flow.legacy.PROJECT,capture_output=True,text=True,timeout=30)
    assert result.returncode==0 and json.loads(result.stdout)['state']['status']=='prepared'
    assert before=={str(p):p.read_bytes() for p in run.rglob('*') if p.is_file()}


def test_background_derivative_invalidates_legacy_frozen_shots_without_rewriting_or_calls(tmp_path):
    run,origin,source=setup(tmp_path);client=StyleClient();flow.plan(run,client=client)
    # Simulate the already-frozen pre-invalidation v5 format; its data stays raw.
    original=flow.packet(run);original.pop('shot_invalidations')
    old_test.write(run/'RESIDENCE_PACKET.json',original)
    old_test.write(run/'RESIDENCE_PACKET.json.binding',dict(content_sha256=flow.fingerprint(original),plan_sha256=flow.files.file_sha(run/'PLAN.json')))
    before={str(p):p.read_bytes() for p in run.rglob('*') if p.is_file()}
    result=flow.background_packet(run)
    assert result['shots']==[] and result['characters']==[]
    assert result['background_derivation']['source_shot_ids']==[s['id'] for s in original['shots']]
    assert result['background_derivation']['source_stage_sha256']==flow.fingerprint(original['shots'])
    assert result['background_derivation']['source_packet']['sha256']==flow.files.file_sha(run/'RESIDENCE_PACKET.json')
    for row in result['shot_invalidations']:
        shot=next(s for s in original['shots'] if s['id']==row['shot_id'])
        assert row['original_stage_sha256']==flow.fingerprint(shot)
        assert row['original_home_style_sha256'] is None and row['status']=='needs_restage'
    assert len(client.calls)==1 and before=={str(p):p.read_bytes() for p in run.rglob('*') if p.is_file()}
    assert 'shot_invalidations' not in flow.packet(run)


def test_inherited_shot_cannot_be_qualified_by_copying_new_style_hash(tmp_path):
    run,origin,source=setup(tmp_path);flow.plan(run,client=StyleClient());value=flow.packet(run)
    for shot in value['shots']:shot['home_style_sha256']=value['style_groups'][0]['definition_sha256']
    records=flow._inherited_shot_invalidations(value)
    assert {r['shot_id'] for r in records}=={s['id'] for s in value['shots']}
    assert all(r['status']=='needs_restage' for r in records)
