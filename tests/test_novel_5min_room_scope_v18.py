"""CPU runtime-mode wiring; original request/unknown ledgers remain authoritative."""
from copy import deepcopy
from pathlib import Path

import pytest

from test_novel_5min_production_runner import frame_review_fixture,run


def scoped_case(tmp_path,monkeypatch,sid='F0014'):
    row,state,image,exits=frame_review_fixture(tmp_path,monkeypatch)
    old_id=row['id'];row['id']=sid
    target=run.ROOT/'data/visual_asset_pipeline/runs'/run.ROOM_SCOPE_RUNS[sid]
    target.mkdir(parents=True);run.assets.write(target/'PLAN.json',dict(frozen='unchanged QA only'))
    row['asset_run']=str(target)
    frame=state['first_frames'].pop(old_id);frame.update(binding_sha256='a'*64,review_attempts=0)
    frame.pop('review',None);state['first_frames'][sid]=frame;state['jobs']['original_image_job']['shot_id']=sid
    state['status']='shot_bindings_ready'
    snapshot=deepcopy(run.assets.status(target));snapshot['state']=deepcopy(state)
    snapshot['plan']['config']['visual_review']=dict(max_tokens=4096)
    monkeypatch.setattr(run.assets,'status',lambda _:snapshot)
    return row,state,image,exits,snapshot


def request_at(row,state,attempt=0,*,mode=None,known=False):
    frame=state['first_frames'][row['id']]
    folder=Path(row['asset_run'])/'first_frame_reviews'/frame['binding_sha256']/frame['sha256']/str(attempt)
    expectation=dict(kind='place');version='target-only-people-furniture-split-v14'
    if mode:expectation['room_comparison_scope']=mode;version='room_compare/v18'
    prepared=[dict(target=dict(sha256=frame['sha256']),expectation=expectation,prompt_version=version)]
    binding=run.assets.fingerprint(dict(config={},requests=prepared))
    request=dict(config={},prepared=prepared,request_binding_sha256=binding)
    run.assets.write(folder/'REQUEST.json',request)
    if known:complete_request(folder)
    return folder


def complete_request(folder):
    request=run.assets.read(folder/'REQUEST.json')
    results=[dict(target_sha256=p['target']['sha256'],binding_sha256=run.assets.fingerprint(p),
                  completion_known=True,outcome_unknown=False) for p in request['prepared']]
    run.assets.write(folder/'RESULTS.json',dict(request_binding_sha256=request['request_binding_sha256'],
        results=results,results_sha256=run.assets.fingerprint(results)))


@pytest.mark.parametrize('sid',['F0014','F0015','F0016','F0018','F0019','F0021'])
def test_only_exact_authorized_namespace_can_opt_in_without_a_request(sid,tmp_path,monkeypatch):
    row,state,_,_,snapshot=scoped_case(tmp_path,monkeypatch,sid)
    assert run._frame_room_scope(row,state,snapshot['plan']['config'])=='compact_room/v18'
    changed=deepcopy(row);changed['asset_run']=str(Path(row['asset_run']).with_name('other_namespace'))
    assert run._frame_room_scope(changed,state,snapshot['plan']['config']) is None
    changed['id']='F0012'  # This source case belongs to its independent sidecar.
    assert run._frame_room_scope(changed,state,snapshot['plan']['config']) is None


@pytest.mark.parametrize('mode',[None,'compact_room/v18'])
def test_current_request_keeps_its_original_mode_even_without_a_result(mode,tmp_path,monkeypatch):
    row,state,_,_,snapshot=scoped_case(tmp_path,monkeypatch)
    folder=request_at(row,state,mode=mode);before=(folder/'REQUEST.json').read_bytes()
    assert run._frame_room_scope(row,state,snapshot['plan']['config'])==mode
    assert (folder/'REQUEST.json').read_bytes()==before and not (folder.parent/'1').exists()


def test_unknown_prior_attempt_cannot_be_bypassed_by_a_new_mode_or_directory(tmp_path,monkeypatch):
    row,state,_,_,snapshot=scoped_case(tmp_path,monkeypatch)
    folder=request_at(row,state);state['first_frames'][row['id']]['review_attempts']=1
    with pytest.raises(run.Blocked,match='prior_outcome_unknown'):
        run._frame_room_scope(row,state,snapshot['plan']['config'])
    assert not (folder.parent/'1').exists()


