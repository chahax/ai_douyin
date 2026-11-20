"""Minute adapter checks use real file inputs but never dispatch media jobs."""
from copy import deepcopy
from pathlib import Path
import subprocess

import pytest

from scripts import run_h3_story_opening_minute as minute


@pytest.fixture
def run(tmp_path,monkeypatch):
    root=tmp_path/'opening_minute';root.mkdir()
    monkeypatch.setattr(minute,'RUN',root)
    def forbidden(*args,**kwargs):raise AssertionError('unexpected network/model dispatch')
    monkeypatch.setattr(minute.stills.jobs,'_http',forbidden)
    monkeypatch.setattr(minute.native,'_http',forbidden)
    return root


def test_real_prepare_keeps_all_original_audio_and_accepted_s02(run):
    before=minute.bind(minute.ACCEPTED/'ROOT_RESULT_REVIEW.json')
    result=minute.prepare(run)
    assert result['model_posts']==0 and minute.prepare(run)==result
    plan=minute.read(run/'PLAN.json')
    assert [x['shot_id'] for x in plan['segments']]==list(minute.IDS)
    original=minute.core._entries(minute.bind(minute.SOURCE/'SOURCE_CASE.json'))
    assert sum(len(e['audio']) for e in original)==10
    for entry in original:
        current=minute.read(minute.segment(run,entry['shot_id'])/'SOURCE_CASE.json')['shots'][0]
        assert current==entry
    imported=minute.read(run/'imported/S02/IMPORT.json')
    assert imported['prompt_id']==minute.ACCEPTED_ID and imported['file']['sha256']==minute.ACCEPTED_SHA
    assert imported['new_model_posts']==0 and imported['temporal_trim'] is False
    assert imported['native_run']==str(minute.ACCEPTED/'visual_h3_v3/opening_S02')
    assert minute.bind(minute.ACCEPTED/'ROOT_RESULT_REVIEW.json')==before
    assert not list(run.rglob('SOURCE_STATE_REVIEW.json'))
    assert not list(run.rglob('ANCHOR_REVIEW.json'))
    assert not list(run.rglob('CLAIM.json')) and not list(run.rglob('REQUEST.json'))


def test_unique_stills_and_native_names_preserve_first_camera_cast(run):
    minute.prepare(run)
    expected={'S01':{'ye_nan','ye_xijue'},'S03':{'ye_xijue'},'S04':{'su_mo'}}
    roots=[]
    for sid in minute.NEW_IDS:
        image_run,video_run=minute.folders(run,sid);roots.append(image_run)
        assert image_run.name==run.name+'_'+sid==video_run.name
        p=minute.read(image_run/'PLAN.json');row=next(x for x in p['items'] if x['id']==sid+'_start')
        assert set(row['visible_cast'])==expected[sid]
        assert len(row['references'])==1+len(expected[sid])
    assert len(set(roots))==3 and {r.parent for r in roots}=={run/'stills'}


def synthetic_source_reviews(run):
    for sid in minute.NEW_IDS:
        part=minute.segment(run,sid);request=minute.read(part/'SOURCE_STATE_REVIEW_REQUEST.json')
        request.update(schema='h3_reanchor_source_state_review/v33',source_current_state_matches=True,
            room_identity_matches=True,completion_known=True,outcome_unknown=False,
            reviewed_by='CPU protocol fixture only; not production observation',
            evidence=['Controlled source-state contract fixture; no model/visual acceptance.'])
        minute.freeze(part/'SOURCE_STATE_REVIEW.json',request)


def test_three_separate_workorders_share_one_budget_and_never_post(run):
    minute.prepare(run);synthetic_source_reviews(run)
    result=minute.prepare_images(run)
    assert set(result)==set(minute.NEW_IDS)
    for sid in minute.NEW_IDS:
        assert result[sid]['status']=='image_job_prepared_not_submitted'
        image_run,_=minute.folders(run,sid)
        assert minute.read(image_run/'SOURCE_STATE_REVIEW_BINDING.json')==minute.bind(minute.segment(run,sid)/'SOURCE_STATE_REVIEW.json')
    budget=minute.read(run/'stills/IMAGE_BRANCH_BUDGET.json')
    assert budget['limit']==3 and budget['reserved_branches']==3
    assert len(list(run.rglob('BUDGET_ADMISSION.json')))==3
    assert not list(run.rglob('CLAIM.json'))
    receipts={sid:minute.bind(minute.segment(run,sid)/'IMAGE_RECEIPT_TEMPLATE.json') for sid in minute.NEW_IDS}
    assert all(row['status']=='image_job_prepared_not_submitted' for row in minute.prepare_images(run).values())
    assert receipts=={sid:minute.bind(minute.segment(run,sid)/'IMAGE_RECEIPT_TEMPLATE.json') for sid in minute.NEW_IDS}
    assert minute.read(run/'stills/IMAGE_BRANCH_BUDGET.json')['reserved_branches']==3


