"""Navigation-context churn retries reads, never a destructive interaction."""
from types import SimpleNamespace as NS

import pytest

from src.platform_adapter import douyin_work_cleanup_delete_v1 as adapter


def test_context_destroyed_then_two_stable_profiles_only_retries_guarded_reads():
    protected=['7709219071845256488','7700201288079920427']
    targets=['7709043480894524722','7708948487446056192']
    good=dict(surface='original_self_profile',public_uids=['75891235130'],truncated=False,visible_card_count=2,
        cards=[dict(native_post_id=p,native_id_bound=True) for p in protected])
    state=NS(reads=0,waits=0,guards=0)
    def evaluate(script):
        assert script=='fixed_native_inventory';state.reads+=1
        if state.reads<=2:raise RuntimeError('Page.evaluate: Execution context was destroyed, most likely because of a navigation')
        return good
    def wait(ms):assert ms==300;state.waits+=1
    page=NS(evaluate=evaluate,wait_for_timeout=wait)
    def rpc(method,*args):
        state.guards+=1
        assert method in (page.evaluate,page.wait_for_timeout)
        return method(*args)
    samples,errors,verified=adapter._read_reloaded_profile(rpc,page,'fixed_native_inventory','75891235130',targets,protected)
    assert verified and samples==[good,good] and len(errors)==2
    assert (state.reads,state.waits,state.guards)==(4,3,7)
    def fatal(script):raise RuntimeError('Page.evaluate: browser closed')
    page.evaluate=fatal
    with pytest.raises(RuntimeError,match='browser closed'):
        adapter._read_reloaded_profile(rpc,page,'fixed_native_inventory','75891235130',targets,protected)
