"""Real prior receipts plus controlled local HTTP; no model execution."""
from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

from src.content_factory import visual_h3_identity_continuation_v1 as flow
from scripts import run_h3_identity_continuation as cli
from test_h3_story_opening_diagnostic import service as diagnostic_http_service


@pytest.fixture
def run(tmp_path):
    root=tmp_path/'identity_continuation';root.mkdir();cfg=cli.specification()['config']
    for key in ('input_root','output_root','gpu_lock_root'):
        p=root/key;p.mkdir();cfg[key]=str(p)
    pause=root/'original_pause.json';flow.freeze(pause,dict(controlled_fixture=True,paused=True))
    cfg.update(protected_pause_path=str(pause),runs_root=str(root/'visual_h3_v3'))
    flow.freeze(root/'H3_CONFIG.json',cfg)
    return root


def initial(run):
    spec=cli.specification();spec['config']=flow.read(run/'H3_CONFIG.json')
    return flow.prepare(run,spec)


def review(run,sid):
    request=flow.review_request(run,sid)
    assert request['status']=='actual_tail_coverage_review_required'
    data=flow.read(flow.core.check(request['request']));data.update(schema=flow.REVIEW,
        actual_anchor_actor_ids=list(data['clip_identity_actor_ids']),completion_known=True,outcome_unknown=False,
        reviewed_by='Controlled CPU contract fixture, not production acceptance',
        evidence=['Protocol fixture using the actual saved prior PNG; no semantic quality approval.'])
    data['identity_by_actor']={cid:dict(present=True,identity_matches=True,
        screen_description='已保存尾图中的'+cid,appearance={'su_mo':'灰纽扣衬衫与深夹克','ye_nan':'灰色纽扣短袖衬衫','ye_xijue':'米色纽扣领衫'}[cid]) for cid in data['clip_identity_actor_ids']}
    path=flow.part(run,sid)/'TAIL_ANCHOR_COVERAGE_REVIEW.json';flow.freeze(path,data)
    return path


def forbid(monkeypatch):monkeypatch.setattr(flow.native,'_http',lambda *a,**k:pytest.fail('unexpected HTTP/model call'))


def test_real_prefix_imports_and_future_S04_are_file_only(run,monkeypatch):
    forbid(monkeypatch);before={s:cli.specification()['prefix_results'][s] for s in ('S01','S02')}
    v=initial(run)
    assert v['model_posts']==0 and v['S04']['status']=='upstream_native_tail_required'
    assert initial(run)==v
    ids=[]
    for sid in ('S01','S02'):
        i=flow.read(run/'imported'/sid/'IMPORT.json');assert i['native_result']==before[sid]
        proof=flow.verify_native(i['native_result']);assert i['native_files']==proof['result']['files'];ids.append(i['prompt_id'])
    assert ids==['5fad6720-7090-4e09-9fb7-302342a951b3','ad632988-544f-4074-91c5-76ccfff0f88e']
    assert not (flow.part(run,'S04')/'TAIL_ANCHOR_COVERAGE_REQUEST.json').exists()
    assert not list(run.rglob('CLAIM.json')) and not list(run.rglob('workflow_api.json'))


def test_actual_tail_full_clip_coverage_is_independent_of_opening(run,monkeypatch):
    forbid(monkeypatch);initial(run);review(run,'S03');v=flow.input_value(run,'S03')
    assert set(v['clip_identity_actor_ids'])=={'su_mo','ye_nan','ye_xijue'}
    assert v['opening_actor_ids']==['ye_xijue'] and set(v['anchor_actor_ids'])==set(v['clip_identity_actor_ids'])
    assert v['first_image']['sha256']=='9ead0f525a028ef2fb4e41536601984d6e3cb65617483e3567168389b75a64c2'
    assert v['conditioning_mode']=='FL2VA_first_frame_only' and v['full_video_quality_passed'] is False
    p=flow.prepare_video(run,'S03',code_files=[cli.__file__]);assert p['status']=='prepared'
    native=flow.read(flow.native_run(run,'S03')/'PLAN.json');graph=flow.read(flow.native_run(run,'S03')/'shots/S03/workflow_api.json')
    assert native['shots'][0]['identity_continuation']['clip_identity_actor_ids']==v['clip_identity_actor_ids']
    assert graph['condition']['inputs']['prompt']==v['compiled_prompt'] and 'last_frame' not in graph['condition']['inputs']
    staged=Path(native['config']['input_root'])/native['shots'][0]['input_name']
    assert flow.native.file_sha(staged)==v['first_image']['sha256']
    assert not list(run.rglob('CLAIM.json'))


def test_missing_identity_stops_instead_of_sending_single_person(run,monkeypatch):
    forbid(monkeypatch);initial(run);path=review(run,'S03');v=flow.read(path)
    v['identity_by_actor']['su_mo']['present']=False;path.write_text(json.dumps(v),encoding='utf-8')
    r=flow.prepare_video(run,'S03')
    assert r['status']=='identity_materialization_or_shot_split_required' and r['missing_actor_ids']==['su_mo']
    assert not (flow.native_run(run,'S03')/'PLAN.json').exists()


