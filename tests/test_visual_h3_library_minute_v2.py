"""Library coverage, immutable inputs and controlled local-HTTP lifecycle."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import threading

import pytest
from PIL import Image

from src.content_factory import visual_h3_library_minute_v2 as flow

PROJECT=Path(__file__).resolve().parents[1]
PREVIOUS=PROJECT/'data/video_generation/h3_story_opening_minute_20261111_v1'
LIBRARY=PROJECT/'data/visual_asset_feature_cards/novel_canonical_20261112_v2/BINDING_INDEX.json'


@pytest.fixture
def run(tmp_path):
    p=tmp_path/'fresh_library_minute';p.mkdir()
    cfg=flow.read(PREVIOUS/'H3_CONFIG.json')
    for key in ('input_root','output_root','gpu_lock_root'):
        path=p/key;path.mkdir();cfg[key]=str(path)
    cfg['runs_root']=str(p/'visual_h3_v3')
    pause=p/'original_protected_pause.json';flow.freeze(pause,dict(controlled_cpu_fixture=True,paused=True));cfg['protected_pause_path']=str(pause)
    flow.freeze(p/'H3_CONFIG.json',cfg)
    binding=flow.read(LIBRARY);allowed=[]
    for category in ('characters','places'):
        for item in binding[category].values():
            for image in item['images'].values():allowed.append(dict(asset_id=image['asset_id'],version=image['version'],sha256=image['image']['sha256']))
    flow.freeze(p/'TEST_BINDING_APPROVAL.json',dict(schema='visual_library_binding_approval/v1',binding_index=flow.bind(LIBRARY),
        approved_by='Controlled CPU fixture, not production visual acceptance',evidence=['Transport and asset binding only.'],
        confirmed_entities=list(binding['characters'])+list(binding['places']),allow_candidate_assets=allowed,production_approved=False))
    return p


def specification(run):
    return dict(sources={s:flow.bind(PREVIOUS/'segments'/s/'SOURCE_CASE.json') for s in flow.IDS},
        library_binding=flow.bind(LIBRARY),binding_approval=flow.bind(run/'TEST_BINDING_APPROVAL.json'),
        library_selection=dict(place_id='su_mo_room',place_name='苏墨的房间',angle_by_actor={c:'left_oblique' for c in ('su_mo','ye_nan','ye_xijue')},place_views=['front','reverse']),
        config=flow.read(run/'H3_CONFIG.json'),authorization=dict(user_statement='Controlled local HTTP fixture only',cloud_calls=0,publication=False,unknown_replay=False))


def prepare(run):return flow.prepare(run,specification(run))


def initial_guide(run):
    cfg=flow.read(run/'H3_CONFIG.json');folder=Path(cfg['output_root'])/run.name/'initial';folder.mkdir(parents=True)
    image=folder/'image_00001_.png';Image.new('RGB',(736,1312),'gray').save(image)
    records=run/'controlled_initial';records.mkdir()
    graph={'save_image':dict(class_type='SaveImage',inputs=dict(filename_prefix=run.name+'/initial/image'))}
    flow.freeze(records/'PLAN.json',dict(controlled_initial=True))
    flow.freeze(records/'REQUEST.json',dict(prompt=graph))
    flow.freeze(records/'HISTORY.json',{'controlled-image-001':dict(prompt=[1,'controlled-image-001',graph],
        status=dict(completed=True,status_str='success'),outputs={'save_image':dict(images=[dict(filename=image.name,subfolder=run.name+'/initial',type='output')])})})
    flow.freeze(records/'RESULT.json',dict(file=flow.bind(image)))
    flow.freeze(run/'INITIAL_GUIDE.json',dict(schema='library_initial_guide/v2',image=flow.bind(image),source_image=flow.bind(image),
        native_prompt_id='controlled-image-001',native_output=dict(node_id='save_image',index=0,source_path=str(image)),
        generation_records={k:flow.bind(records/(k.upper()+'.json')) for k in ('plan','request','history','result')},
        completion_known=True,outcome_unknown=False))


def review(run,sid,visible=('ye_nan','ye_xijue')):
    request=flow.review_request(run,sid);assert request['status']=='actual_guide_state_review_required'
    q=flow.read(flow.core.check(request['request']))
    flow.freeze(flow.part(run,sid)/'GUIDE_STATE_REVIEW.json',dict(schema=flow.REVIEW,shot_id=sid,
        predecessor_result=q['predecessor_result'],guide_image=q['guide_image'],guide_visible_actor_ids=list(visible),
        world_actor_state={c:'角色仍处于原剧情的房间及当前实际持物状态。' for c in q['required_actor_assets']},
        screen_identity_map={c:'控制测试图中的'+c for c in visible},completion_known=True,outcome_unknown=False,
        reviewed_by='Controlled fixture, not a production image observation',evidence=['CPU protocol only.']))


def approve(run,sid):
    flow.freeze(flow.part(run,sid)/'ROOT_LAUNCH_VIDEO.json',dict(request=flow.launch_request(run,sid),
        approved_by='Controlled local HTTP fixture',evidence=['Not a real media/model request.']))


def test_four_sources_are_fresh_prepare_is_file_only_and_idempotent(run,monkeypatch):
    monkeypatch.setattr(flow.native,'_http',lambda *a,**k:pytest.fail('unexpected dispatch'))
    result=prepare(run);assert result==prepare(run) and result['model_posts']==0
    p=flow.read(run/'PLAN.json');assert p['all_segments_new'] is True and 'prefix' not in p
    assert [s['shot_id'] for s in p['sources']]==list(flow.IDS)
    assert flow.review_request(run,'S01')['status']=='initial_generated_guide_required'
    assert flow.review_request(run,'S02')['status']=='upstream_native_tail_required'
    assert not list(run.rglob('CLAIM.json')) and not (run/'imported').exists()


def test_missing_library_notice_precedes_plan_freeze(run,monkeypatch):
    monkeypatch.setattr(flow.features,'resolve_segment',lambda *a,**k:dict(status='missing_notice',notices=[dict(entity_id='ye_nan',code='image_missing')]))
    result=prepare(run);assert result['status']=='waiting_asset' and result['model_posts']==0
    assert (run/'MISSING_ASSETS.latest.json').exists() and not (run/'PLAN.json').exists()
    assert result['details']['shot_id']=='S01'


def test_minimum_payload_library_descriptions_and_interwoven_original_quotes(run):
    prepare(run);initial_guide(run);review(run,'S01');v=flow.input_value(run,'S01')
    assert set(v['script_fields'])=={'characters','time','location','actions','language','visuals'}
    assert v['script_fields']['time']['story_time']=='原文未明确具体时刻'
    assert len(v['references'])==9 and v['guide_visible_actor_ids']==['ye_nan','ye_xijue']
    assert {r['actor_id'] for r in v['references'][:-1] if r['kind']=='character'}=={'su_mo','ye_nan','ye_xijue'}
    for card in v['library_resolution']['character_descriptions'].values():assert card['description'] in v['compiled_prompt']
    assert v['library_resolution']['environment_description']['description'] in v['compiled_prompt']
    entry=flow.core._entries(v['source_case'])[0]
    assert flow.core.QUOTE.findall(v['compiled_prompt'])==flow.core.QUOTE.findall(flow.core.compile_prompt(entry)['compiled_prompt'])
    assert '声音轨按原句依次演出' not in v['compiled_prompt'] and '0—5秒，叶西决本人开口说' in v['compiled_prompt']
    assert '始终三人同时' not in v['compiled_prompt'] and '固定机位' not in v['compiled_prompt']


def test_prepare_stages_all_nine_actual_refs_including_offscreen_father(run):
    prepare(run);initial_guide(run);review(run,'S01');assert flow.prepare_video(run,'S01')['status']=='prepared'
    nr,plan,row=flow._load(run,'S01');g=flow.read(nr/'shots/S01/workflow_api.json')
    assert len(row['reference_map'])==9 and len([v for v in g.values() if v['class_type']=='LoadImage'])==9
    for i,r in enumerate(row['reference_map']):
        assert flow.native.file_sha(Path(plan['config']['input_root'])/r['input_name'])==r['image']['sha256']
        assert g['condition']['inputs'][f'ref_images.ref_image_{i}']==[f'ref_{i}',0]
    assert g['guide_start']['inputs']['image']==['ref_8',0] and g['guide_start']['inputs']['frame_idx']==0


@pytest.mark.parametrize('change',['no_vae','wrong_guide','bypass_positive','extra_ref'])
def test_reference_or_guide_bypass_is_rejected(run,change):
    prepare(run);initial_guide(run);review(run,'S01');flow.prepare_video(run,'S01')
    nr,p,row=flow._load(run,'S01');g=flow.read(nr/'shots/S01/workflow_api.json')
    if change=='no_vae':g['condition']['inputs'].pop('vae')
    elif change=='wrong_guide':g['guide_start']['inputs']['image']=['ref_0',0]
    elif change=='bypass_positive':g['126']['inputs']['conditioning']=['condition',0]
    else:g['condition']['inputs']['ref_images.ref_image_9']=['ref_0',0]
    with pytest.raises(ValueError):flow.validate_graph(g,row['scope'],row['reference_map'])


def test_successful_unrelated_initial_record_cannot_authorize_another_picture(run):
    prepare(run);initial_guide(run);p=run/'INITIAL_GUIDE.json';v=flow.read(p)
    wrong=run/'wrong.png';Image.new('RGB',(736,1312),'red').save(wrong);v['image']=flow.bind(wrong)
    p.write_text(json.dumps(v),encoding='utf-8')
    with pytest.raises(ValueError,match='initial_guide_pixels_not_native_output'):flow.initial_guide(run)


@pytest.fixture
def service(run):
    cfg=flow.read(run/'H3_CONFIG.json');state=dict(posts=0,mode='success',histories={})
    fixtures=run/'cpu_fixtures';fixtures.mkdir()
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=red:s=736x1312:r=24',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=32000','-af','aformat=channel_layouts=stereo,atrim=end_sample=482400,asetpts=N/SR/TB',
        '-frames:v','362','-c:v','libx264','-preset','ultrafast','-threads','2','-c:a','aac','-ar','32000','-ac','2',str(fixtures/'video_00001_.mp4')],capture_output=True,check=True,timeout=60)
    subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(fixtures/'video_00001_.mp4'),'-vn','-c:a','flac',str(fixtures/'audio_00001.flac')],capture_output=True,check=True,timeout=30)
    for role in ('first','last'):Image.new('RGB',(736,1312),'red').save(fixtures/(role+'_00001_.png'))
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def send(self,value):
            b=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
        def do_GET(self):
            if self.path=='/system_stats':return self.send(dict(system=dict(argv=['--input-directory',cfg['input_root'],'--output-directory',cfg['output_root']])))
            if self.path=='/queue':return self.send(dict(queue_running=[],queue_pending=[]))
            if self.path.startswith('/history/'):return self.send({k:v for k,v in state['histories'].items() if k==self.path.rsplit('/',1)[1]})
            raise AssertionError(self.path)
        def do_POST(self):
            assert self.path=='/prompt';r=json.loads(self.rfile.read(int(self.headers['Content-Length'])));state['posts']+=1
            if state['mode']=='unknown':return self.send({})
            pid=f"controlled-http-{state['posts']:03d}";g=deepcopy(r['prompt']);g['124']['inputs']['denoise']=1.0;g['130']['inputs']['fps']=24.0;outputs={}
            for role in ('video','audio','first','last'):
                prefix=Path(g['save_'+role]['inputs']['filename_prefix']);dest=Path(cfg['output_root'])/prefix.parent;dest.mkdir(parents=True,exist_ok=True)
                source=next(fixtures.glob(role+'_*'));target=dest/source.name;shutil.copyfile(source,target)
                outputs['save_'+role]={('audio' if role=='audio' else 'images'):[dict(filename=target.name,subfolder=prefix.parent.as_posix(),type='output')]}
            state['histories'][pid]=dict(prompt=[1,pid,g],status=dict(completed=True,status_str='success'),outputs=outputs)
            self.send(dict(prompt_id=pid))
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
    cfg['service_url']='http://127.0.0.1:'+str(server.server_port);(run/'H3_CONFIG.json').write_text(json.dumps(cfg),encoding='utf-8')
    try:yield state
    finally:server.shutdown();server.server_close();t.join(timeout=3)


def test_actual_local_http_collect_then_only_current_run_tail_drives_next(run,service):
    prepare(run);initial_guide(run);review(run,'S01');flow.prepare_video(run,'S01');approve(run,'S01')
    assert flow.submit(run,'S01')['status']=='submitted' and flow.collect_known(run,'S01')['status']=='media_review_required'
    assert flow.execute(run,'S01',poll_seconds=1,max_seconds=1)['status']=='media_review_required' and service['posts']==1
    review(run,'S02',visible=('su_mo',));v=flow.input_value(run,'S02');previous=flow.native_run(run,'S01')/'shots/S01/RESULT.json'
    assert v['predecessor_result']==flow.bind(previous) and v['references'][-1]['image']['sha256']==flow.read(previous)['files']['last']['sha256']
    assert len(v['references'])==9 and len(v['required_actor_assets'])==3
    assert flow.prepare_video(run,'S02')['status']=='prepared'
    assert not (run/'imported').exists()


def test_unknown_http_claim_is_kept_and_never_blindly_reposted(run,service):
    prepare(run);initial_guide(run);review(run,'S01');flow.prepare_video(run,'S01');approve(run,'S01');service['mode']='unknown'
    assert flow.submit(run,'S01')['status']=='outcome_unknown'
    assert flow.execute(run,'S01',poll_seconds=1,max_seconds=1)['status']=='outcome_unknown' and service['posts']==1


def test_actual_staged_identity_pixels_checked_before_post(run,monkeypatch):
    prepare(run);initial_guide(run);review(run,'S01');flow.prepare_video(run,'S01');approve(run,'S01')
    nr,p,row=flow._load(run,'S01');ref=row['reference_map'][0]
    (Path(p['config']['input_root'])/ref['input_name']).write_bytes(b'controlled mutation')
    monkeypatch.setattr(flow.native,'_service_paths',lambda *a:None);monkeypatch.setattr(flow.native,'_queue',lambda *a:dict(queue_running=[],queue_pending=[]))
    monkeypatch.setattr(flow.native,'_http',lambda *a,**k:pytest.fail('POST must be blocked'))
    with pytest.raises(ValueError,match='actual_staged_reference_pixels_changed'):flow.submit(run,'S01')
    assert not list(run.rglob('CLAIM.json'))
