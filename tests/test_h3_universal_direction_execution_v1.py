"""Actual source/asset staging through private adapters; all HTTP is mocked."""
from copy import deepcopy
from pathlib import Path

import pytest

from test_visual_h3_library_minute_v2 import run
from test_visual_h3_library_continuation_v1 import spec, review, scene_guide
from test_h3_contact_execution_v1 import env as contact_env, PROFILE
from src.content_factory import h3_asset_flow_v2 as flow
from src.content_factory import h3_universal_direction_execution_v1 as execution
from src.content_factory import video_directing_policy_v1 as policy
from src.content_factory import visual_h3_library_continuation_v1 as library


def binding(tmp_path):
    return flow.freeze(tmp_path/'DIRECTION.json', deepcopy(policy.DEFAULT_POLICY))


def approve(run,api,sid='S01',approved_by='root'):
    flow.freeze(api.part(run,sid)/'ROOT_LAUNCH_VIDEO.json',dict(request=api.launch_request(run,sid),
        approved_by=approved_by,evidence=['Mock transport, zero real generation.']))


@pytest.fixture
def library_env(run, monkeypatch):
    cfg=flow.read(run/'H3_CONFIG.json'); state={'posts':0,'response':{'prompt_id':'universal_mock_uuid'}}
    def http(config, route, value=None):
        if value is not None:
            assert route=='/prompt'; state['posts']+=1
            if isinstance(state['response'], Exception):raise state['response']
            return deepcopy(state['response'])
        if route=='/system_stats':
            return {'system':{'argv':['main.py','--input-directory',cfg['input_root'],'--output-directory',cfg['output_root']]}}
        if route=='/queue':return {'queue_running':[],'queue_pending':[]}
        if route.startswith('/history/'):return {}
        raise AssertionError('Unexpected mocked route '+route)
    monkeypatch.setattr(library.base.native,'_http',http)
    return run,state


@pytest.mark.parametrize('cut',[False,True])
def test_actual_library_prompt_receipt_and_scene_guide_reach_compiled_graph(library_env, cut):
    run,state=library_env; library.prepare(run,spec(run,cut=cut))
    if cut:scene_guide(run)
    review(run)
    pb=binding(run); old=library.base.input_value
    api=execution.library_for_run(run,pb)
    value=api.input_value(run,'S01')
    assert value['directing_policy']['policy_binding']==pb
    assert api.prepare_video(run,'S01')['status']=='prepared'
    nr,p,row=api._load(run,'S01');g=flow.read(nr/'shots/S01/workflow_api.json')
    assert g['condition']['inputs']['prompt']==value['compiled_prompt']
    assert row['library_input']['directing_policy']==value['directing_policy']
    assert library.base.input_value is old and state['posts']==0
    if cut:
        assert g['guide_start']['inputs']['image']==['scene_start',0]
        assert row['reference_map'][-1]['kind']=='previous_scene_context'
        assert row['first_frame']!=row['reference_map'][-1]['image']
    else:assert g['guide_start']['inputs']['image']==['ref_8',0]


def test_library_policy_tamper_blocks_before_native_claim(library_env):
    run,state=library_env;library.prepare(run,spec(run));review(run)
    pb=binding(run);api=execution.library_for_run(run,pb);api.prepare_video(run,'S01');approve(run,api)
    Path(pb['path']).write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError):api.submit(run,'S01')
    assert state['posts']==0 and not (api.native_run(run,'S01')/'shots/S01/CLAIM.json').exists()


def test_library_unknown_never_rePOSTs_or_rewrites_claim(library_env):
    run,state=library_env;library.prepare(run,spec(run));review(run)
    api=execution.library_for_run(run,binding(run));api.prepare_video(run,'S01');approve(run,api)
    state['response']=TimeoutError('Controlled ambiguous POST')
    assert api.submit(run,'S01')['status']=='outcome_unknown'
    assert api.submit(run,'S01')['status']=='outcome_unknown'
    assert state['posts']==1


def test_library_nonroot_cannot_claim_or_POST(library_env):
    run,state=library_env;library.prepare(run,spec(run));review(run)
    api=execution.library_for_run(run,binding(run));api.prepare_video(run,'S01');approve(run,api,approved_by='someone')
    with pytest.raises(ValueError,match='Root_launch_approval_required'):api.submit(run,'S01')
    assert state['posts']==0 and not (api.native_run(run,'S01')/'shots/S01/CLAIM.json').exists()


def test_asset_real_contact_and_direction_pinned_in_positive(contact_env):
    e=contact_env;pb=binding(e['tmp']);api=execution.asset_for_run(e['run'],pb)
    # These are the real fixture's transport-only HTTP/service anchors.
    api._service_anchor=e['api']._service_anchor
    assert api.prepare(e['run'],e['draft'],e['cfg'],prompt_profiles=flow.bind(PROFILE),authorization=e['auth'])['status']=='prepared'
    _,p,row,folder=api._load(e['run']);m=flow._bound(p['live_manifest']);g=flow.read(folder/'workflow_api.json')
    assert m['directing_policy']['policy_binding']==pb and 'contact_continuity' in m
    assert len(m['references'])==9 and g['guide_start']['inputs']['image']==['ref_8',0]
    assert g['condition']['inputs']['prompt']==m['compiled_prompt'] and e['state']['posts']==0
    assert {'h3_universal_direction_execution_v1.py','video_directing_policy_v1.py'} <= {Path(x['path']).name for x in p['code']}


@pytest.mark.parametrize('route',['library','asset'])
def test_wrong_run_rejected_before_mutation_or_service(library_env, route):
    run,state=library_env;pb=binding(run);wrong=run/'foreign'
    api=execution.library_for_run(run,pb) if route=='library' else execution.asset_for_run(run,pb)
    with pytest.raises(ValueError,match='bound_to_one_run'):api.submit(wrong,'S01') if route=='library' else api.submit(wrong)
    assert not wrong.exists() and state['posts']==0
