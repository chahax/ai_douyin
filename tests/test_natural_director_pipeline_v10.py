"""Fake native services exercise actual file-backed v10 stage admission."""
from pathlib import Path
import json
import runpy
import pytest
from src.content_factory import natural_director_pipeline_v10 as pipe
F=runpy.run_path(str(Path(__file__).with_name('test_novel_agent_pipeline_v8.py')))
C=runpy.run_path(str(Path(__file__).with_name('test_natural_director_contracts_v10.py')))
fx=F['fx']

def auth(base, old, campaign=None, calls=20):
    campaign=campaign or base/'campaign'
    pipe.core._ensure(campaign/'AUTHORIZATION.json', {'max_rounds':10,'review_interval_rounds':5,'max_calls_per_round':3,'media_authorized':False,'automatic_transport_retry':False})
    path=base/'AUTHORIZATION.json'
    pipe.core._write(path, {'parent_run':str(old.resolve()),'user_statement':'5+5 rounds','max_rounds':10,'review_interval_rounds':5,'max_calls_per_round':3,'old_total_limits':{'calls':calls,'reported_tokens':500000},'new_media_authorized':False,'automatic_transport_retry':False,'campaign_dir':str(campaign.resolve()),'campaign_authorization':pipe.core._binding(campaign/'AUTHORIZATION.json')})
    return path

@pytest.fixture
def prepared(tmp_path,monkeypatch):
    registry=tmp_path/'canonical'
    monkeypatch.setattr(pipe,'CANONICAL_REGISTRY',registry)
    monkeypatch.setattr(pipe.parent,'CANONICAL_REGISTRY',registry)
    monkeypatch.setattr(pipe.core,'_legacy_blocks',lambda *a,**kw:[])
    source=tmp_path/'source.txt'; source.write_text('Original story about choosing and answering.',encoding='utf-8')
    old=tmp_path/'writer'; authorization=auth(tmp_path,old)
    pipe.prepare_source(old,authorization_path=authorization,source_path=source,source_kind='original',title='Natural route',brief={'max_duration_seconds':23})
    view=pipe.execute_writer_only(old,clients=fx.FakeClients(F['success_values']()[:2]))
    assert view['writer_ready'] and view['calls_started']==2
    run=tmp_path/'natural'; pipe.prepare(run,parent_run=old,authorization_path=authorization)
    return tmp_path,old,run,authorization

def values():
    return [fx.result(C['NATURAL']),fx.result(C['extract_native'](),'director'),fx.result(C['final_native'](),'director')]

def revise():
    v=C['extract_native'](); v.update(verdict='revise',faithful_to_natural=False,segments=[],issues=[{'severity':'major','location':'opening','evidence':'The listener never answers.','suggestion':'Rewrite the complete natural director.','responsibility_layer':'director'}]); return v

def snapshot(root):
    return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}

def test_complete_route_has_no_heavy_director_and_native_bound_final_requests(prepared):
    base,old,run,_=prepared; before=snapshot(old)
    assert [pipe.core._read(p)['stage'] for p in sorted(old.glob('REQUEST_*.json'))]==['writer_full','review_full']
    client=fx.FakeClients(values()); v=pipe.execute(run,clients=client)
    assert v['status']=='text_ready_for_production',v['blockers']
    assert (v['rounds_started'],v['calls_started'],v['combined_calls_started'],v['combined_known_reported_tokens'])==(1,3,5,500)
    assert [x['role'] for x in client.calls]==['writer','director','director']
    material=json.loads(client.calls[0]['messages'][-1]['content'])
    assert not {'segments','previous_director','scene_ledger','output_spec'} & set(material)
    assert all(x['parameters']['response_format']=={'type':'json_object'} for x in client.calls[1:])
    assert snapshot(old)==before
    pipe.contracts.validate_handoff_for_dispatch(pipe.core._read(run/'PRODUCTION_HANDOFF.json'))
    assert len(list((base/'campaign').glob('ROUND_*_CLAIM.json')))==1
    assert pipe.execute(run,clients=fx.FakeClients([]))['calls_started']==3

