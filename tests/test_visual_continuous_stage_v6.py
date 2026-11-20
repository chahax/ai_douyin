"""Continuous source/staging receipts and natural ending contracts; CPU only."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest
import test_visual_residence_plan_v5 as home_test
from src.content_factory import visual_continuous_stage_v6 as flow


def setup(tmp_path):
    home,origin,source=home_test.setup(tmp_path);home_test.flow.plan(home,client=home_test.StyleClient())
    baseline=tmp_path/'baseline_assets';flow.files.prepare(baseline,home_test.flow.packet(home),{})
    run=tmp_path/'visual_continuous_stages_v6'/'opening'
    flow.prepare(run,home,baseline,user_statement='Authorized complete source-exact opening video.',target_seconds=24,tolerance=1)
    return run,home,origin


class Planner:
    def __init__(self,mode='valid'):self.calls=[];self.mode=mode
    def binding(self):return dict(provider='fixture',model='not_a_real_model')
    def call(self,messages,schema):
        self.calls.append(deepcopy(messages));payload=json.loads(messages[1]['content'])['materials'];window=payload['window']
        if self.mode=='unknown':raise TimeoutError('Missing native terminal')
        visible=list(dict.fromkeys(a['speaker'] for a in window['audio_fixed'] if a['mode']=='onscreen'))
        if not visible:visible=['a']
        if self.mode=='hide':visible=[]
        result=dict(id=window['id'],place_id=payload['places'][0]['id'],visible_cast=visible,place_view='front',
            visual_prompt='Alice faces the camera in a medium view, her hand moving naturally.',source_ids=[window['source_units'][0]['id']])
        if self.mode=='wrong_id':result['source_ids']=['S_OTHER_UNIT']
        if self.mode=='reverse':result['place_view']='reverse'
        if self.mode=='unknown_view':result['place_view']='ceiling'
        return dict(text=json.dumps(result),native=dict(fixture=True),metadata=dict(finish_reason='stop'),completion_known=True)


def test_source_exact_prefix_restage_current_style_and_known_receipts(tmp_path):
    run,home,origin=setup(tmp_path);planner=Planner();before={str(p):p.read_bytes() for p in origin.rglob('*') if p.is_file()}
    flow.plan(run,client=planner);assert len(planner.calls)==3
    result=flow.packet(run);assert [s['id'] for s in result['shots']]==['F0001','F0002','F0003']
    baseline=flow._read(run,'BASELINE_PACKET.json');expected_style=baseline['style_groups'][0]['definition_sha256']
    assert result['style_groups']==baseline['style_groups']
    assert not result['shot_invalidations']
    for shot in result['shots']:
        assert shot['home_style_sha256']==expected_style and shot['place_view']=='front'
        assert len(shot['visible_cast'])<=2
        assert shot['staging_provenance']['completion_known'] is True
        for key in ('request','native','result'):
            binding=shot['staging_provenance'][key];assert flow.files.file_sha(binding['path'])==binding['sha256']
        source=Path(result['source']['path']).read_text(encoding='utf-8')
        for sound in shot['audio']:assert source[sound['source_start']:sound['source_end']]==sound['text']=='hello'
    assert all(p['required_views']==['front'] for p in result['places'])
    assert all(c['required_views']==['front'] for c in result['characters'])
    assert result['continuous_staging']['selection']['requested_seconds']==24
    assert before=={str(p):p.read_bytes() for p in origin.rglob('*') if p.is_file()}
    flow.plan(run,client=planner);assert len(planner.calls)==3


def test_natural_prefix_skips_comma_and_chooses_nearest_complete_sentence():
    def seg(name,seconds,text):return dict(id=name,native_seconds=seconds,units=[dict(text=text,audio_items=[dict(text=text)])])
    data=dict(segments=[seg('A',15,'One.'),seg('B',15,'Two,'),seg('C',15,'Three.'),seg('D',15,'Four.')])
    assert flow.choose_prefix(data,target_seconds=31,tolerance=15)['segment_ids']==['A','B','C']
    with pytest.raises(flow.StageBlocked,match='no_natural_boundary'):flow.choose_prefix(data,target_seconds=30,tolerance=1)


def test_unknown_native_is_not_replayed_by_another_planner(tmp_path):
    run,_,_=setup(tmp_path);one=Planner('unknown')
    with pytest.raises(flow.StageBlocked,match='unknown_current_stage_call'):flow.plan(run,client=one)
    two=Planner()
    with pytest.raises(flow.StageBlocked,match='unknown_current_stage_call'):flow.plan(run,client=two)
    assert len(one.calls)==1 and not two.calls


@pytest.mark.parametrize('mode',['wrong_id','hide','unknown_view'])
def test_one_known_format_repair_only_and_raw_receipts_preserved(tmp_path,mode):
    run,_,_=setup(tmp_path);planner=Planner(mode)
    with pytest.raises(flow.StageBlocked,match='known_staging_validation_failed'):flow.plan(run,client=planner)
    assert len(planner.calls)==2 and len(list((run/'calls/F0001').glob('*/NATIVE.json')))==2
    with pytest.raises(flow.StageBlocked):flow.plan(run,client=planner)
    assert len(planner.calls)==2 and not (run/'STAGING_PACKET.json').exists()


def test_baseline_source_mutation_blocks_new_text_calls(tmp_path):
    run,_,_=setup(tmp_path);p=flow.status(run)['plan'];baseline=Path(p['baseline_asset_run'])/'PLAN.json'
    baseline.write_text('{}',encoding='utf-8');planner=Planner()
    with pytest.raises(flow.StageBlocked,match='continuous_input_changed'):flow.plan(run,client=planner)
    assert not planner.calls


def test_status_cli_readonly(tmp_path):
    run,_,_=setup(tmp_path);before={str(p):p.read_bytes() for p in run.rglob('*') if p.is_file()}
    result=subprocess.run([sys.executable,'scripts/run_visual_continuous_stage_v6.py','status','--run',str(run)],cwd=flow.legacy.PROJECT,capture_output=True,text=True,timeout=30)
    assert result.returncode==0 and json.loads(result.stdout)['state']['status']=='prepared'
    assert before=={str(p):p.read_bytes() for p in run.rglob('*') if p.is_file()}


def test_validated_provenance_detects_changed_raw_native_receipt(tmp_path):
    run,_,_=setup(tmp_path);flow.plan(run,client=Planner());value=flow.packet(run)
    assert flow.validate_packet(value) is True
    native=Path(value['shots'][0]['staging_provenance']['native']['path']);native.write_text('{}',encoding='utf-8')
    with pytest.raises(flow.StageBlocked,match='stage_native_binding_changed'):flow.validate_packet(value)


def test_real_camera_choice_requires_that_view_plus_front_parent(tmp_path):
    run,_,_=setup(tmp_path);flow.plan(run,client=Planner('reverse'));value=flow.packet(run)
    assert all(s['place_view']=='reverse' for s in value['shots'])
    assert all(p['required_views']==['front','reverse'] for p in value['places'])
    assert flow.validate_packet(value)


def test_exact_native_frames_use_local_requests_without_ceil_drift():
    from src.content_factory.visual_h3_handoff_v3 import _timing
    for frames in (175,209,226,260,277,311,328,345,362):
        timing=_timing(dict(start=0,end=min(15.0,frames/24)))
        assert timing['native_frames']==frames


def test_offscreen_child_dialogue_keeps_named_speaker_and_is_not_narration():
    segment=dict(units=[dict(audio_items=[dict(speaker='Child',channel='画外对白',text='Brother!',start=1,end=9)])])
    sounds=flow._audio(segment,[dict(id='child',name='Child')])
    assert sounds[0]['mode']=='offscreen_dialogue' and sounds[0]['speaker']=='child'
    assert sounds[0]['text']=='Brother!'
