"""CPU orchestration and stub service tests, not novel/media quality approval."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

from PIL import Image
import pytest
from src.content_factory import visual_h3_continuity_minute_v34 as f


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');return f.bind(path)

def module(name):
    path=Path(__file__).with_name(name+'.py');spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

@pytest.fixture
def prepared(tmp_path,monkeypatch):
    # The short CPU fixture is honestly 4x124 frames, not a fake full-minute H3.
    monkeypatch.setattr(f,'RUN',tmp_path/'minute');monkeypatch.setattr(f,'DURATION',5);monkeypatch.setattr(f,'FRAMES',124);monkeypatch.setattr(f,'QUOTES',4)
    monkeypatch.setattr(f.stills,'ROOT',tmp_path/'isolated_project')
    spatial=module('test_visual_spatial_stills_v24');stills_root=tmp_path/'spatial_fixture';stills_root.mkdir()
    _,kw=spatial.prepared.__wrapped__(stills_root);spatial.skin_receipt(kw)
    source=module('test_visual_h3_continuity_input_v33');refs=f.read(kw['inputs'])['references'];rows=[]
    for sid in f.IDS:
        folder=tmp_path/sid;folder.mkdir();row=source.make_entry(folder);row['shot_id']=sid
        row['canonical_characters']={r['entity_id']:r['image'] for r in refs};row['character_names']=dict(su_mo='苏墨',ye_nan='叶南',ye_xijue='叶西决')
        row['character_description_span_ids']={k:['s0'] for k in row['canonical_characters']}
        row['camera_beats'][0]['actors']={k:dict(visible_parts=['face','torso'],pose='躺在床上') for k in row['canonical_characters']}
        # All four source templates use the same canonical room binding.
        if rows:row['canonical_room']=rows[0]['canonical_room']
        rows.append(row)
    source_path=write(tmp_path/'sources.json',dict(schema=f.core.SCHEMA,shots=rows))
    run=f.RUN;run.mkdir();cfg0=f.read(kw['config']) if isinstance(kw['config'],Path) else kw['config']
    # The image fixture's intentionally extraneous Config fields are removed by
    # the real producer whitelist. H3 explicitly shares the same isolated mutex.
    image_cfg=cfg0['config'];config_path=write(tmp_path/'image_config.json',cfg0)
    h3cfg={k:image_cfg[k] for k in ('service_url','input_root','output_root','protected_pause_path')}
    base=tmp_path/'base_workflow.json';shutil.copyfile(f.native.DEFAULT_BASE,base)
    h3cfg.update(gpu_lock_root=str(f.stills.ROOT/'data/visual_asset_pipeline/gpu'),base_workflow=str(base),
        runs_root=str(run/'visual_h3_v3'),video_enabled=True,width=736,height=1312,timeout=3)
    spec=dict(schema='h3_continuity_minute_spec/v34',source_case=source_path,initial_context=dict(image=rows[0]['actual_first_image'],origin='Controlled initial PNG fixture, no semantic identity assertion'),
        spatial=dict(handoff=f.bind(kw['handoff']),render_result=f.bind(kw['render_result']),inputs=f.bind(kw['inputs']),config=config_path),
        stage_items={sid:'S01_start' for sid in f.IDS},h3_config=h3cfg)
    write(run/'MINUTE_SPEC.json',spec)
    auth=dict(schema='h3_continuity_minute_authorization/v34',user_statement='Controlled CPU protocol test only',upstream_spec=source_path,
        engineering_scope_not_user_quoted_numeric_limit=True,engineering_limits=dict(image_submissions=8,video_submissions=4,cloud_media=0),
        text_model_calls=0,publication=False,diagnostic=True,automatic_semantic_video_retakes=False,unknown_replays=False)
    write(run/'USER_AUTHORIZATION.json',auth);f.prepare(run)
    return run,spec,spatial

def context_review(run,sid):
    f.stage_context(run,sid);ctx=f.read(run/'segments'/sid/'CONTEXT.json');row=f.core.read(f.read(run/'PLAN.json')['templates'][sid]);keys=row['canonical_characters']
    write(run/'segments'/sid/'CONTEXT_REVIEW.json',dict(schema=f.core.REVIEW,reviewed_by='CPU fixture observer',target_image=ctx['image'],
        canonical_characters=keys,canonical_room=row['canonical_room'],completion_known=True,outcome_unknown=False,
        checks=dict(topology_coherent=None,room_identity=None,faces={k:None for k in keys},identities={k:None for k in keys}),
        evidence=['Controlled opaque-tail regression; not an actual facial quality approval.']))
    return f.prepare_context_entry(run,sid)

def source_review(run,sid):
    report=context_review(run,sid);entry=f.core._entries(report['context_spec'])[0];spec=f.read(run/'MINUTE_SPEC.json')
    handoff=f.core.read(spec['spatial']['handoff']);spatial=f.core.read(handoff['plan']);state=f.stills._state(spatial,spec['stage_items'][sid])
    write(run/'segments'/sid/'SOURCE_STATE_REVIEW.json',dict(schema='h3_reanchor_source_state_review/v33',
        work_order_sha256=report['work_order_sha256'],entry_base_sha256=f.digest(entry),spatial_plan=handoff['plan'],item_id=spec['stage_items'][sid],
        state_sha256=f.digest(state),canonical_characters=entry['canonical_characters'],canonical_room=entry['canonical_room'],
        source_current_state_matches=True,room_identity_matches=True,completion_known=True,outcome_unknown=False,
        reviewed_by='Controlled CPU protocol',evidence=['Fixture state correspondence, no semantic production claim.']))
    return report

def approve(run,sid,kind):
    value=f.approval_request(run,sid,kind);value.update(approved_for_dispatch=True,reviewed_by='CPU protocol fixture',evidence=['Prepared native graph and bound files fixture.'])
    write(run/'segments'/sid/('ROOT_'+kind.upper()+'_APPROVAL.json'),value)

def launch(run):
    qa=f.PROJECT/'data/qa/h3_continuity_minute_v34_20261109/TEST_FIXTURE_ACCEPTANCE.json';write(qa,dict(cpu_fixture=True,production_approved=False))
    plan=f.read(run/'PLAN.json');write(run/'ROOT_LAUNCH_APPROVAL.json',dict(schema='h3_continuity_minute_launch_approval/v34',
        plan=f.bind(run/'PLAN.json'),authorization=plan['authorization'],approved_for_new_media=True,execution_sources=f._sources(),cpu_acceptance=f.bind(qa)))

class Service:
    def __init__(self,monkeypatch):
        self.posts=[];self.histories={};self.drop=False
        monkeypatch.setattr(f.native,'_http',self.request);monkeypatch.setattr(f.jobs,'_http',self.request)
    def request(self,cfg,route,value=None):
        if route=='/system_stats':return dict(system=dict(argv=['main.py','--input-directory',cfg['input_root'],'--output-directory',cfg['output_root']]))
        if route=='/queue':return dict(queue_running=[],queue_pending=[])
        if route=='/prompt':
            self.posts.append(deepcopy(value))
            if self.drop:raise ConnectionError('Controlled CPU lost response')
            return dict(prompt_id='cpu_native_'+str(len(self.posts)),node_errors={})
        if route.startswith('/history/'):return self.histories
        raise AssertionError(route)
    def finish_image(self,run,sid):
        folder=f._image_job(run,sid);plan=f.read(folder/'PLAN.json');graph=f.read(folder/'workflow_api.json');pid=f.read(folder/'RESPONSE.json')['prompt_id'];outputs={}
        for nid,node in graph.items():
            if node['class_type']=='SaveImage':
                rel=Path(node['inputs']['filename_prefix']+'_00001_.png');path=Path(plan['config']['output_root'])/rel;path.parent.mkdir(parents=True,exist_ok=True)
                Image.new('RGB',(736,1312),'gray').save(path);outputs[nid]=dict(images=[dict(filename=path.name,subfolder=rel.parent.as_posix(),type='output')])
        self.histories[pid]=dict(prompt=[0,pid,graph],status=dict(completed=True,status_str='success'),outputs=outputs)
    def finish_video(self,run,sid,media):
        video=f._video_run(run,sid);folder=video/'shots'/sid;graph=f.read(folder/'workflow_api.json');pid=f.read(folder/'RESPONSE.json')['prompt_id'];cfg=f.read(video/'PLAN.json')['config'];outputs={}
        for role,key,ext,source in [('video','images','mp4',sid+'.mp4'),('audio','audio','flac','audio.flac'),('first','images','png',sid+'.png'),('last','images','png',sid+'.png')]:
            rel=Path(graph['save_'+role]['inputs']['filename_prefix']+'_00001_.'+ext);path=Path(cfg['output_root'])/rel;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(media/source,path)
            outputs['save_'+role]={key:[dict(filename=path.name,subfolder=rel.parent.as_posix(),type='output')]}
        self.histories[pid]=dict(prompt=[0,pid,graph],status=dict(completed=True,status_str='success',messages=[['execution_success',{}]]),outputs=outputs)

def anchor_review(run,sid):
    report=f.prepare_context_entry(run,sid);candidate=f._candidate(run,sid);entry=f.core._entries(report['context_spec'])[0];keys=entry['canonical_characters']
    write(run/'segments'/sid/'ANCHOR_REVIEW.json',dict(schema=f.core.REVIEW,reviewed_by='CPU protocol fixture',target_image=candidate['image'],canonical_characters=keys,
        canonical_room=entry['canonical_room'],completion_known=True,outcome_unknown=False,work_order_sha256=report['work_order_sha256'],source_current_state_matches=True,
        checks=dict(topology_coherent=True,room_identity=True,faces={k:True for k in keys},identities={k:True for k in keys}),evidence=['Protocol-only accepted fixture, not a model quality result.']))

@pytest.fixture(scope='module')
def media(tmp_path_factory):
    root=tmp_path_factory.mktemp('v34_cpu_clock_media')
    for sid,color in zip(f.IDS,['gray','blue','green','red']):
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',f'color=c={color}:s=736x1312:r=24','-f','lavfi','-i','anullsrc=r=48000:cl=stereo',
            '-frames:v','124','-t',str(124/24),'-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac',str(root/(sid+'.mp4'))],check=True,timeout=60)
        Image.new('RGB',(736,1312),color).save(root/(sid+'.png'))
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t',str(124/24),'-c:a','flac',str(root/'audio.flac')],check=True,timeout=30)
    return root

def test_prepare_preserves_source_and_does_not_fabricate_later_tail_or_review(prepared):
    run,spec,_=prepared;assert f.status(run)['technical_saved']==0
    assert f.stage_context(run,'S02')['status']=='awaiting_predecessor'
    assert not (run/'segments/S02/CONTEXT.json').exists() and not (run/'segments/S02/CONTEXT_REVIEW.json').exists()
    assert f.advance(run)['status']=='context_review_required'
    assert not list(run.rglob('REQUEST.json')) and not list((run/'stills').glob('*/PLAN.json'))
    for sid,original in zip(f.IDS,f.core._entries(spec['source_case'])):
        template=f.core.read(f.read(run/'PLAN.json')['templates'][sid]);assert template==f._template(original)

def test_context_missing_face_prepares_real_four_reference_job_only_after_source_review(prepared):
    run,_,_=prepared;report=context_review(run,'S01');assert report['status']=='reanchor_required'
    assert f.prepare_anchor(run,'S01')['status']=='source_state_review_required'
    source_review(run,'S01');prepared=f.prepare_anchor(run,'S01');assert prepared['status']=='image_prepared'
    p=f.read(f._image_job(run,'S01')/'PLAN.json');assert len(p['inputs'])==4 and all(Path(i['staged_path']).is_file() for i in p['inputs'])
    assert not (f._image_job(run,'S01')/'REQUEST.json').exists()

@pytest.mark.parametrize('legacy_record',[False,True])
def test_reprepare_anchor_after_post_running_saved_and_shared_reservation_change_is_idempotent(prepared,monkeypatch,legacy_record):
    run,_,_=prepared;service=Service(monkeypatch);source_review(run,'S01');f.prepare_anchor(run,'S01');launch(run)
    job=f._image_job(run,'S01');record=run/'segments/S01/ANCHOR_PREPARED.json'
    if legacy_record:
        old=f.read(record);old['batch']['state']=f.jobs.status(job);old['batch']['global_reserved_branches']=1;write(record,old)
    prepared_binding=f.bind(record);approve(run,'S01','image');f.tick(run,allow_submit=True)
    original=[f.bind(job/name) for name in ('PLAN.json','workflow_api.json','REQUEST.json','CLAIM.json','RESPONSE.json')]
    pid=f.jobs.status(job)['prompt_id'];graph=f.read(job/'workflow_api.json')
    assert f.prepare_anchor(run,'S01')['status']=='image_prepared' and f.bind(record)==prepared_binding
    # A different, real prepared batch increases the shared branch reservation.
    spatial=f.read(run/'MINUTE_SPEC.json')['spatial'];plan=f.read(run/'PLAN.json')
    f.core.prepare_reanchor(f.bind(run/'segments/S01/CONTEXT_SPEC.json'),'S01',run/'stills/other_reserved_anchor',
        handoff=f.check(spatial['handoff']),render_result=f.check(spatial['render_result']),inputs=f.check(spatial['inputs']),
        authorization=f.check(plan['image_authorization']),config=f.check(spatial['config']),item_id='S01_start',
        source_binding_review=f.bind(run/'segments/S01/SOURCE_STATE_REVIEW.json'))
    assert f.budget(run)['image_reserved']==2
    service.histories[pid]=dict(prompt=[0,pid,graph],status=dict(completed=False,status_str='running'))
    result=f.tick(run,allow_submit=True)
    assert result['dispatch']=='original_image_id_only' and f.jobs.status(job)['status']=='running'
    assert len(service.posts)==1 and f.bind(record)==prepared_binding
    assert f.prepare_anchor(run,'S01')['status']=='image_prepared' and f.bind(record)==prepared_binding
    service.finish_image(run,'S01');f.collect_known(run)
    assert f.jobs.status(job)['status']=='saved' and f.read(job/'RESULT.json')['prompt_id']==pid
    assert f.prepare_anchor(run,'S01')['status']=='image_prepared' and f.bind(record)==prepared_binding
    assert [f.bind(b['path']) for b in original]==original and len(service.posts)==1
    assert f.prepare_video(run,'S01')['status']=='anchor_review_required'

@pytest.mark.parametrize('field',['work_order_sha256','batch_binding','job_identity','producer_plan'])
def test_reprepare_anchor_rejects_changed_static_contract_without_rewriting_event(prepared,field):
    run,_,_=prepared;source_review(run,'S01');f.prepare_anchor(run,'S01');record=run/'segments/S01/ANCHOR_PREPARED.json';value=f.read(record)
    if field=='work_order_sha256':value[field]='0'*64
    elif field=='batch_binding':value['batch']['binding']['sha256']='0'*64
    elif field=='job_identity':value['batch']['state']['job_id']='foreign_native_job'
    else:value['producer']['plan']['sha256']='0'*64
    before=write(record,value)
    with pytest.raises(ValueError,match='frozen_anchor_prepared_contract_changed'):f.prepare_anchor(run,'S01')
    assert f.bind(record)==before and not (f._image_job(run,'S01')/'REQUEST.json').exists()

def test_root_approvals_needed_before_any_stub_post_and_unknown_not_replayed(prepared,monkeypatch):
    run,_,_=prepared;service=Service(monkeypatch);source_review(run,'S01');f.prepare_anchor(run,'S01');launch(run)
    result=f.tick(run,allow_submit=True);assert result['dispatch']=='root_image_approval_required' and not service.posts
    approve(run,'S01','image');service.drop=True;f.tick(run,allow_submit=True);assert len(service.posts)==1
    assert f.tick(run,allow_submit=True)['dispatch']=='native_terminal_or_unknown_preserved' and len(service.posts)==1
    assert f.budget(run)['image_claimed']==1

def test_rejected_anchor_review_is_preserved_and_cannot_enter_h3(prepared,monkeypatch):
    run,_,_=prepared;service=Service(monkeypatch);source_review(run,'S01');f.prepare_anchor(run,'S01');launch(run);approve(run,'S01','image')
    f.tick(run,allow_submit=True);service.finish_image(run,'S01');f.collect_known(run);anchor_review(run,'S01')
    path=run/'segments/S01/ANCHOR_REVIEW.json';review=f.read(path);review['checks']['identities']['su_mo']=None;write(path,review)
    result=f.tick(run,allow_submit=True);assert result['status']=='blocked_current_inputs' and len(service.posts)==1
    assert (f._image_job(run,'S01')/'RESULT.json').exists() and not (f._video_run(run,'S01')/'PLAN.json').exists()

def test_full_serial_new_tail_reanchor_four_videos_cpu_clock_and_binding(prepared,monkeypatch,media):
    run,_,_=prepared;service=Service(monkeypatch);launch(run)
    for index,sid in enumerate(f.IDS):
        source_review(run,sid);f.prepare_anchor(run,sid);approve(run,sid,'image');f.tick(run,allow_submit=True)
        assert len(service.posts)==2*index+1
        service.finish_image(run,sid);f.collect_known(run);anchor_review(run,sid)
        assert f.prepare_video(run,sid)['status']=='video_prepared';binding=f.read(run/'segments'/sid/'VIDEO_BINDING.json')
        assert binding['h3_run']==str(f._video_run(run,sid)) and binding['segment_spec']==f.bind(run/'segments'/sid/'EXECUTABLE_SPEC.json')
        approve(run,sid,'video');f.tick(run,allow_submit=True);assert len(service.posts)==2*index+2
        f.tick(run,allow_submit=True);assert len(service.posts)==2*index+2
        service.finish_video(run,sid,media);f.collect_known(run)
        if index<3:
            next_sid=f.IDS[index+1];f.stage_context(run,next_sid);ctx=f.read(run/'segments'/next_sid/'CONTEXT.json');result=f._result(run,sid)[1]
            assert ctx['image']=={k:result['files']['last'][k] for k in ('path','sha256')} and ctx['origin']['native_id']==result['prompt_id']
    final=f.assemble(run);assert final['clock']['native_frames']==496 and final['clock']['width']==736 and final['clock']['audio_samples']==496*2000
    assert len(set(final['native_ids']))==4 and final['production_approved'] is False and len(service.posts)==8
    assert f.assemble(run)==final and f.budget(run)['video_claimed']==4
    assert len((run/'job_ids.txt').read_text(encoding='utf-8').splitlines())==8

def test_pause_and_changed_current_source_still_collect_original_video(prepared,monkeypatch,media):
    run,_,_=prepared;service=Service(monkeypatch);source_review(run,'S01');f.prepare_anchor(run,'S01');launch(run);approve(run,'S01','image')
    f.tick(run,allow_submit=True);service.finish_image(run,'S01');f.collect_known(run);anchor_review(run,'S01');f.prepare_video(run,'S01');approve(run,'S01','video');f.tick(run,allow_submit=True)
    write(run/'PAUSE.json',dict(operator='Controlled protocol pause'));source=f.core._entries(f.read(run/'PLAN.json')['source_case'])[0]['source'];Path(source['path']).write_text('Changed current source after original POST',encoding='utf-8')
    service.finish_video(run,'S01',media);current=f.collect_known(run)
    assert current['technical_saved']==1 and len(service.posts)==2 and f._result(run,'S01')[1]['prompt_id']=='cpu_native_2'
    assert f.tick(run,allow_submit=True)['dispatch']=='paused_no_new_media' and len(service.posts)==2

@pytest.mark.parametrize('target',['source','authorization','base','canonical'])
def test_current_bound_file_tamper_stops_new_preparation(prepared,target):
    run,spec,_=prepared
    path=spec['source_case']['path'] if target=='source' else run/'USER_AUTHORIZATION.json' if target=='authorization' else spec['h3_config']['base_workflow'] if target=='base' else f.core._entries(spec['source_case'])[0]['canonical_room']['path']
    Path(path).write_bytes(b'changed controlled file')
    with pytest.raises((ValueError,KeyError)):f.advance(run)

def test_projection_remains_bound_to_original_authority_and_cannot_reset_allowance(prepared):
    run,_,_=prepared;source_review(run,'S01');f.prepare_anchor(run,'S01');plan=f.read(run/'PLAN.json')
    projection=f.core.read(plan['image_authorization']);assert projection['root_authorization']==plan['authorization'] and projection['max_image_submissions']==8
    projection['max_image_submissions']=100;write(plan['image_authorization']['path'],projection)
    with pytest.raises(ValueError):f.budget(run)

def test_frozen_stage_approval_and_queue_checks_before_stub_submit(prepared,monkeypatch):
    run,_,_=prepared;service=Service(monkeypatch);source_review(run,'S01');f.prepare_anchor(run,'S01');launch(run);approve(run,'S01','image')
    path=run/'segments/S01/ROOT_IMAGE_APPROVAL.json';value=f.read(path);value['inputs']['graph']['sha256']='0'*64;write(path,value)
    with pytest.raises(ValueError,match='approval_binding'):f.tick(run,allow_submit=True)
    assert not service.posts and not (f._image_job(run,'S01')/'CLAIM.json').exists()

def test_known_image_successor_keeps_failed_original_and_same_work_order(prepared,monkeypatch):
    run,_,_=prepared;service=Service(monkeypatch);report=source_review(run,'S01');f.prepare_anchor(run,'S01');launch(run);approve(run,'S01','image')
    f.tick(run,allow_submit=True);service.finish_image(run,'S01');f.collect_known(run);original=f._candidate(run,'S01')
    rejection=dict(schema='h3_minute_anchor_rejection/v34',decision='rejected',original_native_result=f.bind(f._image_job(run,'S01')/'RESULT.json'),
        original_image=original['image'],original_native_id=original['prompt_id'],work_order_sha256=report['work_order_sha256'],completion_known=True,outcome_unknown=False,
        reviewed_by='CPU protocol observer',evidence=['Controlled known semantic rejection, original remains saved.'])
    write(run/'segments/S01/ROOT_ANCHOR_REJECTION.json',rejection)
    # A separate native image job with its own original ID, same unchanged
    # source work order/canonical inputs and the exact same global projection.
    spec=f.read(run/'MINUTE_SPEC.json');plan=f.read(run/'PLAN.json');spatial=spec['spatial'];successor=run/'stills'/(run.name+'_S01_known_r2')
    value=f.core.prepare_reanchor(f.bind(run/'segments/S01/CONTEXT_SPEC.json'),'S01',successor,
        handoff=f.check(spatial['handoff']),render_result=f.check(spatial['render_result']),inputs=f.check(spatial['inputs']),authorization=f.check(plan['image_authorization']),
        config=f.check(spatial['config']),item_id=spec['stage_items']['S01'],source_binding_review=f.bind(run/'segments/S01/SOURCE_STATE_REVIEW.json'))
    # Test-only service completion uses the same native protocol functions,
    # without changing the coordinator's fixed original image-job selector.
    job=successor/'batches/reanchor_S01';f.stills.tick(successor,'reanchor_S01');p=f.read(job/'PLAN.json');g=f.read(job/'workflow_api.json');pid=f.read(job/'RESPONSE.json')['prompt_id'];outputs={}
    for nid,node in g.items():
        if node['class_type']=='SaveImage':
            rel=Path(node['inputs']['filename_prefix']+'_00001_.png');dest=Path(p['config']['output_root'])/rel;dest.parent.mkdir(parents=True,exist_ok=True);Image.new('RGB',(736,1312),'blue').save(dest)
            outputs[nid]=dict(images=[dict(filename=dest.name,subfolder=rel.parent.as_posix(),type='output')])
    service.histories[pid]=dict(prompt=[0,pid,g],status=dict(completed=True,status_str='success'),outputs=outputs)
    f.stills.tick(successor,'reanchor_S01');candidate=f.read(job/'CANDIDATES.json')['items'][0]
    original_context=f.read(run/'segments/S01/CONTEXT.json');anchor_review(run,'S01');review=f.read(run/'segments/S01/ANCHOR_REVIEW.json')
    rejected=deepcopy(review);rejected['checks']['identities']['su_mo']=False;write(run/'segments/S01/ANCHOR_REVIEW.json',rejected)
    review['target_image']=candidate['image']
    coverage=write(run/'segments/S01/ANCHOR_REVIEW_KNOWN_R2.json',review)
    receipt=deepcopy(value['receipt_template']);receipt['candidates']=f.bind(job/'CANDIDATES.json');receipt_binding=write(run/'segments/S01/KNOWN_R2_RECEIPT.json',receipt)
    selected=f.select_anchor(run,'S01',receipt_binding,coverage);assert selected['status']=='known_successor_selected' and selected['model_calls']==0
    assert f.read(run/'segments/S01/CONTEXT.json')==original_context and f._candidate(run,'S01')==original
    assert f.prepare_video(run,'S01')['status']=='video_prepared'
    assert f.read(run/'segments/S01/VIDEO_BINDING.json')['selected_first']==candidate['image']
    assert f.budget(run)['image_reserved']==2 and f.budget(run)['image_claimed']==2
    with pytest.raises(ValueError,match='frozen_video_handoff'):f.select_anchor(run,'S01',receipt_binding,coverage)

def test_unknown_original_image_cannot_escape_via_successor_selection(prepared,monkeypatch):
    run,_,_=prepared;service=Service(monkeypatch);source_review(run,'S01');f.prepare_anchor(run,'S01');launch(run);approve(run,'S01','image');service.drop=True
    f.tick(run,allow_submit=True)
    with pytest.raises(ValueError,match='known_saved'):f.select_anchor(run,'S01',dict(path='not_read',sha256='0'*64),dict(path='not_read',sha256='0'*64))
    assert len(service.posts)==1

def test_actual_r4_sources_prepare_ten_quotes_without_old_future_inputs(prepared,monkeypatch):
    old,spec,_=prepared;source=f.PROJECT/'data/qa/h3_prompt_identity_v33_20261108/REAL_CASE_r4/SPEC.json'
    run=old.parent/'actual_source_minute';run.mkdir();monkeypatch.setattr(f,'RUN',run)
    monkeypatch.setattr(f,'DURATION',15);monkeypatch.setattr(f,'FRAMES',362);monkeypatch.setattr(f,'QUOTES',10)
    actual=f.core._entries(f.bind(source));spec['source_case']=f.bind(source);spec['initial_context']['image']=actual[0]['actual_first_image'];spec['h3_config']['runs_root']=str(run/'visual_h3_v3')
    write(run/'MINUTE_SPEC.json',spec);auth=f.read(old/'USER_AUTHORIZATION.json');auth['upstream_spec']=spec['source_case'];write(run/'USER_AUTHORIZATION.json',auth)
    f.prepare(run);plan=f.read(run/'PLAN.json')
    assert sum(len(f.core.read(b)['audio']) for b in plan['templates'].values())==10
    for row in actual:
        template=f.core.read(plan['templates'][row['shot_id']]);assert template==f._template(row)
        assert 'actual_first_image' not in template and 'coverage_review' not in template
    assert f.stage_context(run,'S02')['status']=='awaiting_predecessor' and not (run/'segments/S02/CONTEXT.json').exists()
    assert not list(run.rglob('REQUEST.json')) and not list(run.rglob('CLAIM.json'))
