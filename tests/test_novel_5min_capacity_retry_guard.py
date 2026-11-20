"""CPU executor wiring: no extra inference for a known unchanged output capacity."""
from copy import deepcopy

import pytest

from test_novel_5min_production_runner import frame_review_fixture,run


@pytest.mark.parametrize('nested_layout',[False,True])
def test_exact_known_capacity_failure_stops_at_one_tick(nested_layout,tmp_path,monkeypatch):
    row,state,image,exits=frame_review_fixture(tmp_path,monkeypatch)
    snapshot=deepcopy(run.assets.status(row['asset_run']))
    snapshot['plan']['config']['visual_review']['max_tokens']=4096
    monkeypatch.setattr(run.assets,'status',lambda _:snapshot)
    failure=dict(decision='unavailable',retryable=True,completion_known=True,outcome_unknown=False,
        error='local visual output exhausted limit without completion marker')
    subreview=dict(layout_review=failure) if nested_layout else failure
    state['first_frames'][row['id']]['review']['subreviews']=[subreview]
    calls=[];before=image.read_bytes()
    def tick(*args,**kwargs):calls.append(True);assert len(calls)==1;return deepcopy(state)
    monkeypatch.setattr(run.assets,'tick',tick)
    with pytest.raises(run.Blocked,match='first_frame_halted:blocked_first_frame_review'):run.frame(row)
    assert len(calls)==1 and exits==['failed'] and image.read_bytes()==before
    assert state['first_frames'][row['id']]['review_attempts']==1  # No second attempt spent.
