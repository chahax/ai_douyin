"""Video/frame lineage and independent-count brake; no real model or GPU."""
from contextlib import contextmanager,nullcontext
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image
import pytest

from src.content_factory import visual_video_people_qc_v15 as f
from src.content_factory import visual_asset_review_v3 as visual
from test_visual_asset_review_v3 import provider
from test_visual_h3_handoff_v3 import native_media


@contextmanager
def source(tmp_path,native_media,monkeypatch,counts=(1,1,3)):
    answer=dict(people_count=0,evidence=['Protocol fixture visible count.']);seen=[]
    def on_post(body):
        i=len(seen);seen.append(body);answer['people_count']=counts[i]
    with provider([],people_observation=answer,on_post=on_post) as (url,received):
        h3=tmp_path/'h3';asset=tmp_path/'asset';shot=h3/'shots/F1';out=shot/'artifacts';qa_root=tmp_path/'objective'
        out.mkdir(parents=True);asset.mkdir();qa_root.mkdir();text=tmp_path/'source.md';text.write_text('Fixture visible man; child speaks offscreen.')
        audio=[dict(speaker='child',mode='offscreen_dialogue',text='Fixture voice.')]
        packet=dict(schema='visual_asset_packet/v3',book_id='book',source=f.artifact(text),characters=[dict(id='man'),dict(id='child')],
            places=[],shots=[dict(id='F1',visible_cast=['man'],audio=audio)])
        packet_path=tmp_path/'single_packet.json';f.write(packet_path,packet)
        ap=dict(packet=packet,config=dict(visual_review=dict(provider='ollama',endpoint=url,model='vision-test')))
        f.write(asset/'PLAN.json',ap)
        files={}
        for role,name in [('video','video.mp4'),('audio','audio.flac'),('first','frame.png'),('last','frame.png')]:
            dest=out/(role+Path(name).suffix);shutil.copyfile(native_media/name,dest);files[role]=f.artifact(dest)
        graph=dict(fixture=dict(class_type='FixtureOnly',inputs={}))
        f.write(shot/'workflow_api.json',graph)
        hp=dict(schema='visual_h3_handoff/v3',publication=False,old_batch_resume=False,source=packet['source'],asset_run=str(asset),
            asset_plan_sha256=f.sha(asset/'PLAN.json'),shots=[dict(id='F1',graph_sha256=f.digest(graph),first_frame=dict(sha256=files['first']['sha256']))])
        f.write(h3/'PLAN.json',hp);f.write(h3/'STATE.json',dict(plan_sha256=f.digest(hp)))
        f.write(shot/'STATE.json',dict(status='technical_saved',prompt_id='known-fixture-native',plan_sha256=f.digest(hp)))
        f.write(shot/'RESULT.json',dict(schema='visual_h3_handoff/v3',shot_id='F1',prompt_id='known-fixture-native',graph_sha256=f.digest(graph),
            first_frame_sha256=files['first']['sha256'],technical_status='technical_saved',content_status='media_review_required',
            publication=False,production_approved=False,files=files,timing=dict(native_seconds=124/24)))
        frames=[]
        for i,seconds in enumerate([0.,1.,3.]):
            path=qa_root/f'frame_{i}.png';rgb=f._decoded_rgb(files['video']['path'],seconds);Image.frombytes('RGB',(96,128),rgb).save(path)
            frames.append(dict(**f.artifact(path),seconds=seconds))
        objective=qa_root/'OBJECTIVE_QA.json'
        f.write(objective,dict(binding=dict(video=files['video'],source=packet['source'],shot_id='F1',prompt_id='known-fixture-native',audio=audio),seconds=124/24,frames=frames))
        guards=[]
        @contextmanager
        def guard(plan):
            guards.append(True);yield
        monkeypatch.setattr(f.pipeline,'gpu_access',guard) # Protocol fixture: no actual GPU/resource operations.
        yield dict(h3=h3,packet=packet_path,qa=objective,qc=tmp_path/'qc',seen=seen,guards=guards,shot=shot,frames=frames,asset=asset)


def prepare(s):return f.prepare(s['qc'],s['h3'],s['packet'],s['qa'])


def test_prepare_binds_four_files_decode_times_dimensions_and_does_not_dispatch(tmp_path,native_media,monkeypatch):
    with source(tmp_path,native_media,monkeypatch) as s:
        plan=prepare(s)
        assert plan['binding']['allowed_people']==1 and plan['binding']['visible_cast']==['man']
        assert set(plan['binding']['outputs'])=={'video','audio','first','last'}
        assert len(plan['binding']['frames'])==3 and plan['binding']['native_header']['width']==96
        assert s['seen']==[] and s['guards']==[] and prepare(s)==plan


