"""CPU patterns + protocol ASR fixtures, never model-generated media/semantic QA."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

from PIL import Image
import pytest

from scripts import qa_h3_reference_full_minute_cpu as qa


@pytest.fixture(scope='module')
def cpu_media(tmp_path_factory):
    root=tmp_path_factory.mktemp('reference_minute_CPU_FIXTURE')
    for name,frames in [('native',362),('final',1448)]:
        seconds=frames/24;path=root/(name+'.mp4')
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=gray:s=736x1312:r=24','-f','lavfi','-i','anullsrc=r=48000:cl=stereo',
            '-frames:v',str(frames),'-t',str(seconds),'-c:v','libx264','-preset','ultrafast','-threads','2','-pix_fmt','yuv420p','-c:a','aac','-ar','48000',
            '-video_track_timescale','12288','-movie_timescale','48000',str(path)],check=True,timeout=90)
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t',str(362/24),'-c:a','flac',str(root/'audio.flac')],check=True,timeout=30)
    Image.new('RGB',(736,1312),'gray').save(root/'frame.png')
    return root


TEXTS={
 'S01':['二哥，今天没偷到钱，怎么办呀？','哥哥发传单挣了十块，先给你。','不行，你没交上钱，他会打你的。'],
 'S02':['我竟然穿成了六个孩子的恶毒继父。书里，他们长大后会报复我。','爸爸，这是好心人给我的面包。'],
 'S03':['这孩子后来成了独眼神医。还好，现在他的眼睛还是完好的。','他一定在想怎么打我。'],
 'S04':['做得很好，下次不要了。','好的爸爸，我下次一定不会只带个面包，我会偷很多钱回来。','我说的是，不要再出去偷东西啊！']}


def fixture(root,media,sid='S01'):
    run=root/'data/video_generation/h3_reference_full_minute_QA_FIXTURE'
    delivery=root/'data/video_generation/visual_h3_ref_v20'/('CPU_FIXTURE_'+sid);folder=delivery/'shots'/sid;artifacts=folder/'artifacts';artifacts.mkdir(parents=True)
    source=run/'drafts'/(sid+'.adapted.prompt.txt');source.parent.mkdir(parents=True)
    source.write_text('CPU protocol fixture only.\n'+'\n'.join('角色：“'+q+'”' for q in TEXTS[sid]),encoding='utf-8')
    pause=root/'data/legacy_PAUSE.json';qa.write(pause,dict(original=True))
    refs={key:'qa_refs/'+str(i)+'.png' for i,key in enumerate(sorted(qa.REFERENCES))}
    graph={'127':dict(class_type='UNETLoader',inputs=dict(unet_name='minimax_h3_ref2va_pruned_int8_convrot.safetensors')),
        'condition':dict(class_type='MiniMaxH3ReferenceToVideo',inputs=dict(width=736,height=1312,length=362,ref_images=['batch',0]))}
    graph.update({f'load{i}':dict(class_type='LoadImage',inputs=dict(image=value)) for i,value in enumerate(refs.values())})
    qa.write(folder/'workflow_api.json',graph)
    row=dict(id=sid,timing=dict(native_frames=362),input_mapping=refs,graph_sha256=qa.fingerprint(graph),bundle_sha256='a'*64,source_prompt_sha256=qa.sha(source))
    plan=dict(schema='visual_h3_reference_delivery/v20',config=dict(width=736,height=1312),shots=[row],protected_pause=dict(path=str(pause),sha256=qa.sha(pause)))
    qa.write(delivery/'PLAN.json',plan)
    files={}
    for role,name in [('video','native.mp4'),('audio','audio.flac'),('first','frame.png'),('last','frame.png')]:
        target=artifacts/(role+Path(name).suffix);shutil.copyfile(media/name,target)
        files[role]=dict(path=str(target),sha256=qa.sha(target),source_path=str(media/name))
    result=dict(shot_id=sid,prompt_id='CPU_FIXTURE_NATIVE_'+sid,technical_status='technical_saved',files=files,graph_sha256=row['graph_sha256'],reference_bundle_sha256=row['bundle_sha256'],source_prompt_sha256=row['source_prompt_sha256'])
    qa.write(folder/'RESULT.json',result);qa.write(folder/'STATE.json',dict(status='technical_saved',prompt_id=result['prompt_id'],result_sha256=qa.sha(folder/'RESULT.json')))
    return run,delivery,source


def test_actual_cpu_samples_native_last_and_idempotent_metadata(tmp_path,cpu_media):
    run,delivery,source=fixture(tmp_path,cpu_media);before={str(p):p.read_bytes() for p in delivery.rglob('*') if p.is_file()}
    first=qa.qa_segment(run,'S01',delivery,project=tmp_path)
    assert first['status']=='cpu_qa_complete' and first['production_approved'] is False
    manifest=qa.read(first['manifest']['path']);assert manifest['geometry']['decoded_frames']==362 and len(manifest['frames'])==6
    assert manifest['binding']['prompt_id']=='CPU_FIXTURE_NATIVE_S01' and manifest['asr_status']=='not_requested'
    assert qa.sha(manifest['native_last']['path'])==qa.sha(delivery/'shots/S01/artifacts/last.png')
    assert Image.open(manifest['contact']['path']).size==(736,2728)
    assert qa.qa_segment(run,'S01',delivery,project=tmp_path)==first
    assert {str(p):p.read_bytes() for p in delivery.rglob('*') if p.is_file()}==before


def test_asr_is_cpu_only_and_missing_child_is_not_a_listening_verdict(tmp_path,cpu_media,monkeypatch):
    run,delivery,source=fixture(tmp_path,cpu_media,'S03')
    script=tmp_path/'scripts/transcribe_video_local.py';script.parent.mkdir();script.write_text('CPU_FIXTURE={"device": "cpu"}',encoding='utf-8')
    original=qa.subprocess.run;calls=[]
    def fake_asr(args,**kwargs):
        if str(script) in args:
            calls.append((args,kwargs));assert kwargs['env']['CUDA_VISIBLE_DEVICES']=='' and kwargs['env']['HF_HUB_OFFLINE']=='1'
            qa.write(Path(args[5]),dict(models='CPU_PROTOCOL_FIXTURE_NOT_REAL_ASR',result=[dict(text='这孩子后来成了独眼神医还好现在他的眼睛还是完好的')]))
            return SimpleNamespace(returncode=0)
        return original(args,**kwargs)
    monkeypatch.setattr(qa.subprocess,'run',fake_asr)
    receipt=qa.qa_segment(run,'S03',delivery,asr=True,project=tmp_path);result=qa.read(receipt['manifest']['path'])
    assert len(calls)==1 and result['S03_child_inner_voice_exactly_detected'] is False
    assert any(d['kind']=='delete' and '他一定在想怎么打我' in d['expected'] for d in result['asr_differences'])
    assert 'not proof of omission' in result['scope'] and result['production_approved'] is False
    qa.qa_segment(run,'S03',delivery,asr=True,project=tmp_path);assert len(calls)==1


@pytest.mark.parametrize('mutation',['running','pid','result_sha','probe_geometry','v19_mode','first_frame','four_refs','graph_refs','source','file_sha','outside_file','pause'])
def test_inputs_fail_closed_without_media_or_asr(tmp_path,cpu_media,monkeypatch,mutation):
    run,delivery,source=fixture(tmp_path,cpu_media);folder=delivery/'shots/S01';plan=qa.read(delivery/'PLAN.json');state=qa.read(folder/'STATE.json');result=qa.read(folder/'RESULT.json');graph=qa.read(folder/'workflow_api.json')
    if mutation=='running':state['status']='running'
    if mutation=='pid':state['prompt_id']='another'
    if mutation=='result_sha':state['result_sha256']='0'*64
    if mutation=='probe_geometry':plan['config']['width']=288
    if mutation=='v19_mode':graph['condition']['class_type']='MiniMaxH3ImageToVideo'
    if mutation=='first_frame':graph['condition']['inputs']['first_frame']=['image',0]
    if mutation=='four_refs':plan['shots'][0]['input_mapping'].pop(next(iter(plan['shots'][0]['input_mapping'])))
    if mutation=='graph_refs':graph.pop('load4')
    if mutation=='source':source.write_text('changed')
    if mutation=='file_sha':Path(result['files']['video']['path']).write_bytes(b'tampered')
    if mutation=='outside_file':result['files']['video']['path']=str(cpu_media/'native.mp4')
    if mutation=='pause':qa.write(Path(plan['protected_pause']['path']),dict(changed=True))
    qa.write(folder/'STATE.json',state);qa.write(folder/'RESULT.json',result);qa.write(delivery/'PLAN.json',plan);qa.write(folder/'workflow_api.json',graph)
    monkeypatch.setattr(qa,'command',lambda *a,**k:pytest.fail('bad input reached media command'))
    monkeypatch.setattr(qa,'transcribe',lambda *a,**k:pytest.fail('bad input reached ASR'))
    with pytest.raises(ValueError):qa.qa_segment(run,'S01',delivery,project=tmp_path)


def test_source_outside_minute_and_old_run_refused(tmp_path,cpu_media):
    run,delivery,source=fixture(tmp_path,cpu_media)
    with pytest.raises(ValueError,match='scope'):qa.qa_segment(run,'S01',delivery,source_prompt=tmp_path/'outside.txt',project=tmp_path)
    with pytest.raises(ValueError,match='namespace'):qa.qa_segment(tmp_path/'data/video_generation/h3_seedance_prompt_parity_old','S01',delivery,project=tmp_path)


def test_cli_blackbox_uses_only_cpu_and_success_receipt_shape(tmp_path,cpu_media):
    run,delivery,source=fixture(tmp_path,cpu_media)
    args=[sys.executable,'-X','utf8','-B',str(Path(qa.__file__).resolve()),'segment','--run',str(run),'--segment','S01','--delivery-run',str(delivery),'--source-prompt',str(source),'--project-root',str(tmp_path)]
    first=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',timeout=45)
    assert first.returncode==0,first.stdout+first.stderr
    receipt=json.loads(first.stdout);assert set(receipt)>={'manifest','prompt_id','video_sha256','contact','production_approved'}
    second=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',timeout=45)
    assert second.returncode==0 and json.loads(second.stdout)==receipt
    source.write_text('changed',encoding='utf-8')
    failed=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',timeout=15)
    assert failed.returncode==2 and json.loads(failed.stdout)['no_media_retry'] is True


def test_final_actual_cpu_clock_has_1448_frames_and_av_origin_zero(tmp_path,cpu_media):
    run=tmp_path/'data/video_generation/h3_reference_full_minute_FINAL_CPU_FIXTURE';run.mkdir(parents=True)
    video=run/'final.mp4';shutil.copyfile(cpu_media/'final.mp4',video)
    receipt=qa.qa_final(run,video,qa.sha(video),project=tmp_path)
    assert receipt['clock']['decoded_frames']==1448 and receipt['clock']['stream_audio_samples']==2896000
    assert receipt['clock']['seconds']==1448/24 and receipt['clock']['video_start']==receipt['clock']['audio_start']==0
    assert receipt['clock']['production_approved'] is False
    with pytest.raises(ValueError,match='hash'):qa.qa_final(run,video,'0'*64,project=tmp_path)


def test_cpu_asr_failure_retries_same_native_without_dispatch_or_losing_failure_log(tmp_path,cpu_media,monkeypatch):
    run,delivery,source=fixture(tmp_path,cpu_media,'S02')
    script=tmp_path/'scripts/transcribe_video_local.py';script.parent.mkdir();script.write_text('CPU_FIXTURE={"device": "cpu"}',encoding='utf-8')
    original=qa.subprocess.run;calls=[]
    def fake_asr(args,**kwargs):
        if str(script) not in args:return original(args,**kwargs)
        calls.append(args)
        if len(calls)==1:
            kwargs['stderr'].write('Controlled CPU fixture failure; no model or GPU called.')
            raise subprocess.CalledProcessError(1,args)
        qa.write(Path(args[5]),dict(fixture_only=True,result=[dict(text=''.join(TEXTS['S02']))]));return SimpleNamespace(returncode=0)
    monkeypatch.setattr(qa.subprocess,'run',fake_asr)
    before=(delivery/'shots/S02/RESULT.json').read_bytes()
    with pytest.raises(subprocess.CalledProcessError):qa.qa_segment(run,'S02',delivery,asr=True,project=tmp_path)
    folder=run/'qc/S02/CPU_FIXTURE_NATIVE_S02';binding=(folder/'BINDING.json').read_bytes()
    assert not (folder/'OBJECTIVE_QA.json').exists()
    result=qa.qa_segment(run,'S02',delivery,asr=True,project=tmp_path)
    assert len(calls)==2 and qa.read(result['manifest']['path'])['normalized_matches'] is True
    assert (folder/'BINDING.json').read_bytes()==binding and (delivery/'shots/S02/RESULT.json').read_bytes()==before
    assert any('Controlled CPU fixture failure' in p.read_text(encoding='utf-8') for p in folder.glob('ASR_ATTEMPTS/*/ASR.stderr.log'))
