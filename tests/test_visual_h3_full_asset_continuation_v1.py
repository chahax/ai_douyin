"""Actual accepted assets, CPU contracts and controlled local HTTP, no model."""
from copy import deepcopy
from pathlib import Path
import shutil

import pytest

from src.content_factory import visual_h3_full_asset_continuation_v1 as flow
from scripts import run_h3_full_asset_continuation as cli
from test_h3_story_opening_diagnostic import service as diagnostic_http_service


@pytest.fixture
def run(tmp_path):
    root=tmp_path/'full_assets';root.mkdir();cfg=cli.specification()['config']
    for key in ('input_root','output_root','gpu_lock_root'):
        p=root/key;p.mkdir();cfg[key]=str(p)
    pause=root/'protected_pause.json';flow.freeze(pause,dict(controlled_fixture=True,paused=True))
    cfg.update(protected_pause_path=str(pause),runs_root=str(root/'visual_h3_v3'))
    flow.freeze(root/'H3_CONFIG.json',cfg);return root


def initial(run):
    spec=cli.specification();spec['config']=flow.read(run/'H3_CONFIG.json');return flow.prepare(run,spec)


def review(run,sid,visible=('su_mo','ye_nan','ye_xijue')):
    req=flow.review_request(run,sid);assert req['status']=='actual_guide_state_review_required'
    v=flow.read(flow.core.check(req['request']))
    value=dict(schema=flow.REVIEW,shot_id=sid,predecessor_result=v['predecessor_result'],guide_image=v['guide_image'],
        guide_visible_actor_ids=list(visible),world_actor_state={c:'原剧情中该角色仍在同一房间，画外不等于离场。' for c in v['required_actor_assets']},
        screen_identity_map={c:'输入尾帧中的'+c for c in visible},completion_known=True,outcome_unknown=False,
        reviewed_by='Controlled CPU fixture, not production semantic approval',evidence=['Controlled transport test only.'])
    flow.freeze(flow.part(run,sid)/'GUIDE_STATE_REVIEW.json',value)


def no_http(monkeypatch):monkeypatch.setattr(flow.native,'_http',lambda *a,**k:pytest.fail('unexpected HTTP/model dispatch'))


def test_real_fixed_asset_set_and_prefix_prepare_are_file_only(run,monkeypatch):
    no_http(monkeypatch);spec=cli.specification();manifest=flow.bundle(spec['asset_manifest'],spec['asset_observation'])
    assert [r['slot'] for r in manifest['references']]==list(range(5))
    assert [r['intended_person_count'] for r in manifest['references']]==[1,1,1,0,0]
    assert all(r['kind']=='environment_detail' for r in manifest['references'][3:])
    result=initial(run);assert initial(run)==result and result['model_posts']==0
    assert result['S04']['status']=='upstream_native_tail_required'
    assert not list(run.rglob('CLAIM.json')) and not (flow.part(run,'S04')/'GUIDE_STATE_REQUEST.json').exists()
    assert [flow.read(run/'imported'/sid/'IMPORT.json')['prompt_id'] for sid in ('S01','S02')]==[
        '5fad6720-7090-4e09-9fb7-302342a951b3','ad632988-544f-4074-91c5-76ccfff0f88e']


def test_prepare_really_stages_six_independent_refs_and_positive_frame0_guide(run,monkeypatch):
    no_http(monkeypatch);initial(run);review(run,'S03');assert flow.prepare_video(run,'S03',code_files=[cli.__file__])['status']=='prepared'
    nr=flow.native_run(run,'S03');plan=flow.read(nr/'PLAN.json');row=plan['shots'][0];g=flow.read(nr/'shots/S03/workflow_api.json')
    flow.validate_graph(g,row['scope'],row['reference_map'])
    assert len(row['reference_map'])==6 and len([v for v in g.values() if v['class_type']=='LoadImage'])==6
    assert not any(v['class_type']=='ImageBatch' for v in g.values())
    for i,ref in enumerate(row['reference_map']):
        staged=Path(plan['config']['input_root'])/ref['input_name']
        assert flow.native.file_sha(staged)==ref['image']['sha256']
        assert g['condition']['inputs'][f'ref_images.ref_image_{i}']==[f'ref_{i}',0]
    assert row['reference_map'][5]['image']['sha256']=='9ead0f525a028ef2fb4e41536601984d6e3cb65617483e3567168389b75a64c2'
    assert g['guide_start']['inputs']['image']==['ref_5',0] and g['guide_start']['inputs']['frame_idx']==0
    assert g['126']['inputs']['conditioning']==['guide_start',0] and g['125']['inputs']['latent_image']==['condition',1]
    assert not list(run.rglob('CLAIM.json'))


def test_guide_can_show_only_father_while_independent_all_actor_assets_are_sent(run):
    initial(run);review(run,'S03',visible=('su_mo',));v=flow.input_value(run,'S03')
    assert v['guide_visible_actor_ids']==['su_mo'] and len(v['required_actor_assets'])==3
    assert [r['entity_id'] for r in v['references'][:3]]==['su_mo','ye_nan','ye_xijue']
    assert len(v['references'])==6 and len(v['world_actor_state'])==3
    assert flow.prepare_video(run,'S03')['status']=='prepared'