def test_independent_native_counts_stop_extra_people_and_preserve_original_records(tmp_path,native_media,monkeypatch):
    with source(tmp_path,native_media,monkeypatch) as s:
        protected={str(p):f.sha(p) for p in [s['shot']/'RESULT.json',s['shot']/'STATE.json',s['qa'],s['h3']/'PLAN.json']}
        prepare(s);observed=f.observe(s['qc'])
        assert [r['people_count'] for r in observed['results']]==[1,1,3]
        request=f.read(s['qc']/'observation/REQUEST.json')
        assert 'allowed_people' not in request and 'visible_cast' not in request
        for body in s['seen']:
            assert len(body['messages'][0]['images'])==1
            assert set(body['format']['properties'])=={'people_count','evidence'}
            assert 'allowed_people' not in body['messages'][0]['content']
            assert 'visible_cast' not in body['messages'][0]['content']
        decision=f.apply(s['qc'])
        assert decision['decision']=='hard_rejected_people_upper_bound' and decision['hard_reject'] is True
        assert [r['seconds'] for r in decision['violations']]==[3.]
        assert decision['production_approved'] is False and decision['identity_approved'] is False
        assert f.apply(s['qc'])==decision and f.observe(s['qc'])==observed and len(s['seen'])==3
        assert all(f.sha(p)==value for p,value in protected.items())


@pytest.mark.parametrize('counts,decision',[
    ((0,1,0),'needs_semantic_review'),((1,None,0),'needs_review_unknown'),((0,0,0),'needs_semantic_review')])
def test_no_lower_bound_and_unknown_is_never_zero_or_full_acceptance(tmp_path,native_media,monkeypatch,counts,decision):
    with source(tmp_path,native_media,monkeypatch,counts) as s:
        prepare(s);f.observe(s['qc']);value=f.apply(s['qc'])
        assert value['decision']==decision and value['production_approved'] is False
        assert value['environment_approved'] is False and value['duration_approved'] is False
        assert value['lower_bound_enforced'] is False
        assert [r['people_count'] for r in value['observations']]==list(counts)


@pytest.mark.parametrize('mode',['packet_cast','source','qa_identity','frame_pixels','frame_dimensions','negative_time','outside_time','four_file','result_id','missing_file'])
def test_prepare_rejects_wrong_source_video_frame_or_time(tmp_path,native_media,monkeypatch,mode):
    with source(tmp_path,native_media,monkeypatch) as s:
        if mode=='packet_cast':
            x=f.read(s['packet']);x['shots'][0]['visible_cast']=['man','child'];f.write(s['packet'],x)
        elif mode=='source':Path(f.read(s['packet'])['source']['path']).write_text('changed')
        elif mode=='qa_identity':
            x=f.read(s['qa']);x['binding']['prompt_id']='other';f.write(s['qa'],x)
        elif mode in ('frame_pixels','frame_dimensions'):
            x=f.read(s['qa']);path=Path(x['frames'][0]['path']);Image.new('RGB',(96,128) if mode=='frame_pixels' else (48,64),'blue').save(path)
            x['frames'][0]['sha256']=f.sha(path);f.write(s['qa'],x)
        elif mode in ('negative_time','outside_time'):
            x=f.read(s['qa']);x['frames'][0]['seconds']=-1 if mode=='negative_time' else 99;f.write(s['qa'],x)
        elif mode=='four_file':Path(f.read(s['shot']/'RESULT.json')['files']['audio']['path']).write_bytes(b'changed')
        elif mode=='result_id':
            x=f.read(s['shot']/'RESULT.json');x['prompt_id']='other';f.write(s['shot']/'RESULT.json',x)
        else:Path(f.read(s['shot']/'RESULT.json')['files']['last']['path']).unlink()
        with pytest.raises((ValueError,OSError)):prepare(s)
        assert not s['qc'].exists() and s['seen']==[]


@pytest.mark.parametrize('mode',['qa','frame','native','request','count'])
def test_apply_rechecks_every_bound_input_and_native_count(tmp_path,native_media,monkeypatch,mode):
    with source(tmp_path,native_media,monkeypatch) as s:
        prepare(s);f.observe(s['qc']);folder=s['qc']/'observation'
        if mode=='qa':
            x=f.read(s['qa']);x['frames'][1]['seconds']=2.;f.write(s['qa'],x)
        elif mode=='frame':Path(s['frames'][0]['path']).write_bytes(b'changed')
        elif mode=='native':(folder/'FRAME_0002_NATIVE.json').write_text('changed')
        elif mode=='request':
            x=f.read(folder/'FRAME_0002_REQUEST.json');x['prompt']+=' Desired count is 1.';f.write(folder/'FRAME_0002_REQUEST.json',x)
        else:
            x=f.read(folder/'RESULTS.json');x['results'][2]['people_count']=1;x['results_sha256']=f.digest(x['results']);f.write(folder/'RESULTS.json',x)
        with pytest.raises((ValueError,OSError)):f.apply(s['qc'])
        assert not (s['qc']/'DECISION.json').exists()


