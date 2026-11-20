import importlib.util
from pathlib import Path
import subprocess
import pytest


def load(name,file):
    path=Path(__file__).resolve().parents[1]/'scripts'/file
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


p=load('coverage_test','prepare_h3_full_script_coverage_20261102.py')
m=load('full_script_test','run_h3_full_script_20261102.py')


def test_real_source_coverage_and_audio_exactly_once():
    text=p.SOURCE.read_text(encoding='utf-8');scenes,refs=p.parse(text);segments=p.plan_segments(scenes)
    result=p.verify_coverage(text,scenes,segments)
    assert len(scenes)==15 and result['performance_blocks']==228
    for scene in scenes:
        for block in scene['blocks']:
            items=[a for unit in scene['units'] if unit['parent']==block['id'] for a in unit['audio_items']]
            assert ''.join(a['text'] for a in items)==''.join(a['text'] for a in block['sound_spans'])
            assert all(text[a['start']:a['end']]==a['text'] for a in items)
    assert all(124<=s['native_frames']<=362 and (s['native_frames']-5)%17==0 for s in segments)
    assert len(set(s['native_frames'] for s in segments))>3
    assert any(s['reference_strategy']=='scene_entry_requires_asset_decision' for s in segments)


def test_long_narrator_split_keeps_channel_and_speaker():
    text=p.SOURCE.read_text(encoding='utf-8');scenes,_=p.parse(text)
    items=[a for u in scenes[0]['units'] if u['parent']=='CH01_SC01_P009' for a in u['audio_items']]
    assert len(items)>1
    assert {a['channel'] for a in items}=={'旁白'}
    assert {a['speaker'] for a in items}=={'中性旁白'}
    assert all(a['parent_context_only'] for a in items)


def test_mixed_action_and_mind_voice_retains_visible_action():
    text='叶东（近景，拳头攥得发白）\n叶东（心声）果然，他不肯放过小六！'
    start=text.index('果然')
    unit=dict(text=text,start=100,audio_items=[dict(start=100+start,end=100+len(text))])
    visible=m.visible_text(unit)
    assert '拳头攥得发白' in visible
    assert '果然' not in visible and '心声' not in visible


def test_prior_error_stops_even_when_not_completed(tmp_path,monkeypatch):
    graph=tmp_path/'workflow_api.json';m.h.durable(graph,{'a':1})
    plan=dict(pending_prior_task=dict(run=str(tmp_path),prompt_id='known',graph=m.h.binding(graph)))
    monkeypatch.setattr(m,'validate',lambda *a,**kw:plan)
    class Client:
        def get(self,path):
            return {'known':dict(prompt=[0,'known',{'a':1}],status=dict(status_str='error',completed=False))}
    with pytest.raises(ValueError,match='prior_task_failed'):
        m.drain_prior(tmp_path,Client(),sleep=lambda _:pytest.fail('must not sleep after known failure'))
    assert (tmp_path/'PRIOR_TASK_FAILED.json').exists()


def test_ref_graph_has_explicit_ref_model_inputs_and_variable_last_index():
    base=m.h.read(m.b.SERVICE/'workflow_api.json')
    refs=[dict(input_name='one.png'),dict(input_name='two.png')]
    graph=m.build_graph(base,'same source',dict(id='F0101',native_frames=141),'REF2VA',refs)
    assert graph['condition']['class_type']=='MiniMaxH3ReferenceToVideo'
    assert graph['condition']['inputs']['ref_images.ref_image_1']==['reference_1',0]
    assert 'ref2va' in graph['127']['inputs']['unet_name']
    assert graph['pick_last']['inputs']['batch_index']==140
    assert graph['condition']['inputs']['length']==141
    assert base['condition']['inputs']['length']==362


def test_full_manifest_arbitrary_count_stops_at_failure_and_restores_adapter(tmp_path,monkeypatch):
    root=tmp_path/'run';root.mkdir()
    plan={'segments':[dict(id=f'F{i:04d}') for i in range(1,8)]}
    monkeypatch.setattr(m,'validate',lambda *a,**kw:plan)
    monkeypatch.setattr(m,'drain_prior',lambda *a,**kw:None)
    visited=[]
    def segment(batch,run,previous,client,**kw):
        visited.append(run.name)
        if len(visited)==5:raise TimeoutError('unknown original task retained')
        return dict(prompt_id=run.name)
    old=m.b.freeze_predecessor
    monkeypatch.setattr(m.b,'execute_segment',segment)
    with pytest.raises(TimeoutError):m.execute(root,client=object())
    assert visited==[f'F{i:04d}' for i in range(1,6)]
    assert m.b.freeze_predecessor is old
    assert m.h.read(root/'STATE.json')['status']=='stopped'


def test_variable_duration_real_ffmpeg_assembly(tmp_path):
    receipts=[]
    for n in (124,192,141):
        target=tmp_path/f'synthetic_{n}.mp4'
        command=['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=black:s=720x1280:r=24',
                 '-f','lavfi','-i','anullsrc=r=32000:cl=stereo','-t',f'{n/24:.12f}','-c:v','libx264','-preset','ultrafast',
                 '-threads','2','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(target)]
        subprocess.run(command,capture_output=True,check=True)
        receipts.append(dict(frames=n,delivery=m.h.binding(target)))
    result=m.assembly_group(tmp_path/'combined',receipts,'variable')
    assert result['frames']==457 and result['pts_continuous']
    video,audio=m.b.streams(result['metadata'])
    assert abs(float(video['duration'])-457/24)<.001
    assert abs(float(audio['duration'])-457/24)<.05