def test_source_quotes_actions_and_audio_wording_stay_and_detail_labels_are_truthful(run):
    initial(run);review(run,'S03');v=flow.input_value(run,'S03');e=flow.core._entries(v['source_case'])[0]
    text=v['compiled_prompt'];old=flow.core.compile_prompt(e)['compiled_prompt']
    assert flow.core.QUOTE.findall(text)==flow.core.QUOTE.findall(old) and len(flow.core.QUOTE.findall(text))==2
    assert '对白文字仅作为声音轨的发音内容，画面按摄影镜头呈现。' in text
    assert '0—0.5秒' in text and all(f'<Picture {i}>' in text for i in range(1,7))
    assert '<Picture 4>：同一房间的家具与墙面材料局部。' in text
    assert '<Picture 5>：同一房间的窗与墙面局部。' in text
    assert '始终三人同时' not in text and '固定机位' not in text
    req=flow.core.validate_entry(e)
    for beat in e['camera_beats']:
        for span in beat['source_span_ids']:assert req['spans'][span]['text'] in text


@pytest.mark.parametrize('change',['no_vae','guide_wrong_image','references_skip_positive'])
def test_graph_rejects_unused_refs_or_wrong_guide_positive(run,change):
    initial(run);review(run,'S03');flow.prepare_video(run,'S03');nr=flow.native_run(run,'S03')
    p=flow.read(nr/'PLAN.json');g=flow.read(nr/'shots/S03/workflow_api.json')
    if change=='no_vae':g['condition']['inputs'].pop('vae')
    elif change=='guide_wrong_image':g['guide_start']['inputs']['image']=['ref_0',0]
    else:g['126']['inputs']['conditioning']=['condition',0]
    with pytest.raises(ValueError):flow.validate_graph(g,p['shots'][0]['scope'],p['shots'][0]['reference_map'])


def test_every_staged_asset_hash_is_checked_before_post(run,monkeypatch):
    initial(run);review(run,'S03');flow.prepare_video(run,'S03');approve(run,'S03')
    nr=flow.native_run(run,'S03');p=flow.read(nr/'PLAN.json');r=p['shots'][0]['reference_map'][0]
    (Path(p['config']['input_root'])/r['input_name']).write_bytes(b'controlled staged mutation')
    monkeypatch.setattr(flow.native,'_service_paths',lambda *a:None)
    monkeypatch.setattr(flow.native,'_queue',lambda *a:dict(queue_running=[],queue_pending=[]));no_http(monkeypatch)
    with pytest.raises(ValueError,match='actual_staged_reference_pixels_changed'):flow.submit(run,'S03')
    assert not list(run.rglob('CLAIM.json'))


@pytest.fixture
def service(run):
    generator=diagnostic_http_service.__wrapped__(run);state=next(generator)
    tail=flow.verify_native(cli.specification()['prefix_results']['S02'])['last_image']['path']
    for role in ('first','last'):shutil.copyfile(tail,run/'cpu_fixtures'/(role+'_00001_.png'))
    try:yield state
    finally:
        try:next(generator)
        except StopIteration:pass


def approve(run,sid):
    flow.freeze(flow.part(run,sid)/'ROOT_LAUNCH_VIDEO.json',dict(request=flow.launch_request(run,sid),
        approved_by='Controlled local HTTP fixture, not real H3',evidence=['Technical transport test only.']))


def test_local_http_new_Ref_collects_four_originals_and_only_new_tail_for_S04(run,service):
    initial(run);review(run,'S03');flow.prepare_video(run,'S03',code_files=[cli.__file__]);approve(run,'S03')
    assert flow.submit(run,'S03')['status']=='submitted'
    assert flow.collect_known(run,'S03')['status']=='media_review_required'
    assert flow.execute(run,'S03',poll_seconds=1,max_seconds=1)['status']=='media_review_required' and service['posts']==1
    nr=flow.native_run(run,'S03');result=flow.read(nr/'shots/S03/RESULT.json');assert len(result['files'])==4
    assert flow.prepare_video(run,'S04')['status']=='actual_guide_state_review_required'
    review(run,'S04',visible=('su_mo',));v=flow.input_value(run,'S04')
    assert v['predecessor_result']==flow.bind(nr/'shots/S03/RESULT.json') and len(flow.core.QUOTE.findall(v['compiled_prompt']))==3
    old=flow.input_value(run,'S03');assert v['references'][:5]==old['references'][:5]
    assert v['references'][5]['image']=={k:result['files']['last'][k] for k in ('path','sha256')}


def test_local_http_unknown_claim_never_reposts(run,service):
    initial(run);review(run,'S03');flow.prepare_video(run,'S03');approve(run,'S03');service['mode']='unknown'
    assert flow.submit(run,'S03')['status']=='outcome_unknown'
    assert flow.execute(run,'S03',poll_seconds=1,max_seconds=1)['status']=='outcome_unknown' and service['posts']==1