def test_unknown_batch_is_not_replayed_and_not_submitted_frames_stay_unknown(tmp_path,native_media,monkeypatch):
    with source(tmp_path,native_media,monkeypatch) as s:
        prepare(s);called=[]
        def unknown(self,payload):
            called.append(payload);raise visual.ReviewOutcomeUnknown('Fixture ambiguous inference outcome')
        monkeypatch.setattr(visual.VisualReviewClient,'_infer_http',unknown)
        result=f.observe(s['qc']);assert len(called)==1 and result['outcome_unknown'] is True
        assert all(r['people_count'] is None for r in result['results'])
        assert f.observe(s['qc'])==result and len(called)==1
        value=f.apply(s['qc']);assert value['decision']=='needs_review_unknown' and value['outcome_unknown'] is True


def test_claim_without_batch_output_never_restarts_model(tmp_path,native_media,monkeypatch):
    with source(tmp_path,native_media,monkeypatch) as s:
        prepare(s);folder=s['qc']/'observation';folder.mkdir();f.write(folder/'CLAIM.json',dict(original='unknown'))
        with pytest.raises(visual.ReviewOutcomeUnknown):f.observe(s['qc'])
        assert s['seen']==[]


def test_resource_busy_before_claim_is_retryable_without_unknown_inference(tmp_path,native_media,monkeypatch):
    with source(tmp_path,native_media,monkeypatch) as s:
        prepare(s)
        @contextmanager
        def busy(plan):
            raise f.pipeline.images.JobBusyError('Fixture busy');yield
        monkeypatch.setattr(f.pipeline,'gpu_access',busy)
        with pytest.raises(f.pipeline.images.JobBusyError):f.observe(s['qc'])
        assert not (s['qc']/'observation/CLAIM.json').exists() and s['seen']==[]


def test_cli_prepare_then_hard_reject_exit_code_does_not_modify_h3(tmp_path,native_media,monkeypatch):
    with source(tmp_path,native_media,monkeypatch) as s:
        command=[sys.executable,'-B',str(f.PROJECT/'scripts/run_visual_video_people_qc_v15.py')]
        result=subprocess.run(command+['prepare','--run',str(s['qc']),'--h3-run',str(s['h3']),'--packet',str(s['packet']),'--objective-qa',str(s['qa'])],
            cwd=f.PROJECT,capture_output=True,text=True,timeout=30)
        assert result.returncode==0 and s['seen']==[]
        f.observe(s['qc'])
        before=f.sha(s['shot']/'RESULT.json')
        applied=subprocess.run(command+['apply','--run',str(s['qc'])],cwd=f.PROJECT,capture_output=True,text=True,timeout=30)
        assert applied.returncode==4 and json.loads(applied.stdout)['hard_reject'] is True
        assert f.sha(s['shot']/'RESULT.json')==before


def test_real_worker_cli_bootstraps_with_short_temp_and_rejects_bad_claim_before_model(tmp_path):
    folder=tmp_path/'new_native_scope';folder.mkdir()
    f.write(folder/'REQUEST.json',dict(request_binding_sha256='a'*64))
    f.write(folder/'CLAIM.json',dict(request_binding_sha256='b'*64))
    command=[sys.executable,'-B',str(f.PROJECT/'scripts/run_visual_video_people_qc_v15.py'),'worker',
        '--request',str(folder/'REQUEST.json'),'--output',str(folder/'RESULTS.json')]
    import os
    options,metadata=f.runtime.prepare(command,os.environ.copy(),temp_root=f.PROJECT/'data/qa/vp15tmp')
    result=subprocess.run(command,cwd=f.PROJECT,**options,capture_output=True,text=True,timeout=15,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert result.returncode==2 and json.loads(result.stdout)['reason']=='qc_worker_claim_changed'
    assert not (folder/'WORKER_STATE.json').exists() and not (folder/'RESULTS.json').exists()
    if os.name=='nt':assert metadata['mode']=='windows_venv_direct_base' and len(metadata['private_temp'])<180
