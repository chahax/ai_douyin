"""Probe contracts and transient UI checks; DOM execution is verified separately."""
from types import SimpleNamespace
import pytest
from src.platform_adapter.douyin_challenge import (
    DouyinChallengeProbeError,probe_douyin_challenge,confirmed_douyin_challenge,
)


def value(blocking=False,**extra):
    return dict(blocking=blocking,frame_count=1,actionable_frames=int(blocking),visible_dialogs=0,surface_states=["challenge_ready"] if blocking else [],**extra)


def page_for(values):
    queue=iter(values)
    return SimpleNamespace(locator=lambda _:SimpleNamespace(evaluate=lambda _:next(queue)),wait_for_timeout=lambda _:None)


def test_transient_frame_disappearing_on_second_observation_is_not_confirmed():
    evidence=confirmed_douyin_challenge(page_for([value(True),value(False)]))
    assert not evidence['blocking'] and evidence['confirmations']==0 and evidence['observations']==2


def test_persistent_exposed_frame_is_confirmed_with_safe_geometry_only():
    unsafe=value(True,excluded={'ancestor_hidden':2,'secret':'private'},frames=[dict(kind='ignored',
        reason='actionable',x=10,y=20,width=300,height=200,hit_points=5,url='https://private/?token=secret')])
    evidence=confirmed_douyin_challenge(page_for([unsafe,unsafe]))
    assert evidence['blocking'] and evidence['confirmations']==2
    assert evidence['frames'][0]['hit_points']==5 and 'private' not in repr(evidence)
    assert evidence['excluded']=={'ancestor_hidden':2}


@pytest.mark.parametrize('raw',[None,False,{},dict(blocking=True,frame_count=1,actionable_frames=0,visible_dialogs=0)])
def test_unreadable_or_inconsistent_evidence_never_becomes_a_clear_page(raw):
    with pytest.raises(DouyinChallengeProbeError):probe_douyin_challenge(page_for([raw]))


def test_probe_transport_failure_has_safe_non_login_failure():
    def fail(_):raise RuntimeError('https://private/?token=secret')
    page=SimpleNamespace(locator=lambda _:SimpleNamespace(evaluate=fail))
    with pytest.raises(DouyinChallengeProbeError) as failure:probe_douyin_challenge(page)
    assert failure.value.code=='page_probe_failed' and 'secret' not in str(failure.value)


@pytest.mark.parametrize('state',['blank','loading','load_failed','unavailable','unconfirmed'])
def test_unready_surface_never_becomes_ready_or_clear(state):
    raw=value(True);raw['surface_states']=[state]
    waits=[]
    page=SimpleNamespace(locator=lambda _:SimpleNamespace(evaluate=lambda _:raw),wait_for_timeout=waits.append)
    evidence=confirmed_douyin_challenge(page)
    assert evidence['blocking'] and evidence['surface_state']==state
    assert evidence['confirmations']==0 and evidence['observations']==5
    assert sum(waits)==6000
    from src.platform_adapter.douyin_identity import has_visible_douyin_challenge
    from src.platform_adapter.douyin_challenge import DouyinVerificationSurfaceError
    with pytest.raises(DouyinVerificationSurfaceError) as exc:has_visible_douyin_challenge(page)
    assert exc.value.code=='verification_ui_unconfirmed'


def test_legacy_geometry_without_content_is_never_ready_captcha():
    raw=value(True);raw.pop('surface_states')
    page=SimpleNamespace(locator=lambda _:SimpleNamespace(evaluate=lambda _:raw),wait_for_timeout=lambda _:None)
    evidence=confirmed_douyin_challenge(page)
    assert evidence['blocking'] and evidence['surface_state']=='unconfirmed' and evidence['confirmations']==0


def test_loading_then_ready_requires_two_ready_observations():
    first=value(True);first['surface_states']=['loading']
    evidence=confirmed_douyin_challenge(page_for([first,value(True),value(True)]))
    assert evidence['surface_state']=='challenge_ready' and evidence['observations']==3 and evidence['confirmations']==2


def test_content_read_failure_stays_unknown_without_leaking_frame_error():
    from src.platform_adapter.douyin_challenge import probe_challenge_page
    raw=value(True,frames=[dict(index=0,reason='actionable')]);raw.pop('surface_states')
    def fail(**kwargs):raise RuntimeError('private frame token=secret')
    page=SimpleNamespace(evaluate=lambda _:raw,locator=lambda _:SimpleNamespace(nth=lambda _:SimpleNamespace(element_handle=fail)))
    evidence=probe_challenge_page(page)
    assert evidence['surface_states']==['unavailable']
    assert 'secret' not in repr(evidence)