def test_known_content_failure_writes_fresh_whole_natural_next_round(prepared):
    _,_,run,_=prepared
    client=fx.FakeClients([fx.result('First complete natural director.'),fx.result(revise(),'director'),*values()])
    v=pipe.execute(run,clients=client)
    assert v['status']=='text_ready_for_production',v['blockers']
    assert (v['rounds_started'],v['calls_started'])==(2,5)
    material=json.loads(client.calls[2]['messages'][-1]['content'])
    assert isinstance(material['diagnostic_feedback'],list) and 'listener' in str(material['diagnostic_feedback'])
    assert 'First complete natural director.' not in json.dumps(material)
    assert (run/'NATURAL_DIRECTOR_001.md').exists() and (run/'ROUND_001.json').exists()

@pytest.mark.parametrize('finish,unknown',[('length',False),('stop',True)])
def test_unknown_usage_or_truncation_stops_without_redispatch(prepared,finish,unknown):
    _,_,run,_=prepared; client=fx.FakeClients([fx.result('Untrusted.',finish=finish,unknown=unknown)])
    with pytest.raises(RuntimeError): pipe.execute(run,clients=client)
    assert pipe.inspect(run)['pending_call']==1
    assert pipe.execute(run,clients=fx.FakeClients([]))['calls_started']==1
    assert len(client.calls)==1

def test_unknown_transport_interrupt_keeps_original_identity(prepared):
    _,_,run,_=prepared
    with pytest.raises(KeyboardInterrupt): pipe.execute(run,clients=fx.FakeClients([KeyboardInterrupt()]))
    with pytest.raises(RuntimeError,match='未知'): pipe.execute(run,clients=fx.FakeClients([]))
    assert pipe.inspect(run)['pending_call']==1

def test_checkpoint_projection_recovery_does_not_repeat_service(prepared):
    _,_,run,_=prepared; initial=(run/'state.json').read_bytes()
    pipe.execute(run,clients=fx.FakeClients([values()[0]]),max_steps=1)
    (run/'state.json').write_bytes(initial)
    assert pipe.inspect(run)['projection_recovery_available']
    assert pipe.recover_projection(run)['calls_started']==1
    v=pipe.execute(run,clients=fx.FakeClients(values()[1:]))
    assert v['status']=='text_ready_for_production',v['blockers']

def test_same_parent_cannot_reclaim_rounds_in_another_directory(prepared):
    base,old,_,authorization=prepared; before=snapshot(base/'canonical')
    with pytest.raises(RuntimeError,match='唯一'): pipe.prepare(base/'fork',parent_run=old,authorization_path=authorization)
    assert not (base/'fork').exists() and snapshot(base/'canonical')==before

def test_shared_campaign_stops_before_six_until_review(prepared):
    base,_,run,_=prepared
    bad=[x for _ in range(5) for x in (fx.result(C['NATURAL']),fx.result(revise(),'director'))]
    v=pipe.execute(run,clients=fx.FakeClients(bad))
    assert v['status']=='campaign_review_required' and v['rounds_started']==5 and v['calls_started']==10
    pipe.record_campaign_review(base/'campaign',findings='Five full native failures reviewed; the listener is still missing, retry whole natural direction within original budgets.')
    v=pipe.execute(run,clients=fx.FakeClients(values()))
    assert v['status']=='text_ready_for_production',v['blockers']
    assert v['rounds_started']==6

def test_final_native_tamper_invalidates_delivered_handoff(prepared):
    _,_,run,_=prepared; pipe.execute(run,clients=fx.FakeClients(values()))
    p=run/'RESPONSE_003.json'; p.write_bytes(p.read_bytes()+b' ')
    assert pipe.inspect(run)['status']=='evidence_invalid'

def test_writer_only_ready_call_cannot_admit_heavy_director(prepared):
    _,old,_,_=prepared; client=fx.FakeClients([])
    assert pipe.execute_writer_only(old,clients=client)['writer_ready']
    assert not client.calls and not any(pipe.core._read(p)['stage']=='director_full' for p in old.glob('REQUEST_*.json'))

def test_preview_reservation_is_read_only_and_preserves_inherited_budget(prepared):
    _,_,run,_=prepared; before=snapshot(run); v=pipe.preview(run); f=v['next_request_preflight']
    assert v['remaining_calls']==18 and v['remaining_known_tokens']==499800
    assert f['max_output_tokens']==12000 and f['reservation_fits'] and f['read_only']
    assert snapshot(run)==before

