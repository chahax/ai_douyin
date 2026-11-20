"""New minute source/guide separation and real local-HTTP dispatch regressions."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from PIL import Image

from test_visual_h3_library_minute_v2 import run, service
from src.content_factory import visual_h3_library_continuation_v1 as flow

PROJECT=Path(__file__).resolve().parents[1]
PREVIOUS=PROJECT/'data/video_generation/h3_story_opening_minute_20261111_v1'
COMPLETED=PROJECT/'data/video_generation/h3_library_bound_minute_20261112_v1'
LIBRARY=PROJECT/'data/visual_asset_feature_cards/novel_canonical_20261112_v2/BINDING_INDEX.json'


def spec(run,*,cut=False):
    sources={}
    for sid in flow.IDS:
        source=deepcopy(flow.read(PREVIOUS/'segments'/sid/'SOURCE_CASE.json'))
        entry=source['shots'][0];entry['source_entry_role']=flow.SOURCE_ROLE
        entry['planning_preview_image']=deepcopy(entry['actual_first_image'])
        path=run/'source_fixture'/sid/'SOURCE_CASE.json';flow.freeze(path,source);sources[sid]=flow.bind(path)
    final=flow.read(COMPLETED/'FINAL_RESULT.json')
    selected=dict(mode='same_scene',place_id='su_mo_room',place_name='苏墨的房间',
        actor_views={c:['front','left_oblique'] for c in ('su_mo','ye_nan','ye_xijue')},place_views=['front','reverse'])
    selections={s:deepcopy(selected) for s in flow.IDS}
    if cut:selections['S01'].update(mode='scene_cut',scene_guide_path=str(run/'scene_guide.json'),include_predecessor_context_reference=True)
    return dict(sources=sources,library_binding=flow.bind(LIBRARY),binding_approval=flow.bind(run/'TEST_BINDING_APPROVAL.json'),
        segment_selections=selections,config=flow.read(run/'H3_CONFIG.json'),
        continuation_origin=dict(schema=flow.ORIGIN,native_result=final['segments'][-1]['native_result'],preceding_final_result=flow.bind(COMPLETED/'FINAL_RESULT.json')),
        authorization=dict(user_statement='Controlled CPU/localHTTP test only',publication=False))


def review(run,sid='S01'):
    f=flow.for_run(run);request=f.review_request(run,sid)
    assert request['status']=='actual_guide_state_review_required'
    q=flow.read(flow.base.core.check(request['request']))
    flow.freeze(flow.base.part(run,sid)/'GUIDE_STATE_REVIEW.json',dict(schema=flow.base.REVIEW,shot_id=sid,
        predecessor_result=q['predecessor_result'],guide_image=q['guide_image'],guide_visible_actor_ids=['su_mo'],
        world_actor_state={c:'Controlled source state only.' for c in q['required_actor_assets']},screen_identity_map={'su_mo':'Controlled foreground father'},
        previous_scene_state='Controlled previous-room state, not the target scene.',
        completion_known=True,outcome_unknown=False,reviewed_by='Controlled test, not visual acceptance',evidence=['CPU test only.']))
    return f


def scene_guide(run):
    cfg=flow.read(run/'H3_CONFIG.json');jid=run.name+'_children_start'
    folder=Path(cfg['output_root'])/'visual_assets_v3'/jid;folder.mkdir(parents=True)
    source=folder/'image.png';Image.new('RGB',(736,1312),'blue').save(source)
    records=run/'scene_records';records.mkdir()
    local=records/'artifacts/save_scene';local.mkdir(parents=True)
    image=local/source.name;image.write_bytes(source.read_bytes())
    graph={'save_scene':dict(class_type='SaveImage',inputs=dict(filename_prefix='visual_assets_v3/'+jid+'/image'))}
    flow.freeze(records/'PLAN.json',dict(version='visual_image_jobs/v3',job_id=jid,graph_sha256=flow.base.core.digest(graph),inputs=[],config=dict(cfg,allowed_prefix='visual_assets_v3')))
    flow.freeze(records/'REQUEST.json',dict(prompt=graph))
    flow.freeze(records/'HISTORY.json',{'controlled-scene':dict(prompt=[1,'controlled-scene',graph],status=dict(completed=True,status_str='success'),
        outputs={'save_scene':dict(images=[dict(filename=image.name,subfolder='visual_assets_v3/'+jid,type='output')])})})
    flow.freeze(records/'RESULT.json',dict(version='visual_image_jobs/v3',job_id=jid,prompt_id='controlled-scene',technical_status='saved',production_approved=False,
        graph_sha256=flow.base.core.digest(graph),inputs_sha256=flow.base.core.digest([]),images=[dict(**flow.bind(image),source_path=str(source),save_node='save_scene')]))
    flow.freeze(run/'scene_guide.json',dict(schema=flow.SCENE_GUIDE,image=flow.bind(image),source_image=flow.bind(source),native_prompt_id='controlled-scene',
        native_output=dict(node_id='save_scene',index=0,source_path=str(source)),generation_records={k:flow.bind(records/(k.upper()+'.json')) for k in ('plan','request','history','result')},
        completion_known=True,outcome_unknown=False))


def approve(run,f,sid='S01'):
    flow.freeze(flow.base.part(run,sid)/'ROOT_LAUNCH_VIDEO.json',dict(request=f.launch_request(run,sid),
        approved_by='Controlled local HTTP only',evidence=['No model or real service use.']))


def test_prepare_is_source_only_external_tail_not_fabricated_initial(run,monkeypatch):
    monkeypatch.setattr(flow.base.core,'evaluate',lambda *a,**k:pytest.fail('source plan must not evaluate preview as an actual first frame'))
    specification=spec(run);result=flow.prepare(run,specification)
    assert result==flow.prepare(run,specification) and result['model_posts']==0
    f=review(run);value=f.input_value(run,'S01')
    assert value['predecessor_result']==specification['continuation_origin']['native_result']
    assert value['guide_kind']=='native_tail' and value['references'][-1]['asset_id'].startswith('native_tail:d841a1d7')
    assert value['first_image']!=flow.read(specification['sources']['S01']['path'])['shots'][0]['planning_preview_image']
    assert not (run/'INITIAL_GUIDE.json').exists() and not list(run.rglob('CLAIM.json'))
    assert f.prepare_video(run,'S01')['status']=='prepared'
    assert f._load(run,'S01')[1]['shots'][0]['first_frame']==value['first_image']


def test_single_actor_resolves_only_needed_views_and_description(run):
    selected=dict(place_id='su_mo_room',place_name='苏墨的房间',actor_views={'su_mo':['front','left_oblique']},place_views=['front','reverse'])
    result=flow.resolve_library(flow.bind(LIBRARY),flow.bind(run/'TEST_BINDING_APPROVAL.json'),['su_mo'],selected)
    assert result['status']=='ready' and len(result['references'])==4
    assert set(result['character_descriptions'])=={'su_mo'}
    selected['actor_views']['su_mo']=['front']
    assert flow.resolve_library(flow.bind(LIBRARY),flow.bind(run/'TEST_BINDING_APPROVAL.json'),['su_mo'],selected)['status']!='ready'
    selected['capacity_decision']=dict(front_only_actor_ids=['su_mo'],reason='Controlled explicit capacity test')
    result=flow.resolve_library(flow.bind(LIBRARY),flow.bind(run/'TEST_BINDING_APPROVAL.json'),['su_mo'],selected)
    assert result['status']=='ready' and len(result['references'])==3


def test_missing_view_stops_before_plan_claim_or_dispatch(run):
    specification=spec(run);specification['segment_selections']['S02']['actor_views']['su_mo']=['front','nonexistent_side']
    result=flow.prepare(run,specification)
    assert result['status']=='waiting_asset' and result['details']['shot_id']=='S02'
    assert not (run/'PLAN.json').exists() and not list(run.rglob('CLAIM.json'))


def test_capacity_never_silently_removes_requested_view(run):
    specification=spec(run)
    for views in specification['segment_selections']['S01']['actor_views'].values():views.append('right_oblique')
    result=flow.prepare(run,specification)
    assert result['status']=='waiting_asset' and 'capacity' in result['details']['library_notice']['notices'][0]['code']
    assert not (run/'PLAN.json').exists()


def test_wrong_selected_previous_native_rejected(run):
    specification=spec(run);specification['continuation_origin']['native_result']=flow.read(COMPLETED/'FINAL_RESULT.json')['segments'][0]['native_result']
    with pytest.raises(ValueError,match='last_selected_native'):flow.prepare(run,specification)
    assert not (run/'PLAN.json').exists()


def test_scene_cut_separate_start_and_previous_tail_have_distinct_paths(run,monkeypatch):
    flow.prepare(run,spec(run,cut=True));f=flow.for_run(run)
    assert f.review_request(run,'S01')['status']=='scene_generated_guide_required'
    scene_guide(run);f=review(run);v=f.input_value(run,'S01')
    assert len(v['references'])==9 and v['references'][-1]['kind']=='previous_scene_context'
    assert v['first_image']!=v['references'][-1]['image']
    monkeypatch.setattr(flow.base.core,'evaluate',lambda *a,**k:pytest.fail('legacy coverage evaluation is not actual generated guide'))
    assert f.prepare_video(run,'S01')['status']=='prepared'
    nr,p,row=f._load(run,'S01');g=flow.read(nr/'shots/S01/workflow_api.json')
    assert len([n for n in g.values() if n['class_type']=='LoadImage'])==10
    assert len([k for k in g['condition']['inputs'] if k.startswith('ref_images.')])==9
    assert g['guide_start']['inputs']['image']==['scene_start',0]
    assert row['input_name']==row['scope']+'/scene_start.png'
    for r in row['reference_map']:
        assert flow.base.native.file_sha(Path(p['config']['input_root'])/r['input_name'])==r['image']['sha256']
    assert flow.base.native.file_sha(Path(p['config']['input_root'])/row['guide_map']['input_name'])==v['first_image']['sha256']
    g['guide_start']['inputs']['image']=['ref_8',0]
    with pytest.raises(ValueError,match='generated_start_not_previous_room_tail'):f.validate_graph(g,row['scope'],row['reference_map'])


def test_scene_start_pixels_rechecked_before_real_POST(run,monkeypatch):
    flow.prepare(run,spec(run,cut=True));scene_guide(run);f=review(run);f.prepare_video(run,'S01');approve(run,f)
    nr,p,row=f._load(run,'S01')
    (Path(p['config']['input_root'])/row['guide_map']['input_name']).write_bytes(b'controlled mutation')
    monkeypatch.setattr(flow.base.native,'_http',lambda *a,**k:pytest.fail('POST must not happen'))
    with pytest.raises(ValueError,match='actual_staged_scene_guide_pixels_changed'):f.submit(run,'S01')
    assert not (nr/'shots/S01/CLAIM.json').exists()


def test_actual_local_HTTP_unknown_not_reposted_and_saved_tail_drives_later_segment(run,service):
    flow.prepare(run,spec(run));f=review(run);f.prepare_video(run,'S01');approve(run,f)
    assert f.submit(run,'S01')['status']=='submitted'
    assert f.collect_known(run,'S01')['status']=='media_review_required'
    previous=flow.bind(f.native_run(run,'S01')/'shots/S01/RESULT.json')
    f=review(run,'S02');v=f.input_value(run,'S02')
    assert v['predecessor_result']==previous and v['first_image']==flow.base.verify_native(previous)['last_image']
    f.prepare_video(run,'S02');approve(run,f,'S02');service['mode']='unknown'
    assert f.submit(run,'S02')['status']=='outcome_unknown'
    assert f.execute(run,'S02',poll_seconds=1,max_seconds=1)['status']=='outcome_unknown' and service['posts']==2


def test_voiceover_has_no_canonical_actor_or_onscreen_mouth_assignment(run):
    specification=spec(run);p=Path(specification['sources']['S01']['path']);data=flow.read(p)
    entry=data['shots'][0];entry['character_names']['narrator']='旁白';entry['audio'][0].update(speaker='narrator',mode='voiceover')
    p.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');specification['sources']['S01']=flow.bind(p)
    flow.prepare(run,specification);f=review(run);v=f.input_value(run,'S01')
    assert '中性旁白以画外声叙述' in v['compiled_prompt']
    assert '旁白本人开口' not in v['compiled_prompt'] and 'narrator' not in v['required_actor_assets']
    assert v['script_fields']['language'][0]['speaker']=='narrator'


def test_scene_cut_local_HTTP_saves_then_same_scene_uses_its_actual_last(run,service):
    flow.prepare(run,spec(run,cut=True));scene_guide(run);f=review(run);f.prepare_video(run,'S01');approve(run,f)
    assert f.submit(run,'S01')['status']=='submitted'
    assert f.collect_known(run,'S01')['status']=='media_review_required'
    previous=flow.bind(f.native_run(run,'S01')/'shots/S01/RESULT.json')
    f=review(run,'S02');v=f.input_value(run,'S02')
    assert v['predecessor_result']==previous and v['guide_kind']=='native_tail'
    assert len(v['references'])==9 and v['references'][-1]['image']==f.verify_native(previous)['last_image']
    assert f.prepare_video(run,'S02')['status']=='prepared'
    assert len([x for x in flow.read(f.native_run(run,'S02')/'shots/S02/workflow_api.json').values() if x['class_type']=='LoadImage'])==9


def test_wrong_scene_native_output_cannot_become_a_successful_guide(run):
    flow.prepare(run,spec(run,cut=True));scene_guide(run)
    p=run/'scene_guide.json';v=flow.read(p);wrong=run/'wrong.png';Image.new('RGB',(736,1312),'red').save(wrong)
    v['image']=flow.bind(wrong);p.write_text(json.dumps(v),encoding='utf-8')
    with pytest.raises(ValueError,match='actual_output_of_this_run'):flow.for_run(run).review_request(run,'S01')


def test_other_run_scene_job_cannot_be_imported_as_current_scene(run):
    flow.prepare(run,spec(run,cut=True));scene_guide(run)
    with pytest.raises(ValueError,match='image_job_identity_plan_graph_and_RESULT'):
        flow.generated_scene_guide(run,run/'scene_guide.json','a_different_run_children_start')


def test_scene_cut_requires_separately_bound_previous_state_description(run):
    flow.prepare(run,spec(run,cut=True));scene_guide(run);f=review(run)
    p=flow.base.part(run,'S01')/'GUIDE_STATE_REVIEW.json';v=flow.read(p);v.pop('previous_scene_state')
    p.write_text(json.dumps(v),encoding='utf-8')
    with pytest.raises(ValueError,match='actual_previous_scene_state_description'):f.input_value(run,'S01')
