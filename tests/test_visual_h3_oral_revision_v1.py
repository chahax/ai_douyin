"""Real saved prefix evidence and bounded local HTTP, with no model request."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from test_visual_h3_library_minute_v2 import run, service
from src.content_factory import visual_h3_oral_revision_v1 as flow

PROJECT = Path(__file__).resolve().parents[1]
OLD = PROJECT/'data/video_generation/h3_library_bound_next_minute_20261113_v1'
SOURCE = PROJECT/'data/video_generation/h3_oral_revision_next_minute_20261113_v1'


def spec(run):
    old = flow.read(OLD/'PLAN.json')
    selections = deepcopy(flow.read(OLD/'LIBRARY_SELECTION.json')['segments'])
    for sid in flow.NEW:
        selections[sid]['actor_views'] = {c:['front','left_oblique'] if c in flow.ACTIVE[sid] else ['front'] for c in flow.CHILDREN}
        selections[sid]['capacity_decision']['front_only_actor_ids'] = [c for c in flow.CHILDREN if c not in flow.ACTIVE[sid]]
    return dict(sources={s:flow.bind(SOURCE/'segments'/s/'SOURCE_CASE.json') for s in flow.NEW},
        prefix_final_result=flow.bind(OLD/'FINAL_RESULT.json'),
        voice_profiles=flow.bind(SOURCE/'VOICE_PROFILES.json'), script_revision=flow.bind(SOURCE/'SCRIPT_REVISION.json'),
        library_binding=old['library_binding'], binding_approval=old['binding_approval'],
        segment_selections={s:selections[s] for s in flow.NEW}, config=flow.read(run/'H3_CONFIG.json'),
        authorization=dict(user_statement='Controlled CPU/local HTTP only.', publication=False))


def prepared(run):
    flow.prepare(run, spec(run)); f = flow.for_run(run); review(run, f, 'S03'); return f


def review(run, f, sid):
    request = f.review_request(run, sid)
    assert request['status'] == 'actual_guide_state_review_required'
    q = flow.read(request['request']['path'])
    flow.freeze(f.part(run, sid)/'GUIDE_STATE_REVIEW.json', dict(schema=f.REVIEW, shot_id=sid,
        predecessor_result=q['predecessor_result'], guide_image=q['guide_image'], guide_visible_actor_ids=['ye_xijue'],
        world_actor_state={c:'Controlled CPU state only.' for c in flow.CHILDREN},
        screen_identity_map={'ye_xijue':'Controlled middle child, not a visual acceptance.'},
        completion_known=True, outcome_unknown=False, reviewed_by='CPU fixture', evidence=['No model generation.']))


def approve(run, f, sid):
    flow.freeze(f.part(run,sid)/'ROOT_LAUNCH_VIDEO.json', dict(request=f.launch_request(run,sid),
        approved_by='Controlled local HTTP', evidence=['Never a real model request.']))


def test_prepare_authenticates_prefix_without_claiming_four_new_or_creating_jobs(run, monkeypatch):
    monkeypatch.setattr(flow.base.native, '_http', lambda *a, **k:pytest.fail('prepare must not HTTP'))
    result = flow.prepare(run, spec(run))
    assert result == flow.prepare(run, spec(run)) and result['model_posts'] == 0
    p = flow.read(run/'PLAN.json'); imported = flow.verify_imports(run)
    assert p['all_segments_new'] is False and p['new_video_submissions'] == 2 and p['preserved_prefix_frames'] == 724
    assert [r['shot_id'] for r in p['sources']] == ['S03','S04']
    assert [r['prompt_id'] for r in imported['segments']] == ['6464a38b-624f-410e-b581-193c8e00c88b','99759f6b-433d-4198-be09-a174f4024cbd']
    assert imported['identity_compatibility_gate'] is False
    assert not list(run.rglob('CLAIM.json')) and not (run/'visual_h3_v3').exists()


def test_s03_actual_old_s02_tail_and_all_nine_refs_voices_reach_graph(run):
    f = prepared(run); value = f.input_value(run,'S03')
    assert value['first_image']['sha256'] == '240b0bd600cf8cd0095b671831cb946e9d01925595b04ef39562fe81a4780076'
    assert value['predecessor_receipt']['result']['prompt_id'] == '99759f6b-433d-4198-be09-a174f4024cbd'
    assert len(value['references']) == 9 and set(value['required_actor_assets']) == set(flow.CHILDREN)
    assert value['guide_visible_actor_ids'] == ['ye_xijue']
    assert f.prepare_video(run,'S03')['status'] == 'prepared'
    nr, plan, row = f._load(run,'S03'); graph = flow.read(nr/'shots/S03/workflow_api.json')
    assert len([x for x in graph.values() if x['class_type'] == 'LoadImage']) == 9
    assert graph['guide_start']['inputs']['image'] == ['ref_8',0]
    assert graph['condition']['inputs']['prompt'] == value['compiled_prompt']
    for p in value['voice_profiles'].values(): assert p['description'] in graph['condition']['inputs']['prompt']
    assert '其余文字是画面与表演说明' in value['compiled_prompt']
    assert flow.base.core.QUOTE.findall(value['compiled_prompt']) == flow.base.core.QUOTE.findall(flow.base.core.compile_prompt(f.entry_value('S03'))['compiled_prompt'])
    assert all(k in row['library_input'] for k in ('voice_profiles','voice_profiles_binding','script_revision','oral_revision_contract'))
    for ref in row['reference_map']:
        assert flow.base.native.file_sha(Path(plan['config']['input_root'])/ref['input_name']) == ref['image']['sha256']


def test_imported_original_cannot_be_submitted_and_s04_cannot_take_old_s03(run, monkeypatch):
    f = prepared(run)
    monkeypatch.setattr(flow.base.native, '_http', lambda *a, **k:pytest.fail('no real HTTP'))
    with pytest.raises(ValueError): f.submit(run,'S01')
    assert f.review_request(run,'S04')['status'] == 'upstream_native_tail_required'
    assert not list(run.rglob('CLAIM.json'))


def test_voice_quote_injection_and_wrong_child_type_fail_before_plan(run):
    s = spec(run); profiles = flow.read(s['voice_profiles']['path'])
    profiles['profiles']['ye_yaner']['description'] += '“示例台词”'
    p = run/'bad_voice.json'; flow.freeze(p,profiles); s['voice_profiles'] = flow.bind(p)
    with pytest.raises(ValueError,match='child_voice'): flow.prepare(run,s)
    assert not (run/'PLAN.json').exists()
    profiles['profiles']['ye_yaner']['description'] = '女孩轻亮童声'
    profiles['profiles']['ye_yaner']['type'] = 'male_child'
    p = run/'wrong_voice.json'; flow.freeze(p,profiles); s['voice_profiles'] = flow.bind(p)
    with pytest.raises(ValueError,match='child_voice'): flow.prepare(run,s)


def test_face_window_gap_is_rejected_even_when_a_later_beat_has_face(run):
    s = spec(run); entry = flow.read(s['sources']['S03']['path'])['shots'][0]
    entry = deepcopy(entry); speaker = entry['audio'][0]['speaker']
    first = entry['camera_beats'][1]; second = deepcopy(first)
    first['end'] = 2; second['start'] = 2; second['source_span_ids'] = []
    second['actors'][speaker]['visible_parts'] = ['torso','hands']
    entry['camera_beats'].insert(2,second)
    # The old coverage checker accepts the small initial face overlap; the new
    # policy must reject the uncovered remainder of the actual speaking window.
    flow.continuation.source_shot(entry)
    with pytest.raises(ValueError,match='entire_onscreen'): flow.validate_entry(entry,s['script_revision'])


def test_changed_import_manifest_is_rejected_without_touching_originals(run):
    f = prepared(run); p = flow.read(run/'PREFIX_IMPORTS.json')
    p['segments'][1]['prompt_id'] = 'not-original'
    (run/'PREFIX_IMPORTS.json').write_text(json.dumps(p),encoding='utf-8')
    with pytest.raises(ValueError): f.review_request(run,'S03')
    assert not list(run.rglob('CLAIM.json'))


def test_local_http_unknown_is_preserved_and_never_reposted(run,service):
    f = prepared(run); f.prepare_video(run,'S03'); approve(run,f,'S03'); service['mode'] = 'unknown'
    assert f.submit(run,'S03')['status'] == 'outcome_unknown'
    assert f.execute(run,'S03',poll_seconds=1,max_seconds=1)['status'] == 'outcome_unknown'
    assert service['posts'] == 1


def test_local_http_saved_s03_tail_is_only_s04_predecessor(run,service):
    f = prepared(run); f.prepare_video(run,'S03'); approve(run,f,'S03')
    assert f.submit(run,'S03')['status'] == 'submitted'
    assert f.collect_known(run,'S03')['status'] == 'media_review_required'
    assert service['posts'] == 1
    review(run,f,'S04'); value = f.input_value(run,'S04')
    prev = flow.bind(f.native_run(run,'S03')/'shots/S03/RESULT.json')
    assert value['predecessor_result'] == prev and value['predecessor_receipt']['result']['prompt_id'] == 'controlled-http-001'
    assert value['first_image'] == f.verify_native(prev)['last_image']
    assert f.prepare_video(run,'S04')['status'] == 'prepared'
    assert '轻亮、稚嫩、自然的女孩童声' in value['compiled_prompt']


def test_changed_staged_identity_is_blocked_before_claim_or_http(run,service):
    f = prepared(run); f.prepare_video(run,'S03'); approve(run,f,'S03'); nr,p,row = f._load(run,'S03')
    (Path(p['config']['input_root'])/row['reference_map'][0]['input_name']).write_bytes(b'controlled mutation')
    with pytest.raises(ValueError,match='staged_reference'): f.submit(run,'S03')
    assert service['posts'] == 0 and not (nr/'shots/S03/CLAIM.json').exists()


def test_actual_clock_assembly_keeps_two_original_imports_and_two_new_ids(run,service):
    f = prepared(run)
    for sid in flow.NEW:
        if sid == 'S04':
            review(run,f,sid)
            # Distinct controlled original bytes, with the same valid frame/audio
            # clock, so duplicate-output protection is exercised rather than bypassed.
            with (run/'cpu_fixtures/video_00001_.mp4').open('ab') as stream:
                stream.write(b'controlled_second_original')
        f.prepare_video(run,sid); approve(run,f,sid)
        assert f.submit(run,sid)['status'] == 'submitted'
        assert f.collect_known(run,sid)['status'] == 'media_review_required'
    result = f.assemble(run)
    assert [r['kind'] for r in result['segments']] == ['import','import','new','new']
    assert result['native_ids'][2:] == ['controlled-http-001','controlled-http-002']
    assert result['preserved_prefix_frames'] == 724 and result['all_segments_new'] is False
    assert Path(result['file']['path']).name == 'H3_ORAL_REVISION_MINUTE_736x1312.mp4'
    assert result == f.assemble(run) and service['posts'] == 2


def test_assembly_rejects_a_saved_old_native_disguised_as_new(run,service):
    f = prepared(run); f.prepare_video(run,'S03'); approve(run,f,'S03')
    assert f.submit(run,'S03')['status'] == 'submitted'
    assert f.collect_known(run,'S03')['status'] == 'media_review_required'
    path = f.part(run,'S03')/'FINAL_RESULT.json'
    path.write_bytes((OLD/'segments/S03/FINAL_RESULT.json').read_bytes())
    with pytest.raises(ValueError,match='this_run_exact_native'): f.assemble(run)
    assert not (run/'ASSEMBLY_REQUEST.json').exists() and service['posts'] == 1