def test_confirmed_upstream_writer_issue_stops_instead_of_rewriting_director(prepared):
    _,_,run,_=prepared; rejected=revise(); rejected['issues'][0]['responsibility_layer']='writer'
    client=fx.FakeClients([values()[0],fx.result(rejected,'director')])
    view=pipe.execute(run,clients=client)
    assert view['status']=='upstream_writer_revision_required' and view['calls_started']==2
    assert (run/'ROUND_001.json').exists() and len(client.calls)==2

def test_known_native_pass_with_invalid_duration_keeps_verdict_and_restarts_full_round(prepared):
    _,_,run,_=prepared; rejected=C['extract_native'](); rejected['segments'][0]['duration_seconds']=3
    client=fx.FakeClients([values()[0],fx.result(rejected,'director'),*values()])
    view=pipe.execute(run,clients=client)
    assert view['status']=='text_ready_for_production',view['blockers']
    saved=pipe.core._read(run/'REJECTED_EXTRACT_REVIEW_002.json')
    assert saved['original_native']['verdict']=='pass' and saved['original_native']==rejected
    assert view['rounds_started']==2

def test_deleted_campaign_claim_never_lowers_count(prepared):
    base,_,run,_=prepared
    pipe.execute(run,clients=fx.FakeClients([values()[0]]),max_steps=1)
    (base/'campaign'/'ROUND_001_CLAIM.json').unlink()
    assert pipe.inspect(run)['status']=='evidence_invalid'
    with pytest.raises((ValueError,OSError)): pipe.execute(run,clients=fx.FakeClients([]))

def test_fake_empty_campaign_review_does_not_release_sixth_round(prepared):
    base,_,run,_=prepared
    bad=[x for _ in range(5) for x in (fx.result(C['NATURAL']),fx.result(revise(),'director'))]
    pipe.execute(run,clients=fx.FakeClients(bad))
    pipe.core._write(base/'campaign'/'REVIEW_005.json',{})
    client=fx.FakeClients([])
    with pytest.raises(ValueError,match='复盘'): pipe.execute(run,clients=client)
    assert not client.calls and len(list((base/'campaign').glob('ROUND_*_CLAIM.json')))==5

def test_canonical_owner_prevents_claim_and_last_checkpoint_rollback(prepared):
    base,_,run,_=prepared
    pipe.execute(run,clients=fx.FakeClients([values()[0]]),max_steps=1)
    (base/'campaign'/'ROUND_001_CLAIM.json').unlink()
    (base/'campaign'/'CAMPAIGN_STATE_00002.json').unlink()
    with pytest.raises(ValueError,match='缺共享轮claim'):
        pipe._campaign_claims(base/'campaign')

def test_unknown_extract_does_not_start_a_new_natural_round(prepared):
    base,_,run,_=prepared
    with pytest.raises(RuntimeError):
        pipe.execute(run,clients=fx.FakeClients([values()[0],fx.result(C['extract_native'](),'director',finish='length')]))
    view=pipe.inspect(run)
    assert view['pending_call']==2 and view['rounds_started']==1
    assert len(list((base/'campaign').glob('ROUND_*_CLAIM.json')))==1

def test_original_total_call_limit_stops_even_with_rounds_remaining(tmp_path,monkeypatch):
    registry=tmp_path/'canonical'
    monkeypatch.setattr(pipe,'CANONICAL_REGISTRY',registry); monkeypatch.setattr(pipe.parent,'CANONICAL_REGISTRY',registry)
    monkeypatch.setattr(pipe.core,'_legacy_blocks',lambda *a,**kw:[])
    source=tmp_path/'source.txt'; source.write_text('Different budget test source.',encoding='utf-8')
    old=tmp_path/'writer'; authorization=auth(tmp_path,old,calls=4)
    pipe.prepare_source(old,authorization_path=authorization,source_path=source,source_kind='original',title='Budget story',brief={'max_duration_seconds':23})
    pipe.execute_writer_only(old,clients=fx.FakeClients(F['success_values']()[:2]))
    run=tmp_path/'natural'; pipe.prepare(run,parent_run=old,authorization_path=authorization)
    view=pipe.execute(run,clients=fx.FakeClients(values()[:2]))
    assert view['status']=='budget_exhausted' and view['combined_calls_started']==4
    assert view['rounds_started']==1 and not (run/'REQUEST_003.json').exists()