def test_missing_review_does_not_reserve_any_branch(run):
    minute.prepare(run)
    assert all(v['status']=='source_state_review_required' for v in minute.prepare_images(run).values())
    assert not list(run.rglob('BUDGET_ADMISSION.json'))


def test_accepted_native_file_change_is_rejected(run,monkeypatch):
    bad=deepcopy(minute.read(minute.ACCEPTED/'visual_h3_v3/opening_S02/shots/S02/RESULT.json'))
    bad['files']['video']['sha256']='0'*64
    original=minute.read
    monkeypatch.setattr(minute,'read',lambda p:bad if Path(p).name=='RESULT.json' else original(p))
    with pytest.raises(ValueError,match='exact_user_accepted'):minute.import_s02(run)
    assert not (run/'imported/S02/IMPORT.json').exists()


def test_bound_image_approval_detects_graph_change(run):
    minute.prepare(run);synthetic_source_reviews(run);minute.prepare_images(run,'S01')
    part=minute.segment(run,'S01');request=minute.launch_request(run,'image','S01')
    minute.freeze(part/'ROOT_LAUNCH_IMAGE.json',dict(request=request,approved_by='CPU fixture',evidence=['protocol only']))
    minute.require_approval(run,'image','S01')
    graph=minute.core.check(request['graph']);Path(graph).write_text('{"tampered":true}',encoding='utf-8')
    with pytest.raises(ValueError,match='actual_plan_and_code'):minute.require_approval(run,'image','S01')


@pytest.mark.parametrize('state',['outcome_unknown','blocked_native_failure','blocked_upstream_changed','paused'])
def test_existing_terminal_video_never_requests_launch_or_reposts(run,monkeypatch,state):
    _,video_run=minute.folders(run,'S03');video_run.mkdir(parents=True)
    monkeypatch.setattr(minute.native,'poll_collect',lambda *a,**k:dict(status=state))
    monkeypatch.setattr(minute.native,'submit_next',lambda *a,**k:pytest.fail('known terminal job re-posted'))
    monkeypatch.setattr(minute,'require_approval',lambda *a,**k:pytest.fail('known terminal job asks fresh launch'))
    assert minute.execute(run,'video','S03')['status']==state


def test_collect_prepared_image_has_no_post_path(run,monkeypatch):
    monkeypatch.setattr(minute.stills,'status',lambda *a,**k:dict(status='prepared'))
    monkeypatch.setattr(minute.stills,'tick',lambda *a,**k:pytest.fail('prepared image would POST'))
    assert minute.collect_known(run,'image','S01')==dict(status='prepared')


def test_unknown_image_runs_existing_collector_without_fresh_launch(run,monkeypatch):
    monkeypatch.setattr(minute.stills,'status',lambda *a,**k:dict(status='outcome_unknown'))
    monkeypatch.setattr(minute.stills,'execute',lambda *a,**k:dict(status='outcome_unknown'))
    monkeypatch.setattr(minute,'require_approval',lambda *a,**k:pytest.fail('unknown image fresh launch'))
    assert minute.execute(run,'image','S01')['status']=='outcome_unknown'


def test_new_image_requires_launch_before_execute(run,monkeypatch):
    minute.prepare(run);synthetic_source_reviews(run);minute.prepare_images(run,'S01')
    monkeypatch.setattr(minute.stills,'execute',lambda *a,**k:pytest.fail('unapproved POST'))
    with pytest.raises(FileNotFoundError):minute.execute(run,'image','S01')


