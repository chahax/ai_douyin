"""Diagnostic adapter checks: real source receipts, controlled local HTTP only."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import threading

import pytest

from scripts import run_h3_story_opening_diagnostic as diag

ACTUAL=Path(diag.RUN)


@pytest.fixture
def run(tmp_path,monkeypatch):
    root=tmp_path/'opening_diagnostic';root.mkdir();monkeypatch.setattr(diag,'RUN',root)
    cfg=diag.read(ACTUAL/'H3_CONFIG.json')
    for key in ('input_root','output_root','gpu_lock_root'):
        path=root/key;path.mkdir();cfg[key]=str(path)
    cfg['runs_root']=str(root/'visual_h3_v3')
    pause=root/'original_protected_pause.json';diag.freeze(pause,dict(controlled_cpu_fixture=True,paused=True))
    cfg['protected_pause_path']=str(pause)
    diag.freeze(root/'H3_CONFIG.json',cfg)
    diag.freeze(root/'USER_AUTHORIZATION.json',dict(controlled_cpu_fixture=True,max_image_submissions=0,new_cloud_media_calls=0))
    for sid in diag.IDS:
        part=diag.minute.segment(root,sid);actual=diag.minute.segment(ACTUAL,sid)
        for name in ('SOURCE_CASE','IMAGE_RECEIPT_TEMPLATE'):
            diag.freeze(part/(name+'.json'),diag.read(actual/(name+'.json')))
        seen=diag.read(actual/'ACTUAL_ANCHOR_OBSERVATION.json')
        seen['reviewed_by']='CPU fixture retains actual observed deviations'
        diag.freeze(part/'ACTUAL_ANCHOR_OBSERVATION.json',seen)
        selected=diag.read(actual/'DIAGNOSTIC_GENERATION_SELECTION.json')
        selected.update(source_case=diag.bind(part/'SOURCE_CASE.json'),observation=diag.bind(part/'ACTUAL_ANCHOR_OBSERVATION.json'),
            selected_by='CPU fixture',reason='Controlled technical adapter test, no media model call.')
        diag.freeze(part/'DIAGNOSTIC_GENERATION_SELECTION.json',selected)
    return root


def forbid_http(monkeypatch):
    monkeypatch.setattr(diag.native,'_http',lambda *a,**k:pytest.fail('prepare/validation attempted HTTP'))


def test_real_native_and_crop_receipts_retain_failed_quality_without_dispatch(monkeypatch):
    forbid_http(monkeypatch)
    expected={'S01':'d2420e3d','S03':'6f3862e1','S04':'88181658'}
    for sid in diag.IDS:
        value=diag.input_value(ACTUAL,sid)
        assert value['first_image']['sha256'].startswith(expected[sid])
        assert value['quality_passed'] is value['visual_ready'] is False
        assert value['source_evaluation']['status']=='reanchor_required'
        assert value['compiled_prompt']==diag.core.compile_prompt(diag.core._entries(value['source_case'])[0])['compiled_prompt']
        assert value['generation_receipt']['kind']==('derived_opening_crop/v1' if sid=='S03' else 'spatial_still_v24')


def test_prepare_is_real_source_bound_file_only_and_never_manufactures_visual_ready(run,monkeypatch):
    forbid_http(monkeypatch);out=diag.prepare(run)
    assert all(v['status']=='prepared' and v['quality_passed'] is False for v in out.values())
    for sid in diag.IDS:
        native_run=diag.minute.folders(run,sid)[1];p=diag.read(native_run/'PLAN.json');row=p['shots'][0]
        assert p['schema']==diag.SCHEMA and p['upstream_contract']==diag.INPUT_SCHEMA and p['old_batch_resume'] is False
        assert diag.bind(diag.minute.__file__) in p['code']
        assert 'continuity_input' not in row and 'native_prompt' not in row
        current=diag.validate_input(p['diagnostic_input'])
        assert row['diagnostic_input']==current['proof'] and current['source_evaluation']['status']=='reanchor_required'
        graph=diag.read(native_run/'shots'/sid/'workflow_api.json')
        assert graph['condition']['inputs']['prompt']==current['compiled_prompt']
        assert graph['condition']['inputs']['first_frame']==['ref_scene',0]
        assert graph['ref_scene']['inputs']['image'].startswith('visual_h3_v3/'+run.name+'_'+sid+'/')
        assert 'last_frame' not in graph['condition']['inputs']
        assert (graph['condition']['inputs']['length'],graph['124']['inputs']['steps'],graph['130']['inputs']['fps'])==(362,12,24)
    assert not list(run.rglob('H3_INPUT_READY.json')) and not list(run.rglob('CLAIM.json'))
    assert diag.prepare(run)==out


def test_selected_pixels_cannot_use_other_observation(run):
    part=diag.minute.segment(run,'S01');path=part/'DIAGNOSTIC_GENERATION_SELECTION.json';value=diag.read(path)
    value['image']=diag.input_value(run,'S04')['first_image'];path.write_text(json.dumps(value),encoding='utf-8')
    with pytest.raises(ValueError,match='actual_failed_or_deviated'):diag.input_value(run,'S01')


def test_quality_true_cannot_be_smuggled_as_diagnostic_override(run):
    part=diag.minute.segment(run,'S01');path=part/'DIAGNOSTIC_GENERATION_SELECTION.json';value=diag.read(path)
    value['quality_passed']=True;path.write_text(json.dumps(value),encoding='utf-8')
    with pytest.raises(ValueError,match='explicit_observed_diagnostic'):diag.input_value(run,'S01')


def test_prepared_job_without_root_launch_cannot_post(run,monkeypatch):
    diag.prepare(run,'S01');forbid_http(monkeypatch)
    with pytest.raises(FileNotFoundError):diag.submit(run,'S01')


def test_post_prepare_input_tamper_blocks_fresh_launch(run,monkeypatch):
    diag.prepare(run,'S01');part=diag.minute.segment(run,'S01')
    path=part/'ACTUAL_ANCHOR_OBSERVATION.json';value=diag.read(path);value['deviations'].append('controlled mutation')
    path.write_text(json.dumps(value),encoding='utf-8');forbid_http(monkeypatch)
    with pytest.raises(ValueError):diag.launch_request(run,'S01')


@pytest.fixture
def service(run):
    state=dict(posts=0,graph=None,mode='success');cfg=diag.read(run/'H3_CONFIG.json')
    fixtures=run/'cpu_fixtures';fixtures.mkdir()
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=red:s=736x1312:r=24',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=32000','-af',
        'aformat=channel_layouts=stereo,atrim=end_sample=482400,asetpts=N/SR/TB',
        '-frames:v','362','-c:v','libx264','-preset','ultrafast','-threads','2','-c:a','aac','-ar','32000',
        '-ac','2',str(fixtures/'video_00001_.mp4')],capture_output=True,check=True,timeout=60)
    subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(fixtures/'video_00001_.mp4'),
        '-vn','-c:a','flac',str(fixtures/'audio_00001.flac')],capture_output=True,check=True,timeout=30)
    from PIL import Image
    for role in ('first','last'):Image.new('RGB',(736,1312),'red').save(fixtures/(role+'_00001_.png'))
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,value):
            body=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            if self.path=='/system_stats':return self.send(dict(system=dict(argv=['--input-directory',cfg['input_root'],'--output-directory',cfg['output_root']])))
            if self.path=='/queue':return self.send(dict(queue_running=[],queue_pending=[]))
            if self.path=='/history/controlled-http-001':return self.send({'controlled-http-001':state['history']})
            raise AssertionError('unexpected local test route '+self.path)
        def do_POST(self):
            assert self.path=='/prompt';request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['posts']+=1;state['graph']=request['prompt']
            if state['mode']=='unknown':return self.send({})
            graph=deepcopy(request['prompt']);graph['124']['inputs']['denoise']=1.0;graph['130']['inputs']['fps']=24.0
            outputs={}
            for role in ('video','audio','first','last'):
                prefix=Path(graph['save_'+role]['inputs']['filename_prefix']);dest=Path(cfg['output_root'])/prefix.parent
                dest.mkdir(parents=True,exist_ok=True);source=next(fixtures.glob(role+'_*'));shutil.copyfile(source,dest/source.name)
                outputs['save_'+role]={('audio' if role=='audio' else 'images'):[dict(filename=source.name,subfolder=prefix.parent.as_posix(),type='output')]}
            state['history']=dict(prompt=[1,'controlled-http-001',graph],status=dict(completed=True,status_str='success'),outputs=outputs)
            self.send(dict(prompt_id='controlled-http-001'))
    http=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    cfg['service_url']='http://127.0.0.1:'+str(http.server_port)
    (run/'H3_CONFIG.json').write_text(json.dumps(cfg),encoding='utf-8')
    try:yield state
    finally:http.shutdown();http.server_close();thread.join(timeout=3)


def approve(run,sid):
    request=diag.launch_request(run,sid)
    diag.freeze(diag.minute.segment(run,sid)/'ROOT_LAUNCH_DIAGNOSTIC_VIDEO.json',
        dict(request=request,approved_by='Controlled local HTTP fixture; no real model',evidence=['CPU fixture only.']))


def test_local_http_blackbox_posts_once_collects_all_originals_and_preserves_failed_review(run,service):
    (run/'job_ids.txt').write_text('preserved_image original-image-id\n',encoding='utf-8')
    (run/'LOG.md').write_text('Preserved image log\n',encoding='utf-8')
    before=diag.bind(diag.minute.segment(run,'S01')/'ACTUAL_ANCHOR_OBSERVATION.json')
    diag.prepare(run,'S01');approve(run,'S01')
    assert diag.submit(run,'S01')['status']=='submitted'
    assert diag.collect_known(run,'S01')['status']=='media_review_required'
    final=diag.read(diag.minute.segment(run,'S01')/'FINAL_RESULT.json')
    result=diag.read(diag.core.check(final['native_result']))
    assert set(result['files'])=={'video','audio','first','last'} and result['technical_status']=='technical_saved'
    assert result['production_approved'] is False and 'continuity_input' not in result
    receipt=diag.read(diag.core.check(final['diagnostic_receipt']))
    assert receipt['quality_passed'] is receipt['visual_ready'] is False
    native_run=diag.minute.folders(run,'S01')[1]
    assert receipt['native_records']==dict(plan=diag.bind(native_run/'PLAN.json'),
        request=diag.bind(native_run/'shots/S01/REQUEST.json'),history=diag.bind(native_run/'shots/S01/HISTORY.json'))
    assert receipt['source_evaluation']['status']=='reanchor_required'
    assert diag.bind(diag.minute.segment(run,'S01')/'ACTUAL_ANCHOR_OBSERVATION.json')==before
    assert diag.execute(run,'S01',1,1)['status']=='media_review_required' and service['posts']==1
    ledger=(run/'job_ids.txt').read_text(encoding='utf-8');log=(run/'LOG.md').read_text(encoding='utf-8')
    assert ledger.startswith('preserved_image original-image-id\n')
    assert ledger.count('diagnostic_video S01 controlled-http-001\n')==1
    assert log.startswith('Preserved image log\n')
    assert log.count(' NATIVE_ID S01 controlled-http-001\n')==log.count(' SAVED S01 controlled-http-001\n')==1


def test_local_http_unknown_response_preserves_claim_and_never_reposts(run,service):
    service['mode']='unknown';diag.prepare(run,'S01');approve(run,'S01')
    assert diag.submit(run,'S01')['status']=='outcome_unknown'
    assert diag.execute(run,'S01',1,1)['status']=='outcome_unknown'
    assert service['posts']==1
