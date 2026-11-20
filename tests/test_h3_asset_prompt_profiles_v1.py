from copy import deepcopy
from pathlib import Path

import pytest

from h3_asset_flow_fixture_v2 import build_fixture
from src.content_factory import h3_asset_flow_v2 as flow
from src.content_factory import h3_asset_prompt_profiles_v1 as present

PROFILE=Path(__file__).resolve().parents[1]/'data/video_generation/h3_oral_revision_next_minute_20261113_v1/VOICE_PROFILES_V2.json'


def package(tmp_path,mode='prompt_only'):
    spec,_=build_fixture(tmp_path,mode=mode)
    value=flow.compile_spec(flow.read(spec));assert 'manifest' in value
    return value


def test_real_s04_natural_state_preserves_all_quotes_assets_and_child_profiles(tmp_path):
    original=package(tmp_path);before=deepcopy(original)
    value=present.apply(original['manifest'],original['graph'],flow.bind(PROFILE))
    assert original==before
    assert value['manifest']['actor_state']==original['manifest']['actor_state']
    assert value['manifest']['references']==original['manifest']['references']
    assert value['manifest']['voice_identity_locked'] is False
    text=value['manifest']['compiled_prompt']
    assert flow.core.QUOTE.findall(text)==flow.core.QUOTE.findall(original['manifest']['compiled_prompt'])
    assert all(p['description'] in text for p in flow.read(PROFILE)['profiles'].values())
    assert '自己这具身体的右手腕' in text and '女孩童声' in text
    assert '目光朝向' in text and '位置、姿态、视线和持物' in text
    assert ':primary' not in text and 'body_ownership' not in text and 'held_items' not in text
    for cid in original['manifest']['required_actor_assets']:assert cid not in text
    expected=deepcopy(original['graph']);expected['condition']['inputs']['prompt']=text
    assert value['graph']==expected
    assert value['manifest']['routes']['audio_references']==0
    assert value['manifest']['production_ready'] is False


@pytest.mark.parametrize('mutation',['missing','wrong_actor','adult','quoted_instruction'])
def test_missing_or_misleading_child_profile_is_rejected(tmp_path,mutation):
    value=package(tmp_path/'fixtures');p=flow.read(PROFILE);cid=next(iter(p['profiles']))
    if mutation=='missing':p['profiles'].pop(cid)
    elif mutation=='wrong_actor':p['profiles'][cid]['actor']='someone_else'
    elif mutation=='adult':p['profiles'][cid]['type']='mature_male'
    else:p['profiles'][cid]['description']='读出“另加一句话”'
    binding=flow.freeze(tmp_path/'bad_profile.json',p)
    with pytest.raises(ValueError):present.apply(value['manifest'],value['graph'],binding)


def test_profile_file_or_original_graph_tamper_is_not_normalized(tmp_path):
    value=package(tmp_path/'fixtures')
    binding=flow.freeze(tmp_path/'profile.json',flow.read(PROFILE))
    Path(binding['path']).write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError):present.apply(value['manifest'],value['graph'],binding)
    graph=deepcopy(value['graph']);graph['ref_0']['inputs']['image']='wrong.png'
    with pytest.raises(ValueError):present.apply(value['manifest'],graph,flow.bind(PROFILE))


def test_audio_conditioned_package_is_not_misrepresented_as_prompt_only(tmp_path):
    value=package(tmp_path,mode='voice_required')
    with pytest.raises(ValueError):present.apply(value['manifest'],value['graph'],flow.bind(PROFILE))


@pytest.mark.parametrize('mutation',['missing_tail','wrong_time'])
def test_state_and_camera_must_cover_same_complete_timeline(tmp_path,mutation):
    value=package(tmp_path);m=deepcopy(value['manifest'])
    if mutation=='missing_tail':m['actor_state']['state_plan_result']['beats'].pop()
    else:m['actor_state']['state_plan_result']['beats'][-1]['end']+=0.1
    with pytest.raises(ValueError):present.apply(m,value['graph'],flow.bind(PROFILE))