@pytest.mark.parametrize('sid,error',[('S01','single_face_close'),('S04','hand_and_held_prop')])
def test_crop_cannot_remove_second_person_or_held_hands(run,sid,error):
    from PIL import Image
    minute.prepare(run);part=minute.segment(run,sid);image_run,_=minute.folders(run,sid)
    image=run/'synthetic.png';Image.new('RGB',(736,1312),'gray').save(image)
    candidate=dict(id=sid+'_start',image=minute.bind(image),prompt_id='controlled fixture')
    path=image_run/'batches'/('reanchor_'+sid)/'CANDIDATES.json'
    minute.freeze(path,dict(items=[candidate]))
    receipt=dict(kind='spatial_still_v24',candidates=None)
    minute.freeze(part/'IMAGE_RECEIPT_TEMPLATE.json',receipt)
    minute.freeze(part/'DERIVED_OPENING_SELECTION.json',dict(parent_image=candidate['image'],
        parent_generation_receipt=dict(receipt,candidates=minute.bind(path)),image=candidate['image'],crop_result={}))
    with pytest.raises(ValueError,match=error):minute.prepare_video(run,sid)


def test_wrong_run_or_imported_generation_cannot_dispatch(run,tmp_path):
    with pytest.raises(ValueError,match='explicit_new_minute'):minute.scope(tmp_path/'different')
    with pytest.raises(ValueError,match='only_new_segments'):minute.prepare_images(run,'S02')
    with pytest.raises(ValueError,match='explicit_new_image'):minute.execute(run,'video','S02')


def test_cpu_blackbox_assembly_retains_order_audio_and_exact_minute_clock(run,monkeypatch):
    """Actual ffmpeg, four controlled 32k-native-like clips, no media model."""
    import numpy as np
    colors=['red','green','blue','yellow'];frequencies=[310,470,630,790];rows=[]
    minute.freeze(run/'PLAN.json',dict(controlled_cpu_fixture=True))
    for sid,color,frequency in zip(minute.IDS,colors,frequencies):
        path=run/(sid+'.mp4')
        command=['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',f'color=c={color}:s=736x1312:r=24',
            '-f','lavfi','-i',f'sine=frequency={frequency}:sample_rate=32000',
            '-af','aformat=channel_layouts=stereo,atrim=end_sample=482400,asetpts=N/SR/TB',
            '-frames:v','362','-c:v','libx264','-preset','ultrafast','-threads','2','-crf','25',
            '-pix_fmt','yuv420p','-c:a','aac','-ar','32000','-ac','2','-video_track_timescale','12288',str(path)]
        subprocess.run(command,capture_output=True,check=True,timeout=180)
        receipt=run/(sid+'_controlled_receipt.json');minute.freeze(receipt,dict(controlled_cpu_fixture=True,id=sid))
        rows.append(dict(shot_id=sid,native_result=minute.bind(receipt),prompt_id='controlled_'+sid,
            file=minute.bind(path),kind='imported' if sid=='S02' else 'new'))
    minute.freeze(run/'imported/S02/IMPORT.json',dict(controlled_cpu_fixture=True))
    monkeypatch.setattr(minute,'segment_results',lambda ignored:deepcopy(rows))
    final=minute.assemble(run)
    assert final['clock']['native_frames']==1448 and final['clock']['audio_samples']==2896000
    assert final['clock']['audio_start']==final['clock']['video_start']==0
    assert final['segments']==rows and final['temporal_leading_trim'] is False
    request=minute.read(run/'ASSEMBLY_REQUEST.json')
    assert [r['file'] for r in request['inputs']['segments']]==[r['file'] for r in rows]
    assert request['audio_resampled_to_48k'] is True
    movie=final['file']['path'];frames=[0,362,724,1086]
    selected='+'.join(f'eq(n\\,{n})' for n in frames)
    decoded=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',movie,'-vf',f'select={selected},scale=1:1',
        '-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True,timeout=180).stdout
    pixels=np.frombuffer(decoded,dtype=np.uint8).reshape(4,3)
    assert int(pixels[0,0])>220 and int(pixels[0,1])<20
    assert int(pixels[1,1])>90 and int(pixels[1,0])<20
    assert int(pixels[2,2])>220 and int(pixels[2,0])<20
    assert int(pixels[3,0])>220 and int(pixels[3,1])>220
    raw=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',movie,'-map','0:a:0','-ac','1',
        '-f','f32le','-'],capture_output=True,check=True,timeout=180).stdout
    sound=np.frombuffer(raw,dtype='<f4')
    for i,frequency in enumerate(frequencies):
        begin=i*724000+48000;piece=sound[begin:begin+48000]
        peak=int(np.argmax(np.abs(np.fft.rfft(piece))))
        assert abs(peak-frequency)<=1
    assert minute.assemble(run)==final