def test_orphan_claim_and_inconsistent_contract_are_not_treated_as_fresh(tmp_path,monkeypatch):
    row,state,_,_,snapshot=scoped_case(tmp_path,monkeypatch)
    folder=request_at(row,state,mode='compact_room/v18')
    request=run.assets.read(folder/'REQUEST.json');request['prepared'][0]['prompt_version']='legacy'
    run.assets.write(folder/'REQUEST.json',request)
    with pytest.raises(run.Blocked,match='scope_invalid'):run._frame_room_scope(row,state,snapshot['plan']['config'])
    (folder/'REQUEST.json').unlink();run.assets.write(folder/'CLAIM.json',dict(unknown=True))
    with pytest.raises(run.Blocked,match='evidence_blocked'):run._frame_room_scope(row,state,snapshot['plan']['config'])


def test_known_prior_round_allows_fresh_remaining_attempt_without_changing_budget(tmp_path,monkeypatch):
    row,state,_,_,snapshot=scoped_case(tmp_path,monkeypatch);folder=request_at(row,state,known=True)
    frame=state['first_frames'][row['id']];frame.update(review_attempts=1,review=dict(decision='unavailable',retryable=True,
        completion_known=True,outcome_unknown=False))
    assert run._frame_room_scope(row,state,snapshot['plan']['config'])=='compact_room/v18'
    assert frame['review_attempts']==1 and snapshot['plan']['config']['max_review_attempts']==2
    assert not (folder.parent/'1').exists()


def test_accepted_or_unknown_state_without_new_request_keeps_legacy_mode(tmp_path,monkeypatch):
    row,state,_,_,snapshot=scoped_case(tmp_path,monkeypatch)
    for review in [dict(decision='accepted',completion_known=True,outcome_unknown=False),
                   dict(decision='unavailable',completion_known=False,outcome_unknown=True)]:
        state['first_frames'][row['id']]['review']=review
        assert run._frame_room_scope(row,state,snapshot['plan']['config']) is None


def test_constructor_opt_in_is_runtime_only_and_does_not_edit_frozen_plan(tmp_path,monkeypatch):
    row,state,image,exits,snapshot=scoped_case(tmp_path,monkeypatch,'F0015')
    path=Path(row['asset_run'])/'PLAN.json';before=path.read_bytes();config=deepcopy(snapshot['plan']['config']);calls=[]
    def client(value,**kwargs):calls.append((deepcopy(value),kwargs));return object()
    monkeypatch.setattr(run.vision,'VisualReviewClient',client)
    monkeypatch.setattr(run.assets,'tick',lambda *a,**k:dict(status='h3_inputs_ready'))
    run.frame(row)
    assert calls==[(config['visual_review'],dict(room_comparison_scope='compact_room/v18'))]
    assert snapshot['plan']['config']==config and path.read_bytes()==before and exits==['h3_inputs_ready']


def test_existing_legacy_request_is_settled_before_remaining_round_changes_scope(tmp_path,monkeypatch):
    row,state,image,exits,snapshot=scoped_case(tmp_path,monkeypatch)
    folder=request_at(row,state);calls=[];ticks=[]
    monkeypatch.setattr(run.vision,'VisualReviewClient',lambda config,**kw:(calls.append(kw) or object()))
    def tick(*args,**kwargs):
        ticks.append(True)
        if len(ticks)==1:
            complete_request(folder)
            result=deepcopy(state);frame=result['first_frames'][row['id']]
            frame.update(review_attempts=1,review=dict(decision='unavailable',retryable=True,completion_known=True,outcome_unknown=False,
                         error='known room format key missing'))
            result['status']='blocked_first_frame_review';return result
        return dict(status='h3_inputs_ready')
    monkeypatch.setattr(run.assets,'tick',tick)
    run.frame(row)
    assert calls==[{},dict(room_comparison_scope='compact_room/v18')] and len(ticks)==2 and exits==['h3_inputs_ready']
    assert not (folder.parent/'1').exists()  # Fake reviewer never performs an inference/request.
