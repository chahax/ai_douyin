import json
from copy import deepcopy
from pathlib import Path
import pytest
from scripts import creative_review_projection_v11 as view
from scripts import creative_joint_source_binding_v11 as joint

ROOT=Path(__file__).resolve().parents[1]
RECEIPT=ROOT/'data/production_trials/_shared_text_diagnostics/2a3cd8ae66de26ff4eb8f299/modular_bd_v1/resume_20261005_v10/call_144_final_review_s6_d6_r1.json'

def case():
    receipt=json.loads(RECEIPT.read_text(encoding='utf-8-sig'))
    ctx=json.loads(receipt['request']['messages'][1]['content'])
    old=deepcopy(ctx['shots']);ctx['shots']=view.project_storyboard(old,ctx)
    return old,ctx

def test_real_complete_projection_keeps_all_source_events():
    old,ctx=case();assert joint.preflight(ctx)['source_identity_checked']
    assert view.validate_projection(old,ctx['shots'],ctx)['lossless_scheduled_events']
    windows=[w for s in ctx['shots']['shots'] for w in s['declared_performance_windows']]
    assert windows==ctx['declared_performance_window_checks']
    assert len(windows)==6
    assert ctx['shots']['shots'][8]['declared_performance_windows']==[]
    for i,shot in enumerate(ctx['shots']['shots']):
        for g in ctx['state_plan']['beats'][i]['groups']:assert g['performance'] in shot['visible_performance']
        for d in ctx['execution_script']['beats'][i]['dialogue']:assert d['text'] in shot['visible_performance']
        assert '情绪反应窗口' not in shot['prompt']
        assert all('affect' not in e for e in json.loads(shot['start_state']).values())
    assert len(json.dumps(ctx['shots']))<len(json.dumps(old))

def test_text_state_or_window_change_is_rejected():
    old,ctx=case()
    for key in ['visible_performance','start_state','prompt']:
        bad=deepcopy(ctx);bad['shots']['shots'][8][key]+=' invented'
        with pytest.raises(Exception):joint.preflight(bad)
    bad=deepcopy(ctx);bad['declared_performance_window_checks'][0]['subject']='C02'
    with pytest.raises(Exception):joint.preflight(bad)

def test_invalid_original_review_is_not_repaired_or_adopted():
    from scripts import creative_review_wire_v10 as wire
    from jsonschema import Draft202012Validator
    old,ctx=case();r=json.loads(RECEIPT.read_text(encoding='utf-8-sig'))
    assert r['status']=='contract_rejected'
    with pytest.raises(Exception):Draft202012Validator(wire.schema(json.loads(r['request']['messages'][1]['content']))).validate(r['output'])


def test_independent_handoff_binding_carries_spend_and_blocks_parent_change(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from scripts import run_creative_handoff_v11 as runner
    from scripts import creative_resume_dispatch_v3 as control
    receipt=json.loads(RECEIPT.read_text(encoding='utf-8-sig'))
    ctx=json.loads(receipt['request']['messages'][1]['content'])
    compiled=json.loads((RECEIPT.parent/'COMPLETE_d6_61e7fdb64594.json').read_text(encoding='utf-8-sig'))
    parent_file=tmp_path/'parent_frozen.txt';parent_file.write_text('original',encoding='utf-8')
    ledger=RECEIPT.parent/'CALL_LEDGER.json'
    monkeypatch.setattr(runner,'ROOT',tmp_path/'isolated_run')
    monkeypatch.setattr(runner.parent,'final_context',lambda d:(deepcopy(ctx),deepcopy(compiled)))
    monkeypatch.setattr(runner.parent,'runtime',lambda:SimpleNamespace(ledger=ledger,check=lambda x:None))
    monkeypatch.setattr(runner.parent,'summary',lambda:{'effective_calls_started':144,'effective_reported_tokens':2139893,'calls_with_known_usage':143})
    monkeypatch.setattr(runner,'fingerprint',lambda:{str(parent_file):control.sha_file(parent_file)})
    runner.prepare();s=runner.summary()
    assert s['effective_calls_started']==144 and s['effective_reported_tokens']==2139893
    assert s['calls_with_known_usage']==143 and s['unknown_token_reservations']==64010
    assert control.read(runner.ROOT/'CALL_LEDGER.json')['calls']==[]
    parent_file.write_text('changed',encoding='utf-8')
    with pytest.raises(RuntimeError,match='frozen parent files changed'):runner.runtime().check(control.read(runner.ROOT/'CALL_LEDGER.json'))