def test_renderer_keeps_quotes_actions_and_original_audio_only_wording(run):
    initial(run);review(run,'S03');v=flow.input_value(run,'S03');e=flow.core._entries(v['source_case'])[0]
    text=v['compiled_prompt'];original=flow.core.compile_prompt(e)['compiled_prompt']
    assert flow.core.QUOTE.findall(text)==flow.core.QUOTE.findall(original) and len(flow.core.QUOTE.findall(text))==2
    assert '对白文字仅作为声音轨的发音内容，画面按摄影镜头呈现。' in text
    assert '0—0.5秒' in text and '0.5—2秒，明确切到头肩近景' in text
    assert '首图就是下列0秒开始的第一个剧情镜头' not in text
    assert '米色圆领短袖上衣' not in text and '米色纽扣领衫' in text
    req=flow.core.validate_entry(e)
    for beat in e['camera_beats']:
        for sid in beat['source_span_ids']:assert req['spans'][sid]['text'] in text


def test_nested_authority_mutation_is_detected_before_dispatch(run,monkeypatch):
    initial(run);review(run,'S03');flow.prepare_video(run,'S03',code_files=[cli.__file__]);forbid(monkeypatch)
    (run/'USER_AUTHORIZATION.json').write_text('{"changed":true}',encoding='utf-8')
    with pytest.raises(ValueError):flow.submit(run,'S03')


def test_no_launch_approval_cannot_post(run,monkeypatch):
    initial(run);review(run,'S03');flow.prepare_video(run,'S03');forbid(monkeypatch)
    with pytest.raises(FileNotFoundError):flow.submit(run,'S03')


def test_S04_cannot_use_an_old_completed_S03(run,monkeypatch):
    forbid(monkeypatch);initial(run)
    old=cli.PREVIOUS/'visual_h3_v3'/(cli.PREVIOUS.name+'_S03')
    new=flow.native_run(run,'S03');(new/'shots/S03').mkdir(parents=True)
    shutil.copyfile(old/'PLAN.json',new/'PLAN.json')
    shutil.copyfile(old/'shots/S03/RESULT.json',new/'shots/S03/RESULT.json')
    with pytest.raises(ValueError,match='current_run_S03_tail_required'):flow.review_request(run,'S04')


@pytest.fixture
def service(run):
    generator=diagnostic_http_service.__wrapped__(run);state=next(generator)
    # The HTTP emulator's native tail contains the actual three-person PNG.
    # This is a controlled transport fixture, never a real generated movie.
    tail=flow.verify_native(cli.specification()['prefix_results']['S02'])['last_image']['path']
    for role in ('first','last'):shutil.copyfile(tail,run/'cpu_fixtures'/(role+'_00001_.png'))
    try:yield state
    finally:
        try:next(generator)
        except StopIteration:pass


def approve(run,sid):
    flow.freeze(flow.part(run,sid)/'ROOT_LAUNCH_VIDEO.json',dict(request=flow.launch_request(run,sid),
        approved_by='Controlled local HTTP fixture, not real H3',evidence=['Technical transport test.']))


def test_local_http_collects_four_originals_then_S04_uses_only_this_new_tail(run,service):
    initial(run);review(run,'S03');flow.prepare_video(run,'S03',code_files=[cli.__file__]);approve(run,'S03')
    assert flow.submit(run,'S03')['status']=='submitted'
    assert flow.collect_known(run,'S03')['status']=='media_review_required'
    assert flow.execute(run,'S03',poll_seconds=1,max_seconds=1)['status']=='media_review_required' and service['posts']==1
    new=flow.bind(flow.native_run(run,'S03')/'shots/S03/RESULT.json')
    request=flow.review_request(run,'S04');data=flow.read(flow.core.check(request['request']))
    assert data['anchor_result']==new
    assert data['anchor_image']==flow.verify_native(new)['last_image']
    assert flow.prepare_video(run,'S04')['status']=='actual_tail_coverage_review_required'
    review(run,'S04');v=flow.input_value(run,'S04')
    assert v['predecessor_result']==new and len(flow.core.QUOTE.findall(v['compiled_prompt']))==3
    result=flow.read(flow.core.check(new));assert set(result['files'])=={'video','audio','first','last'}
    assert (run/'job_ids.txt').read_text('utf-8').count('S03 controlled-http-001\n')==1


def test_local_http_unknown_response_never_reposts(run,service):
    initial(run);review(run,'S03');flow.prepare_video(run,'S03');approve(run,'S03');service['mode']='unknown'
    assert flow.submit(run,'S03')['status']=='outcome_unknown'
    assert flow.execute(run,'S03',poll_seconds=1,max_seconds=1)['status']=='outcome_unknown'
    assert service['posts']==1
