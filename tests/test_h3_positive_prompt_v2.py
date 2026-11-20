"""Positive content projection, exact dialogue and reference-only graph isolation."""
import copy
import json

import pytest

from src.content_factory import h3_positive_prompt_v2 as compiler


@pytest.fixture
def screenplay():
    segment=dict(id='S01',duration_seconds=15,shot_visual='双人中景，镜头沿桌角缓缓靠近。',
                 location_time='ADMIN_LOCATION_MARKER',start_state='ADMIN_START_MARKER',
                 end_state='ADMIN_END_MARKER',causal_context='不要生成 ADMIN_CAUSAL_MARKER',
                 beats=[dict(start_s=0,end_s=7,action_visual='桂芳放下笔，抬眼看向马涛。',
                             dialogue=[dict(speaker='C01',text='我没提辞职。')]),
                        dict(start_s=7,end_s=15,action_visual='马涛收回手，低头看表格。',
                             dialogue=[dict(speaker='C02',text='我把安排写下来。')])])
    segments=[]
    for sid in compiler.SEGMENTS:
        row=copy.deepcopy(segment);row['id']=sid;segments.append(row)
    return dict(world=dict(scene_visual='清晨的超市值班室，桌上摊着工作本。',
                           character_visuals=dict(C01='周桂芳，中年女员工，黑色齐肩直发，穿灰蓝开衫。',C02='马涛，男经理，棕色短发，穿米驼衬衫。'),
                           sound_visual='室内轻微工作声，两人自然普通话交谈。',
                           admin='WORLD_ADMIN_MARKER 不生成后续内容。'),segments=segments,
                metadata='FULL_METADATA_MARKER')


def test_metadata_never_leaks_and_negative_dialogue_is_exact(screenplay):
    compiler.validate_screenplay(screenplay)
    prompt=compiler.compile_prompt(screenplay,screenplay['segments'][0])
    assert '周桂芳用自然普通话说：“我没提辞职。”' in prompt
    assert '马涛用自然普通话说：“我把安排写下来。”' in prompt
    assert all(marker not in prompt for marker in ('ADMIN','MARKER','不生成','本段','world','causal_context'))
    assert prompt.count('<Picture 1>')==prompt.count('<Picture 2>')==prompt.count('<Picture 3>')==1
    assert '<Picture 4>' not in prompt
    assert prompt.splitlines()[1]=='<Picture 2>：'+screenplay['world']['character_visuals']['C01']
    assert prompt.splitlines()[2]=='<Picture 3>：'+screenplay['world']['character_visuals']['C02']
    assert '周桂芳，周桂芳' not in prompt and '马涛，马涛' not in prompt


@pytest.mark.parametrize('field',['scene_visual','shot_visual','action_visual'])
@pytest.mark.parametrize('directive',['本段只生成两人说话。','不要生成新人物。','不生成字幕。','禁止添加第三位演员。'])
def test_production_controls_in_visual_fields_rejected(screenplay,field,directive):
    if field=='scene_visual':screenplay['world'][field]=directive
    elif field=='shot_visual':screenplay['segments'][0][field]=directive
    else:screenplay['segments'][0]['beats'][0][field]=directive
    with pytest.raises(ValueError,match='production directive'):compiler.validate_screenplay(screenplay)


def test_exact_two_actor_fields_and_known_speaker_required(screenplay):
    missing=copy.deepcopy(screenplay);del missing['world']['character_visuals']['C02']
    with pytest.raises(ValueError,match='exactly'):compiler.validate_screenplay(missing)
    extra=copy.deepcopy(screenplay);extra['world']['character_visuals']['C03']='第三人'
    with pytest.raises(ValueError,match='exactly'):compiler.validate_screenplay(extra)
    screenplay['segments'][0]['beats'][0]['dialogue'][0]['speaker']='C03'
    with pytest.raises(ValueError,match='unknown actor'):compiler.validate_screenplay(screenplay)


@pytest.mark.parametrize('change',[('duration',14),('start',-1),('end',16),('gap',8),('nan',float('nan'))])
def test_duration_and_timeline_are_bounded(screenplay,change):
    key,value=change;segment=screenplay['segments'][0]
    if key=='duration':segment['duration_seconds']=value
    elif key=='start':segment['beats'][0]['start_s']=value
    elif key=='end':segment['beats'][-1]['end_s']=value
    elif key=='gap':segment['beats'][-1]['start_s']=value
    else:segment['beats'][0]['end_s']=value
    with pytest.raises(ValueError):compiler.validate_screenplay(screenplay)


def test_new_s01_graph_is_reference_only_and_baseline_byte_unchanged(screenplay):
    before=compiler.BASELINE.read_bytes()
    baseline=json.loads(before);original=copy.deepcopy(baseline)
    compiler.validate_screenplay(screenplay)
    prompt=compiler.compile_prompt(screenplay,screenplay['segments'][0])
    parameters=dict(prompt=prompt,noise_seed=2026101801,reference_images=[compiler.PREFIX+'/'+name for name in ('scene.png','C01.jpg','C02.jpg')],
                    output_prefix=compiler.PREFIX+'/S01')
    graph=compiler.compile_graph(baseline,compiler.source_recipe(),parameters)
    assert len(graph)==22 and baseline==original and compiler.BASELINE.read_bytes()==before
    assert compiler.sha(compiler.BASELINE)==compiler.BASE_SHA
    assert not any(node['class_type'] in ('LoadAudio','MiniMaxH3AddGuide') for node in graph.values())
    assert graph['126']['inputs']['conditioning']==['condition',0]
    assert graph['125']['inputs']['latent_image']==['condition',1]
    assert graph['condition']['inputs']['prompt']==prompt
    assert not any('ref_audio' in key or key=='audio_vae' for key in graph['condition']['inputs'])
    assert [graph[node]['inputs']['image'] for node in ('ref_scene','ref_C01','ref_C02')]==parameters['reference_images']
    image_paths=[node['inputs']['image'] for node in graph.values() if node['class_type']=='LoadImage']
    assert len(image_paths)==3 and all('board' not in path.lower() and 'tail' not in path.lower() for path in image_paths)
    bad=copy.deepcopy(parameters);bad['reference_images'][1]='old/rejected/native_last.png'
    with pytest.raises(ValueError):compiler.compile_graph(baseline,compiler.source_recipe(),bad)


def test_board_source_format_is_rejected(tmp_path):
    source=tmp_path/'C01_BOARD.png';source.write_bytes(b'encoded-placeholder')
    scene=tmp_path/'scene.png';scene.write_bytes(b'scene')
    second=tmp_path/'portrait.jpg';second.write_bytes(b'person')
    rows=[dict(picture=i,role=role,kind=kind,source=compiler.binding(path),human_approved=False,
               staged_image_relative_path=compiler.PREFIX+'/'+path.name)
          for i,role,kind,path in [(1,'scene','empty_scene',scene),(2,'C01','single_person_portrait',source),(3,'C02','single_person_portrait',second)]]
    with pytest.raises(ValueError,match='multi-view'):compiler.validate_references(rows)
