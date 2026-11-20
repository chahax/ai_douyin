"""Fixed, version-aware native text proof. Never fall back to a ready flag."""
import importlib
import json
from pathlib import Path

VERSION='creative_world_scene_text_handoff_verifier/v1'
VERIFIERS={
    'creative_world_scene_live_session/v1/state':'scripts.creative_world_scene_live_session_v1',
    'creative_world_scene_live_session/v2/state':'scripts.creative_world_scene_live_session_v2',
    'creative_world_scene_live_session/v3/state':'scripts.creative_world_scene_live_session_v3',
    'creative_world_scene_live_session/v4/state':'scripts.creative_world_scene_live_session_v4',
}


def verify_text_handoff(root):
    root=Path(root).resolve()
    state=json.loads((root/'STATE.json').read_text('utf-8-sig'))
    module=VERIFIERS.get(state.get('schema'))
    if module is None:raise ValueError('unsupported original text session version; no fallback')
    if state.get('status')!='text_ready_for_director':raise ValueError('original text session is not text ready')
    result=importlib.import_module(module).verify_text_handoff(root)
    if not (result.get('valid') is True and result.get('accepted') is True and result.get('status')=='text_ready_for_director'
            and Path(result['root']).resolve()==root and Path(result['source_root']).resolve()==root):
        raise ValueError('fixed original text verifier did not accept this root')
    return result
