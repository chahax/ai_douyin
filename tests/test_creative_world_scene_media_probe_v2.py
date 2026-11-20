"""Explicit encoding contracts; no live proof, queue or video request."""
from copy import deepcopy
import importlib
from pathlib import Path
import pytest
from scripts import creative_world_scene_media_probe_v2 as m
from scripts import creative_world_scene_text_handoff_verifier_v1 as selector
from tests.test_creative_world_scene_media_probe_v1 import case,offline


def encoded_case(case):
    cfg,text,prod,snapshot=case
    prod.update(native_source_duration_seconds=7.6,native_integer_duration_seconds=8,encoded_duration_seconds=8,
        frame_length=192,encoding_hold_seconds=.4,production_review_context_sha256='OFFLINE context',encoding_hold_reviewed=True)
    prod['encoding_certificate_sha256']=m.digest(m.encoding_identity(prod))
    return cfg,text,prod,snapshot


def test_explicit_native_and_encoded_hold_preparation_and_live_rebuild(case,monkeypatch):
    cfg,text,prod,snapshot=encoded_case(case)
    # Fixed verifier function symbols are replaced only by this explicit
    # synthetic test, with network disabled; no real proof is claimed.
    monkeypatch.setattr(selector,'verify_text_handoff',lambda root:deepcopy(text))
    production=importlib.import_module('scripts.creative_world_scene_production_probe_v1')
    monkeypatch.setattr(production,'verify_first_segment_handoff',lambda root,**kw:deepcopy(prod))
    monkeypatch.setattr(m.base,'inspect_service',lambda:deepcopy(snapshot))
    result=m.prepare(cfg)
    assert result['native_encoding']['identity']['native_source_duration_seconds']==7.6
    assert result['native_encoding']['identity']['encoded_duration_seconds']==8
    verified=m.verify_prepared(cfg.output_root)
    assert verified['valid'] and verified['graph']['condition']['inputs']['length']==192
    assert str((m.base.PROJECT/'scripts/creative_world_scene_text_handoff_verifier_v1.py').resolve()) in verified['source_files']
    assert verified['reference_map'][1]['character_id']==prod['reference_map'][1]['character_id']
    output=Path(cfg.output_root);graph=m.base.read(output/'workflow_api.json');graph['condition']['inputs']['prompt']+=' changed'
    m.base.dump(output/'CHANGED_GRAPH.json',graph)
    (output/'workflow_api.json').write_text(__import__('json').dumps(graph,ensure_ascii=False),'utf8')
    with pytest.raises(ValueError,match='graph differs'):m.verify_prepared(cfg.output_root)


@pytest.mark.parametrize('fault',['hidden_hold','wrong_frame','unreviewed','extra_acting','source_too_long','certificate'])
def test_unreviewed_or_hidden_encoding_is_blocked_before_any_graph(case,fault):
    cfg,text,prod,snapshot=encoded_case(case)
    if fault=='hidden_hold':prod['encoding_hold_seconds']=0
    elif fault=='wrong_frame':prod['frame_length']=193
    elif fault=='unreviewed':prod['encoding_hold_reviewed']=False
    elif fault=='extra_acting':prod['native_source_duration_seconds']=6;prod['encoding_hold_seconds']=2;prod['native_integer_duration_seconds']=6
    elif fault=='source_too_long':prod['native_source_duration_seconds']=16;prod['native_integer_duration_seconds']=16
    else:prod['encoding_certificate_sha256']='wrong'
    with pytest.raises((ValueError,KeyError)):m.prepare(cfg,text_verifier=lambda root:deepcopy(text),
        production_verifier=lambda root,**kw:deepcopy(prod),service_snapshot=snapshot,offline_test=True)
    assert not Path(cfg.output_root).exists()


@pytest.mark.parametrize('version',[1,2,3,4])
def test_fixed_original_text_version_verifier_and_no_fallback(tmp_path,monkeypatch,version):
    root=tmp_path/'text';root.mkdir();m.base.dump(root/'STATE.json',{'schema':f'creative_world_scene_live_session/v{version}/state','status':'text_ready_for_director'})
    calls=[]
    class Module:
        @staticmethod
        def verify_text_handoff(p):calls.append(str(p));return {'valid':True,'accepted':True,'status':'text_ready_for_director','root':str(root),'source_root':str(root)}
    monkeypatch.setattr(selector.importlib,'import_module',lambda name:(calls.append(name) or Module))
    assert selector.verify_text_handoff(root)['valid']
    assert calls[0]==f'scripts.creative_world_scene_live_session_v{version}'
    (root/'STATE.json').write_text('{"schema":"unknown/state","status":"text_ready_for_director"}','utf8')
    with pytest.raises(ValueError,match='unsupported'):selector.verify_text_handoff(root)
